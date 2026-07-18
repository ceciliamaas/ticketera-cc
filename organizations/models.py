from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
import uuid


class UserProxy(User):
    """Proxy of auth.User so it appears in the Organizaciones y Usuarios admin section."""
    class Meta:
        proxy = True
        app_label = 'organizations'
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'


class Organization(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)
    email = models.EmailField(blank=True)
    photo = models.ImageField(upload_to='organizations/photos', blank=True, null=True, help_text="Default header image for events")
    location = models.CharField(max_length=255, blank=True, help_text="Default venue name for events")
    address = models.CharField(max_length=500, blank=True, help_text="Default physical address for events")
    ciudad = models.CharField(max_length=200, blank=True, help_text="Default city for events")
    location_url = models.URLField(max_length=500, blank=True, help_text="Default location URL (e.g. Google Maps) for events")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # MercadoPago Marketplace credentials
    mp_access_token = models.CharField(max_length=500, blank=True, help_text="Seller access token (obtained via OAuth)")
    mp_refresh_token = models.CharField(max_length=500, blank=True, help_text="Token to refresh the access token")
    mp_public_key = models.CharField(max_length=500, blank=True, help_text="Seller public key")
    mp_user_id = models.CharField(max_length=100, blank=True, help_text="Seller MercadoPago user ID")
    mp_token_expires_at = models.DateTimeField(null=True, blank=True, help_text="When the access token expires")
    mp_marketplace_fee_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Marketplace fee percentage (e.g. 5.00 = 5%). Leave at 0 to charge no fee."
    )

    @property
    def mp_connected(self):
        return bool(self.mp_access_token)

    def mp_marketplace_fee_for(self, amount):
        """Return absolute fee amount for a given payment amount."""
        if not self.mp_marketplace_fee_pct:
            return 0
        from decimal import Decimal
        return float((Decimal(str(amount)) * self.mp_marketplace_fee_pct / 100).quantize(Decimal('0.01')))

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        EDITOR = 'editor', 'Editor'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='organization_memberships',
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADMIN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'organization')]
        indexes = [
            models.Index(fields=['organization']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f'{self.user} — {self.organization} ({self.role})'

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_admin_or_above(self):
        return self.role in (self.Role.OWNER, self.Role.ADMIN)


@receiver(post_save, sender=OrganizationMembership)
def grant_staff_on_membership(sender, instance, created, **kwargs):
    """Grant is_staff=True and model permissions when a user is added to any organization."""
    if not created:
        return
    user = instance.user
    changed = False
    if not user.is_staff:
        user.is_staff = True
        changed = True
    if changed:
        user.save(update_fields=['is_staff'])

    # Grant view/add/change/delete permissions for events and organizations
    from django.contrib.contenttypes.models import ContentType
    from django.contrib.auth.models import Permission
    from events.models import Event
    from organizations.models import Organization, OrganizationMembership as OM

    target_models = [Event, Organization, OM]
    for model_class in target_models:
        ct = ContentType.objects.get_for_model(model_class)
        perms = Permission.objects.filter(content_type=ct)
        user.user_permissions.add(*perms)


class OrganizationInvitation(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='invitations'
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=OrganizationMembership.Role.choices,
        default=OrganizationMembership.Role.ADMIN,
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_invitations')
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('organization', 'email')]

    @property
    def is_pending(self):
        return self.accepted_at is None

    def __str__(self):
        return f'Invitación a {self.email} — {self.organization}'

