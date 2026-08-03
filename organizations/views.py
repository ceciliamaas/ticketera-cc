import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib.auth.models import User
from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST

from django.utils.text import slugify
from events.models import Event
from .forms import EventForm, OrganizationForm, TicketTypeFormSet
from .models import Organization, OrganizationMembership, OrganizationInvitation
from .permissions import get_authorized_organization, user_can_edit_event

logger = logging.getLogger(__name__)


@login_required
def dashboard_home(request):
    """Show orgs the user belongs to; redirect directly if only one."""
    memberships = request.user.organization_memberships.select_related('organization').filter(
        organization__is_active=True
    )
    if memberships.count() == 1:
        return redirect('dashboard_event_list', org_slug=memberships.first().organization.slug)
    return render(request, 'dashboard/org_select.html', {'memberships': memberships})


@login_required
def dashboard_event_list(request, org_slug):
    from django.utils import timezone
    from tickets.models import Order
    organization = get_authorized_organization(request.user, org_slug)
    now = timezone.now()
    all_events = Event.objects.filter(organization=organization).order_by('-start')
    from django.db.models import Q
    # Upcoming: end in the future, or no end date and start in the future
    upcoming_events = all_events.filter(
        Q(end__gte=now) | Q(end__isnull=True, start__gte=now)
    ).exclude(status=Event.Status.CANCELLED)
    # Past: ended and not cancelled
    past_events = all_events.filter(
        Q(end__lt=now) | Q(end__isnull=True, start__lt=now)
    ).exclude(status=Event.Status.CANCELLED)
    # Cancelled events in their own bucket
    cancelled_events = all_events.filter(status=Event.Status.CANCELLED)
    # Build a dict of order counts per event id for delete confirmation
    order_counts = {
        row['event_id']: row['cnt']
        for row in Order.objects.filter(event__organization=organization)
                                .values('event_id')
                                .annotate(cnt=models.Count('id'))
    }
    return render(request, 'dashboard/event_list.html', {
        'organization': organization,
        'upcoming_events': upcoming_events,
        'past_events': past_events,
        'cancelled_events': cancelled_events,
        'order_counts': order_counts,
    })


