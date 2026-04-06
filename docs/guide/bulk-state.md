# Bulk State Operations

Sometimes you need to move a large number of comics through the pipeline without processing each one individually. This page covers Django shell commands for bulk state changes.

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
This skips the write step entirely for the affected comics. If you later change metadata for those comics (re-scrape, re-tag, etc.), the `needs_rewrite` flag will be set and they will appear in the Maintenance queue for a targeted re-write at that point.
:::
