import re

from django.db import migrations

_CHAR_REF = re.compile(r"&#(?:(\d+)|[xX]([0-9a-fA-F]+));")


def _decode(text):
    def char(m):
        try:
            return chr(int(m.group(1)) if m.group(1) else int(m.group(2), 16))
        except (ValueError, OverflowError):
            return m.group(0)
    return _CHAR_REF.sub(char, text)


def decode_char_refs(apps, schema_editor):
    """Custom values imported from ComicRack's ComicDb.xml kept its escaping:
    a comma came in as &#44; and an equals sign as &#61;. Decode them, and mark
    the comics changed so files already written show as Stale Metadata."""
    Comic = apps.get_model("core", "Comic")
    for comic in Comic.objects.exclude(custom_values={}).exclude(custom_values__isnull=True).iterator():
        values = comic.custom_values
        if not isinstance(values, dict):
            continue
        decoded = {_decode(str(k)): _decode(v) if isinstance(v, str) else v for k, v in values.items()}
        if decoded != values:
            comic.custom_values = decoded
            comic.save(update_fields=["custom_values", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_comic_imprint'),
    ]

    operations = [
        migrations.RunPython(decode_char_refs, migrations.RunPython.noop),
    ]
