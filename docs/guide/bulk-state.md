# Bulk State Operations

Sometimes you need to move a large number of comics through the pipeline without processing each one individually. This page covers Django shell commands for bulk state changes.

## First-time import of an existing ComicRack library

If you are migrating an entire existing library (already organized and tagged by ComicRack or another tool), you don't need to run it through the full pipeline. Use the `import_library` management command instead:

```bash
docker compose exec web python manage.py import_library --path /comics/library
```

Optionally pass `--comicdb /path/to/ComicDb.xml` to enrich imports with Tags, Teams, Locations, and CustomValuesStore data that isn't present in `ComicInfo.xml`. Files that have no `ComicInfo.xml` at all are then imported from their ComicDb.xml entry. Use `--dry-run` first to preview what would be imported.

This command reads each CBZ's embedded `ComicInfo.xml` and creates a `Comic` record already in the **Write to CBZ** state (it assumes the file is already fully tagged, since it came from an existing library). It does not touch the pipeline states before that (New, Scrape, Tagging, etc.) and it does not advance anything to **Done** on its own.

Once the import finishes, follow the steps below to bulk-advance those records from **Write to CBZ** to **Done**.

## Advancing old imports past the Write stage

If you have a large backlog of comics in the **Write to CBZ** state that were imported from a previous tool (such as ComicRack), they likely already have correct `ComicInfo.xml` data embedded. Re-writing all of them just to confirm this wastes significant disk I/O and time, especially on large libraries.

The safe approach is to check the import date. Comics imported more than 7 days ago are assumed to be pre-existing, well-tagged files that do not need a re-write. You can inspect the numbers first, then advance them in a second step.

**Step 1: Check the counts**

```bash
docker compose exec web python manage.py shell -c "
from django.utils import timezone
from datetime import timedelta
from apps.core.models import Comic

cutoff = timezone.now() - timedelta(days=7)
total = Comic.objects.filter(state='write').count()
old = Comic.objects.filter(state='write', imported_at__lt=cutoff).count()
recent = total - old

print(f'Total in write state: {total}')
print(f'Imported > 7 days ago (old/CR imports): {old}')
print(f'Imported <= 7 days ago (recent, needs write): {recent}')
"
```

**Step 2: Advance old imports to Done**

Once you are satisfied with the numbers, run this to bulk-advance them:

```bash
docker compose exec web python manage.py shell -c "
from django.utils import timezone
from datetime import timedelta
from apps.core.models import Comic

cutoff = timezone.now() - timedelta(days=7)
updated = Comic.objects.filter(state='write', imported_at__lt=cutoff).update(state='done')
print(f'Advanced {updated} comics to done')
"
```

The recently imported comics (within 7 days) remain in the **Write** state and go through the normal write pipeline so their `ComicInfo.xml` is freshly generated from your current DB metadata.

::: warning
This skips the write step entirely for the affected comics. If you later change metadata for those comics (re-scrape, re-tag, etc.), the dashboard will surface them as "Stale Metadata" (a dynamic check comparing `updated_at` against `last_written`) and they will appear in the Maintenance queue for a targeted re-write at that point.
:::
