from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """ModelBackend that looks the user up by email instead of username.

    Login forms (admin included) still send the value as `username`.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        email = kwargs.get(User.EMAIL_FIELD, username)
        if email is None or password is None:
            return None
        try:
            user = User._default_manager.get(
                email__iexact=User._default_manager.normalize_email(email)
            )
        except User.DoesNotExist, User.MultipleObjectsReturned:
            # Hash anyway, so a missing user takes as long as a wrong password.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
