from django.shortcuts import render
from django.db.models import Count
from apps.core.models import Comic


def index(request):
    stats = {
        "total":     Comic.objects.count(),
        "digital":   Comic.objects.filter(medium="digital").count(),
        "physical":  Comic.objects.filter(medium="physical").count(),
        "new":       Comic.objects.filter(state="new").count(),
        "written":   Comic.objects.filter(state="written").count(),
    }

    # Get counts per workflow state
    state_counts = dict(
        Comic.objects.values("state").annotate(count=Count("id")).values_list("state", "count")
    )

    # Workflow pipeline stages
    pipeline = [
        {"state": "new", "label": "1. New", "description": "Awaiting processing", "count": state_counts.get("new", 0)},
        {"state": "imported", "label": "2. Imported", "description": "File info extracted", "count": state_counts.get("imported", 0)},
        {"state": "scraped", "label": "3. Scraped", "description": "ComicVine matched", "count": state_counts.get("scraped", 0)},
        {"state": "counted", "label": "4. Counted", "description": "Issue count set", "count": state_counts.get("counted", 0)},
        {"state": "tagged", "label": "5. Tagged", "description": "Publisher rules applied", "count": state_counts.get("tagged", 0)},
        {"state": "formatted", "label": "6. Formatted", "description": "Format detected", "count": state_counts.get("formatted", 0)},
        {"state": "deduplicated", "label": "7. Deduplicated", "description": "Duplicates resolved", "count": state_counts.get("deduplicated", 0)},
        {"state": "organized", "label": "8. Organized", "description": "Moved to library", "count": state_counts.get("organized", 0)},
        {"state": "written", "label": "9. Written", "description": "ComicInfo.xml saved", "count": state_counts.get("written", 0)},
    ]

    # Review queue - count comics with each flag type
    # Using __contains for JSONField lookup
    review_queue = [
        {
            "flag": "low_page_count",
            "label": "Low Page Count",
            "description": "Less than 5 pages - likely incomplete",
            "count": Comic.objects.filter(flags__low_page_count=True).count(),
            "action": "delete",
        },
        {
            "flag": "is_pdf",
            "label": "PDF Files",
            "description": "PDF format needs manual review",
            "count": Comic.objects.filter(flags__is_pdf=True).count(),
            "action": "review",
        },
        {
            "flag": "no_series",
            "label": "No Series Parsed",
            "description": "Couldn't extract series name from filename",
            "count": Comic.objects.filter(flags__no_series=True).count(),
            "action": "edit",
        },
        {
            "flag": "cover_only",
            "label": "Cover Only",
            "description": "Likely just a cover image (≤3 pages)",
            "count": Comic.objects.filter(flags__cover_only=True).count(),
            "action": "delete",
        },
        {
            "flag": "needs_conversion",
            "label": "Needs Conversion",
            "description": "CBR/CB7 files need conversion to CBZ",
            "count": Comic.objects.filter(flags__needs_conversion=True).count(),
            "action": "convert",
        },
    ]

    # Total flagged comics (any flag)
    flagged_count = Comic.objects.exclude(flags={}).count()

    return render(request, "dashboard/index.html", {
        "stats": stats,
        "pipeline": pipeline,
        "review_queue": review_queue,
        "flagged_count": flagged_count,
    })
