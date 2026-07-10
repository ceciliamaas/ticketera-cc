from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.contrib.auth.admin import UserAdmin
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from auditlog.models import LogEntry

from .models import Organization, OrganizationMembership, UserProxy

for model in (Group, EmailAddress, SocialAccount, SocialApp, SocialToken, LogEntry):
    try:
        admin.site.unregister(model)
    except admin.sites.NotRegistered:
        pass


def _user_org_ids(user):
    return list(user.organization_memberships.values_list('organization_id', flat=True))


# ── Organizations (superuser only) ────────────────────────────────────────────

class MembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 1
    verbose_name = 'Membresía'
    verbose_name_plural = 'Membresías en organizaciones'

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == 'role':
            kwargs['choices'] = [(OrganizationMembership.Role.ADMIN, 'Admin')]
        return super().formfield_for_choice_field(db_field, request, **kwargs)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [MembershipInline]

    def has_module_perms(self, user_obj):
        return user_obj.is_superuser  # hidden from org admins

    def has_view_permission(self, request, obj=None):
        # Superusers can view all; org members need view permission so that
        # the autocomplete endpoint (used in EventAdmin) doesn't return 403.
        if request.user.is_superuser:
            return True
        if obj is None:
            # List-level: allow org members (autocomplete uses this path)
            return request.user.organization_memberships.exists()
        # Object-level: only allow if the user belongs to that org
        return request.user.organization_memberships.filter(organization=obj).exists()

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_search_results(self, request, queryset, search_term):
        qs, use_distinct = super().get_search_results(request, queryset, search_term)
        if not request.user.is_superuser:
            qs = qs.filter(id__in=_user_org_ids(request.user))
        return qs, use_distinct


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'role']
    list_filter = ['role', 'organization']
    search_fields = ['user__email', 'organization__name']

    def has_module_perms(self, user_obj):
        return user_obj.is_superuser  # hidden from org admins

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ── Users ─────────────────────────────────────────────────────────────────────

class OrgMembershipInline(admin.TabularInline):
    """Inline shown on user edit — org admins can only see/add to their own orgs."""
    model = OrganizationMembership
    extra = 1
    verbose_name = 'Organización'
    verbose_name_plural = 'Organizaciones'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'organization' and not request.user.is_superuser:
            from django import forms as dj_forms
            org_ids = _user_org_ids(request.user)
            org_qs = Organization.objects.filter(id__in=org_ids)
            # Show as a disabled select pre-set to their org
            field = dj_forms.ModelChoiceField(
                queryset=org_qs,
                initial=org_qs.first(),
                widget=dj_forms.Select(attrs={'disabled': True, 'style': 'pointer-events:none;opacity:0.7;'}),
                required=False,
            )
            # Pair with a hidden input so the value is actually submitted
            return field
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if not request.user.is_superuser:
            org_ids = _user_org_ids(request.user)
            org = Organization.objects.filter(id__in=org_ids).first()
            if org:
                # Override the form to force the org value on save
                _org = org
                original_clean = formset.form.clean if hasattr(formset.form, 'clean') else None

                class PatchedForm(formset.form):
                    def clean(self):
                        data = super().clean() if original_clean else {}
                        self.cleaned_data['organization'] = _org
                        return self.cleaned_data

                formset.form = PatchedForm
        return formset

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == 'role':
            kwargs['choices'] = [(OrganizationMembership.Role.ADMIN, 'Admin')]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization_id__in=_user_org_ids(request.user))


@admin.register(UserProxy)
class UserProxyAdmin(UserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_superuser', 'get_orgs')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    inlines = [OrgMembershipInline]
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Información personal', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permisos', {'fields': ('is_active', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'first_name', 'last_name'),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Org admins see only users in their own organizations
        org_ids = _user_org_ids(request.user)
        return qs.filter(organization_memberships__organization_id__in=org_ids).distinct()

    def has_module_perms(self, user_obj):
        if user_obj.is_superuser:
            return True
        return user_obj.organization_memberships.exists()

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return bool(_user_org_ids(request.user))
        # Can view users in their orgs
        if obj == request.user:
            return True
        return obj.organization_memberships.filter(
            organization_id__in=_user_org_ids(request.user)
        ).exists()

    def has_add_permission(self, request):
        if request.user.is_superuser:
            return True
        return bool(_user_org_ids(request.user))

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_fieldsets(self, request, obj=None):
        if not request.user.is_superuser:
            # Org admins only see personal info fields (no is_superuser)
            return (
                (None, {'fields': ('username', 'password')}),
                ('Información personal', {'fields': ('first_name', 'last_name', 'email')}),
                ('Permisos', {'fields': ('is_active',)}),
            )
        return super().get_fieldsets(request, obj)

    def save_model(self, request, obj, form, change):
        if obj.is_superuser:
            obj.is_staff = True
        elif not obj.is_staff:
            # New users created by org admins get is_staff so they can log in
            obj.is_staff = True
        super().save_model(request, obj, form, change)
        # If org admin creates a new user, add them to the org admin's first org
        if not change and not request.user.is_superuser:
            org_ids = _user_org_ids(request.user)
            if org_ids:
                org = Organization.objects.get(id=org_ids[0])
                OrganizationMembership.objects.get_or_create(
                    user=obj, organization=org,
                    defaults={'role': OrganizationMembership.Role.ADMIN},
                )

    def get_orgs(self, obj):
        memberships = obj.organization_memberships.select_related('organization').all()
        return ', '.join(f'{m.organization.name} ({m.role})' for m in memberships) or '—'
    get_orgs.short_description = 'Organizaciones'
