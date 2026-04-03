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

Running **Organize All** in the dashboard starts a Celery task that handles file movements in the background.

Before any file is moved, ComicManager performs a "dry run" to ensure:
- The target path doesn't already exist.
- The target folder structure can be created.
- There are no file conflicts.

**Error Logging**: Any file move failures (e.g. file in use, permission denied, missing source file) are recorded as `organize_error` events in the **Batch Audit Log** for easy review.

**Progress Tracking**: Real-time progress bars and toast notifications keep you informed about the status of your batch organization.

---

## Path Auditing & Re-organizing

Over time, your library structure might change or metadata might be updated after a file was already organized.

- **`needs_reorganize` flag**: Whenever a core metadata field (like Series, Publisher, or Format) changes on a comic that is already in the `Organized` or `Written` state, ComicManager sets this flag. The comic appears in the Maintenance tab of your dashboard so you can safely move it to its new, correct path.
- **Scan Path Audit**: A manual tool to scan your entire library and compare current file paths with the "Expected" paths based on your organization profile. It identifies any comics that are in the wrong location or have the wrong filename.

![Path Audit Tool](/path_audit.png)

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

### TPB Profile Setup — Multi-volume vs Standalone

TPB collections come in two shapes:

- **Multi-volume series** — a run of numbered trade paperbacks (e.g. Spider-Gwen TPB #001, #002, #003). These should be grouped into a series subfolder so they stay together.
- **Standalone collected editions** — a single TPB with no numbered siblings (e.g. Moon Knight by MacKay). A subfolder adds no value; the writer name in the filename makes it instantly recognisable.

The `Count` field (the total issue count from ComicVine) is the discriminator. Create two profiles and set their priorities so the more specific one is evaluated first.

**Profile 1 — TPB multi-volume (lower priority number = evaluated first)**

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

**Profile 2 — TPB standalone (higher priority number = fallback)**

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

## Physical Comics

Physical comics do not use the Library Organizer because there is no file to move. Instead, they utilize a **Storage Location** text field (e.g. "Box 12", "Shelf A") to keep track of where the physical issue is located. This field can be updated directly from the comic detail page.
