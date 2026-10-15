from django.db import migrations, models


def move_custom_imprint(apps, schema_editor):
    """Move an "Imprint" custom value (the only way to store an imprint before
    this field existed) into the new field. Imprint is now a standard
    ComicInfo.xml element, so the custom value would be dropped on the next write."""
    Comic = apps.get_model("core", "Comic")
    for comic in Comic.objects.filter(custom_values__has_key="Imprint").iterator():
        value = str(comic.custom_values.pop("Imprint") or "").strip()
        if value and not comic.imprint:
            comic.imprint = value
        comic.save(update_fields=["imprint", "custom_values"])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_comic_story_arc'),
    ]

    operations = [
        migrations.AddField(
            model_name='comic',
            name='imprint',
            field=models.CharField(blank=True, max_length=256, null=True),
        ),
        migrations.RunPython(move_custom_imprint, migrations.RunPython.noop),
    ]
