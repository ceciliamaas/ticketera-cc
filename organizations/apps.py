from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'organizations'
    verbose_name = 'Organizaciones y Usuarios'

    def ready(self):
        from allauth.account.signals import user_signed_up
        from django.contrib.auth.signals import user_logged_in
        from django.dispatch import receiver
        from django.utils import timezone

        def accept_pending_invitations_for(user):
            from organizations.models import OrganizationInvitation, OrganizationMembership
            if not user.email:
                return
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

        @receiver(user_signed_up)
        def on_user_signed_up(request, user, **kwargs):
            accept_pending_invitations_for(user)

        # Also check on every login: covers users whose account was created outside
        # the allauth signup flow (e.g. guest ticket purchase) before accepting the invite.
        @receiver(user_logged_in)
        def on_user_logged_in(request, user, **kwargs):
            accept_pending_invitations_for(user)
