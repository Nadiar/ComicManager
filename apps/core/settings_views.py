from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Setting


def settings_index(request):
    settings = Setting.objects.all()
    # Group them for the template
    grouped = {}
    for s in settings:
        grouped.setdefault(s.group, []).append(s)
    return render(request, "core/settings.html", {"grouped": grouped})


def settings_update(request):
    if request.method == "POST":
        for key, value in request.POST.items():
            if key.startswith("csrf"):
                continue
            Setting.objects.filter(key=key).update(value=value)
        messages.success(request, "Settings saved.")
    return redirect("settings:index")
