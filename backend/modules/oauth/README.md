# Log in with a provider

`modules/oauth` adds "Continue with Mock / Google / Microsoft" to `/login` (OpenID Connect, Authorization Code + PKCE through the backend, with [Authlib](https://docs.authlib.org/)). It only logs in existing, active users: the first time by their verified email, which links that provider account to them (`UserIdentity`, in the admin), and from then on by that link, even if the email changes at the provider. Nobody is signed up this way. Failures come back as `/login?error=oauth_<reason>`. The login page only shows the providers that are on: `/api/auth/providers` lives in the core and lists the password plus what modules return on `login_options_requested` (`oauth` returns its providers in `signals.py`).

Each provider redirects back to `/api/auth/<provider>/callback` on the frontend (for example `http://localhost:3000/api/auth/google/callback`); register that URL with it. Django builds it from the `X-Forwarded-Host` the Next proxy sends (and `X-Forwarded-Proto` from an HTTPS load balancer), so in production `ALLOWED_HOSTS` must include the frontend's host.

- **Mock:** `manage.py oauth_mock` (started by `make dev` and the e2e tests) is a fake provider on port 8001 that logs in as any email you type. On when `AUTH_MOCK_URL` is set and `DEBUG=True`.
- **Google:** create a "Web application" OAuth client in the [Google Cloud console](https://console.cloud.google.com/apis/credentials) and set `AUTH_GOOGLE_CLIENT_ID` and `AUTH_GOOGLE_CLIENT_SECRET`.
- **Microsoft:** register an app in [Microsoft Entra](https://entra.microsoft.com) for any account type, add a client secret, and set `AUTH_MICROSOFT_CLIENT_ID` and `AUTH_MICROSOFT_CLIENT_SECRET`. Under "Token configuration", add the optional claim `xms_edov` to the ID token: any tenant can give its users any email, so a work or school email is only trusted when `xms_edov` says the tenant owns its domain (personal accounts don't need it). Without it, work and school accounts get `oauth_unverified_email`.

## Depends on

The packages `authlib` and `requests`. It answers `login_options_requested` (`modules/signals`).

## Removing it

Delete `backend/modules/oauth/` and these lines: `INSTALLED_APPS` in `config/settings.py`; the import and `add_router` in `config/urls.py`. Then `make api-types`. Its table stays in the database until you drop it. `make dev` and the e2e tests stop starting the mock provider on their own.
