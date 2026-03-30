![](docs/public/pipeline.png)

# ComicManager

A web application for managing large comic collections, both digital and physical. Built to replace the ComicRack workflow, it processes comics through an 8-phase pipeline from raw files to a fully organized, tagged, and metadata-enriched library.

<a href="https://www.buymeacoffee.com/frederikb" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="41" width="174"></a>

## Features

- 8-phase workflow pipeline: Ingest, Scrape, Count, Tag, Format, Deduplicate, Organize, Write
- ComicVine matching via pHash cover comparison, fuzzy metadata matching, and live API fallback
- DataManager tagging rules engine for publisher-based metadata enrichment
- Format detection: Main Series, Limited Series, One-Shot, TPB, Omnibus, Annual, and more
- Duplicate detection by ComicVine ID, series and number, and perceptual hash
- Template-based Library Organizer with profile-based rules
- ComicInfo.xml generation and embedding into CBZ files
- Smart Lists: saved filter queries with optional ComicVine volume completion tracking
- First-class physical comic support with the same pipeline workflow
- Handles 40,000+ comics with server-side pagination

## Preferred setup: pre-built Docker image

See [Quick Start](docs/guide/quickstart.md) to get up and running right away.

See [Getting Started](docs/guide/getting-started.md) for a more detailed guide.

## Documentation

- [Quick Start](docs/guide/quickstart.md)
- [Getting Started](docs/guide/getting-started.md)
- [Philosophy and Scope](docs/guide/philosophy.md)
- [Workflow Pipeline](docs/guide/workflow.md)
- [Scraping](docs/guide/scraping.md)
- [Tagging](docs/guide/tagging.md)
- [Organizing](docs/guide/organizing.md)
- [Settings Reference](docs/reference/settings.md)
