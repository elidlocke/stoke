import type { LinkCategory, Purchase } from './api'

export interface LinkKind {
  label: string
  placeholder: string // an example link
  purchase?: Purchase // revenue sources: how it's usually bought on this platform
}

// The types of each list, in the order they're offered. Mirrors LINK_KINDS in backend/app/models.py.
export const LINK_KINDS: Record<LinkCategory, Record<string, LinkKind>> = {
  // The platforms a revenue source can be sold on, plus a fallback.
  revenue_source: {
    calendly: { label: 'Calendly', placeholder: 'calendly.com/you/strategy-call', purchase: 'repeat' },
    maven: { label: 'Maven', placeholder: 'maven.com/you/course', purchase: 'once' },
    gumroad: { label: 'Gumroad', placeholder: 'you.gumroad.com/l/templates', purchase: 'once' },
    teachable: { label: 'Teachable', placeholder: 'you.teachable.com/p/course', purchase: 'once' },
    circle: { label: 'Circle', placeholder: 'you.circle.so', purchase: 'subscription' },
    luma: { label: 'Luma', placeholder: 'lu.ma/you', purchase: 'repeat' },
    other: { label: 'Somewhere else', placeholder: 'you.com/shop', purchase: 'once' },
  },
  social: {
    substack: { label: 'Substack', placeholder: 'you.substack.com' },
    x: { label: 'X', placeholder: 'x.com/you' },
    instagram: { label: 'Instagram', placeholder: 'instagram.com/you' },
    linkedin: { label: 'LinkedIn', placeholder: 'linkedin.com/in/you' },
    youtube: { label: 'YouTube', placeholder: 'youtube.com/@you' },
    tiktok: { label: 'TikTok', placeholder: 'tiktok.com/@you' },
    threads: { label: 'Threads', placeholder: 'threads.net/@you' },
    bluesky: { label: 'Bluesky', placeholder: 'bsky.app/profile/you' },
    facebook: { label: 'Facebook', placeholder: 'facebook.com/you' },
    podcast: { label: 'Podcast', placeholder: 'podcasts.apple.com/podcast/your-show' },
    website: { label: 'Website', placeholder: 'you.com' },
    other: { label: 'Other', placeholder: 'you.com' },
  },
}

export const PURCHASES: { value: Purchase; label: string }[] = [
  { value: 'once', label: 'One-time purchase (eg. pdf download)' },
  { value: 'repeat', label: 'Repeat purchase (eg. coaching session)' },
  { value: 'subscription', label: 'Subscription (eg. membership)' },
]

export function kindLabel(category: LinkCategory, kind: string): string {
  return LINK_KINDS[category][kind]?.label ?? kind
}

/** A full https:// link from what was typed: "calendly.com/you" or "http://…" both become https. */
export function normalizeUrl(typed: string): string {
  const url = typed.trim()
  return url ? `https://${url.replace(/^https?:\/\//i, '')}` : ''
}
