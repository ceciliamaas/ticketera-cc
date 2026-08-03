import json
import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from caja.context import mi_fuego_admin_context
from caja.forms import (
    EventCajaCreateForm,
    EventCajaForm,
    EventProductCreateForm,
    EventProductEditForm,
    EventProductForm,
    StockQuantityForm,
)
from caja.models import (
    CajaSale,
    EventCaja,
    EventCajaProduct,
    EventProduct,
    EventProductStockRecord,
)
from caja.permissions import get_event_for_admin, get_event_for_caja, user_has_caja_access
from caja.stock import adjust_stock, available, ensure_stock_row, initialize_product_stock, set_unlimited
from events.models import Event

logger = logging.getLogger(__name__)


@login_required
def products_list_view(request, event_slug):
    event = get_event_for_admin(request.user, event_slug)
    products = EventProduct.objects.filter(event=event).select_related('ticket_type', 'stock')

    if request.method == 'POST' and request.POST.get('action') == 'create':
        form = EventProductCreateForm(request.POST, event=event)
        if form.is_valid():
            product = form.save(commit=False)
            product.event = event
            if product.ticket_type_id:
                product.name = product.ticket_type.name
                if product.price is None:
                    product.price = product.ticket_type.price
            product.save()
            initialize_product_stock(
                product,
                unlimited=form.cleaned_data.get('unlimited_stock'),
                initial_quantity=form.cleaned_data.get('initial_stock'),
                user=request.user,
            )
            messages.success(request, f'Producto "{product.display_name}" creado.')
            return redirect('caja_products', event_slug=event.slug)
    else:
        form = EventProductCreateForm(event=event)

    context = mi_fuego_admin_context(request, event, f'caja_products_{event.slug}')
    context.update({'products': products, 'form': form})
    return render(request, 'mi_fuego/caja_v2/products_list.html', context)


@login_required
def product_edit_view(request, event_slug, product_id):
    event = get_event_for_admin(request.user, event_slug)
    product = get_object_or_404(EventProduct, id=product_id, event=event)
    stock = ensure_stock_row(product)
    is_unlimited = stock.quantity is None

    if request.method == 'POST':
        form = EventProductEditForm(
            request.POST,
            request.FILES,
            instance=product,
            event=event,
            stock_unlimited=is_unlimited,
        )
        if form.is_valid():
            product = form.save()
            unlimited = form.cleaned_data.get('unlimited_stock')
            if unlimited:
                set_unlimited(product, True, request.user)
            elif is_unlimited:
                set_unlimited(product, False, request.user)
            messages.success(request, 'Producto actualizado.')
            return redirect('caja_product_edit', event_slug=event.slug, product_id=product.id)
    else:
        form = EventProductEditForm(instance=product, event=event, stock_unlimited=is_unlimited)

    context = mi_fuego_admin_context(request, event, f'caja_products_{event.slug}')
    context.update({
        'product': product,
        'form': form,
        'is_unlimited': is_unlimited,
    })
    return render(request, 'mi_fuego/caja_v2/product_edit.html', context)


