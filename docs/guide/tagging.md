# Tagging: The Rule-Based Logic

ComicManager includes a built-in rule engine for automatically tagging and categorizing comics. The system is inspired by and compatible with the ComicRack DataManager plugin. You can import your existing `dataman.dat` file directly.

![Rule List](/tags.png)

## Why Rules?

ComicVine provides the "Source of Truth," but it doesn't know how *you* want to organize your library. The rule engine bridges the gap between raw scraped metadata and your personal organization preferences.

Imagine you have a comic titled "Batman #1 (2011)." ComicVine tells you it's published by DC Comics. But in your library, you want to:
- Group all "Batman" titles under a **Series Group** called "Batman Family."
- Assign a **Main Character** called "Batman" for better sorting.
- Standardize the **Publisher** name to "DC Comics" (instead of e.g. "DC Comics/Vertigo").

Rulesets do this automatically.

## How Tagging Works

After comics are scraped (reach the **Tagging** state), running **Tag All** evaluates every enabled ruleset against each comic. Rules can set:

1. **Series Group**: Grouping related series together (e.g., "Spider-Man Universe," "X-Men").
2. **Main Character or Team**: Identifying the primary focus of the series for cleaner filtering.
3. **Tags and Genres**: Categorizing series into specific buckets (e.g., "Crime," "Superhero," "Horror").
4. **Any other field**: Publisher normalization, custom values, notes, etc.

Rulesets are evaluated in **priority order** (lower number = earlier). All matching rulesets apply in sequence. Each ruleset sees the changes already made by earlier ones and can override them.

---

## Rulesets and Group Paths

All rules are organized into **Rulesets**. Each ruleset has:

- **Name**: e.g., "Green Lantern"
- **Group Path**: hierarchical path for organizing rulesets in the sidebar (e.g., `DC Series Groups/Earth Cities/Gotham`)
- **Mode**: AND (all rules must match) or OR (any single rule matches)
- **Priority**: evaluation order
- **Rules (conditions)**: what to match
- **Actions**: what to change when the ruleset matches

The ruleset list (`/tagging/`) shows a folder tree on the left built from group paths, letting you navigate and filter by group.

---

## Importing a dataman.dat File

If you already have a ComicRack DataManager setup, you can import your rulesets directly.

**Via the UI**: Go to **Tagging** and click **Import DataManager**. Upload your `dataman.dat` file and optionally check **Clear existing rulesets** before importing.

**Via the CLI** (useful if the file is already inside the container):

```bash
docker compose exec web python manage.py import_datamanager /path/to/dataman.dat
# Add --clear to wipe existing rulesets first
docker compose exec web python manage.py import_datamanager /path/to/dataman.dat --clear
```

Duplicate rulesets (same name + group path) are skipped automatically.

## Publisher Management

ComicManager helps you track which publishers are covered by your enabled rulesets via the **Publishers** page (`/tagging/publishers/`).

- **Known publishers**: publishers explicitly matched by `Is` or `IsAnyOf` conditions in your enabled rulesets.
- **Uncovered publishers**: publishers present in your library that are not handled by any enabled ruleset.
- **`unknown_publisher` flag**: after scraping, comics whose publisher is not covered by any ruleset get flagged and appear in the Review Queue.
- **Create from Publisher**: click an uncovered publisher to instantly generate a new ruleset pre-filled with a matching condition for that publisher.

## Batch Operations and Audit Log

ComicManager runs tagging as a Celery task, providing real-time progress bars and an Audit Log.

**The Safety Net**: Every change made by a ruleset is logged. If a rule was too broad and tagged too many comics incorrectly, use the **Rollback** button in the audit log to undo those changes in a single click.

## Rule Syntax Reference

### Available Fields

Rules can match and modify the following fields:

**Standard metadata fields:**

| Field Name | Description |
|------------|-------------|
| `Series` | Comic series name |
| `Title` | Issue title |
| `Publisher` | Publisher name |
| `Writer` | Writer credits |
| `Format` | Format type (Main Series, TPB, One-Shot, etc.) |
| `Volume` | Volume number |
| `Notes` | Notes field |
| `Number` | Issue number |
| `Year` | Publication year |
| `Tags` | Tags |
| `Original Format` | Original format from source data |
| `FileName` | The comic's filename (without path) |

**Organizational fields:**

| Field Name | Description |
|------------|-------------|
| `SeriesGroup` | Series group classification |
| `MainCharacterOrTeam` | Primary character or team |

**Custom value fields** (stored in the comic's `custom_values` JSON):

| Field Name | Description |
|------------|-------------|
| `First Series` | First series in a multi-series story |
| `Second Series` | Second series reference |
| `comicvine_issue` | ComicVine issue ID |
| `comicvine_volume` | ComicVine volume ID |
| `DataManager_Processed` | Processing stamp |
| `Review` | Review notes |
| `SeriesComplete` | Series completion marker |

---

### Condition Operators

These operators define how the rule matches a field's current value:

| Operator | Description | Example Value |
|----------|-------------|---------------|
| `Is` | Exact match (case-insensitive) | `"DC Comics"` |
| `IsAnyOf` | Matches any of the given values | `"Marvel\|\|DC\|\|Image"` |
| `Not` | Does NOT exactly match | `"Unknown"` |
| `Contains` | Field contains this substring | `"Batman"` |
| `ContainsAnyOf` | Contains any of the given substrings | `"Batman\|\|Robin"` |
| `NotContains` | Does NOT contain this substring | `"Annual"` |
| `NotContainsAnyOf` | Does NOT contain any of the given substrings | `"Special\|\|Annual"` |
| `StartsWith` | Field begins with this string | `"Uncanny"` |
| `StartsWithAnyOf` | Starts with any of the given strings | `"Amazing\|\|Uncanny"` |
| `NotStartsWith` | Does NOT start with this string | `"The"` |
| `RegEx` | Matches this regular expression (case-insensitive) | `"^Batman.*\d{4}$"` |
| `NotRegEx` | Does NOT match this regular expression | `"\(Annual\)"` |

**Multi-value separator:** For `IsAnyOf`, `ContainsAnyOf`, `StartsWithAnyOf`, and their negations, separate values with a double pipe `||`. Example: `"Marvel||DC||Image"`.

---

### Action Types

These define what the ruleset does when it matches:

| Action | Description | Value Format |
|--------|-------------|--------------|
| `SetValue` | Replace the field with a new value | `"DC Comics"` |
| `Add` | Append to the field (comma-separated) | `"Superhero"` |
| `Remove` | Remove a substring from the field value | `"(of 6)"` |
| `Replace` | Replace one substring with another | `"Batman\|\|The Dark Knight"` |
| `RegExVarReplace` | Replace using a named regex capture group | `"(?P<year>\d{4})"` |
| `RegExVarAppend` | Append using a named regex capture group | `"(?P<arc>.*?) Part \d"` |

**Replace format:** For the `Replace` action, use double pipe to separate the old and new values: `"old text||new text"`.

---

### Ruleset Modes

Each ruleset has a **mode** that controls how its conditions are evaluated together:

- **AND**: All rules in the ruleset must match for it to apply.
- **OR**: Any single rule matching causes the ruleset to apply.

---

### Evaluation Order

- Rulesets are evaluated in **priority order** (lower priority number = evaluated first).
- All matching rulesets apply in sequence. Each ruleset sees the changes made by earlier ones and can override them.

---