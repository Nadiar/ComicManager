from django.db import migrations

# 0002 seeded fields without braces. The template engine only fills fields
# inside {...}, so these produced paths like "[publisher]/[series]".
OLD = {
    "folder_template": "<publisher>/<series>{ (<volume>)}",
    "file_template": "<series>{ #<number>}{ (<year>)}",
}
NEW = {
    "folder_template": "{<publisher>}/{<series>}{ (<volume>)}",
    "file_template": "{<series>}{ #<number>}{ (<year>)}",
}


def _swap(apps, old, new):
    OrganizerProfile = apps.get_model("organizer", "OrganizerProfile")
    for field in ("folder_template", "file_template"):
        OrganizerProfile.objects.filter(name="Default", **{field: old[field]}).update(**{field: new[field]})


def fix_templates(apps, schema_editor):
    _swap(apps, OLD, NEW)


def restore_templates(apps, schema_editor):
    _swap(apps, NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("organizer", "0002_default_profile"),
    ]

    operations = [
        migrations.RunPython(fix_templates, restore_templates),
    ]
