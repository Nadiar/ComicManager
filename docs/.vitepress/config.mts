import { defineConfig } from 'vitepress'
import lightbox from 'vitepress-plugin-lightbox'

export default defineConfig({
  title: "ComicManager",
  description: "Comprehensive Django-based application for managing comic book collections",
  markdown: {
    config: (md) => {
      md.use(lightbox, {})
    }
  },

  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'Workflow', link: '/guide/workflow' },
      { text: 'Screenshots', link: '/reference/screenshots' }
    ],
    sidebar: [
      {
        text: 'Guide',
        items: [
          { text: 'Quick Start', link: '/guide/quickstart' },
          { text: 'Getting Started', link: '/guide/getting-started' },
          { text: 'Philosophy & Scope', link: '/guide/philosophy' },
          { text: 'Searching & Filtering', link: '/guide/searching' },
          { text: 'Smart Lists', link: '/guide/smart-lists' },
          { text: 'Physical Comics', link: '/guide/physical-comics' }
        ]
      },
      {
        text: 'Workflow',
        items: [
          { text: 'Workflow Pipeline', link: '/guide/workflow' },
          { text: 'Scraping', link: '/guide/scraping' },
          { text: 'Tagging', link: '/guide/tagging' },
          { text: 'Formatting', link: '/guide/formatting' },
          { text: 'Deduplication', link: '/guide/duplicates' },
          { text: 'Organizing', link: '/guide/organizing' },
          { text: 'Writing Files', link: '/guide/writing' }
        ]
      },
      {
        text: 'Advanced Features',
        items: [
          { text: 'Audit Log & Rollback', link: '/guide/audit-log' },
          { text: 'CBZ Page Manager', link: '/guide/page-manager' },
          { text: 'Missing Issues Detection', link: '/guide/missing-issues' },
          { text: 'File Format Handling', link: '/guide/file-formats' }
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'Settings', link: '/reference/settings' },
          { text: 'Screenshots', link: '/reference/screenshots' }
        ]
      }
    ],
    socialLinks: [
      { icon: 'github', link: 'https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager' }
    ]
  }
})
