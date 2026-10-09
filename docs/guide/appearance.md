# Appearance & Display Settings

Display settings control the look and feel of the interface. They are per-user preferences stored in the database and can be changed at any time from **Settings** (`/settings/`).

These are separate from the runtime [Settings Reference](/reference/settings), which controls library paths, scraping behaviour, and pipeline thresholds.

---

## Navigation Layout

Choose between two navigation layouts:

| Option | Description |
|--------|-------------|
| **Top Nav** | A horizontal top bar with the main navigation links. Default. |
| **Sidebar** | A collapsible left sidebar with icon-based navigation. Collapses to icons only to save space. |

![Top nav layout](/navbar.png)

![Sidebar layout](/sidebar.png)

---

## Theme and Color

### Mood Presets

Four built-in color presets set a cohesive accent and background palette:

| Preset | Character |
|--------|-----------|
| **Warm** | Amber/orange accents, warm neutral backgrounds. Default. |
| **Cool** | Blue/cyan accents, cool neutral backgrounds. |
| **Forest** | Green accents, earthy backgrounds. |
| **Rose** | Pink/rose accents, soft neutral backgrounds. |

### OLED Mode

Enabling **OLED** forces pure black (`#000000`) backgrounds.

### High Contrast

Increases foreground/background contrast ratios for improved readability.

### Custom Colors

The color picker lets you override individual design tokens independently of the preset. You can set custom values for:

- **Accent**: the primary highlight and interactive color
- **Background**: the page background
- **Background Level 1**: card and panel surfaces
- **Foreground**: primary text color
- **Foreground Level 1**: secondary text color

Custom values layer on top of the selected mood preset. Clearing a custom color field reverts that token to the preset value.

---

## Table Density

Controls vertical padding in table and list rows.

| Option | Description |
|--------|-------------|
| **Compact** | Minimal padding. Maximum rows visible without scrolling. |
| **Default** | Standard padding. Balanced density. |
| **Comfy** | Extra padding. Easier to read on large displays. |

![Default table density](/dens_detault.png)

![Compact table density](/dens_compact.png)

![Comfy table density](/dens_comfy.png)

---

## Show Covers

Toggles the cover thumbnail column in the comic list table views. Disable to reduce bandwidth on slow connections or to increase visible columns.

---

## Dashboard Pipeline Variant

Controls which pipeline visualization is shown on the dashboard. See [Workflow Pipeline](/guide/workflow#dashboard) for a description of each variant (Segments, Flow, None).

---

## Dashboard Hero Style

Controls the visual style of the hero banner at the top of the dashboard.

| Option | Description |
|--------|-------------|
| **Editorial** | Bold typographic layout with stronger visual hierarchy. Default. |
| **Subtle** | Minimal, low-contrast header. |
| **Bold** | High-contrast, full-bleed hero with strong accent color. |

![Editorial hero style](/hero_editorial.png)

![Subtle hero style](/hero_subtle.png)

![Bold hero style](/hero_bold.png)

---

## Dashboard Visible Sections

Two additional dashboard cards can be shown or hidden independently:

| Option | Default | Description |
|--------|---------|-------------|
| **Show Weekly Summary** | On | Shows the "This Week" bar chart of recent import and pipeline activity. |
| **Show Priority Banner** | On | Shows the bottleneck banner when one pipeline stage holds a significantly larger backlog than the others. |

![Weekly summary section](/weekly.png)

![Priority banner section](/priority_banner.png)

These checkboxes are in the **Dashboard** section of **Settings** (`/settings/`).

## Dashboard Attention Style

Controls how the "Needs Attention" queue is presented on the dashboard.

| Option | Description |
|--------|-------------|
| **List** | Compact list view. Best for reviewing many flagged comics quickly. Default. |
| **Grid** | Cover tile grid. Better for visual browsing of flagged items. |
| **Triage** | A ranked list ordered by urgency. Each item is numbered so you know exactly what to tackle first. |

![Needs Attention: List view](/needs_list.png)

![Needs Attention: Grid view](/needs_grid.png)

![Needs Attention: Triage view](/needs_triage.png)

![Needs Attention: List view with expanded card](/needs_expand.png)
