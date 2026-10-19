# Organizing: Your Structured Library

The **Organizing** stage moves and renames your comic files into a structured library folder based on your configuration. This is the "Commit" phase of our workflow.

## Why Organize?

A messy file structure is the downfall of any large comic collection. You might have:
- Files scattered across multiple folders.
- Files named inconsistently (e.g., `Btm_1_2011.cbz` vs. `Batman #1.cbz`).
- No clear way to find a specific issue or series.

ComicManager solves this by enforcing a standardized library structure. Instead of just letting files sit in your "Untagged" directory, we move them into a permanent home using an **Organization Profile**.

---

## Importing a ComicRack Library Organizer Profile

If you used ComicRack's Library Organizer, you can import your existing `.lop` file directly and replicate your setup without rebuilding templates from scratch.

Go to **Organizer** and click **Import Profile**. Upload your `.lop` file and choose whether to clear existing profiles before importing. The profiles appear immediately in the profile list and are ready to use.

::: warning Check the base folder after importing
ComicRack saves a base folder in every profile, usually a Windows path such as `D:\Comics`. The import keeps that path, but inside the container your library is at `/comics/library`. After importing, edit each profile and set **Base Folder** to `/comics/library` before you move any files.

With a Windows base folder, Move Files fails with a permission error, and Path Audit lists the comics as needing reorganization. If the containers run as root, the move goes through but puts the files inside the container, where they are lost when it is recreated.
:::

Importing also carries over a few behaviors from the original ComicRack profile that have no equivalent form field in ComicManager today: the post-move flags (`RemoveEmptyFolder`, `AutoSpaceFields`, `ReplaceMultipleSpaces`, all On by default) and the illegal-character replacement map used to sanitize path segments (e.g. `:` becomes ` -`, `/` becomes `-`). A profile created from scratch in the UI gets the same defaults. To change any of these values, re-import an edited `.lop`.

### Exporting Organizer Profiles

Go to **Organizer** and click **Export Profiles**. This downloads a `.lop` file generated from the current database state. It includes profiles you created or edited in the UI, not just the originally imported file.

::: warning Compatibility note
ComicManager-specific features (indexed credit fields like `{<writer[1][l]>}`) are not recognized by ComicRack's Library Organizer. If any of your profiles use these features, the exported `.lop` file will open in ComicRack but those template tokens will not work correctly. Profiles that only use standard fields and variables will round-trip without issues.
:::

### Reordering Profiles

ComicManager evaluates profiles **top-to-bottom**, applying the first profile whose conditions match a comic. Drag the handle on the left of any row to reorder profiles and control which rules take priority. Changes are saved automatically.

### Duplicating and Toggling Profiles

Each profile row has two additional actions:

- **Duplicate**: Creates an identical copy of the profile with " (copy)" appended to the name. Use this to create a variant of an existing profile without starting from scratch.
- **Toggle**: Enables or disables the profile inline without opening the edit form. Disabled profiles are skipped during organization but remain in the list for later use.

---

## Library Organization Rules

Your organization profile defines exactly where and how your comic files will be stored:

1.  **Base Folder**: The root directory for your entire comic library.
2.  **Path Templates**: A flexible system for building folder structures based on metadata.
    - **Example**: `{<publisher>}/{<seriesgroup>}/{<series>}{ (<year>)}/`
    - **Result**: `DC Comics/Batman Family/Batman (2011)/`
3.  **File Naming**: A template for standardized filenames.
    - **Example**: `{<series>} { #<number3>}{ (<year>)}`
    - **Result**: `Batman #1 (2011).cbz`

---

## Batch Organization with Precision

Running **Organize All** in the dashboard starts a task that handles file movements in the background.

Before any file is moved, ComicManager performs a "dry run" to ensure:
- The target path doesn't already exist.
- The target folder structure can be created.
- There are no file conflicts.

