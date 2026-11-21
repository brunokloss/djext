"""The links in the emails: Django's PasswordResetTokenGenerator, signed with
SECRET_KEY and valid for PASSWORD_RESET_TIMEOUT. Nothing is stored: a token
stops working once what it was made from changes (the password and last login
for a reset; is_active and the password for a verification, so signing up
again kills the earlier links), so each link works once."""

from django.contrib.auth.tokens import (
    PasswordResetTokenGenerator,
    default_token_generator,
)


class VerifyTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "modules.signup.verify"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.email}{user.password}{user.is_active}{timestamp}"


verify_tokens = VerifyTokenGenerator()
reset_tokens = default_token_generator
