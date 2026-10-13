# Stoke → Actions: from customer data to personal notes

## Context

Stoke shows a writer who their customers are, but it doesn't help them act on it. v1 adds a library of **actions**. Each action says who to reach out to and why, and offers a note in the writer's voice. The writer approves the note. Stoke then sends it from their Gmail after a 24-hour window in which they can cancel. Stoke tracks who's been contacted and who converted, and emails a weekly digest that brings the writer back. It's built directly as v1 for a small beta: up to 100 Google test users while Gmail verification runs.

## Current state (2026-10-13)

**Stripe data is stored in Postgres**, not read live from the Stripe API:
- `backend/app/projection.py` keeps an allowlist of fields of each Stripe object, in Stripe's own shape. Email addresses are sealed under each account's data key.
- The tables are `stripe_objects`, `stripe_sync_queue` and `stripe_backfills` (`0002_stripe_objects.py`).
- A Connect webhook (`POST /api/stripe/webhook`, `routers/webhooks.py`, secret `STRIPE_WEBHOOK_SECRET`, endpoint created by `scripts/register_webhook.py`) queues re-reads.
- `sync.run_worker()` runs imports and re-reads inside the web process (started in the `main.py` lifespan, behind the `sync_worker` setting).
- `fetch.py` and `service.*` read the stored objects. While an account's first import runs, views answer `importing` and the UI shows `ImportProgress.tsx`.

**Analytics:** the Overview (with trend charts), and tabs at `/analytics/<tab>` (top, new, anniversaries, cancellations, at-risk) from `frontend/src/analyticsTabs.tsx`. The older top-level URLs already redirect there (`MovedToAnalytics` in `App.tsx`).

