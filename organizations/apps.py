from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'organizations'
    verbose_name = 'Organizaciones y Usuarios'

    def ready(self):
        from allauth.account.signals import user_signed_up
        from django.dispatch import receiver
        from django.utils import timezone

        @receiver(user_signed_up)
        def accept_pending_invitations(request, user, **kwargs):
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
