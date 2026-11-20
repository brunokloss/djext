from django.db import migrations

# The housekeeping jobs now follow `<thing>_purge`. Rename the existing rows,
# so each keeps whether it is on, its expression override and its runs,
# instead of being left behind next to a new disabled row.
RENAMED = {
    "prune_task_results": "task_result_purge",
    "cleanup_mail": "mail_purge",
    "clear_sessions": "session_purge",
}


def rename(apps, schema_editor, names):
    CronSchedule = apps.get_model("cron", "CronSchedule")
    for old, new in names.items():
        if not CronSchedule.objects.filter(name=new).exists():
            CronSchedule.objects.filter(name=old).update(name=new)


class Migration(migrations.Migration):
    dependencies = [("cron", "0001_initial")]

    operations = [
        migrations.RunPython(
            lambda apps, editor: rename(apps, editor, RENAMED),
            lambda apps, editor: rename(
                apps, editor, {new: old for old, new in RENAMED.items()}
            ),
        )
    ]
