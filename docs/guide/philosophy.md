# The Philosophy of ComicManager

ComicManager is a personal project built to solve a specific problem: managing a large comic collection with metadata and filesystem organization on Linux. Gaming on Linux has finally caught up with Windows, but ComicRack was the last thing keeping me on Windows. I have my workflow well documented at [comicrack.baerentsen.space](https://comicrack.baerentsen.space/Introduction/) and figured I could rebuild it as a self-hosted web app that runs in Docker on any OS.

## What This Is (and Isn't)

ComicManager is strictly a **metadata management and library organization tool**. It is not a comic reader, and it does not track reading progress, reading lists, or reading history.

The goal is to take a folder of messy comic files, scrape accurate metadata from ComicVine or I.N.D.U.C.K.S., apply consistent naming and tagging rules, deduplicate the collection, move files into a clean folder structure, and embed `ComicInfo.xml` into every CBZ. Once a comic is written, it's done. Hand it off to whatever reader you prefer.

This workflow was built for my own use case and my own collection. It may not fit yours.

---

## Scope and Constraints

### Output Format: CBZ Only
All output files are CBZ. ComicManager will convert CBR and CB7 archives to CBZ, but will never produce CBR output. CBZ is a ZIP-based format that is universally supported and allows embedding `ComicInfo.xml` directly inside the archive.

### Metadata Standard: ComicInfo.xml
Every written file includes a `ComicInfo.xml` embedded in the CBZ archive. The schema follows a combination of the original ComicRack definition and the community-maintained [anansi-project/comicinfo](https://github.com/anansi-project/comicinfo) standard. If new standards are developed, I'm open to implement them.  ComicRackCE's [ComicBook.xml](https://github.com/maforget/ComicRackCE/discussions/260)looks promising, but a schema hasn't been released yet. 

### Metadata Sources: ComicVine and I.N.D.U.C.K.S. Only
ComicManager supports two external metadata sources. No other sources will be added.

- **ComicVine**: the primary source for most comics. Requires a local database file (`comicvine.db` + `latest.mcl`) or an API key. The `latest.mcl` file is updated daily and available at [gitea.baerentsen.space](https://gitea.baerentsen.space/FrederikBaerentsen/ComicRack_Scripts/src/branch/master/Update%20Missing). A proof-of-concept offline ComicVine database was posted here: [An offline ComicVine tagger (r/comicrackusers)](https://old.reddit.com/r/comicrackusers/comments/1q7rex8/here_it_is_an_offline_comicvine_tagger_for/). Do not open issues on this repository asking where to get the database. 
- **I.N.D.U.C.K.S.**: a great alternative to ComicVine for Disney comics. The database is built from the official ISV export at [inducks.org/inducks/isv.tgz](https://inducks.org/inducks/isv.tgz). You need to extract the archive and build the SQLite database yourself using the `createtables.sql` included in the archive. Do not open issues on this repository asking for how to create the database.

---

## Core Principles

### 1. Metadata Integrity First
Metadata is the foundation of a useful library. Filenames are guesses; ComicVine is the source of truth. The pipeline is designed to fetch, verify, and enrich metadata before anything is moved or written.

### 2. State-Based Workflow
The pipeline, from *New* to *Done*, prevents errors by making each phase a gate. A comic can't be organized until it's been deduplicated. It can't be formatted until it's been tagged. Every transition is logged.

### 3. Automation with Human Oversight
Repetitive tasks like image hashing, file moving, and bulk scraping are automated. But an Audit Log exist so you can catch and correct mistakes before they become permanent.

### 4. Open Standards
Metadata shouldn't be locked into one application. ComicInfo.xml is used throughout so your data remains portable to any other comic tool.

### 5. Performance for Large Collections
Built for large comic libraries. Celery handles all heavy lifting in the background so the UI stays responsive during batch operations.

---

[Explore the Getting Started Guide](/guide/getting-started)
