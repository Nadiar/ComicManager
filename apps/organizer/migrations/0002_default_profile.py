from django.db import migrations


DEFAULT_NAME = "Default"
DEFAULTS = {
    "priority": 9999,  # evaluated last; catch-all for comics no other profile matches
    "is_enabled": True,
    "folder_template": "<publisher>/<series>{ (<volume>)}",
    "file_template": "<series>{ #<number>}{ (<year>)}",
    "base_folder": "/comics/library",
    "exclude_rules": {},
}


def create_default_profile(apps, schema_editor):
    OrganizerProfile = apps.get_model("organizer", "OrganizerProfile")
    OrganizerProfile.objects.get_or_create(name=DEFAULT_NAME, defaults=DEFAULTS)


def remove_default_profile(apps, schema_editor):
    OrganizerProfile = apps.get_model("organizer", "OrganizerProfile")
    OrganizerProfile.objects.filter(name=DEFAULT_NAME, priority=9999).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("organizer", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_profile, remove_default_profile),
    ]
