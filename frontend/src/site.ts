// The public site (site/): pricing, privacy, terms. Unset in a dev setup without it, which falls back to
// this app's own origin.
const SITE_URL = (import.meta.env.VITE_SITE_URL ?? '').replace(/\/$/, '')

/** A page on the public site, e.g. siteUrl('/privacy/'). */
export function siteUrl(path = '/'): string {
  return (SITE_URL || window.location.origin) + path
}

/** Where signing out lands: the public site's home. Listed in Auth0's Allowed Logout URLs. */
export function signedOutUrl(): string {
  return SITE_URL || window.location.origin
}

export const SITE_LINKS = [
  { path: '/privacy/', label: 'Privacy' },
  { path: '/terms/', label: 'Terms' },
  { path: '/contact/', label: 'Help' },
]
