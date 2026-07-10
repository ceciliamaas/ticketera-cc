from allauth.account.adapter import DefaultAccountAdapter


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