@login_required
@transaction.atomic
def dashboard_event_create(request, org_slug):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES)
        formset = TicketTypeFormSet(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.organization = organization
            if not event.slug:
                event.slug = slugify(event.name)
            if not event.max_tickets_per_order:
                event.max_tickets_per_order = 0
            # Ensure slug is unique within the organization
            base_slug = event.slug
            counter = 1
            qs = Event.objects.filter(organization=organization, slug=event.slug)
            if event.pk:
                qs = qs.exclude(pk=event.pk)
            while qs.exists():
                event.slug = f'{base_slug}-{counter}'
                counter += 1
                qs = Event.objects.filter(organization=organization, slug=event.slug)
                if event.pk:
                    qs = qs.exclude(pk=event.pk)
            event.save()
            formset = TicketTypeFormSet(request.POST, instance=event)
            if formset.is_valid():
                formset.save()
                if event.max_tickets:
                    total = sum(
                        tt.ticket_count or 0
                        for tt in event.tickettype_set.exclude(ticket_count__isnull=True)
                    )
                    if total > event.max_tickets:
                        messages.warning(
                            request,
                            f'Atención: la suma de entradas por tipo ({total}) supera el máximo del evento ({event.max_tickets}). Máximo disponible: {event.max_tickets}.'
                        )
            messages.success(request, f'Evento "{event.name}" creado.')
            return redirect(reverse('dashboard_event_edit', kwargs={'org_slug': org_slug, 'event_id': event.pk}) + '?created=1')
    else:
        form = EventForm(initial={
            'location': organization.location,
            'address': organization.address,
            'location_url': organization.location_url,
            'ciudad': organization.ciudad,
        })
        formset = TicketTypeFormSet()
    return render(request, 'dashboard/event_form.html', {
        'organization': organization,
        'form': form,
        'formset': formset,
        'action': 'Crear',
    })


@login_required
def dashboard_event_reservas(request, org_slug, event_id):
    from django.db.models import Sum, Count
    from tickets.models import Order, OrderTicket
    from events.models import EventInvitation
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_invitation':
            name = request.POST.get('invitation_name', '').strip()
            if name:
                EventInvitation.objects.create(event=event, name=name)
                event.invitations_count = EventInvitation.objects.filter(event=event).count()
                event.save(update_fields=['invitations_count'])
                messages.success(request, f'Invitación agregada: {name}')
        elif action == 'remove_invitation':
            inv_id = request.POST.get('invitation_id')
            inv = get_object_or_404(EventInvitation, pk=inv_id, event=event)
            if inv.checked_in:
                messages.error(request, f'No se puede eliminar a {inv.name}: ya realizó el check-in.')
            else:
                inv.delete()
                event.invitations_count = EventInvitation.objects.filter(event=event).count()
                event.save(update_fields=['invitations_count'])
        elif action == 'toggle_checkin_ticket':
            from tickets.models import NewTicket
            ticket_id = request.POST.get('ticket_id')
            ticket = get_object_or_404(NewTicket, pk=ticket_id, event=event)
            ticket.is_used = not ticket.is_used
            ticket.save(update_fields=['is_used'])
        elif action == 'toggle_checkin_invitation':
            inv_id = request.POST.get('invitation_id')
            inv = get_object_or_404(EventInvitation, pk=inv_id, event=event)
            inv.checked_in = not inv.checked_in
            inv.save(update_fields=['checked_in'])
        elif action == 'close_reservations':
            event.reservations_closed = True
            event.save(update_fields=['reservations_closed'])
            messages.success(request, 'Ventas cerradas. Ya no se pueden comprar nuevas entradas.')
        elif action == 'reopen_reservations':
            event.reservations_closed = False
            event.save(update_fields=['reservations_closed'])
            messages.success(request, 'Ventas reabiertas.')
        return redirect('dashboard_event_reservas', org_slug=org_slug, event_id=event_id)

    orders = (
        Order.objects.filter(event=event, status=Order.OrderStatus.CONFIRMED)
        .select_related('user')
        .prefetch_related('order_tickets__ticket_type')
        .order_by('-created_at')
    )

    tickets_sold = (
        OrderTicket.objects.filter(
            order__event=event,
            order__status=Order.OrderStatus.CONFIRMED,
            ticket_type__ignore_max_amount=False,
        ).aggregate(total=Sum('quantity'))['total'] or 0
    )
    total_revenue = orders.aggregate(total=Sum('amount'))['total'] or 0
    capacity = event.max_tickets or '∞'
    remaining = event.tickets_remaining() if event.max_tickets else None

    from events.models import EventInvitation
    from tickets.models import NewTicket
    # Build per-ticket display names for the attendees list
    all_new_tickets = (
        NewTicket.objects.filter(
            order__event=event,
            order__status=Order.OrderStatus.CONFIRMED,
        )
        .select_related('holder', 'ticket_type', 'order')
        .order_by('order_id', 'id')
    )
    # Count tickets per order first to decide whether to add a number suffix
    order_totals: dict = {}
    for t in all_new_tickets:
        oid = str(t.order.id)
        order_totals[oid] = order_totals.get(oid, 0) + 1
    # Build display rows
    order_counters: dict = {}
    ticket_rows = []
    for t in all_new_tickets:
        oid = str(t.order.id)
        order_counters[oid] = order_counters.get(oid, 0) + 1
        holder_name = (
            (t.holder.get_full_name().strip() if t.holder else '')
            or f"{t.order.first_name} {t.order.last_name}".strip()
        )
        if order_totals.get(oid, 1) > 1:
            display_name = f"{holder_name} {order_counters[oid]}" if holder_name else str(order_counters[oid])
        else:
            display_name = holder_name
        ticket_rows.append({'ticket': t, 'display_name': display_name})

    # Named invitations
    invitations = EventInvitation.objects.filter(event=event)

    # Combined attendee list: tickets first (sold), then invitations
    attendees = []
    for row in ticket_rows:
        attendees.append({
            'name': row['display_name'],
            'type': 'venta',
            'ticket_id': row['ticket'].id,
            'invitation_id': None,
            'checked_in': row['ticket'].is_used,
        })
    for inv in invitations:
        attendees.append({
            'name': inv.name,
            'type': 'invitacion',
            'ticket_id': None,
            'invitation_id': inv.id,
            'checked_in': inv.checked_in,
        })
    # Sort: tickets first (by name), then invitations (by name) - no check-in sorting
    attendees.sort(key=lambda a: a['name'].lower())

    return render(request, 'dashboard/event_reservas.html', {
        'organization': organization,
        'event': event,
        'orders': orders,
        'tickets_sold': tickets_sold,
        'total_revenue': total_revenue,
        'capacity': capacity,
        'remaining': remaining,
        'ticket_rows': ticket_rows,
        'invitations': invitations,
        'attendees': attendees,
    })


@login_required
@transaction.atomic
def dashboard_event_edit(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        formset = TicketTypeFormSet(request.POST, instance=event)
        if form.is_valid() and formset.is_valid():
            event = form.save(commit=False)
            if not event.max_tickets_per_order:
                event.max_tickets_per_order = 0
            if not event.slug:
                event.slug = slugify(event.name)
            # Ensure slug uniqueness within the org
            base_slug = event.slug
            counter = 1
            qs = Event.objects.filter(organization=organization, slug=event.slug).exclude(pk=event.pk)
            while qs.exists():
                event.slug = f'{base_slug}-{counter}'
                counter += 1
                qs = Event.objects.filter(organization=organization, slug=event.slug).exclude(pk=event.pk)
            event.save()
            formset.save()
            # Validate ticket_count sum vs max_tickets
            if event.max_tickets:
                total = sum(
                    tt.ticket_count or 0
                    for tt in event.tickettype_set.exclude(ticket_count__isnull=True)
                )
                if total > event.max_tickets:
                    messages.warning(
                        request,
                        f'Atención: la suma de entradas por tipo ({total}) supera el máximo del evento ({event.max_tickets}).'
                    )
            messages.success(request, f'Evento "{event.name}" guardado.')
            return redirect(reverse('dashboard_event_list', kwargs={'org_slug': org_slug}))
    else:
        form = EventForm(instance=event)
        formset = TicketTypeFormSet(instance=event)
    return render(request, 'dashboard/event_form.html', {
        'organization': organization,
        'event': event,
        'form': form,
        'formset': formset,
        'action': 'Editar',
    })


@login_required
@require_POST
def dashboard_event_cancel(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    event.status = Event.Status.CANCELLED
    event.save(update_fields=['status'])
    messages.success(request, f'Evento "{event.name}" cancelado. Las entradas vendidas ahora aparecen como canceladas.')
    return redirect('dashboard_event_list', org_slug=org_slug)


@login_required
@require_POST
def dashboard_event_delete(request, org_slug, event_id):
    from django.db import transaction
    from tickets.models import Order, OrderTicket
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    order_count = Order.objects.filter(event=event).count()
    if order_count > 0 and request.POST.get('confirmed_sold_tickets') != '1':
        messages.error(
            request,
            f'No se puede eliminar "{event.name}" porque tiene {order_count} orden(es) asociada(s). '
            f'Confirmar que se ha contactado a quienes adquirieron entradas.'
        )
        return redirect('dashboard_event_list', org_slug=org_slug)
    event_name = event.name
    with transaction.atomic():
        # Must delete in this order due to RESTRICT foreign keys
        OrderTicket.objects.filter(order__event=event).delete()
        Order.objects.filter(event=event).delete()
        event.delete()  # TicketTypes cascade automatically
    messages.success(request, f'Evento "{event_name}" eliminado.')
    return redirect('dashboard_event_list', org_slug=org_slug)


@login_required
@require_POST
@transaction.atomic
def dashboard_ticket_type_delete(request, org_slug, event_id, tt_id):
    from tickets.models import TicketType
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    tt = get_object_or_404(TicketType, pk=tt_id, event=event)
    tt.delete()
    messages.success(request, f'Tipo de ticket "{tt.name}" eliminado.')
    return redirect('dashboard_event_edit', org_slug=org_slug, event_id=event_id)


@login_required
@require_POST
def dashboard_event_set_status(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    new_status = request.POST.get('status')
    if new_status == Event.Status.PUBLISHED:
        event.status = Event.Status.PUBLISHED
    else:
        event.status = Event.Status.DRAFT
    event.save(update_fields=['status'])
    return redirect('dashboard_event_list', org_slug=org_slug)


@login_required
@require_POST
def dashboard_event_publish(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    event.status = Event.Status.PUBLISHED
    event.save(update_fields=['status'])
    messages.success(request, f'"{event.name}" is now published.')
    return redirect('dashboard_event_list', org_slug=org_slug)


@login_required
@require_POST
def dashboard_event_unpublish(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    event.status = Event.Status.DRAFT
    event.save(update_fields=['status'])
    messages.success(request, f'"{event.name}" moved to draft.')
    return redirect('dashboard_event_list', org_slug=org_slug)


# ── Member management ──────────────────────────────────────────────────────────

@login_required
def dashboard_members(request, org_slug):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    memberships = organization.memberships.select_related('user').order_by('role', 'user__email')
    invitations = organization.invitations.filter(accepted_at__isnull=True).order_by('-created_at')
    return render(request, 'dashboard/members.html', {
        'organization': organization,
        'memberships': memberships,
        'invitations': invitations,
    })


@login_required
@require_POST
def dashboard_member_add(request, org_slug):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    email = request.POST.get('email', '').strip().lower()
    role = request.POST.get('role', OrganizationMembership.Role.ADMIN)

    try:
        user = User.objects.get(email__iexact=email)
        _, created = OrganizationMembership.objects.get_or_create(
            user=user, organization=organization,
            defaults={'role': role},
        )
        if created:
            messages.success(request, f'{email} agregado como {role}.')
        else:
            messages.warning(request, f'{email} ya es miembro.')
    except User.DoesNotExist:
        # User doesn't have an account yet — create a pending invitation
        _, created = OrganizationInvitation.objects.get_or_create(
            organization=organization,
            email=email,
            defaults={'role': role, 'invited_by': request.user},
        )
        if created:
            messages.success(request, f'Invitación enviada a {email}. Cuando se registre, tendrá acceso como {role}.')
        else:
            messages.warning(request, f'Ya existe una invitación pendiente para {email}.')
    return redirect('dashboard_members', org_slug=org_slug)


@login_required
@require_POST
def dashboard_invitation_cancel(request, org_slug, invitation_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    invitation = get_object_or_404(OrganizationInvitation, pk=invitation_id, organization=organization)
    email = invitation.email
    invitation.delete()
    messages.success(request, f'Invitación a {email} cancelada.')
    return redirect('dashboard_members', org_slug=org_slug)


@login_required
@require_POST
def dashboard_member_remove(request, org_slug, membership_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    membership = get_object_or_404(OrganizationMembership, pk=membership_id, organization=organization)
    # Prevent removing yourself if you're the only owner
    if membership.user == request.user:
        messages.error(request, "You can't remove yourself.")
        return redirect('dashboard_members', org_slug=org_slug)
    email = membership.user.email
    membership.delete()
    messages.success(request, f'{email} removed from organization.')
    return redirect('dashboard_members', org_slug=org_slug)


# ── Organisation settings ────────────────────────────────────────────────────

@login_required
def dashboard_org_edit(request, org_slug):
    """Let org admins edit their organisation's basic details."""
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    if request.method == 'POST':
        form = OrganizationForm(request.POST, request.FILES, instance=organization)
        if form.is_valid():
            form.save()
            messages.success(request, 'Datos de la organización actualizados.')
            return redirect('dashboard_org_edit', org_slug=organization.slug)
    else:
        form = OrganizationForm(instance=organization)
    return render(request, 'dashboard/org_edit.html', {'organization': organization, 'form': form})
