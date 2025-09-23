"""
Library Organizer Models - Profiles for organizing comics into folder structures.
"""

from django.db import models


class OrganizerProfile(models.Model):
    """
    Stores organizer profiles imported from .lop files or created by users.

    Each profile defines:
    - Matching rules (which comics this profile applies to)
    - Folder/file templates (how to generate the destination path)
    - Character sanitization rules
    """

    name = models.CharField(max_length=256)
    priority = models.IntegerField(default=0, db_index=True)  # Lower = evaluated first
    is_enabled = models.BooleanField(default=True)

    # Templates for path generation
    folder_template = models.CharField(max_length=1024)
    file_template = models.CharField(max_length=512)
    base_folder = models.CharField(max_length=512, default="/comics/library")

    # Rules stored as JSON - nested structure with groups
    # Example:
    # {
    #     "operator": "All",  # "All" (AND) or "Any" (OR)
    #     "mode": "Only",     # "Only" = include matching, "Do not" = exclude matching
    #     "rules": [
    #         {"type": "rule", "field": "Publisher", "operator": "is", "value": "Marvel"},
    #         {"type": "group", "operator": "Any", "rules": [
    #             {"type": "rule", "field": "Format", "operator": "is", "value": "TPB"},
    #             {"type": "rule", "field": "Format", "operator": "is", "value": "HC"},
    #         ]},
    #     ]
    # }
    exclude_rules = models.JSONField(default=dict)

    # Character mappings for sanitization
    # Default: {'"': "'", '/': '', '*': '', '<': '[', '?': '', '>': ']', '|': '!', ':': ' - ', '\\': ''}
    illegal_characters = models.JSONField(default=dict)

    # Month number to name mapping
    # Default: {1: "January", ..., 12: "December", 13: "Spring", 14: "Summer", 15: "Fall", 16: "Winter"}
    months = models.JSONField(default=dict)

    # Processing flags
    remove_empty_folder = models.BooleanField(default=True)
    auto_space_fields = models.BooleanField(default=True)
    replace_multiple_spaces = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'name']

    def __str__(self):
        return f"{self.priority:02d} - {self.name}"

    @classmethod
    def get_default_illegal_characters(cls) -> dict:
        """Return default illegal character mapping."""
        return {
            '"': "'",
            '/': '',
            '*': '',
            '<': '[',
            '?': '',
            '>': ']',
            '|': '!',
            ':': ' - ',
            '\\': '',
        }

    @classmethod
    def get_default_months(cls) -> dict:
        """Return default month number to name mapping."""
        return {
            "1": "January",
            "2": "February",
            "3": "March",
            "4": "April",
            "5": "May",
            "6": "June",
            "7": "July",
            "8": "August",
            "9": "September",
            "10": "October",
            "11": "November",
            "12": "December",
            "13": "Spring",
            "14": "Summer",
            "15": "Fall",
            "16": "Winter",
        }