**Error Logging**: Any file move failures (e.g. file in use, permission denied, missing source file) are recorded as `organize_error` events in the **Audit Log** with the reason, for easy review. Errors from the file system are also written in full to the container log (`docker compose logs web` for a move started from the comic's page, `docker compose logs worker` for Move Files and Re-organize).

**Progress Tracking**: Real-time progress bars and toast notifications keep you informed about the status of your batch organization.

---

## Path Auditing & Re-organizing

Over time, your library structure might change or metadata might be updated after a file was already organized.

- **`needs_reorganize` flag**: Whenever a core metadata field (like Series, Publisher, or Format) changes on a comic that is already in the `Organized` or `Written` state, ComicManager sets this flag. The comic appears in the Maintenance tab of your dashboard so you can safely move it to its new, correct path.
- **Scan Path Audit**: A manual tool to scan your entire library and compare current file paths with the "Expected" paths based on your organization profile. It identifies any comics that are in the wrong location or have the wrong filename.
- **Missing files**: If a comic's file is not on disk at all, the audit does not offer to move it. It gets the `file_missing` flag and is listed in a separate **Missing files** table on the Path Audit page with two actions:
  - **Relink** looks for the file at the comic's expected path, in the expected folder, and in the folder it used to be in. If exactly one matching file is found and no other comic uses it, the comic's path is updated and the flag is cleared.
  - **Remove** deletes only the database record (and its metadata). It never touches files, and it refuses if the file is back on disk.
- **Moves never overwrite**: A move refuses to replace an existing file. When the file moves between the untagged folder and the library (separate volumes), it is copied to a hidden temporary file next to the destination first, so an interrupted move never leaves a half-copied comic under its real name.

::: info Path Audit scope
Path Audit only considers comics in the **Write to CBZ** or **Done** states. Comics still in earlier pipeline stages are excluded, they will be organized as they progress through the pipeline naturally.
:::

![Path Audit Tool](/path_audit.png)

### AU Scan: Alternate Universe Re-organization

Comics that were organized without a `main_character_or_team` set can land in a generic "Alternate Universe" folder as a fallback. If tagging rules later assign a main character to those comics, they need to be moved to the correct folder.

The **AU Scan** (under **Workflow → AU Scan**) handles this automatically. Run it after any tagging pass that might have assigned new main characters. It detects AU-folder comics that now have a main character, flags them `needs_reorganize`, and lets you re-organize them in bulk. 

---

## The Default Profile

Every install includes a built-in **Default** profile at the lowest priority, so it is evaluated last. It has no matching conditions, which means it catches any comic that none of your own profiles match and files it as `Publisher/Series (Volume)/Series #Number (Year)`. This guarantees every organized comic runs through the same path generation and illegal-character handling as the rest of your profiles, rather than a separate fallback path.

You can edit, reorder, or disable the Default profile like any other. If you delete it, ComicManager recreates it the next time a comic needs organizing so there is always a catch-all.

## Profile Matching Conditions

Each organizer profile can have one or more matching conditions that control which comics the profile applies to. A profile with no conditions matches all comics.

**Available fields for conditions:**

| Field | Type | Example |
|-------|------|---------|
| `Format` | Text | `TPB`, `Main Series` |
| `Publisher` | Text | `DC Comics` |
| `Imprint` | Text | `Vertigo` |
| `Series` | Text | `Batman` |
| `SeriesGroup` | Text | `Batman Family` |
| `MainCharacterOrTeam` | Text | `Batman` |
| `Count` | Numeric | `12` |
| `Page Count` | Numeric | `120` |

**Condition mode:** Each condition set has a **mode** toggle:

- **Only**: The profile applies only to comics that match the conditions (include filter).
- **Do not**: The profile applies to all comics *except* those that match the conditions (exclude filter).

Use "Do not" to create a catch-all profile that handles everything except, for example, a specific publisher or format that has its own profile higher in the list.

**Text operators:** `Is`, `IsAnyOf`, `Contains`, `StartsWith`, `Not`, `NotContains`, and their variants.

**Numeric operators** (for `Count` and `Page Count`):

| Operator | Meaning |
|----------|---------|
| `greater than` | Field value is strictly greater than the given number |
| `less than` | Field value is strictly less than the given number |
| `greater than or equal` | Field value is greater than or equal to the given number |
| `less than or equal` | Field value is less than or equal to the given number |

These numeric operators make it possible to split TPBs by volume count (e.g. `Count greater than 1` for multi-volume series) or to treat thick omnibus-sized books differently from slim one-shots.

---

## Path Template Variable Reference

The following variables are available when building path and filename templates in your Organization Profile.

### Standard Variables

All variables use angle brackets around the field name: `{<field>}`.

| Variable | Description | Example Output |
|----------|-------------|----------------|
| `{<series>}` | Comic series name | `Batman` |
| `{<title>}` | Issue title | `The Dark Knight Falls` |
| `{<number>}` | Issue number | `1` |
| `{<volume>}` | Volume number | `2` |
| `{<year>}` | Publication year | `2011` |
| `{<month>}` | Publication month (auto-converted to name, see Modifiers below) | `March` |
| `{<day>}` | Publication day | `15` |
| `{<publisher>}` | Publisher name | `DC Comics` |
| `{<imprint>}` | Imprint name (empty for comics without one) | `Vertigo` |
| `{<format>}` | Format type | `Main Series` |
| `{<genre>}` | Genre | `Superhero` |
| `{<seriesgroup>}` | Series group (set by DataManager) | `Batman Family` |
| `{<maincharacter>}` | Main character or team | `Batman` |
| `{<writer>}` | Writer | `Scott Snyder` |
| `{<penciller>}` | Penciller | `Greg Capullo` |
| `{<inker>}` | Inker | `Jonathan Glapion` |
| `{<colorist>}` | Colorist | `FCO Plascencia` |
| `{<letterer>}` | Letterer | `Richard Starkings` |
| `{<coverartist>}` | Cover artist | `Greg Capullo` |
| `{<editor>}` | Editor | `Katie Kubert` |
| `{<count>}` | Total issue count | `60` |
| `{<storyarc>}` | Story arc name (from custom values) | `Court of Owls` |
| `{<altnumber>}` | Alternate number (from custom values) | `12.1` |
| `{<startyear>}` | Series start year (from custom values) | `2011` |

### Custom Value Variables

Access any custom value field with `{<Custom(key)>}`:

```
{<Custom(comicvine_issue)>}   -> the ComicVine issue ID
{<Custom(comicvine_volume)>}  -> the ComicVine volume ID
{<Custom(StoryArc)>}          -> story arc name
```

Imprint is a standard field, not a custom value. Use `{<imprint>}`, not `{<Custom(Imprint)>}`. Since 1.1.1, an `Imprint` custom value is moved into the Imprint field when you upgrade, so a profile that still uses `{<Custom(Imprint)>}` gets an empty value and leaves out the imprint folder.

---

### Modifiers

**Zero-padding numbers:** append a digit to set the minimum width:

| Syntax | Description | Example |
|--------|-------------|---------|
| `{<number2>}` | Zero-pad to 2 digits | `01`, `12` |
| `{<number3>}` | Zero-pad to 3 digits | `001`, `012` |
| `{<volume0>}` | Use `0` if the field is empty | `0`, `2` |

**Prefix modifier:** place a literal character before the `<` to include it only when the field has a value:

```
{ <volume>}    -> " 2" if volume exists, "" if empty
{#<number3>}   -> "#001" if number exists, "" if empty
```

This prevents orphaned characters (spaces, `#`) when optional fields are absent.

**Conditional segments:** wrap an optional segment in `{}`. The entire segment is dropped if the field inside it is empty:

```
{ - (<storyarc>)}   -> " - (Court of Owls)" if storyarc exists, "" if empty
{ (<year>)}         -> " (2011)" if year exists, "" if empty
```

**Indexed list fields:** comma-separated fields like `writer`, `penciller`, `characters` can be accessed by position. Indices are 1-based. Append `[f]` for first name or `[l]` for last name:

| Syntax | Description | Example (writer = "Chuck Dixon, Kelley Puckett") |
|--------|-------------|--------------------------------------------------|
| `{<writer[1]>}` | First writer, full name | `Chuck Dixon` |
| `{<writer[2]>}` | Second writer, full name | `Kelley Puckett` |
| `{<writer[1][f]>}` | First writer, first name only | `Chuck` |
| `{<writer[1][l]>}` | First writer, last name only | `Dixon` |
| `{<writer[2][l]>}` | Second writer, last name only | `Puckett` |

If the index is out of range (e.g. `writer[3]` when there is only one writer) the field renders as empty, so it works safely with conditional segments:

```
{ by <writer[1][l]>}   -> " by Dixon" if writer exists, "" if empty
```

**Month names:** `{<month>}` maps numeric months to names automatically:

| Number | Name | Number | Name |
|--------|------|--------|------|
| 1 | January | 7 | July |
| 2 | February | 8 | August |
| 3 | March | 9 | September |
| 4 | April | 10 | October |
| 5 | May | 11 | November |
| 6 | June | 12 | December |
| 13 | Spring | 15 | Fall |
| 14 | Summer | 16 | Winter |

---

### Example Templates

**Common path template:**
```
{<publisher>}/{<seriesgroup>}/{<series>}{ (<year>)}/
```
Result: `DC Comics/Batman Family/Batman (2011)/`

**Filename with zero-padded issue number:**
```
{<series>} {#<number3>}{ (<year>)}.cbz
```
Result: `Batman #001 (2011).cbz`

**Filename with optional story arc:**
```
{<series>} {#<number3>}{ - (<storyarc>)}.cbz
```
Result: `Batman #001 - (Court of Owls).cbz`, or `Batman #001.cbz` if no story arc is set.

**TPB with optional volume:**
```
{<series>}{ v<volume>}{ (<year>)}.cbz
```
Result: `Batman v2 (2014).cbz`, or `Batman (2014).cbz` if no volume is set.

---

### TPB Profile Setup: Multi-volume vs Standalone

TPB collections come in two shapes:

- **Multi-volume series**: a run of numbered trade paperbacks (e.g. Spider-Gwen TPB #001, #002, #003). These should be grouped into a series subfolder so they stay together.
- **Standalone collected editions**: a single TPB with no numbered siblings (e.g. Moon Knight by MacKay). A subfolder adds no value; the writer name in the filename makes it instantly recognisable.

The `Count` field (the total issue count from ComicVine) is the discriminator. Create two profiles and set their priorities so the more specific one is evaluated first.

**Profile 1: TPB multi-volume (lower priority number = evaluated first)**

Matching rule: `Format is TPB` AND `Count greater than 1`

```
Folder:  {<publisher>}/{<seriesgroup>}/{<series>}/{<format>}/{<series>} ({<volume>})
File:    {<series>} #{<number3>} [{<month>}, {<year>}]
```

Result:
```
Marvel/Earth/Spider-Gwen/TPB/Spider-Gwen (2017)/Spider-Gwen #001 [February, 2017].cbz
Marvel/Earth/Spider-Gwen/TPB/Spider-Gwen (2017)/Spider-Gwen #002 [January, 2018].cbz
```

**Profile 2: TPB standalone (higher priority number = fallback)**

Matching rule: `Format is TPB` (catches all remaining TPBs that did not match Profile 1)

```
Folder:  {<publisher>}/{<seriesgroup>}/{<series>}/{<format>}
File:    {<series>}{ by <writer[1][l]>}{ [{<month>}, {<year>}]}
```

Result:
```
Marvel/Earth/Moon Knight/TPB/Moon Knight by MacKay [April, 2022].cbz
```

If `writer` is empty the entire `by …` segment is dropped because `by` lives inside the `{}`, leaving just `Moon Knight [April, 2022].cbz`.

---

## Example Setups

These examples show different ways to structure a library. They range from simple to detailed so you can find a style that fits your collection.

---

### 1. Simple flat structure

Good for smaller collections where you just want everything tidy without deep nesting.

**Folder:** `{<publisher>}/{<series>}{ (<year>)}/`
**File:** `{<series>} {#<number3>}{ (<year>)}`

```
DC Comics/Batman (2011)/Batman #001 (2011).cbz
Marvel Comics/Daredevil (1998)/Daredevil #001 (1998).cbz
Image Comics/Saga (2012)/Saga #001 (2012).cbz
```

---

### 2. Publisher + series group + series

A common structure for large Marvel/DC collections. The series group (e.g. "Batman Family") creates a mid-level grouping so related titles stay together.

**Folder:** `{<publisher>}/{<seriesgroup>}/{<series>}{ (<year>)}/`
**File:** `{<series>} {#<number3>}{ (<year>)}`

```
DC Comics/Batman Family/Batman (2011)/Batman #001 (2011).cbz
DC Comics/Batman Family/Detective Comics (2011)/Detective Comics #001 (2011).cbz
Marvel Comics/X-Men/Uncanny X-Men (1963)/Uncanny X-Men #001 (1963).cbz
```

---

### 3. Character-first browsing

Organizes by main character before series, so browsing by character feels natural. Works well if you collect a specific character across many titles.

**Folder:** `{<publisher>}/{<maincharacter>}/{<format>}/{<series>}{ (<year>)}/`
**File:** `{<series>} {#<number3>}`

```
DC Comics/Batman/Main Series/Batman (2011)/Batman #001.cbz
DC Comics/Batman/Limited Series/Batman - Noel (2011)/Batman - Noel #001.cbz
DC Comics/Batman/TPB/Batman by Snyder & Capullo (2012)/Batman by Snyder & Capullo #001.cbz
Marvel Comics/Spider-Man/Main Series/Amazing Spider-Man (1963)/Amazing Spider-Man #001.cbz
```

---

### 4. Format-first split

Separates ongoing issues from collected editions at the top level. Useful if you mix periodicals and trades heavily and want them completely separated.

**Folder (ongoing):** `Ongoing/{<publisher>}/{<series>}{ (<year>)}/`
**Folder (TPB):** `Collected/{<publisher>}/{<series>}{ (<year>)}/`
**File:** `{<series>} {#<number3>}{ (<year>)}`

```
Ongoing/Marvel Comics/Amazing Spider-Man (2022)/Amazing Spider-Man #001 (2022).cbz
Ongoing/DC Comics/Batman (2016)/Batman #001 (2016).cbz
Collected/Marvel Comics/Immortal Hulk (2018)/Immortal Hulk #001 (2018).cbz
Collected/DC Comics/All-Star Superman (2005)/All-Star Superman #001 (2005).cbz
```

---

### 5. Indie publisher (flat per publisher)

For smaller publishers where a deep hierarchy adds noise. One folder per series under the publisher is enough.

**Folder:** `{<publisher>}/{<series>}/`
**File:** `{<series>} {#<number3>}{ (<year>)}`

```
Image Comics/Saga/Saga #001 (2012).cbz
Image Comics/Invincible/Invincible #001 (2003).cbz
Dark Horse Comics/Hellboy/Hellboy #001 (1994).cbz
BOOM! Studios/Something is Killing the Children/Something is Killing the Children #001 (2019).cbz
```

---

### 6. Manga-style by author

For manga or creator-owned work where the author is more meaningful than the publisher. Groups all of an author's work in one place.

**Folder:** `{<writer[1][l]>}, {<writer[1][f]>}/{<series>}/`
**File:** `{<series>} {#<number3>}`

```
Oda, Eiichiro/One Piece/One Piece #001.cbz
Miura, Kentaro/Berserk/Berserk #001.cbz
Urasawa, Naoki/Monster/Monster #001.cbz
Urasawa, Naoki/20th Century Boys/20th Century Boys #001.cbz
```

---

### 7. Year-based archive

Good for people who browse by era rather than by character or publisher. Each year gets its own folder under the publisher.

**Folder:** `{<publisher>}/{<year>}/{<series>}/`
**File:** `{<series>} {#<number3>} [{<month>}, {<year>}]`

```
Marvel Comics/1963/Amazing Spider-Man/Amazing Spider-Man #001 [March, 1963].cbz
DC Comics/1986/Batman/Batman #001 [January, 1986].cbz
DC Comics/2011/Action Comics/Action Comics #001 [November, 2011].cbz
```

---

### 8. Story arc in filename

If you re-read by story arc rather than issue number, embedding the arc name in the filename makes it easy to find specific runs.

**Folder:** `{<publisher>}/{<seriesgroup>}/{<series>}{ (<year>)}/`
**File:** `{<series>} {#<number3>}{ - <storyarc>}{ (<year>)}`

```
DC Comics/Batman Family/Batman (2011)/Batman #001 - Court of Owls (2011).cbz
DC Comics/Batman Family/Batman (2011)/Batman #009 - Night of the Owls (2012).cbz
DC Comics/Batman Family/Batman (2011)/Batman #013 - Death of the Family (2012).cbz
```

---

### 9. TPB multi-volume with volume year subfolder

Groups a TPB run into a subfolder named after the series and its start year so volumes stay together and sort in order.

**Folder:** `{<publisher>}/{<seriesgroup>}/{<series>}/{<format>}/{<series>}{ (<year>)}/`
**File:** `{<series>} {#<number3>} [{<month>}, {<year>}]`

```
Marvel Comics/Spider-Man Family/Spider-Gwen/TPB/Spider-Gwen (2017)/Spider-Gwen #001 [February, 2017].cbz
Marvel Comics/Spider-Man Family/Spider-Gwen/TPB/Spider-Gwen (2017)/Spider-Gwen #002 [January, 2018].cbz
Marvel Comics/Avengers/Moon Knight/TPB/Moon Knight (2021)/Moon Knight #001 [May, 2022].cbz
```

---

### 10. Franchise-first (custom field)

For cross-publisher franchises like Star Wars, use a custom field to break them out into their own top-level folder regardless of publisher.

**Folder:** `{<Custom(Franchise)>}/{<maincharacter>}/{<format>}/{<series>}{ (<year>)}/`
**File:** `{<series>} {#<number3>} [{<month>}, {<year>}]`

```
Star Wars/Darth Vader/Main Series/Darth Vader (2020)/Darth Vader #001 [March, 2020].cbz
Star Wars/X-Wing Rogue Squadron/Main Series/X-Wing Rogue Squadron (1995)/X-Wing Rogue Squadron #001 [July, 1995].cbz
Star Wars/General/TPB/Star Wars Legends Epic Collection (2015)/Star Wars Legends Epic Collection #001 [March, 2015].cbz
```

---

### 11. Publisher + imprint

The ComicRack-style structure with an imprint folder between the publisher and the series. When a comic has no imprint, the empty folder is left out, so those comics go straight into the publisher folder.

**Folder:** `{<publisher>}/{<imprint>}/{<series>}{ (V<volume>)}/`
**File:** `{<series>} {#<number3>}{ (<year>)}`

```
DC Comics/Vertigo/Sandman (V1989)/Sandman #001 (1989).cbz
DC Comics/Black Label/Harleen (V2019)/Harleen #001 (2019).cbz
DC Comics/Batman (V2016)/Batman #001 (2016).cbz
```

The imprint comes from the `<Imprint>` element in ComicInfo.xml (read by `import_library`), from the Imprint box on the comic's edit page, or from a tagging rule that sets the `Imprint` field, for example a rule that matches the series and sets the imprint for a whole run. ComicVine does not provide imprints, so scraping does not fill it in. For comics imported before 1.1.1, run `backfill_imprint` (see [Getting Started](/guide/getting-started)) to read the imprint from their files.

---

## Per-Comic Path Preview

Before organizing in bulk, you can preview the expected destination path for a single comic. Open the comic detail page and look for the **Expected Path** line in the Organization section. This shows exactly where the file would be moved under the current active profile, including all variable substitutions and character replacements.

## Syncing Library Paths

If you move files outside of ComicManager (for example, reorganizing your library manually or migrating to a new drive), the database records will still point to the old paths. The sync logic exists and works, but is not yet exposed as a button anywhere in the UI. Trigger it via a POST request, for example from the Django shell:

```bash
docker compose exec web python manage.py shell -c "
from apps.organizer.services import sync_library_paths
print(sync_library_paths())
"
```

1. It scans every organized, written, or done digital comic whose recorded `file_path` does not exist on disk.
2. For each missing file, it computes the expected organized path from your active profile and checks whether the file exists there. If not, it looks in the expected folder for a single file whose name starts with the series name followed by the issue number (so `Batman Beyond #001` is never taken for `Batman #001`).
3. If found, the database record is updated to the new path. If not found, the comic is left in place for manual review.
4. Duplicate database entries found during the scan are also removed automatically.

Run this after any external library reorganization or after migrating to a new storage location. For individual comics, the **Relink** button in the Missing files table on the Path Audit page does the same search.

## Physical Comics

Physical comics do not use the Organizer because there is no file to move. Instead, they utilize a **Storage Location** text field (e.g. "Box 12", "Shelf A") to keep track of where the physical issue is located. This field can be updated directly from the comic detail page.
