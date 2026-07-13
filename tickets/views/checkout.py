import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from events.models import Event, EventTermsAndConditions, EventTermsAndConditionsAcceptance
from events.utils import get_event_from_request, store_event_in_session
from tickets.forms import CheckoutTicketSelectionForm
from tickets.models import TicketType, Order, OrderTicket


def _checkout_door_context(event, ticket_data):
    if ticket_data or not event.show_door_remaining:
        return {}
    return {
        'show_door_remaining_notice': True,
        'door_tickets_remaining': event.door_tickets_remaining(),
    }


def _parse_occurrence_date(occ_ts):
    """Convert Unix timestamp string to aware datetime, or None."""
    if not occ_ts:
        return None
    try:
        from datetime import datetime, timezone as dt_tz
        return datetime.fromtimestamp(int(occ_ts), tz=dt_tz.utc)
    except (ValueError, TypeError):
        return None


@login_required
def select_tickets(request, event_slug=None):
    # Get event from URL slug or request
    if event_slug:
        event = Event.get_by_slug(event_slug)
        if not event:
            return HttpResponse('Event not found', status=404)
    else:
        event = get_event_from_request(request)
    
    # Store event in session for checkout flow
    store_event_in_session(request, event)

    if event.reservations_closed:
        return render(request, 'checkout/select_tickets.html', {
            'reservations_closed': True,
            'event': event,
            'current_event': event,
        })
    
    if request.method == 'POST':
        occ_ts = request.session.get('occ_ts')
        occurrence_date = _parse_occurrence_date(occ_ts)
        form = CheckoutTicketSelectionForm(request.POST, user=request.user, event=event, occurrence_date=occurrence_date)
        if form.is_valid():
            request.session['ticket_selection'] = form.cleaned_data
            # Skip donations step — set empty donations and order_sid directly
            request.session['donations'] = {}
            request.session['order_sid'] = str(uuid.uuid4())
            if event.slug:
                return redirect(f"{reverse('order_summary')}?event={event.slug}")
            return redirect('order_summary')
        else:
            tickets_remaining = event.tickets_remaining() or 0
            available_tickets = min(event.max_tickets_per_order, tickets_remaining) if event.max_tickets_per_order else tickets_remaining
            context = {
                'form': form,
                'ticket_data': form.ticket_data,
                'available_tickets': available_tickets,
                'tickets_remaining': tickets_remaining,
                'current_event': event,
                'event': event,
                'occurrence_date': _parse_occurrence_date(request.session.get('occ_ts')),
            }
            context.update(_checkout_door_context(event, form.ticket_data))
            return render(request, 'checkout/select_tickets.html', context)

    tickets_remaining = event.tickets_remaining() or 0
    available_tickets = min(event.max_tickets_per_order, tickets_remaining) if event.max_tickets_per_order else tickets_remaining

    initial_data = request.session.get('ticket_selection', {})

    if 'new' in request.GET or request.session.get('order_sid') is None:
        request.session['order_sid'] = str(uuid.uuid4())
        request.session['event_id'] = event.id
        request.session.pop('ticket_selection', None)
        request.session.pop('donations', None)
        occ_ts = request.GET.get('occ')
        request.session['occ_ts'] = occ_ts  # store (None clears previous)
        ticket_id = request.GET.get('ticket_id')
        if ticket_id:
            initial_data[f'ticket_{ticket_id}_quantity'] = 1
    else:
        occ_ts = request.session.get('occ_ts')

    occurrence_date = _parse_occurrence_date(occ_ts)
    form = CheckoutTicketSelectionForm(initial=initial_data, event=event, occurrence_date=occurrence_date)

    context = {
        'form': form,
        'ticket_data': form.ticket_data,
        'available_tickets': available_tickets,
        'tickets_remaining': tickets_remaining,
        'current_event': event,
        'event': event,
        'occurrence_date': occurrence_date,
    }
    context.update(_checkout_door_context(event, form.ticket_data))
    return render(request, 'checkout/select_tickets.html', context)


@login_required
def select_donations(request, event_slug=None):
    # Get event from session or request
    event = get_event_from_request(request)
    
    if request.method == 'POST':
        form = CheckoutDonationsForm(request.POST)
        if form.is_valid():
            request.session['donations'] = form.cleaned_data
            # Redirect with event parameter
            if event.slug:
                return redirect(f"{reverse('order_summary')}?event={event.slug}")
            return redirect('order_summary')

    if 'new' in request.GET or request.session.get('order_sid') is None:
        request.session['order_sid'] = str(uuid.uuid4())
        request.session.pop('ticket_selection', None)
        request.session.pop('donations', None)

    initial_data = request.session.get('donations', {})
    form = CheckoutDonationsForm(initial=initial_data)

    return render(request, 'checkout/select_donations.html', {
        'form': form,
        'ticket_selection': request.session.get('ticket_selection', None),
        'current_event': event,
    })


