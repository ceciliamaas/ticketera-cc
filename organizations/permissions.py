from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Organization, OrganizationMembership


def get_membership(user, organization):
    """Return the membership for user in organization, or None."""
    if not user.is_authenticated:
        return None
    return OrganizationMembership.objects.filter(
        user=user, organization=organization
    ).first()


def get_authorized_organization(user, organization_slug, min_role=None):
    """
    Return the Organization identified by slug if user has a membership there.
    Raises Http404 if the org doesn't exist or user has no membership.
    Optionally enforce a minimum role: 'admin' or 'owner'.
    Superusers bypass all membership checks.
    """
    organization = get_object_or_404(Organization, slug=organization_slug, is_active=True)
    if user.is_superuser:
        return organization
    membership = get_membership(user, organization)
    if membership is None:
        raise Http404

    if min_role == 'admin' and not membership.is_admin_or_above:
        raise Http404
    if min_role == 'owner' and not membership.is_owner:
        raise Http404

    return organization


def user_can_edit_event(user, event):
    """Return True if user has admin-or-above membership in the event's organization."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    membership = get_membership(user, event.organization)
    return membership is not None and membership.is_admin_or_above


def user_can_manage_org(user, organization):
    """Return True if user has admin-or-above membership in the organization."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    membership = get_membership(user, organization)
    return membership is not None and membership.is_admin_or_above