**Step 1 (the writer's links) is built but not yet committed:**
- Backend: `0003_writer_links.py`, `WriterLink` in `db_models.py`, `app/links.py` (user scoping, a cap of 50, and a check that "paid through" is one of the writer's accounts), `LinkIn` / `LinkOut` / `LINK_KINDS` in `models.py`, and `/api/links` CRUD in `routers/settings.py`.
- Frontend: `pages/SettingsLinks.tsx` and `linkKinds.ts`.
- Tests: `tests/test_links.py`.
- Also `dev.sh`, which starts Postgres, migrations, the API and the frontend locally.

**Step 2 (action audiences) is built but not yet committed:**
- `projection.py` keeps each subscription's price (id, amount, currency, interval) and each payment's `application`, at `PROJECTION_REV = 2`. Run `scripts/resync.py` after deploying; until an account's re-import finishes, upgrade audiences fall back to plan names.
- `app/actions.py` has the twelve rules, with thresholds as module constants. `GET /api/actions` and `GET /api/actions/{kind}` are in `routers/actions.py`.
- The frontend adds `pages/Actions.tsx`, `pages/Action.tsx` and `actionTypes.ts`. The nav is Overview · Actions · Top customers · Settings. The New customers, Anniversaries, Cancellations and At risk pages are gone, and their old URLs redirect to Welcome, Anniversary thank-you, Win-back and the retention actions. The Overview cards still show the old lists' data, but link to the actions.
- Tests: `tests/test_actions.py`, plus cases in `test_projection.py` and `test_response_shape.py`.

**Step 3 (writer profile) is built but not yet committed:**
- `0004_writer_profiles.py` and `WriterProfile` hold `plan_labels` (price id → standard / founding) and `application_labels` (Connect application id → a revenue source's link id, `newsletter` or `other`). The profile's other columns arrive with the steps that use them.
- `app/profile.py` loads and saves the labels, and lists the plans and payment sources with Stoke's guesses. A source's platform name comes from its application fee's label (e.g. "Substack application fee").
- API: `GET /api/plans`, `PUT /api/plans/{id}`, `GET /api/payment-sources` and `PUT /api/payment-sources/{id}`. Prices and applications are referred to by opaque ids (`customer_id.ref_id`), so Stripe ids never leave the backend.
- In `app/actions.py`, a labelled price overrides the Founding guess. A revenue source with confirmed applications finds its buyers (for Cross-sell and Repeat booking) from those applications, on any account, and no longer needs "paid through". Payments from an application labelled `newsletter` (e.g. Substack gift subscriptions) never count as revenue-source sales.
- Settings has two new sections, Your plans and Where payments come from (`pages/SettingsProfile.tsx`). Each row shows Stoke's guess with Confirm, or the confirmed label with "Use Stoke's guess".
- Tests: `tests/test_profile.py`, plus label cases in `tests/test_actions.py`.

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
- **Revenue streams** (revenue sources), by the platform they're sold on: Calendly, Maven, Gumroad, Teachable, Circle, Luma, or somewhere else. Each revenue source has a name, a link, "paid through" (one of their Stripe accounts, or somewhere else) and how people pay (one-time purchase, repeat purchase such as a session or ticket, or subscription), defaulted from the platform.
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
| 8 | Repeat booking: *name* | Cross-sell | Bought this before, nothing in 180+ days. Only for revenue sources bought as a "repeat purchase" and paid through Stripe | Its link | new |
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
- The stored projection already has what this needs (dispute status, reason and `evidence_details.due_by`), as do the refund exclusions.

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
Alembic migrations, with models in `backend/app/db_models.py`. `0001`–`0003` exist; new tables start at `0004`.
- **`writer_links`** (step 1, `0003_writer_links.py`): category (revenue_source / social), kind, name, url, paid-through account, purchase (once / repeat / subscription), position.
- **`writer_profiles`** (`0004_writer_profiles.py`): plan labels and application labels (step 3). Later migrations add display name, sign-off, voice guide, timezone, daily cap, paused and digest on/off with the steps that use them.
- **`actions`** and **`outreach`** (`0005_actions_outreach.py`).
  - **`actions`**: kind, type, enabled, params (JSONB), subject/body template, template `approved_at`, and an optional `link_id` (for Cross-sell actions).
  - **`outreach`**: action_id, customer_id (HMAC from `backend/app/customer_id.py`; no email is stored), status, subject/body as sent, scheduled_for, sent_at, Gmail message/thread id, converted_at. Unique on (user, action, customer).
- **Projection change** (step 2): add `items.data.price.{id, unit_amount, currency, recurring.interval}` to subscriptions, and `application` to payment intents and their charges, in `projection.py`. Bump `PROJECTION_REV` to 2, then run `scripts/resync.py`. Doing both at once means one resync.
- **`gmail_connections`** (`0006_gmail_connections.py`): an encrypted refresh token, reusing the envelope encryption in `backend/app/crypto.py` (the same pattern as `StripeCredential`).

### Backend
- **`app/links.py`** + `/api/links` (step 1, built): CRUD for the writer's links.
- **`app/actions.py`**: pure audience rules over the existing aggregates (`aggregate.rank_customers`, `cancellations`, `anniversaries`, `new_customers`, `at_risk`, and the timeline's `subscription_changed` / `purchased` events). Each candidate carries a "why" string, and each type defines its conversion check.
- **`app/voice.py`**: RSS fetch → voice guide, and template drafting (Claude API, latest model). Only fields allowlisted in `models.py` are sent to the LLM.
- **`app/gmail.py`**: the OAuth flow, token refresh, and sending (an RFC 822 message via `users.messages.send`).
- **`app/routers/actions.py`**:
  - actions CRUD;
  - `GET /actions/{id}/audience` (analytics, which works while the action is off);
  - the queue, with approve / edit / cancel for outreach;
  - pause all;
  - per-customer outreach history.
- **`app/jobs/send.py`** (every 15 minutes):
  - sends scheduled notes that are due, enforcing caps, pause and exclusions;
  - re-resolves the email at send time with `customer_id.resolve(cid, emails)`, over the emails in the stored objects;
  - runs the conversion checks, since the stored data is kept current by webhooks.
- **`app/jobs/digest.py`** (weekly): for each action, new candidates, sent, converted, and upcoming scheduled notes, with Review / Pause links. It's sent from Stoke's own transactional ESP (e.g. Resend).
- **How the jobs run:**
  - Both are periodic loops beside `sync.run_worker()` in the web process, not Render cron services. A cron service would need its own copies of the database URL and every secret.
  - Each tick claims a DB lease with `FOR UPDATE SKIP LOCKED` and a heartbeat, like `_claim_backfill` in `app/sync.py`, so only one instance does the work.
  - Jobs build `CurrentUser` from the database and read stored data through `service.*` / `fetch.*`. They skip accounts whose import isn't finished.

### Frontend
- **Settings** (step 1): Your channels: Revenue streams and Audience channels. Later: voice guide, plan labels, Connect Gmail, caps, pause.
- **`pages/Actions.tsx`**: the action library, grouped by type (audience size, on/off, sent/converted).
- **`pages/Action.tsx`**:
  - audience analytics with "why this person";
  - a template editor with highlighted merge fields;
  - the queue, with preview, cancel / edit and schedule.
- The existing analytics tabs (`frontend/src/analyticsTabs.tsx`, at `/analytics/<tab>`) are replaced by action pages, per the table's last column. `/analytics/<tab>`, and the older top-level URLs, redirect to the matching action.
- "Contacted Nd ago" chips on the existing lists and on `CustomerProfile.tsx`.

## Build steps

Each step ships on its own, is useful by itself, and is one reviewable PR.

1. **Settings: the writer's links.** *Built, awaiting its PR* (the uncommitted files listed under Current state). The `writer_links` table and the two Settings sections. This unlocks the Cross-sell actions and gives social links to the gratitude actions.
2. **Action audiences (read-only).** *Built, awaiting its PR.*
   - `app/actions.py` rules with "why" strings, `GET /actions` and `/actions/{kind}`.
   - The library page grouped by type, and an action page per action, replacing the analytics pages.
   - The projection change (see Data): the subscription price and the payment's `application`, in one `PROJECTION_REV` bump and resync. It serves the Founding and Monthly → annual audiences now, and step 3's auto-detection.
   - No new tables. Value: writers see who to reach out to.
3. **Writer profile.** *Built, awaiting its PR.* `0004_writer_profiles`. Plan labels (standard / Founding), and Stripe application auto-detection with confirmation (using the `application` stored in step 2), which makes the upgrade and cross-sell audiences accurate.
4. **Outreach tracking, without sending.**
   - The `actions` and `outreach` migration (`0005`), and hand-written templates with merge fields.
   - A queue with preview, copy and "mark sent", plus "Contacted Nd ago" chips everywhere.
   - This proves the workflow and tracking before any integration.
5. **AI voice.** RSS → an editable voice guide. AI drafts each action's template, and the writer edits and approves it.
6. **Gmail send.**
   - `0006_gmail_connections`. OAuth (`gmail.send`), an encrypted refresh token, test-to-self, and sending from the queue.
   - Submit Google's verification (privacy policy, domain, demo video) now, because it has a long lead time. The beta is limited to 100 test users until it's approved.
7. **Scheduling and guardrails.** The 24-hour window, the send loop in the worker, the daily cap, the 14-day rule, dispute/refund exclusions, and pause-all.
8. **Conversion detection.** Per-type conversion checks run by the send loop, sent → converted, and the results on the library and action pages.
9. **Weekly digest.** A transactional ESP and a weekly loop in the worker: new audience members, sent, converted, and upcoming scheduled notes with Review / Pause links.

Order: 1 → 2 → 3 → 4 → 5/6 (in parallel) → 7 → 8 → 9. A simple digest of audience counts could ship right after step 2 if re-engagement matters sooner.

## Verification

**Unit tests:**
- `tests/test_links.py`: CRUD, validation, user scoping and the cap.
- `tests/test_actions.py`: audience rules and conversion checks for each type, on fixture data, like `test_aggregate.py`.
- `tests/test_outreach.py`: status transitions, uniqueness, the 14-day rule, caps, pause, and user scoping (like `test_scope.py`).
- `tests/test_projection.py`: the new price and `application` fields are kept, and nothing else is.
- The send and digest jobs: one tick of each loop body, with a mocked Gmail client and a test of the lease (two claimers, one wins).

**Local end to end:**
1. Start everything with `./dev.sh`. Keep stored data current with `stripe listen --forward-connect-to localhost:8000/api/stripe/webhook`.
2. Run `backend/scripts/seed_test_data.py` with long-tenure, one-off and canceled customers. After the projection change, run `backend/scripts/resync.py`.
3. Add a revenue stream in Settings and enable Founding upgrade.
4. Approve the template. A test copy should arrive in your own Gmail (as a test user).
5. Run the send loop with time advanced. The scheduled batch should send and the chips should appear.
6. Simulate an upgrade in Stripe test mode. Once the webhook re-read lands, the next send tick should mark it converted, and the digest dry-run should show it.
