from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import patch

from events.models import Event
from organizations.models import Organization
from tickets.models import Order, TicketType, OrderTicket, NewTicket
from tickets.processing import mint_tickets


def _setup_event_and_order():
    org = Organization.objects.create(name='Test Org', slug='test-org')
    user = User.objects.create_user('buyer', password='pass', email='buyer@example.com')
    event = Event.objects.create(
        organization=org, slug='test-event', name='Test Event',
        status=Event.Status.PUBLISHED, active=True,
        start=timezone.now(), end=timezone.now(),
        transfers_enabled_until=timezone.now(),
        header_image='', title='T', description='D',
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

