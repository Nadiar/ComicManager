"""
Organizer signals.

Flags all organized/written comics for re-organization when an
OrganizerProfile template changes, since the computed paths may differ.
"""

from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import OrganizerProfile


# Fields that determine the output path of a comic
_TEMPLATE_FIELDS = frozenset({"folder_template", "file_template", "base_folder"})


@receiver(pre_save, sender=OrganizerProfile)
def flag_all_on_profile_template_change(sender, instance, **kwargs):
    """
    When a path-determining field changes on an OrganizerProfile, mark every
    organized/written digital comic as needing re-organization.

    We use pre_save (not post_save) so we can compare old vs new template
    values before the change is committed.
    """
    if not instance.pk:
        return  # New profile — no existing comics affected

    try:
        old = sender.objects.only(*_TEMPLATE_FIELDS).get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    changed = any(getattr(instance, f) != getattr(old, f) for f in _TEMPLATE_FIELDS)
    if not changed:
        return

    from apps.core.models import Comic

    Comic.objects.filter(
        state__in=[Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN],
        medium=Comic.MEDIUM_DIGITAL,
    ).exclude(file_path="").exclude(file_path__isnull=True).update(needs_reorganize=True)
