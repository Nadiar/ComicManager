---
layout: home

hero:
  name: "ComicManager"
  text: "Automated Comic Collection Management"
  tagline: "The modern successor to my ComicRack workflow."
  actions:
    - theme: brand
      text: "Get Started"
      link: "/guide/quickstart"
    - theme: alt
      text: "Philosophy & Scope"
      link: "/guide/philosophy"
    - theme: alt
      text: "Screenshots"
      link: "/reference/screenshots"

features:
  - title: "State-Based Pipeline"
    details: "A linear, 8-stage workflow that ensures every comic is verified, matched, and tagged before it enters your library."
  - title: "ComicVine First"
    details: "Deep integration with ComicVine using a hybrid approach of local SQLite for speed and Live API for the latest data."
  - title: "Deterministic Rules"
    details: "A powerful rule engine, based on DataManager and Library Organizer, allows you to automate naming and organization."
---

## What is ComicManager?

ComicManager is a personal tool for managing large comic collections, both digital and physical. It is strictly a **metadata scraping, tagging, and library organization tool**. It is not a complete ComicRack replacement, as it is not a reader and does not track reading progress. For serving your processed library to any OPDS or OPDS-PSE compatible reader, you can use [ComicOPDS](https://gitea.baerentsen.space/FrederikBaerentsen/ComicOPDS).

The goal is to take a folder of messy comic files and run them through a structured pipeline: parse filenames, scrape accurate metadata from ComicVine or I.N.D.U.C.K.S., apply personal tagging rules, deduplicate, move files into a clean folder structure, and embed `ComicInfo.xml` into every CBZ. Physical comics follow the same pipeline for metadata and tracking, just without the file handling steps. Once a comic is processed, hand it off to whatever reader you prefer.

This was built for one specific workflow, my own. It is opinionated and may not fit everyone's needs. The workflow is based on my [ComicRack Guide](https://comicrack.baerentsen.space/).
 
- [Explore the Workflow](/guide/workflow)