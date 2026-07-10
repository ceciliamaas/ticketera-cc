import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizations.models import Organization
from tickets.models import Order, TicketType, OrderTicket, NewTicket
from tickets.processing import mint_tickets


TEST_MP_SETTINGS = {
    'PUBLIC_KEY': 'TEST-public-key',
    'ACCESS_TOKEN': 'TEST-access-token',
    'WEBHOOK_SECRET': 'test-webhook-secret',
    'COLLECTOR_USER_ID': '12345',
}


def _setup_event_and_order():
    org = Organization.objects.create(name='Test Org', slug='test-org')
    user = User.objects.create_user('buyer', password='pass', email='buyer@example.com')
    event = Event.objects.create(
        organization=org, slug='test-event', name='Test Event',
        status=Event.Status.PUBLISHED, active=True,
        start=timezone.now(), end=timezone.now(),
        transfers_enabled_until=timezone.now(),
        header_image='', description='D',
    )
    ticket_type = TicketType.objects.create(
        event=event, name='General', price=100,
        ticket_count=10, cardinality=1,
    )
    order = Order.objects.create(
        user=user, event=event,
        status=Order.OrderStatus.PENDING,
        email='buyer@example.com',
        first_name='Test', last_name='Buyer',
        phone='', dni='',
        amount=100,
    )
    OrderTicket.objects.create(order=order, ticket_type=ticket_type, quantity=1)
    return order, ticket_type, user


class MintTicketsIdempotenceTest(TestCase):

    def test_mint_tickets_creates_tickets(self):
        order, ticket_type, user = _setup_event_and_order()
        with patch.object(Order, 'send_confirmation_email'):
            mint_tickets(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.OrderStatus.CONFIRMED)
        self.assertEqual(NewTicket.objects.filter(order=order).count(), 1)

    def test_mint_tickets_called_twice_does_not_duplicate(self):
        order, ticket_type, user = _setup_event_and_order()
        with patch.object(Order, 'send_confirmation_email'):
            mint_tickets(order)
            mint_tickets(order)  # second call — should be a no-op
        self.assertEqual(NewTicket.objects.filter(order=order).count(), 1)

    def test_already_confirmed_order_is_skipped(self):
        order, ticket_type, user = _setup_event_and_order()
        order.status = Order.OrderStatus.CONFIRMED
        order.save()
        with patch.object(Order, 'send_confirmation_email') as mock_email:
            mint_tickets(order)
            mock_email.assert_not_called()
        self.assertEqual(NewTicket.objects.filter(order=order).count(), 0)


def _make_mp_signature(data_id, request_id, ts, secret):
    """Build a valid MercadoPago x-signature header value."""
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    digest = hmac.new(secret.encode(), msg=manifest.encode(), digestmod=hashlib.sha256).hexdigest()
    return f"ts={ts},v1={digest}"


