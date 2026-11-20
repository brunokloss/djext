# Queue monitor

`modules/queue` adds Tasks › Queue to the admin (next to Task Results), for superusers, refreshed every 5 s from a JSON endpoint (`/admin/queue/stats/`): what is due now in the task and email queues, the oldest one waiting, the average and maximum latency of the last hour, and the emails that failed or are being retried (last 24 h and 30 days). Failed tasks are not counted on purpose: a failed send stays on the email. When something has waited more than 60 s, the page and the admin's home say that the worker seems stopped. The page's "Enqueue test task" button enqueues `ping` (`modules/queue/tasks.py`), a task that does nothing, and opens its result, where you watch the worker run it.

## Depends on

`django-tasks-db` for the task queue. The email queue shows only with `post_office` (`mail`).

## Removing it

Delete `backend/modules/queue/` and these lines: `INSTALLED_APPS` and its `ADMIN_APP_GROUPS` line in `config/settings.py`.
