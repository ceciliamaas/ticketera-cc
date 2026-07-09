from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST

from events.models import Event
from .forms import EventForm
from .models import Organization, OrganizationMembership
from .permissions import get_authorized_organization, user_can_edit_event


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
            event.save()
            messages.success(request, f'Event "{event.name}" created.')
            return redirect('dashboard_event_list', org_slug=org_slug)
    else:
        form = EventForm()
    return render(request, 'dashboard/event_form.html', {
        'organization': organization,
        'form': form,
        'action': 'Create',
    })


@login_required
def dashboard_event_edit(request, org_slug, event_id):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, f'Event "{event.name}" updated.')
            return redirect('dashboard_event_list', org_slug=org_slug)
    else:
        form = EventForm(instance=event)
    return render(request, 'dashboard/event_form.html', {
        'organization': organization,
        'event': event,
        'form': form,
        'action': 'Edit',
    })


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
    return render(request, 'dashboard/members.html', {
        'organization': organization,
        'memberships': memberships,
    })


@login_required
@require_POST
def dashboard_member_add(request, org_slug):
    organization = get_authorized_organization(request.user, org_slug, min_role='admin')
    email = request.POST.get('email', '').strip()
    role = request.POST.get('role', OrganizationMembership.Role.EDITOR)

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        messages.error(request, f'No user found with email "{email}".')
        return redirect('dashboard_members', org_slug=org_slug)

    _, created = OrganizationMembership.objects.get_or_create(
        user=user, organization=organization,
        defaults={'role': role},
    )
    if created:
        messages.success(request, f'{email} added as {role}.')
    else:
        messages.warning(request, f'{email} is already a member.')
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