@override_settings(MERCADOPAGO=TEST_MP_SETTINGS, APP_URL='http://testserver')
class MercadoPagoWebhookTest(TestCase):

    def _post_webhook(self, payload, data_id='42', request_id='req-1', ts='1700000000'):
        secret = TEST_MP_SETTINGS['WEBHOOK_SECRET']
        signature = _make_mp_signature(data_id, request_id, ts, secret)
        return self.client.post(
            reverse('mercadopago_webhook') + f'?data.id={data_id}',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_SIGNATURE=signature,
            HTTP_X_REQUEST_ID=request_id,
        )

    def test_invalid_hmac_returns_403(self):
        payload = {'action': 'payment.created', 'data': {'id': '42'}}
        response = self.client.post(
            reverse('mercadopago_webhook') + '?data.id=42',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_SIGNATURE='ts=1700000000,v1=invalidsignature',
            HTTP_X_REQUEST_ID='req-1',
        )
        self.assertEqual(response.status_code, 403)

    def test_unknown_action_returns_200_without_side_effects(self):
        payload = {'action': 'merchant_order.updated', 'data': {'id': '42'}}
        response = self._post_webhook(payload)
        self.assertEqual(response.status_code, 200)

    @patch('tickets.views.webhooks.mercadopago.SDK')
    def test_approved_payment_mints_tickets_and_confirms_order(self, MockSDK):
        order, _, _ = _setup_event_and_order()

        fake_payment = {
            'status': 'approved',
            'external_reference': str(order.key),
            'transaction_details': {'net_received_amount': '90.00'},
        }
        mock_sdk_instance = MagicMock()
        mock_sdk_instance.payment.return_value.get.return_value = {'response': fake_payment}
        MockSDK.return_value = mock_sdk_instance

        with patch.object(Order, 'send_confirmation_email'):
            payload = {'action': 'payment.created', 'data': {'id': '42'}}
            response = self._post_webhook(payload)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.OrderStatus.CONFIRMED)
        self.assertEqual(NewTicket.objects.filter(order=order).count(), 1)

    @patch('tickets.views.webhooks.mercadopago.SDK')
    def test_non_approved_payment_does_not_confirm_order(self, MockSDK):
        order, _, _ = _setup_event_and_order()

        fake_payment = {
            'status': 'pending',
            'external_reference': str(order.key),
            'transaction_details': {'net_received_amount': '0'},
        }
        mock_sdk_instance = MagicMock()
        mock_sdk_instance.payment.return_value.get.return_value = {'response': fake_payment}
        MockSDK.return_value = mock_sdk_instance

        payload = {'action': 'payment.created', 'data': {'id': '42'}}
        response = self._post_webhook(payload)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.OrderStatus.PENDING)

    @patch('tickets.views.webhooks.mercadopago.SDK')
    def test_duplicate_webhook_does_not_mint_twice(self, MockSDK):
        order, _, _ = _setup_event_and_order()

        fake_payment = {
            'status': 'approved',
            'external_reference': str(order.key),
            'transaction_details': {'net_received_amount': '90.00'},
        }
        mock_sdk_instance = MagicMock()
        mock_sdk_instance.payment.return_value.get.return_value = {'response': fake_payment}
        MockSDK.return_value = mock_sdk_instance

        payload = {'action': 'payment.created', 'data': {'id': '42'}}
        with patch.object(Order, 'send_confirmation_email'):
            self._post_webhook(payload)
            self._post_webhook(payload)  # duplicate

        order.refresh_from_db()
        self.assertEqual(NewTicket.objects.filter(order=order).count(), 1)


@override_settings(MERCADOPAGO=TEST_MP_SETTINGS, APP_URL='http://testserver')
class GetPaymentPreferenceTest(TestCase):

    @patch('mercadopago.SDK')
    def test_creates_preference_with_correct_fields(self, MockSDK):
        order, _, _ = _setup_event_and_order()

        mock_sdk_instance = MagicMock()
        mock_sdk_instance.preference.return_value.create.return_value = {
            'response': {'id': 'PREF-123', 'init_point': 'https://mp.com/checkout'}
        }
        MockSDK.return_value = mock_sdk_instance

        result = order.get_payment_preference()

        self.assertEqual(result['id'], 'PREF-123')
        called_payload = mock_sdk_instance.preference.return_value.create.call_args[0][0]
        self.assertEqual(called_payload['external_reference'], str(order.key))
        self.assertIn('notification_url', called_payload)
        self.assertIn('back_urls', called_payload)
        self.assertEqual(called_payload['payer']['email'], order.email)

    @patch('mercadopago.SDK')
    def test_notification_url_points_to_webhook_endpoint(self, MockSDK):
        order, _, _ = _setup_event_and_order()

        mock_sdk_instance = MagicMock()
        mock_sdk_instance.preference.return_value.create.return_value = {
            'response': {'id': 'PREF-456'}
        }
        MockSDK.return_value = mock_sdk_instance

        order.get_payment_preference()

        called_payload = mock_sdk_instance.preference.return_value.create.call_args[0][0]
        self.assertIn('/webhooks/mercadopago', called_payload['notification_url'])

