# Bearer keys

For programs calling the API as a user, `modules/bearer` gives each user one key: `POST /api/auth/bearer-key` makes it (shown once; making another replaces it), `GET` shows its start and `DELETE` revokes it, all three with the session only, so a leaked key can't make keys. Programs send it as `Authorization: Bearer <key>`, without CSRF, to endpoints with `auth=user_auth` (`modules/bearer/security.py`), such as `/api/users/me`. Only an HMAC of the key is stored (changing `SECRET_KEY` invalidates every key), and keys start with `BEARER_KEY_PREFIX` in `config/settings.py`. Making and revoking are logged (`auth.bearer_rotate`, `auth.bearer_revoke`); the admin shows it on the user's page, and deleting it there revokes it.

## Depends on

Nothing else.

## Removing it

Delete `backend/modules/bearer/` and these lines: `INSTALLED_APPS` and `BEARER_KEY_PREFIX` in `config/settings.py`; the `BearerKey` imports, inline and `revoke` in `apps/authd/admin.py`; the import and `add_router` in `config/urls.py`. Then `make api-types`. `user_auth` keeps working with the session only. Its table stays in the database until you drop it.
