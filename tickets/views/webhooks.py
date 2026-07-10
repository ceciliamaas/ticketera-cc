import hashlib
import hmac
import json
import logging
import urllib

import mercadopago
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from tickets.models import Order, OrderTicket


@csrf_exempt
def mercadopago_webhook(request):
    if request.method == 'POST':
        try:
            if not verify_hmac_request(request):
                logging.info("HMAC verification failed")
                # In test mode, skip HMAC — payment is still verified via MP API
                if not settings.MERCADOPAGO.get('TEST_MODE'):
                    return JsonResponse({"status": "forbidden"}, status=403)
                logging.warning("TEST_MODE: bypassing HMAC check")

            payload = json.loads(request.body)
            logging.info("Webhook payload:")
            logging.info(payload)

            if payload.get('action') == 'payment.created':
                handle_payment_created(payload)
            elif payload.get('topic') == 'merchant_order':
                handle_merchant_order_ipn(request, payload)
            elif payload.get('topic') == 'payment':
                handle_payment_ipn(request, payload)

            return JsonResponse({"status": "success"}, status=200)

        except AttributeError as e:
            logging.error(f"Attribute error: {str(e)}")
            return JsonResponse({"status": "error", "message": "Internal attribute error"}, status=500)

        except KeyError as e:
            logging.error(f"Key error: {str(e)}")
            return JsonResponse({"status": "error", "message": f"Missing key: {str(e)}"}, status=400)

        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            return JsonResponse({"status": "error", "message": "An unexpected error occurred"}, status=500)
    else:
        return JsonResponse({"status": "method not allowed"}, status=405)


def verify_hmac_request(request):
    try:
        x_signature = request.headers.get("x-signature")
        x_request_id = request.headers.get("x-request-id")
        query_params = urllib.parse.parse_qs(request.GET.urlencode())
        # New webhook format uses data.id; IPN/merchant_order format uses id
        data_id = query_params.get("data.id", [""])[0] or query_params.get("id", [""])[0]

        ts, hash_value = parse_signature(x_signature)

        if verify_hmac(data_id, x_request_id, ts, hash_value):
            logging.info("HMAC verification passed")
            return True
        return False

    except Exception as e:
        logging.error(f"Error during HMAC verification: {str(e)}")
        raise e


def parse_signature(x_signature):
    ts = None
    hash_value = None
    parts = x_signature.split(",")

    for part in parts:
        key_value = part.split("=", 1)
        if len(key_value) == 2:
            key = key_value[0].strip()
            value = key_value[1].strip()
            if key == "ts":
                ts = value
            elif key == "v1":
                hash_value = value

    return ts, hash_value


def verify_hmac(data_id, x_request_id, ts, hash_value):
    secret = settings.MERCADOPAGO['WEBHOOK_SECRET']
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    hmac_obj = hmac.new(secret.encode(), msg=manifest.encode(), digestmod=hashlib.sha256)
    sha = hmac_obj.hexdigest()
    return sha == hash_value


def handle_payment_created(payload):
    try:
        sdk = mercadopago.SDK(settings.MERCADOPAGO['ACCESS_TOKEN'])
        payment = sdk.payment().get(payload['data']['id'])['response']
        logging.info(payment)

        if payment['status'] == 'approved':
            order_approved(payment)

    except KeyError as e:
        logging.error(f"Missing key in payload: {str(e)}")
        raise e

    except Exception as e:
        logging.error(f"Error handling payment creation: {str(e)}")
        raise e


def order_approved(payment):
    try:
        from django.db import transaction
        with transaction.atomic():
            order = Order.objects.select_for_update().get(key=payment['external_reference'])
            if order.status != Order.OrderStatus.PENDING:
                logging.info(f"Order {order.key} already processed (status={order.status})")
                return

            order.status = Order.OrderStatus.PROCESSING
            order.processor_callback = payment
            order.net_received_amount = payment.get('transaction_details', {}).get('net_received_amount')
            order.save()

    except Order.DoesNotExist as e:
        logging.error(f"Order not found: {str(e)}")
        raise e

    except AttributeError as e:
        logging.error(f"Attribute error in processing order: {str(e)}")
        raise e

    except Exception as e:
        logging.error(f"Error processing order: {str(e)}")
        raise e


def handle_merchant_order_ipn(request, payload):
    """Handle IPN notification for merchant_order topic (sent via notification_url in preferences)."""
    try:
        sdk = mercadopago.SDK(settings.MERCADOPAGO['ACCESS_TOKEN'])
        merchant_order_id = request.GET.get('id')
        if not merchant_order_id:
            resource = payload.get('resource', '')
            merchant_order_id = resource.rstrip('/').split('/')[-1]

        merchant_order = sdk.merchant_order().get(merchant_order_id)['response']
        logging.info(f"Merchant order: {merchant_order.get('id')} status={merchant_order.get('status')}")

        external_reference = merchant_order.get('external_reference')
        if not external_reference:
            logging.warning("merchant_order has no external_reference, skipping")
            return

        paid_amount = sum(
            p['total_paid_amount']
            for p in merchant_order.get('payments', [])
            if p['status'] == 'approved'
        )
        total_amount = merchant_order.get('total_amount', 0)
        logging.info(f"paid={paid_amount} total={total_amount}")

        if paid_amount >= total_amount > 0:
            # Use the first approved payment object for processor_callback
            approved_payment = next(
                (p for p in merchant_order.get('payments', []) if p['status'] == 'approved'),
                {}
            )
            order_approved({
                'external_reference': external_reference,
                'transaction_details': {'net_received_amount': approved_payment.get('total_paid_amount')},
                **approved_payment,
            })

    except Exception as e:
        logging.error(f"Error handling merchant_order IPN: {str(e)}")
        raise e


def handle_payment_ipn(request, payload):
    """Handle IPN notification for payment topic."""
    try:
        sdk = mercadopago.SDK(settings.MERCADOPAGO['ACCESS_TOKEN'])
        payment_id = request.GET.get('id')
        if not payment_id:
            return
        payment = sdk.payment().get(payment_id)['response']
        logging.info(f"Payment IPN: id={payment_id} status={payment.get('status')}")
        if payment.get('status') == 'approved':
            order_approved(payment)
    except Exception as e:
        logging.error(f"Error handling payment IPN: {str(e)}")
        raise e
