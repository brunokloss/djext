# Audit log

`modules/audit` saves every login, logout and failed login (with the email typed in), and every create, update, delete and many-to-many change of the models that have an `Audit` class: the whole row before and after (the admin highlights what changed), who did it, their IP, browser and session (an HMAC of the session key salted with the user; a link lists everything that login did) and the `request_id`. It is written in the same transaction as the change, and shown read only in the admin, which also shows it on each audited model's History page.

```python
class Order(models.Model):
    class Audit:
        subjects = ["user", "tenant"]
        exclude = ["updated_at"]
        mask = ["card_token"]
```

The class needs no import, and children inherit it (an abstract model can audit them all). Models you can't edit, like Django's `auth.Group`, go in `AUDIT_MODELS` (`config/settings.py`) with the same options.

`subjects` say whose data each row is: `"self"` or a path to a foreign key (`"order__user"`). A log can name up to three (the `subject_1` to `subject_3` columns, as `authd.user:6`), to find someone's logs. Deleting a subject deletes none of them: a log may be someone else's record too (a company's orders, made by an employee who left). **TODO:** each model decides how it is anonymized or erased, and so what happens to its logs (delete them, mask personal values, forget the actor). `mask` keeps secrets out (only their first and last characters), `exclude` leaves fields out.

Logs hold personal data (IP, browser, old and new values), so they don't live forever: `AUDIT_RETENTION_DAYS` (default 1825, five years; 0 keeps everything) is how long to keep each one, and `manage.py audit_purge` deletes the older ones. `modules/cron` runs it for you, daily.

On Postgres a trigger (migration `0002`) refuses any `UPDATE` of a log, even raw SQL from the app. The one exception is forgetting who did it: actor, IP, browser and session can go to empty, never change (deleting a user sets the actor to empty). `DELETE` stays allowed, for `audit_purge`. SQLite (development) only has the check in `AuditLog.save()`.

Auditing is opt-in, so `manage.py check` warns (`audit.W001`) about every model that is neither audited nor marked `skip = True` (in its `Audit` class or in `AUDIT_MODELS`), until someone decides. Django's own `LogEntry`, `Permission`, `ContentType` and `Session` are left out.

> **Note:** it works through Django's model signals, so `QuerySet.update()`, `bulk_create()` and raw SQL aren't logged.

## Depends on

Nothing besides the core. It logs what is sent on `action_performed` (`modules/signals`). The daily purge runs through `cron`; without it, run `manage.py audit_purge` yourself. The `UPDATE` trigger needs Postgres.

## Removing it

Delete `backend/modules/audit/` and these lines: `INSTALLED_APPS`, its middleware in `MIDDLEWARE` and `AUDIT_MODELS` in `config/settings.py`. The `Audit` classes on models can stay (Django ignores them). Its tables stay in the database until you drop them.
