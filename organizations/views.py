import logging
import urllib.parse

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
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
    organization = get_authorized_organization(request.user, org_slug)
    events = Event.objects.filter(organization=organization).order_by('-start')
    return render(request, 'dashboard/event_list.html', {
        'organization': organization,
        'events': events,
    })


@login_required
def dashboard_event_create(request, org_slug):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.organization = organization
            if not event.slug:
                event.slug = slugify(event.name)
            if event.max_tickets_per_order is None:
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
            messages.success(request, f'Evento "{event.name}" creado.')
            return redirect('dashboard_event_edit', org_slug=org_slug, event_id=event.pk)
    else:
        form = EventForm(initial={
            'location': organization.location,
            'location_url': organization.location_url,
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
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)

    if request.method == 'POST':
        try:
            invitations = int(request.POST.get('invitations_count', 0))
            event.invitations_count = max(0, invitations)
            event.save(update_fields=['invitations_count'])
            messages.success(request, 'Invitaciones actualizadas.')
        except ValueError:
            messages.error(request, 'Número de invitaciones inválido.')
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

    return render(request, 'dashboard/event_reservas.html', {
        'organization': organization,
        'event': event,
        'orders': orders,
        'tickets_sold': tickets_sold,
        'total_revenue': total_revenue,
        'capacity': capacity,
        'remaining': remaining,
    })


@login_required
def dashboard_event_edit(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        formset = TicketTypeFormSet(request.POST, instance=event)
        if form.is_valid() and formset.is_valid():
            event = form.save(commit=False)
            if event.max_tickets_per_order is None:
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
            messages.success(request, f'Evento "{event.name}" guardado.')
            return redirect('dashboard_event_edit', org_slug=org_slug, event_id=event.pk)
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
def dashboard_event_delete(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    from tickets.models import Order
    order_count = Order.objects.filter(event=event).count()
    if order_count > 0:
        messages.error(
            request,
            f'No se puede eliminar "{event.name}" porque tiene {order_count} orden(es) asociada(s). '
            f'Solo se pueden eliminar eventos sin órdenes.'
        )
        return redirect('dashboard_event_list', org_slug=org_slug)
    event.delete()
    messages.success(request, f'Evento "{event.name}" eliminado.')
    return redirect('dashboard_event_list', org_slug=org_slug)


@login_required
@require_POST
def dashboard_event_set_status(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    new_status = request.POST.get('status')
    if new_status == Event.Status.PUBLISHED:
        if not organization.mp_connected:
            messages.error(request, 'Debes conectar una cuenta de MercadoPago antes de publicar eventos.')
            return redirect('dashboard_mp_connect', org_slug=org_slug)
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
    if not organization.mp_connected:
        messages.error(request, 'Debes conectar una cuenta de MercadoPago antes de publicar eventos.')
        return redirect('dashboard_mp_connect', org_slug=org_slug)
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


# ── MercadoPago Marketplace OAuth ─────────────────────────────────────────────

@login_required
def dashboard_mp_connect(request, org_slug):
    """Show MP connection status and redirect to MP OAuth."""
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    return render(request, 'dashboard/mp_connect.html', {'organization': organization})


@login_required
def dashboard_mp_oauth_start(request, org_slug):
    """Redirect admin to MercadoPago OAuth authorization page."""
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    app_id = settings.MERCADOPAGO.get('APP_ID')
    if not app_id:
        messages.error(request, 'MERCADOPAGO_APP_ID no está configurado.')
        return redirect('dashboard_mp_connect', org_slug=org_slug)

    callback_url = settings.APP_URL.rstrip('/') + reverse('dashboard_mp_callback')
    params = urllib.parse.urlencode({
        'client_id': app_id,
        'response_type': 'code',
        'platform_id': 'mp',
        'redirect_uri': callback_url,
        'state': org_slug,
    })
    return redirect(f'https://auth.mercadopago.com.ar/authorization?{params}')


def dashboard_mp_callback(request):
    """Handle OAuth callback from MercadoPago, exchange code for tokens."""
    code = request.GET.get('code')
    org_slug = request.GET.get('state')

    if not code or not org_slug:
        messages.error(request, 'OAuth callback inválido.')
        return redirect('dashboard_home')

    organization = get_object_or_404(Organization, slug=org_slug)

    callback_url = settings.APP_URL.rstrip('/') + reverse('dashboard_mp_callback')
    try:
        resp = requests.post(
            'https://api.mercadopago.com/oauth/token',
            json={
                'client_id': settings.MERCADOPAGO['APP_ID'],
                'client_secret': settings.MERCADOPAGO['CLIENT_SECRET'],
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': callback_url,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error('MP OAuth token exchange failed: %s', e)
        messages.error(request, f'Error al conectar con MercadoPago: {e}')
        return redirect('dashboard_mp_connect', org_slug=org_slug)

    from datetime import timedelta
    organization.mp_access_token = data['access_token']
    organization.mp_refresh_token = data.get('refresh_token', '')
    organization.mp_public_key = data.get('public_key', '')
    organization.mp_user_id = str(data.get('user_id', ''))
    organization.mp_token_expires_at = timezone.now() + timedelta(seconds=data.get('expires_in', 15552000))
    organization.save(update_fields=[
        'mp_access_token', 'mp_refresh_token', 'mp_public_key',
        'mp_user_id', 'mp_token_expires_at',
    ])

    messages.success(request, f'Cuenta de MercadoPago conectada correctamente para {organization.name}.')
    return redirect('dashboard_mp_connect', org_slug=org_slug)


@login_required
@require_POST
def dashboard_mp_disconnect(request, org_slug):
    """Remove stored MP credentials for an organization."""
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    organization.mp_access_token = ''
    organization.mp_refresh_token = ''
    organization.mp_public_key = ''
    organization.mp_user_id = ''
    organization.mp_token_expires_at = None
    organization.save(update_fields=[
        'mp_access_token', 'mp_refresh_token', 'mp_public_key',
        'mp_user_id', 'mp_token_expires_at',
    ])
    messages.success(request, 'Cuenta de MercadoPago desconectada.')
    return redirect('dashboard_mp_connect', org_slug=org_slug)
