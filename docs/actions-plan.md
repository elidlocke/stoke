# Stoke → Actions: from customer data to personal notes

## Context

Stoke shows a writer who their customers are, but it doesn't help them act on it. v1 adds a library of **actions**. Each action says who to reach out to and why, and offers a note in the writer's voice. The writer approves the note. Stoke then sends it from their Gmail after a 24-hour window in which they can cancel. Stoke tracks who's been contacted and who converted, and emails a weekly digest that brings the writer back. It's built directly as v1 for a small beta: up to 100 Google test users while Gmail verification runs.

## Product decisions

**Action library.** Every action is listed. Each action's page shows analytics for its audience, whether or not the action is on. Turning an action on adds its outreach queue.

**Voice.**
- The writer's Substack URL (from Settings → Audience channels) gives Stoke the public RSS feed, `<handle>.substack.com/feed` or `<domain>/feed`.
- From the feed, AI writes a voice guide that the writer can edit.
- For each action, AI drafts one template, which the writer edits and approves.
- Per-person notes fill merge fields deterministically, and the filled fields are highlighted. No AI text is ever written per person.

**First run of an action:**
1. The writer approves the template.
2. Stoke previews every filled note, with "why this person".
3. The first batch of about 5 is scheduled for 9am tomorrow in the reader's time zone (falling back to the writer's).
4. Until then, the writer can cancel or edit any note. A test copy goes to the writer first.

**Sending.**
- Gmail OAuth with `gmail.send` only. That's a sensitive scope, so it needs verification but not a CASA assessment.
- Drafts and the schedule live in Stoke, because `gmail.compose` (for Gmail drafts) is restricted and the API has no scheduled send.
- Sent mail lands in the writer's Sent folder, and replies go to them.

**Guardrails:**
- A daily cap (default 50).
- Never two notes to one person within 14 days, across all actions.
- A pause-all switch.
- Highest-value people first, so large audiences drip out.
- Anyone with an open dispute, or a full refund in the last 90 days, is excluded from every action except Dispute check-in.

**Tracking.**
- Statuses: draft → approved → scheduled → sent → converted.
- Converted is detected from Stripe within 30 days of sending, using the check for the action's type (see below). Gratitude actions don't convert.
- No open pixels, and no reply reading in v1.

**The writer's links** (Settings, step 1), under "Your channels". The writer is asked for two lists:
- **Revenue streams** (revenue sources), by the platform they're sold on: Calendly, Maven, Gumroad, Teachable, Circle, Luma, or somewhere else. Each revenue source has a name, a link, "paid through" (one of their Stripe accounts, or somewhere else) and how people pay (one-time purchase, per session or ticket, or subscription), defaulted from the platform.
- **Audience channels**: Substack and social profiles.

Referral and affiliate programs are deferred until after v1.

These links are each action's call to action. Revenue sources paid through a connected Stripe account also tell Stoke who has already bought.

**Out of scope for v1:** free → paid (Substack CSV), ESP/domain sending, Outlook, Gmail drafts, and any auto-send level beyond "approve the template + the 24-hour window".

## v1 action library

Audited for Substack writers:
- Substack runs its own Stripe Connect account, usually with one paid tier priced monthly and annually, plus a Founding member price.
- Substack already sends automated welcome, receipt, dunning and renewal emails, so notes must feel personal.
- Substack runs its own cancel flow, so Stripe's cancellation reason is usually empty.

