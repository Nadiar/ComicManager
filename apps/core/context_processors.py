def active_tasks(request):
    """Inject active background task IDs into template context."""
    return {
        "active_write_task_id": request.session.get("write_task_id", ""),
        "active_audit_task_id": request.session.get("audit_task_id", ""),
        "active_reorganize_task_id": request.session.get("reorganize_task_id", ""),
        "active_smartlist_action_task_id": request.session.get("smartlist_action_task_id", ""),
        # Generic slot used by all new batch tasks
        "active_task_id": request.session.get("active_task_id", ""),
        "active_task_label": request.session.get("active_task_label", ""),
    }
