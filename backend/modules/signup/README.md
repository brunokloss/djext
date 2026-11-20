# Sign-up and password reset

`modules/signup` is for projects that need self-service accounts. djext is B2B, so it starts off. Two settings turn it on, and both need `AUTH_PASSWORD`:

- **`AUTH_SIGNUP=True`:** anyone can sign up with email and password at `/signup`. The account stays inactive until they open the link sent by email (`/verify`) and type that password again, then they log in as usual. Signing up again before that replaces the password and kills the earlier links, so whoever signs up first with someone else's email can't keep the account. Only accounts created this way get activated by a link (the `Signup` row). A user the team blocked or anonymized stays inactive. A dead link offers to send a new one.
- **`AUTH_PASSWORD_RESET=True`:** "Forgot your password?" on `/login` sends a link to choose a new one (`/reset-password`). Only active users who have a password get one. A new password ends all of that user's sessions and lifts the login lock on their email (`authd` listens for `auth.password_reset`).

The links use Django's `PasswordResetTokenGenerator`, so no tokens are stored. Each link works once and expires after `PASSWORD_RESET_TIMEOUT` (1 hour). They are built from the host the Next proxy sends, so the frontend's host must be in `ALLOWED_HOSTS`, as for `oauth`.

The endpoints that take an email (sign up, resend the verification, forgot the password) always answer 204, whether the email has an account or not. They are limited per address and per IP (`AUTH_MAIL_THROTTLE_EMAIL`, `AUTH_MAIL_THROTTLE_IP`); past a limit they answer 429 and send nothing. Signing up, verifying, asking for a reset and resetting are logged as `auth.*` actions (`action_performed`), always with the user as the target.

The emails are the `verify_email` and `password_reset` templates in the admin (Post Office › Email templates). The migrations create them, and an edited one is left as it is. In development the worker prints them, links included (see `mail`).

## Depends on

`mail` (django-post-office) to send the emails. The login page shows the links when `/api/auth/providers` says `signup` or `password_reset` is on.

## Removing it

Delete `backend/modules/signup/` and these lines: `INSTALLED_APPS` and the `AUTH_SIGNUP` / `AUTH_PASSWORD_RESET` / `PASSWORD_RESET_TIMEOUT` / `AUTH_MAIL_THROTTLE_*` block in `config/settings.py`, the import and `add_router` in `config/urls.py`, the `Signup` lines in `User.anonymize()` (`apps/authd/models.py`), and the matching lines in `.env.example`. On the frontend, delete `app/signup/`, `app/verify/`, `app/forgot-password/`, `app/reset-password/`, `components/account-forms.tsx` and `e2e/signup.spec.ts`, and the `AUTH_SIGNUP` / `AUTH_PASSWORD_RESET` env of the backend in `playwright.config.ts`. Then run `make api-types`. The links on `/login`, `getLoginOptions` (`lib/auth.ts`) and the pages in `PUBLIC_PAGES` (`lib/login-guard.ts`) can stay: `/api/auth/providers` says both are off. Its table and email templates stay in the database until you drop them.
