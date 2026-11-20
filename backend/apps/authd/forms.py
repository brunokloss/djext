from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .api.auth import limited_authenticate


class AdminLoginForm(AdminAuthenticationForm):
    """The admin's own password form (opened directly on Django), behind the
    same failure limits as /api/auth/login. The email comes in `username`."""

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username is not None and password:
            email = get_user_model().objects.normalize_email(username)
            self.user_cache, wait = limited_authenticate(
                AdminLoginForm, self.request, email, password
            )
            if wait:
                raise ValidationError(
                    "Too many failed logins. Try again later.", code="throttled"
                )
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data
