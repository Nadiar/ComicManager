import csv
import io

from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from apps.core.models import Comic

FORMAT_CHOICES = [
    "", "Main Series", "TPB", "One-Shot", "Limited Series",
    "Omnibus", "Annual", "Director's Cut", "Black & White", "Hardcover",
]


def index(request):
    return redirect("/comics/?medium=physical")


@require_http_methods(["GET", "POST"])
def add_physical(request):
    if request.method == "POST":
        series = request.POST.get("series", "").strip()
        number = request.POST.get("number", "").strip()
        volume = request.POST.get("volume", "").strip()
        year = request.POST.get("year", "").strip()
        publisher = request.POST.get("publisher", "").strip()
        format_ = request.POST.get("format", "").strip()
        title = request.POST.get("title", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not series:
            messages.error(request, "Series is required.")
            return render(request, "physical/add.html", {
                "form": request.POST,
                "format_choices": FORMAT_CHOICES,
            })

        comic = Comic(
            medium=Comic.MEDIUM_PHYSICAL,
            state=Comic.STATE_IMPORTED,
            series=series,
            number=number or None,
            volume=int(volume) if volume.isdigit() else None,
            year=int(year) if year.isdigit() else None,
            publisher=publisher or None,
            format=format_ or None,
            title=title or None,
            notes=notes or None,
        )
        comic.save()
        messages.success(request, f"Physical comic added: {comic}")
        return redirect(f"/comics/{comic.pk}/")

    return render(request, "physical/add.html", {
        "format_choices": FORMAT_CHOICES,
    })


@require_http_methods(["GET", "POST"])
def import_csv(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No CSV file uploaded.")
            return render(request, "physical/import_csv.html")

        try:
            content = csv_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            created = 0
            errors = []

            for i, row in enumerate(reader, start=2):
                series = (row.get("series") or row.get("Series") or "").strip()
                if not series:
                    errors.append(f"Row {i}: missing series, skipped")
                    continue

                try:
                    number = (row.get("number") or row.get("Number") or "").strip()
                    volume = (row.get("volume") or row.get("Volume") or "").strip()
                    year = (row.get("year") or row.get("Year") or "").strip()
                    publisher = (row.get("publisher") or row.get("Publisher") or "").strip()
                    format_ = (row.get("format") or row.get("Format") or "").strip()
                    title = (row.get("title") or row.get("Title") or "").strip()
                    notes = (row.get("notes") or row.get("Notes") or "").strip()

                    comic = Comic(
                        medium=Comic.MEDIUM_PHYSICAL,
                        state=Comic.STATE_IMPORTED,
                        series=series,
                        number=number or None,
                        volume=int(volume) if volume.isdigit() else None,
                        year=int(year) if year.isdigit() else None,
                        publisher=publisher or None,
                        format=format_ or None,
                        title=title or None,
                        notes=notes or None,
                    )
                    comic.save()
                    created += 1
                except Exception as e:
                    errors.append(f"Row {i}: {e}")

        except Exception as e:
            messages.error(request, f"Failed to parse CSV: {e}")
            return render(request, "physical/import_csv.html")

        if created:
            messages.success(request, f"Imported {created} physical comic(s).")
        for err in errors[:10]:
            messages.warning(request, err)
        return redirect("/comics/?medium=physical")

    return render(request, "physical/import_csv.html")
