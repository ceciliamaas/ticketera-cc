from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from allauth.account.models import EmailAddress


class Command(BaseCommand):
    help = (
        "One-time grandfather fix: marks all current users' emails as verified so "
        "mandatory email verification (enabled afterwards) only applies to new signups."
    )

    def handle(self, *args, **options):
        created = 0
        updated = 0
        skipped = 0
        for user in User.objects.exclude(email=''):
            email_address, was_created = EmailAddress.objects.get_or_create(
                user=user,
                email=user.email,
                defaults={'verified': True, 'primary': True},
            )
            if was_created:
                created += 1
            elif not email_address.verified:
                email_address.verified = True
                email_address.primary = True
                email_address.save(update_fields=['verified', 'primary'])
                updated += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'Created {created}, updated {updated}, already verified {skipped}.'
        ))
