from django.core.management import call_command
from django.db import migrations, models

# Written out on purpose, not caches.CACHE_TABLE: a migration must do the
# same whenever it runs. Renaming the table later is a new migration.
CACHE_TABLE = "cache"


def create_cache_table(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        # Same columns as django.core.cache.backends.db, but UNLOGGED: no WAL,
        # so writes are cheap. The table is emptied after a crash.
        schema_editor.execute(
            f"CREATE UNLOGGED TABLE IF NOT EXISTS {CACHE_TABLE} ("
            "cache_key varchar(255) NOT NULL PRIMARY KEY, "
            "value text NOT NULL, "
            "expires timestamptz NOT NULL)"
        )
        schema_editor.execute(
            f"CREATE INDEX IF NOT EXISTS {CACHE_TABLE}_expires ON {CACHE_TABLE} (expires)"
        )
    else:
        call_command("createcachetable", CACHE_TABLE, database=connection.alias)


def drop_cache_table(apps, schema_editor):
    schema_editor.execute(f"DROP TABLE IF EXISTS {CACHE_TABLE}")


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
        # The table above, for the admin (managed=False: Django never touches it).
        migrations.CreateModel(
            name="CacheEntry",
            fields=[
                (
                    "cache_key",
                    models.CharField(max_length=255, primary_key=True, serialize=False),
                ),
                ("value", models.TextField()),
                ("expires", models.DateTimeField()),
            ],
            options={
                "verbose_name": "cache entry",
                "verbose_name_plural": "cache entries",
                "db_table": "cache",
                "managed": False,
            },
        ),
    ]
