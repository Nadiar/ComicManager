from django.db import models


class DataManagerRuleset(models.Model):
    """
    Stores imported rulesets from dataman.dat XML file.

    Each ruleset contains:
    - Conditions (rules) that must match for the ruleset to apply
    - Actions that modify comic metadata when conditions are met

    Rules are evaluated in priority order. With cascading enabled,
    ALL matching rulesets apply - later matches can override fields
    set by earlier matches.
    """

    MODE_AND = "AND"
    MODE_OR = "OR"
    MODE_CHOICES = [
        (MODE_AND, "AND - All rules must match"),
        (MODE_OR, "OR - Any rule can match"),
    ]

    name = models.CharField(max_length=256, help_text="Ruleset name (e.g., 'Green Lantern')")
    group_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        db_index=True,
        help_text="Hierarchical group path (e.g., 'DC Series Groups/Cosmic/OA')",
    )
    comment = models.TextField(blank=True, default="", help_text="Optional notes about this ruleset")
    mode = models.CharField(
        max_length=3,
        choices=MODE_CHOICES,
        default=MODE_AND,
        help_text="How to combine multiple rules",
    )
    priority = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Order of evaluation (lower = earlier). Preserves import order.",
    )
    is_enabled = models.BooleanField(default=True, db_index=True, help_text="Whether this ruleset is active")

    # Rules stored as list of dicts:
    # [{"field": "Series", "modifier": "Contains", "value": "Green Lantern"}, ...]
    rules = models.JSONField(
        default=list,
        help_text="List of rule conditions: [{field, modifier, value}, ...]",
    )

    # Actions stored as list of dicts:
    # [{"field": "SeriesGroup", "modifier": "SetValue", "value": "OA"}, ...]
    actions = models.JSONField(
        default=list,
        help_text="List of actions to apply: [{field, modifier, value}, ...]",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "group_path", "name"]
        indexes = [
            models.Index(fields=["group_path", "priority"]),
            models.Index(fields=["is_enabled", "priority"]),
        ]

    def __str__(self):
        if self.group_path:
            return f"{self.group_path}/{self.name}"
        return self.name

    @property
    def rule_count(self):
        return len(self.rules) if self.rules else 0

    @property
    def action_count(self):
        return len(self.actions) if self.actions else 0

    @property
    def top_level_group(self):
        """Return the first part of the group path (e.g., 'DC Series Groups')."""
        if self.group_path:
            return self.group_path.split("/")[0]
        return ""
