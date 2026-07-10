from django.contrib import admin
from django.db import models as db_models
from django import forms
from django.forms import DateTimeInput
from .models import Event
from tickets.models import TicketType

DATETIME_OVERRIDE = {
    'form_class': forms.DateTimeField,
    'widget': DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
    'input_formats': ['%Y-%m-%dT%H:%M'],
}


def _user_org_ids(user):
    """Return org IDs the user is an admin of (empty = no orgs = show nothing)."""
    return user.organization_memberships.values_list('organization_id', flat=True)


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 1
    show_change_link = True
    fields = ('name', 'price', 'occurrence_date')
    formfield_overrides = {db_models.DateTimeField: DATETIME_OVERRIDE}

    class Media:
        js = ('admin/js/ticket_type_inline.js',)

    def get_readonly_fields(self, request, obj=None):
        return ()

    def has_add_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return _user_org_ids(request.user).exists()

    def has_change_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'status', 'start', 'end')
    list_filter = ('status', 'organization')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ['organization']
    inlines = [TicketTypeInline]
    formfield_overrides = {db_models.DateTimeField: DATETIME_OVERRIDE}
    fields = (
        'organization', 'status',
        'name', 'slug',
        'location', 'address', 'location_url',
        'start', 'is_recurring',
        'max_tickets', 'max_tickets_per_order',
        'header_image', 'description',
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(organization_id__in=_user_org_ids(request.user))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'organization' and not request.user.is_superuser:
            from organizations.models import Organization
            kwargs['queryset'] = Organization.objects.filter(
                id__in=_user_org_ids(request.user)
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_module_perms(self, user_obj):
        if user_obj.is_superuser:
            return True
        return user_obj.organization_memberships.exists()

    def has_add_permission(self, request):
        if request.user.is_superuser:
            return True
        return _user_org_ids(request.user).exists()

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return _user_org_ids(request.user).exists()
        return obj.organization_id in list(_user_org_ids(request.user))

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def get_changeform_initial_data(self, request):
        """Pre-fill new event form with the user's organization defaults."""
        initial = super().get_changeform_initial_data(request)
        from organizations.models import Organization
        org_ids = list(_user_org_ids(request.user))
        if not org_ids:
            return initial
        try:
            org = Organization.objects.get(id=org_ids[0])
        except Organization.DoesNotExist:
            return initial
        if org.location:
            initial.setdefault('location', org.location)
        if org.address:
            initial.setdefault('address', org.address)
        if org.location_url:
            initial.setdefault('location_url', org.location_url)
        return initial

    def save_model(self, request, obj, form, change):
        # On new events: if no image was uploaded, inherit from the organization's photo
        if not change and not obj.header_image and obj.organization_id:
            from organizations.models import Organization
            try:
                org = Organization.objects.get(pk=obj.organization_id)
                if org.photo:
                    obj.header_image = org.photo.name  # reuse same file path, no re-upload
            except Organization.DoesNotExist:
                pass
        super().save_model(request, obj, form, change)
