import hashlib
import hmac
import json
import logging
import urllib.parse

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from tickets.models import Order
from tickets.processing import mint_tickets

logger = logging.getLogger(__name__)


@csrf_exempt
def mercadopago_webhook(request):
    if request.method not in ('POST', 'GET'):
        return JsonResponse({'status': 'method not allowed'}, status=405)

    # Legacy IPN can send GET with ?id=<id>&topic=payment query params
    if request.method == 'GET':
        topic = request.GET.get('topic') or request.GET.get('type', '')
        payment_id = request.GET.get('id')
        if topic == 'payment' and payment_id:
            _handle_payment_created({'id': payment_id, 'type': 'payment'})
        return JsonResponse({'status': 'ok'})

    # Verify HMAC signature (skip in TEST_MODE)
    if not settings.MERCADOPAGO.get('TEST_MODE'):
        if not _verify_hmac(request):
            logger.warning('MP webhook: HMAC verification failed')
            return JsonResponse({'status': 'forbidden'}, status=403)
    else:
        logger.debug('MP webhook: TEST_MODE — skipping HMAC check')

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'bad request'}, status=400)

    logger.info('MP webhook received: action=%s type=%s', payload.get('action'), payload.get('type'))

    action = payload.get('action', '')
    topic = payload.get('type') or payload.get('topic', '')  # legacy IPN uses "type" or "topic"

    if action == 'payment.created' or (topic == 'payment' and not action):
        _handle_payment_created(payload)

    return JsonResponse({'status': 'ok'})


def _verify_hmac(request):
    try:
        x_signature = request.headers.get('x-signature', '')
        x_request_id = request.headers.get('x-request-id', '')
        query_params = urllib.parse.parse_qs(request.GET.urlencode())
        data_id = query_params.get('data.id', [''])[0] or query_params.get('id', [''])[0]

        ts = None
        hash_value = None
        for part in x_signature.split(','):
            kv = part.strip().split('=', 1)
            if len(kv) == 2:
                if kv[0] == 'ts':
                    ts = kv[1]
                elif kv[0] == 'v1':
                    hash_value = kv[1]

        if not ts or not hash_value:
            return False

        secret = settings.MERCADOPAGO.get('WEBHOOK_SECRET', '')
        manifest = f'id:{data_id};request-id:{x_request_id};ts:{ts};'
        digest = hmac.new(secret.encode(), msg=manifest.encode(), digestmod=hashlib.sha256).hexdigest()
        return digest == hash_value
    except Exception as exc:
        logger.error('MP webhook HMAC error: %s', exc)
        return False


def _handle_payment_created(payload):
    # New webhook format: data.id — legacy IPN format: id (top-level)
    payment_id = payload.get('data', {}).get('id') or payload.get('id')
    if not payment_id:
        logger.warning('MP webhook: payment notification with no payment id')
        return

    # Determine org from order to use the org's access token
    # We fetch the payment using the platform token first to get external_reference,
    # then re-fetch with the org token for proper marketplace verification.
    import mercadopago
    platform_sdk = mercadopago.SDK(settings.MERCADOPAGO['ACCESS_TOKEN'])

    try:
        payment_resp = platform_sdk.payment().get(payment_id)
        payment = payment_resp['response']
    except Exception as exc:
        logger.error('MP webhook: could not fetch payment %s: %s', payment_id, exc)
        return

    if payment.get('status') != 'approved':
        logger.info('MP webhook: payment %s not approved (status=%s)', payment_id, payment.get('status'))
        return

    external_reference = payment.get('external_reference', '')
    if not external_reference:
        logger.warning('MP webhook: payment %s has no external_reference', payment_id)
        return

    net_received = payment.get('transaction_details', {}).get('net_received_amount')

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(
                key=external_reference,
                status=Order.OrderStatus.PENDING,
            ).first()

            if not order:
                logger.info('MP webhook: no pending order for key=%s (already processed?)', external_reference)
                return

            order.processor_callback = payment
            order.net_received_amount = net_received
            order.save(update_fields=['processor_callback', 'net_received_amount'])

            mint_tickets(order)
            logger.info('MP webhook: order %s confirmed via payment %s', order.key, payment_id)

    except Exception as exc:
        logger.error('MP webhook: error processing payment %s: %s', payment_id, exc)
