import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from caja.context import mi_fuego_admin_context
from caja.models import CajaSale, EventCaja, EventCajaProduct
from caja.operator_stats import ticket_caja_operator_stats
from caja.permissions import get_event_for_caja
from caja.services.sales import create_pending_sale, finalize_caja_sale
from caja.stock import available, InsufficientStockError

logger = logging.getLogger(__name__)


def _caja_products_for_sale(caja):
    return EventCajaProduct.objects.filter(
        event_caja=caja,
        event_product__is_active=True,
    ).select_related('event_product', 'event_product__ticket_type', 'event_product__stock')


def _caja_payment_totals(caja):
    paid_sales = CajaSale.objects.filter(
        event_caja=caja,
        status=CajaSale.Status.PAID,
    )
    totals = paid_sales.aggregate(
        cash_total=models.Sum(
            'total_amount',
            filter=models.Q(
                payment_method__in=[
                    CajaSale.PaymentMethod.EFECTIVO,
                    CajaSale.PaymentMethod.TRANSFERENCIA,
                ],
            ),
            default=0,
        ),
    )
    return {
        'cash_total': totals['cash_total'] or 0,
        'tx_count': paid_sales.count(),
    }


def _serialized_caja_payment_totals(caja):
    totals = _caja_payment_totals(caja)
    return {
        'cash_total': str(totals['cash_total']),
        'tx_count': totals['tx_count'],
    }


@login_required
def caja_v2_operator_view(request, event_slug, caja_id):
    event = get_event_for_caja(request.user, event_slug)
    caja = get_object_or_404(EventCaja, id=caja_id, event=event, is_active=True)
    caja_products = _caja_products_for_sale(caja)

    products = []
    has_ticket_products = False
    for cp in caja_products:
        product = cp.event_product
        if product.ticket_type_id:
            has_ticket_products = True
        qty = available(product)
        products.append({
            'product': product,
            'available': qty,
            'unlimited': qty is None,
            'sort_order': cp.sort_order,
        })

    context = mi_fuego_admin_context(request, event, f'caja_v2_{event.slug}_{caja.id}')
    context.update({
        'caja': caja,
        'products': products,
        'has_ticket_products': has_ticket_products,
        'caja_payment_totals': _caja_payment_totals(caja),
    })
    if has_ticket_products:
        context['stats'] = ticket_caja_operator_stats(event)
    return render(request, 'mi_fuego/caja_v2/operator.html', context)


@login_required
def caja_v2_summary_view(request, event_slug, caja_id):
    event = get_event_for_caja(request.user, event_slug)
    caja = get_object_or_404(EventCaja, id=caja_id, event=event, is_active=True)
    sales = (
        CajaSale.objects.filter(
            event_caja=caja,
        )
        .exclude(status=CajaSale.Status.PENDING)
        .select_related('sold_by', 'related_sale')
        .prefetch_related('lines__event_product', 'cancellations')
        .order_by('-created_at')
    )
    context = mi_fuego_admin_context(request, event, f'caja_v2_{event.slug}_{caja.id}')
    context.update({
        'caja': caja,
        'sales': sales,
        'caja_payment_totals': _caja_payment_totals(caja),
    })
    return render(request, 'mi_fuego/caja_v2/caja_summary.html', context)


@login_required
@require_POST
def api_create_sale(request, event_slug, caja_id):
    event = get_event_for_caja(request.user, event_slug)
    caja = get_object_or_404(EventCaja, id=caja_id, event=event, is_active=True)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    payment_method = data.get('payment_method')
    if payment_method not in dict(CajaSale.PaymentMethod.choices):
        return JsonResponse({'error': 'Método de pago inválido'}, status=400)

    lines_data = []
    allowed_product_ids = set(
        EventCajaProduct.objects.filter(event_caja=caja).values_list('event_product_id', flat=True)
    )
    for item in data.get('lines', []):
        pid = int(item.get('product_id'))
        qty = int(item.get('quantity', 0))
        if pid not in allowed_product_ids or qty <= 0:
            continue
        from caja.models import EventProduct
        product = get_object_or_404(EventProduct, id=pid, event=event)
        lines_data.append({'event_product': product, 'quantity': qty})

    try:
        sale = create_pending_sale(
            event_caja=caja,
            sold_by=request.user,
            payment_method=payment_method,
            lines_data=lines_data,
            customer_email=data.get('email', ''),
            mark_as_used=data.get('mark_as_used', False),
        )
    except InsufficientStockError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    if sale.status == CajaSale.Status.PAID:
        return JsonResponse({
            'sale_id': sale.id,
            'status': sale.status,
            'total_amount': str(sale.total_amount),
            'order_key': str(sale.order.key) if sale.order_id else None,
            'caja_totals': _serialized_caja_payment_totals(caja),
        })

    return JsonResponse({
        'sale_id': sale.id,
        'status': sale.status,
        'total_amount': str(sale.total_amount),
        'caja_totals': _serialized_caja_payment_totals(caja),
    })


@login_required
@require_GET
def api_sale_status(request, event_slug, caja_id, sale_id):
    event = get_event_for_caja(request.user, event_slug)
    caja = get_object_or_404(EventCaja, id=caja_id, event=event)
    sale = get_object_or_404(CajaSale, id=sale_id, event_caja=caja)

    return JsonResponse({
        'sale_id': sale.id,
        'status': sale.status,
        'total_amount': str(sale.total_amount),
        'order_key': str(sale.order.key) if sale.order_id else None,
        'caja_totals': _serialized_caja_payment_totals(caja),
    })


@login_required
@require_POST
def api_cancel_sale(request, event_slug, caja_id, sale_id):
    event = get_event_for_caja(request.user, event_slug)
    caja = get_object_or_404(EventCaja, id=caja_id, event=event)
    sale = get_object_or_404(CajaSale, id=sale_id, event_caja=caja)

    if sale.status != CajaSale.Status.PENDING:
        return JsonResponse({'error': 'La venta no está pendiente'}, status=400)

    sale.status = CajaSale.Status.CANCELLED
    sale.save(update_fields=['status', 'updated_at'])
    return JsonResponse({'sale_id': sale.id, 'status': sale.status})


@login_required
@require_POST
def api_cancel_paid_sale(request, event_slug, caja_id, sale_id):
    event = get_event_for_caja(request.user, event_slug)
    caja = get_object_or_404(EventCaja, id=caja_id, event=event)
    sale = get_object_or_404(
        CajaSale,
        id=sale_id,
        event_caja=caja,
        status=CajaSale.Status.PAID,
        sale_type=CajaSale.SaleType.SALE,
    )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    reason = (data.get('reason') or '').strip()
    if not reason:
        return JsonResponse({'error': 'Debe indicar un motivo'}, status=400)

    with transaction.atomic():
        sale = CajaSale.objects.select_for_update().get(pk=sale.pk)
        if sale.cancellations.exists():
            return JsonResponse({'error': 'La transacción ya fue cancelada'}, status=400)

        cancellation = CajaSale.objects.create(
            event_caja=sale.event_caja,
            sold_by=request.user,
            payment_method=sale.payment_method,
            sale_type=CajaSale.SaleType.CANCELLATION,
            status=CajaSale.Status.PAID,
            total_amount=-sale.total_amount,
            customer_email=sale.customer_email,
            related_sale=sale,
            notes=f'Cancelación de tx #{sale.id}. Motivo: {reason}',
            mark_as_used=False,
        )

    return JsonResponse({
        'sale_id': sale.id,
        'cancellation_id': cancellation.id,
        'status': 'ok',
    })