@login_required
def order_summary(request, event_slug=None):
    event = get_event_from_request(request)
    
    if request.session.get('order_sid') is None:
        if event.slug:
            return redirect(f"{reverse('select_tickets')}?event={event.slug}")
        return redirect('select_tickets')

    ticket_selection = request.session.get('ticket_selection', {})
    donations = request.session.get('donations', {})

    total_amount = 0
    ticket_data = []
    items = []

    # Filter ticket types by the specific event using the same logic as get_available_ticket_types_for_current_events
    from django.utils import timezone
    from django.db.models import Q
    ticket_types = (TicketType.objects
                  .filter(event=event)
                  .filter(Q(date_from__lte=timezone.now()) | Q(date_from__isnull=True))
                  .filter(Q(date_to__gte=timezone.now()) | Q(date_to__isnull=True))
                  .filter(Q(ticket_count__gt=0) | Q(ticket_count__isnull=True))
                  .filter(is_direct_type=False)
                  .filter(do_not_show_in_checkout=False)
                  .order_by('cardinality', 'price'))

    for ticket_type in ticket_types:
        field_name = f'ticket_{ticket_type.id}_quantity'
        quantity = ticket_selection.get(field_name, 0)
        price = ticket_type.price or 0

        # For free tickets (price = 0), use custom amount
        if price == 0:
            custom_amount_field = f'ticket_{ticket_type.id}_custom_amount'
            custom_amount = float(ticket_selection.get(custom_amount_field) or 0)
            subtotal = custom_amount * quantity
            effective_price = custom_amount
        else:
            subtotal = price * quantity
            effective_price = price

        if quantity > 0:
            total_amount += subtotal
            ticket_data.append({
                'id': ticket_type.id,
                'name': ticket_type.name,
                'description': ticket_type.description,
                'price': effective_price,
                'quantity': quantity,
                'subtotal': subtotal,
                'is_free_ticket': False,  # Price 0 = free, never a custom amount
                'original_price': price,
            })
            items.append({
                "id": ticket_type.name,
                "title": ticket_type.name,
                "description": ticket_type.description,
                "quantity": quantity,
                "unit_price": float(effective_price),
            })

    donation_data = []

    for donation_type, donation_name in [('donation_art', 'Becas de Arte'), ('donation_venue', 'Donaciones a La Sede'),
                                         ('donation_grant', 'Beca Inclusión Radical')]:
        donation_amount = donations.get(donation_type, 0)
        if donation_amount > 0:
            total_amount += donation_amount
            donation_data.append({
                'id': donation_type,
                'name': donation_name,
                'quantity': 1,
                'subtotal': donation_amount,
            })
            items.append({
                "id": donation_type,
                "title": donation_name,
                "quantity": 1,
                "unit_price": donation_amount,
            })

    # Get terms and conditions for the event
    terms_and_conditions = event.terms_and_conditions.all().order_by('order', 'id')

    if request.method == 'POST':
        # Validate that all terms and conditions are accepted
        accepted_terms = request.POST.getlist('accepted_terms')
        required_term_ids = set(terms_and_conditions.values_list('id', flat=True))
        accepted_term_ids = set(int(term_id) for term_id in accepted_terms if term_id)
        
        if required_term_ids != accepted_term_ids:
            return render(request, 'checkout/order_summary.html', {
                'ticket_data': ticket_data,
                'donation_data': donation_data,
                'total_amount': total_amount,
                'terms_and_conditions': terms_and_conditions,
                'current_event': event,
                'error_message': 'Debes aceptar todos los términos y condiciones para continuar.',
            })

        total_quantity = sum(item['quantity'] for item in ticket_data)
        remaining_event_tickets = event.tickets_remaining()

        if event.max_tickets_per_order and total_quantity > event.max_tickets_per_order:
            return HttpResponse('Superaste la cantidad máxima de tickets permitida.', status=401)

        # Check if any ticket type ignores max amount
        has_ignore_max_amount = any(
            ticket_type.ignore_max_amount 
            for ticket_type in ticket_types 
            if ticket_selection.get(f'ticket_{ticket_type.id}_quantity', 0) > 0
        )

        # Only check remaining event tickets if no ticket type ignores max amount
        if not has_ignore_max_amount and total_quantity > remaining_event_tickets:
            return HttpResponse('No hay suficientes tickets disponibles.', status=400)

        with transaction.atomic():
            _profile = getattr(request.user, 'profile', None)
            order = Order(
                first_name=request.user.first_name or '',
                last_name=request.user.last_name or '',
                email=request.user.email,
                phone=getattr(_profile, 'phone', '') or '',
                dni=getattr(_profile, 'document_number', '') or '',
                amount=total_amount,
                status=Order.OrderStatus.PENDING,
                event=event,
                user=request.user,
                order_type=Order.OrderType.ONLINE_PURCHASE,
            )
            order.save()

            if ticket_types.exists():
                order_tickets = [
                    OrderTicket(
                        order=order,
                        ticket_type=ticket_type,
                        quantity=quantity
                    )
                    for ticket_type in ticket_types
                    if (quantity := ticket_selection.get(f'ticket_{ticket_type.id}_quantity', 0)) > 0
                ]
                if order_tickets:
                    OrderTicket.objects.bulk_create(order_tickets)
            
            # Crear registros de aceptación de términos y condiciones
            if terms_and_conditions.exists():
                acceptances = [
                    EventTermsAndConditionsAcceptance(
                        user=request.user,
                        term=term,
                        order=order
                    )
                    for term in terms_and_conditions
                ]
                # Usar get_or_create para evitar duplicados si ya existe
                for acceptance in acceptances:
                    EventTermsAndConditionsAcceptance.objects.get_or_create(
                        user=acceptance.user,
                        term=acceptance.term,
                        defaults={'order': acceptance.order}
                    )

        # Confirm immediately — no payment gateway
        from tickets.processing import mint_tickets
        mint_tickets(order)
        return redirect(reverse('checkout_payment_callback', kwargs={'order_key': order.key}))

    return render(request, 'checkout/order_summary.html', {
        'ticket_data': ticket_data,
        'donation_data': donation_data,
        'total_amount': total_amount,
        'terms_and_conditions': terms_and_conditions,
        'current_event': event,
    })


def view_term_description(request, slug):
    """View to display the full description of a term and condition"""
    term = get_object_or_404(EventTermsAndConditions, slug=slug)
    
    return render(request, 'checkout/term_description.html', {
        'term': term,
        'event': term.event,
    })
