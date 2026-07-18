import { defineConfig } from 'vitepress'
import lightbox from 'vitepress-plugin-lightbox'

export default defineConfig({
  title: "ComicManager",
  description: "Comprehensive Django-based application for managing comic book collections",
  markdown: {
    config: (md) => {
      md.use(lightbox, {})
      const defaultImageRender = md.renderer.rules.image!
      md.renderer.rules.image = (tokens, idx, options, env, self) => {
        const token = tokens[idx]
        const alt = token.content
        const rendered = defaultImageRender(tokens, idx, options, env, self)
        if (!alt) return rendered
        return `${rendered}<span class="img-caption">${alt}</span>`
      }
    }
  },

  themeConfig: {
    outline: { level: [2, 4] },
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
          { text: 'Dashboard', link: '/guide/dashboard' },
          { text: 'Searching & Filtering', link: '/guide/searching' },
          { text: 'Comic Detail Page', link: '/guide/comic-detail' },
          { text: 'Appearance & Display', link: '/guide/appearance' },
          { text: 'Smart Lists', link: '/guide/smart-lists' },
          { text: 'Physical Comics', link: '/guide/physical-comics' },
          { text: 'Philosophy & Scope', link: '/guide/philosophy' }
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
          { text: 'Flags', link: '/guide/flags' },
          { text: 'Audit Log & Rollback', link: '/guide/audit-log' },
          { text: 'CBZ Page Manager', link: '/guide/page-manager' },
          { text: 'Missing Issues Detection', link: '/guide/missing-issues' },
          { text: 'File Format Handling', link: '/guide/file-formats' },
          { text: 'Bulk State Operations', link: '/guide/bulk-state' }
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
    search: {
      provider: 'local'
    },
    socialLinks: [
      { icon: 'github', link: 'https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager' }
    ]
  }
})
