// The business details the public pages show. Fill in each empty value: until then the pages show a highlighted
// TODO, and a deploy refuses to build (scripts/check-placeholders.mjs).

export const BUSINESS = {
  product: 'Stoke',
  // Where writers get help, refunds and privacy requests. Google and Stripe both check for one.
  supportEmail: '',
  // The company (or your own name, as a sole proprietor) that runs Stoke and signs the terms.
  legalName: '',
  // A mailing address for legal notices and privacy requests: at least city, state or province, and country.
  address: '',
  // Whose law governs the terms, and where disputes are heard, e.g. "the State of Delaware, USA".
  governingLaw: '',
}

// The app, for Sign in and Get started. Set in .env (PUBLIC_APP_URL), e.g. https://localhost:5173 locally.
export const APP_URL = (import.meta.env.PUBLIC_APP_URL || 'https://stoke-y4sf.onrender.com').replace(/\/$/, '')

/** The Get started link: Auth0's sign-up screen, then the app. The plan is kept for billing later. */
export function signupUrl(plan?: string): string {
  return `${APP_URL}/?signup${plan ? `&plan=${encodeURIComponent(plan)}` : ''}`
}

// Plans go by audience size, counted as paying customers a month: the distinct Stripe customers, across every
// connected account, who paid anything that month (a subscription renewal, a course, a download, a tip). An annual
// subscriber counts once a year, in the month they pay. Every plan includes everything.
export const FREE_LIMIT = 250
// Every paid plan starts free for this many days.
export const TRIAL_DAYS = 30

export interface Tier {
  id: string
  name: string
  // Paid subscribers the plan covers.
  limit: number
  // Monthly price in USD; 0 is free. Yearly is two months free.
  price: number
  blurb: string
  featured?: boolean
}

export const TIERS: Tier[] = [
  { id: 'debut', name: 'Debut', limit: FREE_LIMIT, price: 0, blurb: 'Your first readers, fully looked after.' },
  {
    id: 'rising',
    name: 'Rising',
    limit: 1000,
    price: 19,
    blurb: 'You’re catching on. Let’s keep the momentum.',
    featured: true,
  },
  { id: 'headliner', name: 'Headliner', limit: 5000, price: 49, blurb: 'A real business. Stoke keeps up.' },
  { id: 'marquee', name: 'Marquee', limit: 10000, price: 99, blurb: 'A big audience, still personal.' },
]

export const yearly = (t: Tier) => t.price * 10

export const count = (n: number) => n.toLocaleString('en-US')