@login_required
def product_stock_view(request, event_slug, product_id):
    event = get_event_for_admin(request.user, event_slug)
    product = get_object_or_404(EventProduct, id=product_id, event=event)
    stock = ensure_stock_row(product)
    records = EventProductStockRecord.objects.filter(event_product=product)[:20]
    is_unlimited = stock.quantity is None

    if request.method == 'POST':
        action = request.POST.get('action')
        if action not in ('add_stock', 'remove_stock'):
            raise Http404('Acción inválida')

        stock.refresh_from_db()
        if stock.quantity is None:
            messages.error(request, 'No podés ajustar stock mientras el producto es ilimitado.')
            return redirect('caja_product_stock', event_slug=event.slug, product_id=product.id)

        stock_form = StockQuantityForm(request.POST)
        if stock_form.is_valid():
            qty = stock_form.cleaned_data['quantity']
            delta = qty if action == 'add_stock' else -qty
            notes = stock_form.cleaned_data.get('notes', '')
            adjust_stock(product, delta, request.user, notes=notes)
            verb = 'agregado' if action == 'add_stock' else 'quitado'
            messages.success(request, f'Stock {verb}: {qty} unidad(es).')
            return redirect('caja_product_stock', event_slug=event.slug, product_id=product.id)

        for field, errors in stock_form.errors.items():
            for error in errors:
                messages.error(request, f'{field}: {error}')
    else:
        stock_form = StockQuantityForm()

    context = mi_fuego_admin_context(request, event, f'caja_products_{event.slug}')
    context.update({
        'product': product,
        'stock': stock,
        'stock_form': stock_form,
        'records': records,
        'available': available(product),
        'is_unlimited': is_unlimited,
    })
    return render(request, 'mi_fuego/caja_v2/product_stock.html', context)


@login_required
def cajas_list_view(request, event_slug):
    event = get_event_for_admin(request.user, event_slug)
    cajas = EventCaja.objects.filter(event=event).prefetch_related('products')

    if request.method == 'POST' and request.POST.get('action') == 'create':
        form = EventCajaCreateForm(request.POST)
        if form.is_valid():
            caja = form.save(commit=False)
            caja.event = event
            caja.save()
            messages.success(request, f'Caja "{caja.name}" creada.')
            return redirect('caja_v2_edit', event_slug=event.slug, caja_id=caja.id)
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f'{field}: {error}')
    else:
        form = EventCajaCreateForm()

    context = mi_fuego_admin_context(request, event, f'cajas_v2_{event.slug}')
    context.update({'cajas': cajas, 'form': form})
    return render(request, 'mi_fuego/caja_v2/cajas_list.html', context)


@login_required
def caja_edit_view(request, event_slug, caja_id):
    event = get_event_for_admin(request.user, event_slug)
    caja = get_object_or_404(EventCaja, id=caja_id, event=event)
    active_products = list(
        EventProduct.objects.filter(event=event, is_active=True)
        .select_related('ticket_type')
        .order_by('name', 'id')
    )
    generic_products = [p for p in active_products if p.ticket_type_id is None]
    ticket_products = [p for p in active_products if p.ticket_type_id is not None]
    inactive_generic_products = list(
        EventProduct.objects.filter(
            event=event,
            is_active=False,
            ticket_type__isnull=True,
        ).order_by('name', 'id')
    )
    assigned_ids = set(
        EventCajaProduct.objects.filter(event_caja=caja).values_list('event_product_id', flat=True)
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_caja':
            form = EventCajaForm(request.POST, instance=caja)
            if form.is_valid():
                form.save()
                messages.success(request, 'Caja actualizada.')
                return redirect('caja_v2_edit', event_slug=event.slug, caja_id=caja.id)
        elif action == 'save_products':
            selected = request.POST.getlist('products')
            with transaction.atomic():
                EventCajaProduct.objects.filter(event_caja=caja).delete()
                for idx, pid in enumerate(selected):
                    EventCajaProduct.objects.create(
                        event_caja=caja,
                        event_product_id=int(pid),
                        sort_order=idx,
                    )
            messages.success(request, 'Productos de la caja actualizados.')
            return redirect('caja_v2_edit', event_slug=event.slug, caja_id=caja.id)

    context = mi_fuego_admin_context(request, event, f'cajas_v2_{event.slug}')
    context.update({
        'caja': caja,
        'caja_form': EventCajaForm(instance=caja),
        'active_products': active_products,
        'all_products': active_products,
        'ticket_products': ticket_products,
        'generic_products': generic_products,
        'inactive_generic_products': inactive_generic_products,
        'assigned_ids': assigned_ids,
    })
    return render(request, 'mi_fuego/caja_v2/caja_edit.html', context)


@login_required
def caja_events_v2_view(request):
    return redirect('caja_events')