| # | Action | Type | Audience (default thresholds) | Ask / link used | Replaces |
|---|---|---|---|---|---|
| 1 | Welcome | Gratitude | Started a paid subscription in the last 30 days | Reply and say hi; social links | New customers |
| 2 | Anniversary thank-you | Gratitude | Still subscribed, paid-anniversary in the last 30 days. Sent after the renewal succeeds, never before | None, just thanks | Anniversaries |
| 3 | Welcome back | Gratitude | Resubscribed in the last 60 days after canceling | None, just thanks | new |
| 4 | VIP / testimonial | Gratitude | Top 20 by lifetime take-home and still subscribed, or any current Founding member | Testimonial | Top customers |
| 5 | Founding upgrade | Upgrade | Current non-Founding subscriber, ≥ 2 renewals, no failed payments in 12 months | Become a Founding member | new |
| 6 | Monthly → annual | Upgrade | Current monthly subscriber, ≥ 3 renewals, no failed payments in 12 months | Switch to annual | new |
| 7 | Cross-sell: *name* (one per saved revenue source) | Cross-sell | Depends on how people pay for it (below). Excludes past buyers when it's paid through a connected Stripe account | Its link | new |
| 8 | Repeat booking: *name* | Cross-sell | Bought this before, nothing in 180+ days. Only for revenue sources paid "per session or ticket" and paid through Stripe | Its link | new |
| 9 | Win-back | Win-back | Ended in the last 90 days, not resubscribed, canceled by the customer (not a failed payment) | Come back: a discount if "too expensive", best posts if "unused", otherwise generic | Cancellations |
| 10 | Save | Retention | Canceling at period end, still active | Stay | At risk |
| 11 | Card failing | Retention | Payment failing, retries exhausted, or lapsed in the last 30 days | Update card: a helpful heads-up, not a pitch | At risk |
| 12 | Dispute check-in | Retention | Open dispute or inquiry awaiting a response, by evidence deadline | "Were you having trouble canceling? I can cancel and refund you directly. If so, could you withdraw the dispute with your bank?" | At risk |

