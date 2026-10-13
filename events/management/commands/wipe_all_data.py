"""
DESTRUCTIVE: deletes all application data (users, organizations, events, tickets,
orders, caja sales, La Sede subscriptions, etc.) except for a single User kept as
a verified superuser.

Usage:
    python manage.py wipe_all_data --keep-email=superuser@ticketera.com --yes-i-am-sure

Everything runs inside one DB transaction: if anything fails, nothing is deleted.
"""
from django.contrib.admin.models import LogEntry as AdminLogEntry
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.socialaccount.models import SocialAccount, SocialToken
from auditlog.models import LogEntry as AuditLogEntry

from caja.models import (
    CajaSale, CajaSaleLine, EventCaja, EventCajaProduct,
    EventProduct, EventProductStock, EventProductStockRecord,
)
from events.models import (
    Event, EventInvitation, EventRequest, EventRequestTicketType,
    EventTermsAndConditions, EventTermsAndConditionsAcceptance,
    Grupo, GrupoMiembro, GrupoTipo,
)
from organizations.models import Organization, OrganizationInvitation, OrganizationMembership
from tickets.models import (
    Coupon, DirectTicketTemplate, MessageIdempotency, NewTicket, NewTicketTransfer,
    Order, OrderTicket, Ticket, TicketPhoto, TicketTransfer, TicketType,
)
from user_profile.models import Profile, SedeSubscription, SedeSubscriptionPlan, SedeUnmatchedSubscription


class Command(BaseCommand):
    help = "DESTRUCTIVE: wipes all app data except one kept superuser. Requires --yes-i-am-sure."

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep-email', default='superuser@ticketera.com',
            help='Email of the User to keep as a verified superuser (default: superuser@ticketera.com).',
        )
        parser.add_argument(
            '--yes-i-am-sure', action='store_true',
            help='Required confirmation flag. Without it, the command only prints what it would do.',
        )

    def handle(self, *args, **options):
        keep_email = options['keep_email']
        confirmed = options['yes_i_am_sure']

        try:
            keep_user = User.objects.get(email__iexact=keep_email)
        except User.DoesNotExist:
            raise CommandError(f'No user found with email {keep_email!r}. Aborting.')

        other_users_count = User.objects.exclude(pk=keep_user.pk).count()
        self.stdout.write(self.style.WARNING(
            f'This will DELETE ALL application data and {other_users_count} user(s), '
            f'keeping only {keep_user.email!r} as a verified superuser.'
        ))

        if not confirmed:
            self.stdout.write(self.style.NOTICE(
                'Dry run (no --yes-i-am-sure passed). Nothing was deleted. '
                'Re-run with --yes-i-am-sure to actually wipe the data.'
            ))
            return

        with transaction.atomic():
            # Audit/session/social-login housekeeping (safe to clear first, nothing depends on them).
            AuditLogEntry.objects.all().delete()
            AdminLogEntry.objects.all().delete()
            Session.objects.all().delete()
            SocialToken.objects.all().delete()
            SocialAccount.objects.all().delete()
            EmailConfirmation.objects.exclude(email_address__user=keep_user).delete()
            EmailAddress.objects.exclude(user=keep_user).delete()

            # Ticket chain (leaf tables first).
            TicketPhoto.objects.all().delete()
            NewTicketTransfer.objects.all().delete()
            NewTicket.objects.all().delete()
            OrderTicket.objects.all().delete()
            TicketTransfer.objects.all().delete()
            Ticket.objects.all().delete()
            DirectTicketTemplate.objects.all().delete()

            # Caja (point-of-sale) chain.
            CajaSaleLine.objects.all().delete()
            EventProductStockRecord.objects.all().delete()
            CajaSale.objects.all().delete()
            EventCajaProduct.objects.all().delete()
            EventCaja.objects.all().delete()
            EventProductStock.objects.all().delete()
            EventProduct.objects.all().delete()

            # Orders must go before Coupon (RESTRICT) and before Event (RESTRICT).
            Order.objects.all().delete()
            Coupon.objects.all().delete()

            # Events and related structures.
            EventTermsAndConditionsAcceptance.objects.all().delete()
            EventTermsAndConditions.objects.all().delete()
            GrupoMiembro.objects.all().delete()
            Grupo.objects.all().delete()
            GrupoTipo.objects.all().delete()
            EventInvitation.objects.all().delete()
            EventRequestTicketType.objects.all().delete()
            EventRequest.objects.all().delete()
            TicketType.objects.all().delete()
            MessageIdempotency.objects.all().delete()
            Event.objects.all().delete()

            # Organizations.
            OrganizationInvitation.objects.all().delete()
            OrganizationMembership.objects.all().delete()
            Organization.objects.all().delete()

            # La Sede / profiles.
            SedeSubscription.objects.all().delete()
            SedeUnmatchedSubscription.objects.all().delete()
            SedeSubscriptionPlan.objects.all().delete()
            Profile.objects.exclude(user=keep_user).delete()

            # Finally, every other user.
            User.objects.exclude(pk=keep_user.pk).delete()

            # Guarantee the kept account is an active, verified superuser.
            keep_user.is_superuser = True
            keep_user.is_staff = True
            keep_user.is_active = True
            keep_user.save(update_fields=['is_superuser', 'is_staff', 'is_active'])
            EmailAddress.objects.update_or_create(
                user=keep_user, email=keep_user.email,
                defaults={'verified': True, 'primary': True},
            )

        self.stdout.write(self.style.SUCCESS(
            f'Done. All data wiped except {keep_user.email!r} (verified superuser).'
        ))
