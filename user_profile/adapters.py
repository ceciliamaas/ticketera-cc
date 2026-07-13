from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


class AccountAdapter(DefaultAccountAdapter):
    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=commit)
        if commit and user.first_name:
            try:
                user.profile.profile_completion = 'COMPLETE'
                user.profile.save()
            except Exception:
                pass
        return user

    def get_login_redirect_url(self, request):
        user = request.user
        if user.is_superuser or user.organization_memberships.exists():
            return reverse('dashboard_home')
        return reverse('mi_fuego')