**Cross-sell audiences (#7)**, by how people pay:
- **Expensive one-off** (Calendly, Maven, Luma): top readers by lifetime value with at least N renewals.
- **Cheap** (Gumroad, Teachable): current paid subscribers, 30+ days after subscribing.
- **Subscription** (Circle): long-tenured annual and Founding members.

With no revenue sources saved, the library shows "Add a revenue stream in Settings" in place of #7 and #8.

**Dispute check-in (#12):**
- Many disputes are really "I couldn't cancel" or "I didn't recognise the charge", and Stripe recommends contacting the customer.
- The page reminds the writer to still submit evidence in Stripe before the deadline. A customer withdrawing through their bank isn't guaranteed or instant.
- The tone is never accusatory.

**Not actions:** the by-period Top customers leaderboard. Only its all-time top slice maps to VIP.

**Backlog:** gift-giver thanks, and a trial-ending nudge. Each needs data Stoke doesn't store yet.

**Thresholds and types.**
- Each action has adjustable thresholds.
- The writer labels their Substack plans (standard / Founding) once. Until then, Founding is detected from the plan name or the highest yearly price.
- The library groups actions by type: Gratitude, Upgrade, Cross-sell, Win-back, Retention.

**Conversion checks, by type:**
- **Upgrade**: Founding → a Founding plan; Monthly → annual → a yearly interval.
- **Cross-sell**: a purchase of that revenue source, through its Stripe account.
- **Win-back**: a resubscribe.
- **Retention**: the subscription is still active after its end date, or a retry succeeded. For Dispute check-in, the dispute closed in the writer's favour.

## Implementation outline

### Data
Alembic migrations, with models in `backend/app/db_models.py`:
- **`writer_links`** (step 1, `0003_writer_links.py`): category (revenue_source / social), kind, name, url, paid-through account, purchase (once / repeat / subscription), position.
- **`writer_profiles`**: display name, sign-off, voice guide, timezone, daily cap, paused, digest on/off, plan labels, and Stripe application ids for auto-labelling charges.
- **`actions`**: kind, type, enabled, params (JSONB), subject/body template, template `approved_at`, and an optional `link_id` (for Cross-sell actions).
- **`outreach`**: action_id, customer_id (HMAC from `backend/app/customer_id.py`; no email is stored), status, subject/body as sent, scheduled_for, sent_at, Gmail message/thread id, converted_at. Unique on (user, action, customer).
- **`gmail_connections`**: an encrypted refresh token, reusing the envelope encryption in `backend/app/crypto.py` (the same pattern as `StripeCredential`).

### Backend
- **`app/links.py`** + `/api/links` (step 1): CRUD for the writer's links.
- **`app/actions.py`**: pure audience rules over the existing aggregates (`aggregate.rank_customers`, `cancellations`, `anniversaries`, `new_customers`, `at_risk`, and the timeline's `subscription_changed` / `purchased` events). Each candidate carries a "why" string, and each type defines its conversion check.
- **`app/voice.py`**: RSS fetch → voice guide, and template drafting (Claude API, latest model). Only fields allowlisted in `models.py` are sent to the LLM.
- **`app/gmail.py`**: the OAuth flow, token refresh, and sending (an RFC 822 message via `users.messages.send`).
- **`app/routers/actions.py`**:
  - actions CRUD;
  - `GET /actions/{id}/audience` (analytics, which works while the action is off);
  - the queue, with approve / edit / cancel for outreach;
  - pause all;
  - per-customer outreach history.
- **`app/jobs/send.py`** (cron, every 15 minutes): sends scheduled notes that are due, enforcing caps, pause and exclusions. It re-resolves the email from the customer_id at send time.
- **`app/jobs/digest.py`** (weekly cron): for each action, new candidates, sent, converted, and upcoming scheduled notes, with Review / Pause links. It's sent from Stoke's own transactional ESP (e.g. Resend), and conversion detection runs here too.
- Both jobs build `CurrentUser` from the database and reuse `get_scope` (`backend/app/stripe_client.py`) and `service.*`. Two Render cron services are added to `render.yaml`.

### Frontend
- **Settings** (step 1): Your channels: Revenue streams and Audience channels. Later: voice guide, plan labels, Connect Gmail, caps, pause.
- **`pages/Actions.tsx`**: the action library, grouped by type (audience size, on/off, sent/converted).
- **`pages/Action.tsx`**:
  - audience analytics with "why this person";
  - a template editor with highlighted merge fields;
  - the queue, with preview, cancel / edit and schedule.
- The existing analytics tabs (`frontend/src/analyticsTabs.tsx`) are replaced by action pages, per the table's last column. Old URLs redirect.
- "Contacted Nd ago" chips on the existing lists and on `CustomerProfile.tsx`.

## Build steps

Each step ships on its own, is useful by itself, and is one reviewable PR.

1. **Settings: the writer's links.** The `writer_links` table and the two Settings sections. This unlocks the Cross-sell actions and gives social links to the gratitude actions.
2. **Action audiences (read-only).**
   - `app/actions.py` rules with "why" strings, `GET /actions` and `/actions/{kind}`.
   - The library page grouped by type, and an action page per action, replacing the analytics pages.
   - Adds price amount and interval to the subscription projection (bump `PROJECTION_REV`, then run `scripts/resync.py`) for the Founding and Monthly → annual audiences.
   - No new tables. Value: writers see who to reach out to.
3. **Writer profile.** Plan labels (standard / Founding), and Stripe application auto-detection with confirmation, which makes the upgrade and cross-sell audiences accurate.
4. **Outreach tracking, without sending.**
   - The `actions` and `outreach` migration, and hand-written templates with merge fields.
   - A queue with preview, copy and "mark sent", plus "Contacted Nd ago" chips everywhere.
   - This proves the workflow and tracking before any integration.
5. **AI voice.** RSS → an editable voice guide. AI drafts each action's template, and the writer edits and approves it.
6. **Gmail send.**
   - OAuth (`gmail.send`), an encrypted refresh token, test-to-self, and sending from the queue.
   - Submit Google's verification (privacy policy, domain, demo video) as early as step 1, because it has a long lead time. The beta is limited to 100 test users until it's approved.
7. **Scheduling and guardrails.** The 24-hour window, the send cron job in `render.yaml`, the daily cap, the 14-day rule, dispute/refund exclusions, and pause-all.
8. **Conversion detection.** Per-type conversion checks, sent → converted, and the results on the library and action pages.
9. **Weekly digest.** A transactional ESP and a weekly cron: new audience members, sent, converted, and upcoming scheduled notes with Review / Pause links.

Order: 1 → 2 → 3 → 4 → 5/6 (in parallel) → 7 → 8 → 9. A simple digest of audience counts could ship right after step 2 if re-engagement matters sooner.

## Verification

**Unit tests:**
- `tests/test_links.py`: CRUD, validation, user scoping and the cap.
- `tests/test_actions.py`: audience rules and conversion checks for each type, on fixture data, like `test_aggregate.py`.
- `tests/test_outreach.py`: status transitions, uniqueness, the 14-day rule, caps, pause, and user scoping (like `test_scope.py`).
- The send job, with a mocked Gmail client.

**Local end to end:**
1. Run `seed_test_data.py` with long-tenure, one-off and canceled customers.
2. Add a revenue stream in Settings and enable Founding upgrade.
3. Approve the template. A test copy should arrive in your own Gmail (as a test user).
4. Run the job with time advanced. The scheduled batch should send and the chips should appear.
5. Simulate an upgrade in Stripe test mode. The digest dry-run should show the conversion.
