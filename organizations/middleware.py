from django.utils import timezone


class AcceptPendingInvitationsMiddleware:
    """
    Safety net: grants pending OrganizationInvitations on every authenticated request,
    not just at signup/login time. Signals (user_signed_up/user_logged_in) can miss
    this for reasons that are hard to pin down in production (e.g. social-login edge
    cases), so this guarantees the invite gets applied on the user's very next page view.
    Cheap no-op for users with no pending invitations once accepted (session-cached).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and user.email and not request.session.get('_invites_checked'):
            self._accept_pending_invitations(user)
            request.session['_invites_checked'] = True
        return self.get_response(request)

    def _accept_pending_invitations(self, user):
        from organizations.models import OrganizationInvitation, OrganizationMembership
        pending = OrganizationInvitation.objects.filter(
            email__iexact=user.email,
            accepted_at__isnull=True,
        ).select_related('organization')
        for invitation in pending:
            OrganizationMembership.objects.get_or_create(
                user=user,
                organization=invitation.organization,
                defaults={'role': invitation.role},
            )
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=['accepted_at'])
