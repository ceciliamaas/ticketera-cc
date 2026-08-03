import logging

from django.forms import modelformset_factory, BaseModelFormSet
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.template import loader
from django.urls import reverse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from events.models import Event
from tickets.models import Order, TicketType, OrderTicket, Coupon, Ticket
from tickets.forms import OrderForm, CheckoutTicketSelectionForm, TicketForm

from .utils import is_order_valid, _complete_order

class BaseTicketFormset(BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        super(BaseTicketFormset, self).__init__(*args, **kwargs)
        self.queryset = Ticket.objects.none()
def order(request, ticket_type_id):
    try:
        from events.utils import get_event_from_request
        event = get_event_from_request(request)
    except Exception:
        return HttpResponse('Lo sentimos, este link es inválido.', status=404)

    coupon = Coupon.objects.filter(token=request.GET.get('coupon')).first()
    ticket_types = TicketType.objects.get_available(coupon, event)

    for ticket_type in ticket_types:
        if ticket_type.pk == ticket_type_id:
            break
    if ticket_type.pk != ticket_type_id:
        return HttpResponse('Lo sentimos, este link es inválido.', status=404)

    max_tickets = min(ticket_type.available_tickets, coupon.tickets_remaining() if coupon else 5, event.tickets_remaining())
    order_form = OrderForm(request.POST or None)
    TicketsFormSet = modelformset_factory(Ticket, formset=BaseTicketFormset, form=TicketForm,
                                          max_num=max_tickets, validate_max=True, min_num=1, validate_min=True,
                                          extra=0)
    tickets_formset = TicketsFormSet(request.POST or None)

    if request.method == 'POST':
        if order_form.is_valid() and tickets_formset.is_valid():
            order = order_form.save(commit=False)
            if coupon:
                order.coupon = coupon
            order.ticket_type = ticket_type
            order.coupon = coupon
            tickets = tickets_formset.save(commit=False)
            price = ticket_type.price_with_coupon if order.coupon else ticket_type.price
            order.amount = len(tickets) * price
            order.amount += order.donation_art or 0
            order.amount += order.donation_grant or 0
            order.amount += order.donation_venue or 0
            order.save()
            for ticket in tickets:
                ticket.order = order
                ticket.price = price
                ticket.save()

            return HttpResponseRedirect(redirect_to=reverse('order_detail', kwargs={'order_key': order.key}))

    template = loader.get_template('tickets/order_new.html')
    context = {
        'max_tickets': max_tickets,
        'ticket_type': ticket_type,
        'order_form': order_form,
        'coupon': coupon,
        'tickets_formset': tickets_formset,
    }

    return HttpResponse(template.render(context, request))

def order_detail(request, order_key):
    order = Order.objects.get(key=order_key)

    context = {
        'order': order,
        'event': order.ticket_type.event,
        'is_order_valid': (order.status == 'CONFIRMED') or is_order_valid(order),
    }

    template = loader.get_template('tickets/order_detail.html')
    rendered_template = template.render(context, request)

    return HttpResponse(rendered_template)

def free_order_confirmation(request, order_key):
    order = Order.objects.get(key=order_key)

    if not is_order_valid(order):
        return HttpResponse('Lo sentimos, este link es inválido.', status=404)

    if order.amount > 0:
        raise HttpResponseBadRequest('This order cannot be confirmed without payment')

    return _complete_order(order)

def payment_success(request, order_key):
    order = Order.objects.get(key=order_key)
    order.response = request.GET.dict()
    order.save(update_fields=['response'])
    return HttpResponseRedirect(order.get_resource_url())

def payment_failure(request, order_key):
    return HttpResponse('PAYMENT FAILURE')

def payment_pending(request, order_key):
    return HttpResponse('PAYMENT PENDING')

@csrf_exempt
def payment_notification(request):
    return HttpResponse('OK')

@login_required
def check_order_status(request, order_key):
    try:
        order = Order.objects.get(key=order_key)
    except Order.DoesNotExist:
        return JsonResponse({"status": "error"}, status=404)

    if order.email != request.user.email:
        return HttpResponseForbidden('Forbidden')

    payload = {"status": order.status}
    if order.status == Order.OrderStatus.CONFIRMED:
        try:
            from logros.services import check_and_unlock_for_user, get_pending_celebrations
            check_and_unlock_for_user(request.user)
            pending = get_pending_celebrations(request.user)
            payload['new_achievements'] = [
                {
                    'slug': ua.achievement.slug,
                    'name': ua.achievement.name,
                    'description': ua.achievement.description,
                    'image_url': ua.achievement.image_url,
                }
                for ua in pending
            ]
        except Exception as e:
            logging.warning('check_order_status: logros service error: %s', e)
            payload['new_achievements'] = []

    return JsonResponse(payload)

@login_required
def checkout_payment_callback(request, order_key):
    request.session.pop('ticket_selection', None)
    request.session.pop('donations', None)
    request.session.pop('order_sid', None)

    return render(request, 'checkout/payment_callback.html', {
        'order_key': order_key,
    })
