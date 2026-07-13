from django.http import HttpResponse
from django.template import loader

from events.models import Event
from events.utils import get_event_from_request
from tickets.models import Coupon, TicketType


def home(request, event_slug=None):
    context = {}

    # If a specific event slug is requested, show that single event page
    if event_slug:
        event = Event.get_by_slug(event_slug)
        if not event:
            return HttpResponse('Event not found', status=404)

        coupon = Coupon.objects.filter(token=request.GET.get('coupon'), ticket_type__event=event).first()
        from django.utils import timezone
        from django.db.models import Q
        ticket_types = (TicketType.objects
                      .filter(event=event)
                      .filter(Q(ticket_count__gt=0) | Q(ticket_count__isnull=True))
                      .filter(is_direct_type=False)
                      .filter(do_not_show_in_checkout=False)
                      .order_by('occurrence_date', 'cardinality', 'price'))

        if event.is_recurring:
            # For recurring events, only show future occurrences
            ticket_types = ticket_types.filter(
                Q(occurrence_date__gt=timezone.now()) | Q(occurrence_date__isnull=True)
            )
        else:
            # For one-off events, auto-close sales when event has started
            if event.start and event.start <= timezone.now():
                ticket_types = ticket_types.none()

        next_ticket_type = None
        if not ticket_types.exists():
            next_ticket_type = TicketType.objects.get_next_ticket_type_available(event)

        context.update({
            'coupon': coupon,
            'ticket_types': ticket_types,
            'current_event': event,
            'event': event,
        })
        if next_ticket_type:
            context['next_ticket_type'] = next_ticket_type

        template = loader.get_template('tickets/home.html')
        return HttpResponse(template.render(context, request))

    # Homepage: show gallery of all upcoming published events
    from django.utils import timezone
    from django.db.models import Q
    now = timezone.now()
    active_events = Event.get_active_events().filter(
        Q(end__gte=now) | Q(end__isnull=True, start__gte=now)
    ).order_by('start')
    context['active_events'] = active_events
    context['event'] = None  # override context processor so gallery renders

    template = loader.get_template('tickets/home.html')
    return HttpResponse(template.render(context, request))


def events_listing(request):
    """List all active upcoming events"""
    from django.shortcuts import render
    from django.utils import timezone

    # Only show events that haven't ended yet
    active_events = Event.get_active_events().filter(end__gte=timezone.now())

    context = {
        'active_events': active_events,
    }

    return render(request, 'tickets/events_listing.html', context)


def ping(request):
    response = HttpResponse('pong 🏓')
    response['x-depreheader'] = 'tu vieja'
    return response
