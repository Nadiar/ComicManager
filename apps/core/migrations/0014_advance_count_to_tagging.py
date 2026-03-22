from django.db import migrations


def advance_count_to_tagging(apps, schema_editor):
    Comic = apps.get_model("core", "Comic")
    Comic.objects.filter(state="count").update(state="tagging")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_alter_comic_state"),
    ]

    operations = [
        migrations.RunPython(advance_count_to_tagging, migrations.RunPython.noop),
    ]
