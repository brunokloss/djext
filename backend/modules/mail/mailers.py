"""Turns EMAIL_URL into Django's `MAILERS`."""

from urllib.parse import parse_qs, unquote, urlsplit


def mailers_from_url(url: str) -> dict:
    """`MAILERS` for `EMAIL_URL`. "default" is what `send_mail` uses: post_office,
    which saves the email in the database. "direct" is the one that really sends
    (POST_OFFICE["DEFAULT_MAILER"]): the console when the URL is empty."""
    return {
        "default": {"BACKEND": "post_office.EmailBackend"},
        "direct": _backend(url),
    }


# Providers through django-anymail: `<scheme>://<key>@`, and the option the key is.
# Other options go in the query (mailgun://KEY@?sender_domain=mg.example.com).
PROVIDERS = {
    "resend": "api_key",
    "postmark": "server_token",
    "sendgrid": "api_key",
    "brevo": "api_key",
    "mailgun": "api_key",
}


def _backend(url: str) -> dict:
    """Empty: print each email to the console (development).

    `resend://API_KEY@`, `postmark://SERVER_TOKEN@`, `sendgrid://`, `brevo://` and
    `mailgun://` send through that provider (django-anymail).

    `smtp://user:pass@host:587` sends through SMTP, with STARTTLS if you add
    `?tls=true`; `smtps://user:pass@host:465` is SMTP over SSL. User and password
    are percent-decoded, so `@` in a password is written `%40`.
    """
    if not url:
        return {"BACKEND": "django.core.mail.backends.console.EmailBackend"}
    parts = urlsplit(url)
    if parts.scheme in PROVIDERS:
        if not parts.username:
            raise ValueError(f"EMAIL_URL must look like {parts.scheme}://API_KEY@")
        options = {k: v[0] for k, v in parse_qs(parts.query).items()}
        options[PROVIDERS[parts.scheme]] = unquote(parts.username)
        return {
            "BACKEND": f"anymail.backends.{parts.scheme}.EmailBackend",
            "OPTIONS": options,
        }
    if parts.scheme not in ("smtp", "smtps") or not parts.hostname:
        raise ValueError(
            "EMAIL_URL must look like smtp://user:pass@host:587 or resend://API_KEY@"
        )
    tls = parse_qs(parts.query).get("tls", ["false"])[0].lower() in ("1", "true")
    ssl = parts.scheme == "smtps"
    return {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": parts.hostname,
            "port": parts.port or (465 if ssl else 587 if tls else 25),
            "username": unquote(parts.username or ""),
            "password": unquote(parts.password or ""),
            "use_tls": tls and not ssl,
            "use_ssl": ssl,
            "timeout": 10,
        },
    }
