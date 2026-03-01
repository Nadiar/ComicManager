from django.db import migrations
from django.db.models import F


def backfill_last_written(apps, schema_editor):
    """
    For comics already in 'written' state that have no last_written timestamp,
    set last_written = updated_at so they are not counted as stale.
    These existed before last_written tracking was added.
    """
    Comic = apps.get_model("core", "Comic")
    Comic.objects.filter(
        state="written",
        last_written__isnull=True,
    ).update(last_written=F("updated_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_comic_format_ok"),
    ]

    operations = [
        migrations.RunPython(backfill_last_written, migrations.RunPython.noop),
    ]
