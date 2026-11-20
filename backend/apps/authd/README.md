# authd

## Users

`apps/authd` has a custom `User` (Django's `AbstractUser`) with these changes:

- `username` is a generated UUIDv7. It is the user's public id: expose it in the API and URLs, never the integer `id`.
- People log in with their **email** (`apps/authd/backends.py`, listed in `AUTHENTICATION_BACKENDS`). Login forms, the admin's included, still send it as `username`.
- `phone_number` is optional, validated and stored in E.164 (`+5511912345678`) by [django-phonenumber-field](https://github.com/stefanfoulis/django-phonenumber-field). A number typed without a country code is read as `PHONENUMBER_DEFAULT_REGION`'s (default `BR`). The admin shows it with a country picker: `IntlTelInputWidget` from `modules/phone` ([intl-tel-input](https://github.com/jackocnr/intl-tel-input), vendored), which any app can use on a `PhoneNumberField` with `formfield_overrides = {PhoneNumberField: {"widget": IntlTelInputWidget}}`.

`User.objects.create_user(email=..., password=...)` generates the username. Use `make superuser` to create an admin.

To erase someone's personal data (LGPD), **anonymize** them instead of deleting them: the "Anonymize" action on a user's page in the admin (one user at a time, never in bulk; it needs the delete permission, warns that it can't be undone and asks you to type their email and the last 4 characters of their id), or `user.anonymize(request)` (`request` may be `None`). Deleting removes the row and everything that points at it; anonymizing keeps the row. What it erases is the project's call, so `User.anonymize()` (`apps/authd/models.py`) does it all by hand, in one transaction, logged as `user.anonymize` with who asked: it blocks the user (`is_active=False`), deletes their sessions, the emails sent to them (`mail`), their identities (`oauth`), their key (`bearer`), their stored responses (`idempotency`), shreds their key (`crypto`) and masks the values in their logs (`audit`). The modules don't know about it, they only offer the functions. Drop the line of a module you remove, add what your apps keep about them; their email, names and phone stay as they are until you do.

## Login

Session login, the stock Django way: `/api/auth/login` sets the session cookie through the proxy, so it belongs to the Next origin.

- `/login` posts the form from the browser. A failed login keeps the email.
- `/` reads the user on the server (`lib/api/server.ts` forwards the incoming cookies and request id to Django) and in the browser, and redirects to `/login` when there is no session.
- `proxy.ts` sends visits without the session cookie straight to `/login` (a real 307; `lib/login-guard.ts`). It only checks that the cookie exists; the pages still check the session with Django. On `/login` with a cookie it asks Django (`/api/users/me`) and sends a valid session on to `?next=` or `/`, also with a 307; a stale cookie gets the login page.

`make db-seed` creates example users (password `password`), for example `ana@example.com`.

`AUTH_PASSWORD=False` turns email and password off, leaving only the providers of [`modules/oauth`](../../modules/oauth/README.md).

The admin always keeps Django's password form, with the same failure limits as `/api/auth/login` (`AUTH_LOGIN_THROTTLE_EMAIL`, `AUTH_LOGIN_THROTTLE_IP`); `AUTH_PASSWORD` only covers the frontend and the API.
