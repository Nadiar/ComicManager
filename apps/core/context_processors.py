def active_tasks(request):
    """Inject active background task IDs into template context."""
    return {
        "active_write_task_id": request.session.get("write_task_id", ""),
    }
