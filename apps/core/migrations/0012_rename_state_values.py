from django.db import migrations

FORWARD_SQL = """
UPDATE core_comic SET state = 'scrape'      WHERE state = 'imported';
UPDATE core_comic SET state = 'count'       WHERE state = 'counted';
UPDATE core_comic SET state = 'tagging'     WHERE state = 'tagged';
UPDATE core_comic SET state = 'formats'     WHERE state = 'formatted';
UPDATE core_comic SET state = 'deduplicate' WHERE state = 'deduplicated';
UPDATE core_comic SET state = 'move'        WHERE state = 'organized';
UPDATE core_comic SET state = 'write'       WHERE state = 'written';
"""

REVERSE_SQL = """
UPDATE core_comic SET state = 'imported'    WHERE state = 'scrape';
UPDATE core_comic SET state = 'counted'     WHERE state = 'count';
UPDATE core_comic SET state = 'tagged'      WHERE state = 'tagging';
UPDATE core_comic SET state = 'formatted'   WHERE state = 'formats';
UPDATE core_comic SET state = 'deduplicated' WHERE state = 'deduplicate';
UPDATE core_comic SET state = 'organized'   WHERE state = 'move';
UPDATE core_comic SET state = 'written'     WHERE state = 'write';
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_storage_location_nullable"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
