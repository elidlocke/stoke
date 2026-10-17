import sitemap from '@astrojs/sitemap'
import { defineConfig } from 'astro/config'

// The public site: plain HTML pages, no sign-in. The app itself is frontend/, served by the API.
export default defineConfig({
  // Its own address, for canonical links and the sitemap (SITE_URL in render.yaml).
  site: process.env.SITE_URL || 'http://localhost:4321',
  integrations: [sitemap()],
  // Astro's HTML minifier drops the line break before a link that starts a line ("See the<a>…"), running words
  // together. The pages are small, so keep the HTML as written.
  compressHTML: false,
  // Stylesheets as files, not inline, so the strict Content-Security-Policy in render.yaml holds.
  build: { inlineStylesheets: 'never' },
  vite: {
    // One .env at the repo root, as for the app; only PUBLIC_ variables reach the pages.
    envDir: '..',
    // The color tokens are shared with the app (frontend/src/tokens.css).
    server: { fs: { allow: ['..'] } },
  },
})
