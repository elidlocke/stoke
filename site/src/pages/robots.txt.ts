import type { APIRoute } from 'astro'

// Allow everything, and point to the sitemap at the site's own address.
export const GET: APIRoute = ({ site }) =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${new URL('sitemap-index.xml', site)}\n`)
