"""The links in the emails: Django's PasswordResetTokenGenerator, signed with
SECRET_KEY and valid for PASSWORD_RESET_TIMEOUT. Nothing is stored: a token
stops working once what it was made from changes (the password and last login
for a reset; the password for a verification, so signing up again kills the
earlier links), so a reset link works once. A verification link keeps working
until it expires, for a second device or a mail scanner that opened it first:
the Signup row says it was used (services.verify). A login link is made from
the last login, so logging in (with it or any other way) kills it.

Each kind has its own key_salt: one kind of token never passes for another."""

from django.contrib.auth.tokens import (
    PasswordResetTokenGenerator,
    default_token_generator,
)


class VerifyTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "modules.signup.verify"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.email}{user.password}{timestamp}"


class LoginLinkTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "modules.signup.login_link"

    def _make_hash_value(self, user, timestamp):
        # As Django's reset token: a new password ends the link too.
        login = (
            user.last_login.replace(microsecond=0, tzinfo=None)
            if user.last_login
            else ""
        )
        return f"{user.pk}{user.email}{user.password}{login}{timestamp}"


verify_tokens = VerifyTokenGenerator()
reset_tokens = default_token_generator
login_link_tokens = LoginLinkTokenGenerator()
