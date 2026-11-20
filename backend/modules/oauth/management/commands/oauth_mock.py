import base64
import hashlib
import html
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PORT = 8001

PAGE = """<!doctype html>
<title>Mock login</title>
<style>form {{ font-family: sans-serif; max-width: 20rem; margin: 4rem auto }}</style>
<form method="post">
  <h1>Mock login</h1>
  <p>Log in as any email. Development only.</p>
  <label>Email
    <input name="email" type="email" value="admin@example.com" required>
  </label>
  {hidden}
  <button type="submit">Continue</button>
</form>
"""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def id_token(email: str, client_id: str, issuer: str, nonce: str = "") -> str:
    """An unsigned ID token: the backend reads it but doesn't check signatures
    (see modules/oauth/providers/)."""
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": hashlib.sha256(email.encode()).hexdigest(),
        "aud": client_id,
        "iat": now,
        "exp": now + 300,
        "email": email,
        "email_verified": True,
    }
    if nonce:
        claims["nonce"] = nonce
    header = b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return f"{header}.{b64url(json.dumps(claims).encode())}."


class Handler(BaseHTTPRequestHandler):
    # Authorization codes waiting for the token request: code -> grant.
    codes: dict[str, dict] = {}

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path != "/authorize":
            return self.send_error(404)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        hidden = "".join(
            f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
            for k, v in query.items()
        )
        self.reply(200, PAGE.format(hidden=hidden), "text/html")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        # The login page posts back to its own URL, query string included.
        path = urlsplit(self.path).path
        if path == "/authorize":
            self.authorize(form)
        elif path == "/token":
            self.token(form)
        else:
            self.send_error(404)

    def authorize(self, form):
        # Only back to the frontend, so this can't be used as an open redirect.
        if urlsplit(form.get("redirect_uri", "")).hostname != "localhost":
            return self.send_error(400, "redirect_uri must be on localhost")
        code = secrets.token_urlsafe(16)
        self.codes[code] = form
        query = urlencode({"code": code, "state": form.get("state", "")})
        self.send_response(302)
        self.send_header("Location", f"{form['redirect_uri']}?{query}")
        self.end_headers()

    def token(self, form):
        grant = self.codes.pop(form.get("code", ""), None)
        verifier = form.get("code_verifier", "")
        challenge = b64url(hashlib.sha256(verifier.encode()).digest())
        if grant is None or challenge != grant.get("code_challenge"):
            return self.reply(400, json.dumps({"error": "invalid_grant"}))
        body = {
            "access_token": secrets.token_urlsafe(16),
            "token_type": "Bearer",
            "expires_in": 300,
            # The URL the backend reached it at, which is AUTH_MOCK_URL.
            "id_token": id_token(
                grant["email"],
                grant.get("client_id", ""),
                f"http://{self.headers['Host']}",
                grant.get("nonce", ""),
            ),
        }
        self.reply(200, json.dumps(body))

    def reply(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode())


class Command(BaseCommand):
    help = (
        f"Run a fake OpenID Connect provider on port {PORT} that logs in as any "
        "email (DEBUG only). Set AUTH_MOCK_URL to use it."
    )

    def handle(self, *args, **options):
        # Anyone could log in as anyone: never on a real server.
        if not settings.DEBUG:
            raise CommandError("Refusing to run with DEBUG=False.")
        server = ThreadingHTTPServer(("localhost", PORT), Handler)
        self.stdout.write(f"Mock OAuth provider at http://localhost:{PORT}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
