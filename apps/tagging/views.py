"""
Tagging App Views - Ruleset management UI (CRUD, Import, Export).
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from .models import DataManagerRuleset
from .parser import import_datamanager_file, export_datamanager_xml
from .engine import FIELD_MAP, RULE_MODIFIERS, ACTION_MODIFIERS


def ruleset_list(request):
    """
    List all rulesets with filtering and grouping options.
    """
    rulesets = DataManagerRuleset.objects.all()

    # Search filter
    search = request.GET.get("search", "").strip()
    if search:
        rulesets = rulesets.filter(
            Q(name__icontains=search) | Q(group_path__icontains=search)
        )

    # Group filter
    group = request.GET.get("group", "").strip()
    if group:
        rulesets = rulesets.filter(group_path__startswith=group)

    # Enabled filter
    enabled = request.GET.get("enabled", "")
    if enabled == "true":
        rulesets = rulesets.filter(is_enabled=True)
    elif enabled == "false":
        rulesets = rulesets.filter(is_enabled=False)

    rulesets = rulesets.order_by("priority", "group_path", "name")

    # Get unique top-level groups for filter dropdown
    all_groups = DataManagerRuleset.objects.values_list("group_path", flat=True).distinct()
    top_level_groups = sorted(set(g.split("/")[0] for g in all_groups if g))

    # Pagination
    paginator = Paginator(rulesets, 50)
    page = request.GET.get("page", 1)
    rulesets_page = paginator.get_page(page)

    # Stats
    total_count = DataManagerRuleset.objects.count()
    enabled_count = DataManagerRuleset.objects.filter(is_enabled=True).count()

    return render(request, "tagging/ruleset_list.html", {
        "rulesets": rulesets_page,
        "search": search,
        "group": group,
        "enabled": enabled,
        "top_level_groups": top_level_groups,
        "total_count": total_count,
        "enabled_count": enabled_count,
    })


def ruleset_detail(request, pk):
    """
    View details of a single ruleset.
    """
    ruleset = get_object_or_404(DataManagerRuleset, pk=pk)

    return render(request, "tagging/ruleset_detail.html", {
        "ruleset": ruleset,
    })


def _validate_ruleset_form(post_data):
    """
    Check that every rule and action row has both a field and a modifier.

    Returns a list of human-readable error strings (empty means valid).
    """
    errors = []
    i = 0
    while f"rule_field_{i}" in post_data:
        field = post_data.get(f"rule_field_{i}", "").strip()
        modifier = post_data.get(f"rule_modifier_{i}", "").strip()
        if field and not modifier:
            errors.append(f"Rule {i + 1}: a modifier is required when a field is selected.")
        elif modifier and not field:
            errors.append(f"Rule {i + 1}: a field is required when a modifier is selected.")
        i += 1

    i = 0
    while f"action_field_{i}" in post_data:
        field = post_data.get(f"action_field_{i}", "").strip()
        modifier = post_data.get(f"action_modifier_{i}", "").strip()
        if field and not modifier:
            errors.append(f"Action {i + 1}: a modifier is required when a field is selected.")
        elif modifier and not field:
            errors.append(f"Action {i + 1}: a field is required when a modifier is selected.")
        i += 1

    return errors


def ruleset_create(request):
    """
    Create a new ruleset.
    """
    if request.method == "POST":
        errors = _validate_ruleset_form(request.POST)
        if errors:
            for error in errors:
                messages.error(request, error)
            context = _get_form_context()
            return render(request, "tagging/ruleset_form.html", {
                "action": "Create",
                **context,
            })
        ruleset = _save_ruleset_from_form(request.POST)
        messages.success(request, f"Ruleset '{ruleset.name}' created successfully.")
        return redirect("tagging:ruleset_detail", pk=ruleset.pk)

    # Get field/modifier options for form
    context = _get_form_context()
    return render(request, "tagging/ruleset_form.html", {
        "action": "Create",
        **context,
    })


def ruleset_edit(request, pk):
    """
    Edit an existing ruleset.
    """
    ruleset = get_object_or_404(DataManagerRuleset, pk=pk)

    if request.method == "POST":
        errors = _validate_ruleset_form(request.POST)
        if errors:
            for error in errors:
                messages.error(request, error)
            context = _get_form_context()
            return render(request, "tagging/ruleset_form.html", {
                "action": "Edit",
                "ruleset": ruleset,
                **context,
            })
        _save_ruleset_from_form(request.POST, ruleset)
        messages.success(request, f"Ruleset '{ruleset.name}' updated successfully.")
        return redirect("tagging:ruleset_detail", pk=ruleset.pk)

    context = _get_form_context()
    return render(request, "tagging/ruleset_form.html", {
        "action": "Edit",
        "ruleset": ruleset,
        **context,
    })


@require_POST
def ruleset_delete(request, pk):
    """
    Delete a ruleset.
    """
    ruleset = get_object_or_404(DataManagerRuleset, pk=pk)
    name = ruleset.name
    ruleset.delete()

    messages.success(request, f"Ruleset '{name}' deleted successfully.")
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("tagging:ruleset_list")


@require_POST
def ruleset_duplicate(request, pk):
    """
    Duplicate a ruleset.
    """
    original = get_object_or_404(DataManagerRuleset, pk=pk)

    # Find a unique name
    base_name = f"{original.name} (copy)"
    name = base_name
    counter = 1
    while DataManagerRuleset.objects.filter(name=name, group_path=original.group_path).exists():
        counter += 1
        name = f"{base_name} {counter}"

    # Get the max priority + 1
    max_priority = DataManagerRuleset.objects.order_by("-priority").values_list("priority", flat=True).first() or 0

    copy = DataManagerRuleset.objects.create(
        name=name,
        group_path=original.group_path,
        comment=original.comment,
        mode=original.mode,
        priority=max_priority + 1,
        is_enabled=True,
        rules=original.rules.copy() if original.rules else [],
        actions=original.actions.copy() if original.actions else [],
    )

    messages.success(request, f"Ruleset duplicated as '{copy.name}'.")
    next_url = request.POST.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("tagging:ruleset_edit", pk=copy.pk)


@require_POST
def ruleset_toggle(request, pk):
    """
    Toggle a ruleset's enabled status.
    """
    ruleset = get_object_or_404(DataManagerRuleset, pk=pk)
    ruleset.is_enabled = not ruleset.is_enabled
    ruleset.save()

    status = "enabled" if ruleset.is_enabled else "disabled"
    return JsonResponse({
        "success": True,
        "is_enabled": ruleset.is_enabled,
        "message": f"Ruleset '{ruleset.name}' {status}.",
    })


def import_datamanager(request):
    """
    Import a dataman.dat XML file.
    """
    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            messages.error(request, "No file uploaded.")
            return redirect("tagging:import")

        clear_existing = request.POST.get("clear_existing") == "on"

        try:
            created, skipped = import_datamanager_file(uploaded_file, clear_existing=clear_existing)
            messages.success(
                request,
                f"Import complete: {created} rulesets created, {skipped} skipped (duplicates)."
            )
        except Exception as e:
            messages.error(request, f"Import failed: {str(e)}")

        return redirect("tagging:ruleset_list")

    return render(request, "tagging/import.html", {
        "total_rulesets": DataManagerRuleset.objects.count(),
    })


def export_datamanager(request):
    """
    Export all rulesets to DataManager XML format.
    """
    xml_content = export_datamanager_xml()

    response = HttpResponse(xml_content, content_type="application/xml")
    response["Content-Disposition"] = 'attachment; filename="dataman.dat"'
    return response


# =============================================================================
# Helper Functions
# =============================================================================


def _get_form_context():
    """Get context data for ruleset forms (field/modifier options)."""
    return {
        "field_options": sorted(FIELD_MAP.keys()),
        "rule_modifier_options": sorted(RULE_MODIFIERS.keys()),
        "action_modifier_options": sorted(ACTION_MODIFIERS.keys()),
        "mode_choices": DataManagerRuleset.MODE_CHOICES,
    }


def _save_ruleset_from_form(post_data, ruleset=None):
    """
    Save a ruleset from form POST data.

    Form data format:
    - name, group_path, comment, mode, priority, is_enabled (standard fields)
    - rule_field_0, rule_modifier_0, rule_value_0 (rules)
    - action_field_0, action_modifier_0, action_value_0 (actions)
    """
    if ruleset is None:
        ruleset = DataManagerRuleset()

    ruleset.name = post_data.get("name", "").strip()
    ruleset.group_path = post_data.get("group_path", "").strip()
    ruleset.comment = post_data.get("comment", "").strip()
    ruleset.mode = post_data.get("mode", "AND")
    ruleset.is_enabled = post_data.get("is_enabled") == "on"

    try:
        ruleset.priority = int(post_data.get("priority", 0))
    except ValueError:
        ruleset.priority = 0

    # Parse rules from indexed form fields
    rules = []
    i = 0
    while f"rule_field_{i}" in post_data:
        field = post_data.get(f"rule_field_{i}", "").strip()
        modifier = post_data.get(f"rule_modifier_{i}", "").strip()
        value = post_data.get(f"rule_value_{i}", "")

        if field and modifier:
            rules.append({
                "field": field,
                "modifier": modifier,
                "value": value,
            })
        i += 1

    ruleset.rules = rules

    # Parse actions from indexed form fields
    actions = []
    i = 0
    while f"action_field_{i}" in post_data:
        field = post_data.get(f"action_field_{i}", "").strip()
        modifier = post_data.get(f"action_modifier_{i}", "").strip()
        value = post_data.get(f"action_value_{i}", "")

        if field and modifier:
            actions.append({
                "field": field,
                "modifier": modifier,
                "value": value,
            })
        i += 1

    ruleset.actions = actions

    ruleset.save()
    return ruleset
