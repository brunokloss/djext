# Email

Email is [django-post-office](https://github.com/ui/django-post_office) (a queue in the database with retries, templates and a log, all in the admin under Post Office) and [django-anymail](https://anymail.dev) (providers). Use Django's own API: `send_mail(...)` or `post_office.mail.send(...)`, which also takes `template=`, `scheduled_time=` (send later) and `expires_at=`. The email is saved and **one task per email** sends it (`send_email` in `modules/mail/tasks.py`; `manage.py db_worker`, started by `make dev`), so a request never waits for the mail server. The task locks the email's row in the database while it sends (`SELECT ... FOR UPDATE SKIP LOCKED`), so a duplicate task does nothing, with any number of workers and machines. A failed send is tried again 3 times, 5 minutes apart (`POST_OFFICE` in `config/settings.py`); `modules/cron` runs `enqueue_due_emails` every minute to make the task of each retry and of each email scheduled for later (`scheduled_time`).

With `EMAIL_URL` empty (the default) the worker **prints each email in its console** (the `[WRK]` lines of `make dev`), so you read the links in development. To send for real, set `EMAIL_URL` and `DEFAULT_FROM_EMAIL`: `smtp://user:pass@host:587?tls=true` (`smtps://` for SSL; write `@` in a password as `%40`) or a provider: `resend://API_KEY@`, `postmark://SERVER_TOKEN@`, `sendgrid://API_KEY@`, `brevo://API_KEY@` or `mailgun://API_KEY@?sender_domain=mg.example.com` (more: add them to `PROVIDERS` in `modules/mail/mailers.py`). Tests collect emails in `mail.outbox`.

Templates live in the admin (Post Office › Email templates, with translations); `make db-seed` creates two examples (`welcome`, `invoice`); `modules/signup` creates its own. Wrap the plain text in `{% autoescape off %}...{% endautoescape %}`, as they do: it is rendered like HTML, so a `&` in a link would arrive as `&amp;`. To send one (in development the worker prints it): `mail.send("ana@example.com", None, template="welcome", context={"name": "Ana", "url": "https://..."})`. Attachments go through `send_mail` / `EmailMessage.attach(...)` or `mail.send(attachments={"name.pdf": file})` and are kept in `MEDIA_ROOT` (`backend/media/`) until the email is deleted. A missing template raises in the request, but a broken one is better rendered by the worker, where it only fails that email (status failed, the error in the log): pass `render_on_delivery=True` and a `context` (`{}` if empty; without it the render fails).

Emails are stored with their text, reset links included, so they are deleted after `EMAIL_RETENTION_DAYS` (default 30, daily by `modules/cron`; 0 keeps them). Mind who can open Post Office in the admin.

## Depends on

The packages `django-post-office` and `django-anymail`, and `django-tasks-db` with a worker (`manage.py db_worker`) to send. Retries and emails scheduled for later need `cron` (`enqueue_due_emails`).

## Removing it

Delete `backend/modules/mail/` and these lines: `INSTALLED_APPS` and the `mailers_from_url` import in `config/settings.py` (write `MAILERS` by hand), plus `seed_email_templates` in the `Makefile`'s `db-seed`. Queued emails are no longer sent.
