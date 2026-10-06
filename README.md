# Stoke

A home base for a creator's customers across one or more Stripe accounts. It's aimed at creators who sell through platforms like Substack or Maven.

## Views
- **Overview** (`/`): two month-by-month charts for the past 12 months, then a card for each list below covering the past month.
  - *New vs churned customers.* New customers are counted the same way as the New customers list. A customer churns when a subscription ends (not when they click cancel) and they have no other subscription still running, so a plan change isn't churn. A customer who leaves and later comes back still churned that month. Churn needs Subscriptions access.
  - *Monthly take-home*, with the change from the month before. A payment's refunds and disputes count against the month of the payment, as on the Top customers list.
  - The current month is drawn dashed, since it's still in progress. Months are calendar months in UTC. Each chart can also be viewed as a table.
- **At risk** (`/at-risk`): customers you can still reach, most urgent first. That's subscriptions whose payment is failing (with Stripe's next retry date, the amount owed and the decline reason), unpaid ones whose retries are over (from the past 90 days), subscriptions canceled at period end that are still active (with the customer's chosen reason), subscriptions canceled by a failed payment in the past 30 days whose customer hasn't come back, and disputes or bank inquiries still waiting on your response (with the deadline). Someone who's canceling a second plan but keeps another isn't listed. It can be filtered by kind and by account.
- **Top customers** (`/top`): customers ranked by net paid over a period.
- **New customers** (`/new`): first-time customers, most recent first: anyone whose very first successful payment or subscription was recent. That includes a first one-off purchase (a paid coaching session, a tip) as well as a new subscription or trial. Each shows what they started with, their subscription now, and their take-home so far. Someone coming back after canceling isn't new; Cancellations shows them as *Resubscribed*.
- **Anniversaries** (`/anniversaries`): customers whose first successful payment had an anniversary recently, with which one it was (1 year, 2 years, …). It shows whether they're still subscribed or when they last paid.
- **Cancellations** (`/cancellations`): canceled subscriptions, most recent cancellation first. This includes subscriptions canceled at period end, which stay active until then. It shows Stripe's reason: the customer's chosen feedback (e.g. "Too expensive"), or *Payment failed* or *Disputed* for involuntary churn. It also shows the customer's lifetime value and whether they've since resubscribed. The customer's free-text cancellation comment is never returned.
- **Customer profile** (`/customers/:id`): the full transaction history for one email. The id is opaque (see Security notes), so URLs never contain the email.

The three event lists (New customers, Anniversaries, Cancellations) can be filtered to the past week, month or 3 months, and by account.

## How it reaches Stripe accounts
A creator doesn't own the platform they sell through. What they have is their own Stripe account, connected to the platform. Each signed-in user adds a restricted, read-only key for each of their Stripe accounts on the **Settings** page (`/settings`). Every view aggregates only that user's accounts.

When a key is added, Stoke checks it with Stripe: which account it belongs to, and which of the permissions below it lacks. A key is refused if it's a publishable key, a live secret key (it could move money, and Stoke only reads), a key Stripe rejects, or a second key for an account already added (use **Replace key** to rotate a key). A key that's missing permissions is still accepted, and Settings lists what to grant before you choose **Re-check**. Later, a Stripe App with OAuth would replace hand-issued keys.

For local development, `DEV_MODE=true` with `STRIPE_PLATFORM_KEY` adds your own Connect platform's connected accounts to *every* user's view, to simulate creators.

**What a creator can see depends on how the platform charges:**
- **Direct charges.** Substack works this way: creators connect a Standard account, and the platform takes an application fee. Customers and emails live in the creator's account, so the app works.
- **Destination charges.** This is typical with Express accounts. The platform charges customers on its own account and transfers money to the creator, so the creator's account has no customer data. The app can't rank these accounts' customers: they'll show no paying customers.

- `backend/`: FastAPI and Postgres (SQLAlchemy, Alembic). Reads live from the Stripe API and caches results in memory for 5 minutes. Postgres holds users, their settings and their encrypted keys.
- `frontend/`: React (Vite, React Router, TanStack Query), with sign-in through Auth0.

## How the numbers work
- **A payment is one PaymentIntent.** Every retry of the same payment attaches to it, so a card that's declined 4 times is one failed payment, not 4. Each payment is matched to its invoice, when it has one. The invoice supplies the plan name, whether the payment was a new subscription, a renewal or a one-off, and the number of attempts.
- **Totals are take-home**: what reached your Stripe balance and can be paid out. That's what customers paid, minus refunds, minus the fees deducted from each payment: the platform's cut (Substack's 10% "application fee") and Stripe's processing fee. Each payment on a profile shows this breakdown. The fees come from the payment's balance transaction, so they're exactly what Stripe recorded. Not included: fees Stripe charges the account directly rather than per payment (they show in the Dashboard as "Stripe fee" balance transactions, sometimes with tax), and payout fees.
- **Refunds** come off take-home in full, and the payment's fees stay deducted: Stripe keeps its processing fee. The app also assumes the platform keeps its fee; if Substack returns its 10% on a refund, take-home is slightly understated. Pending refunds count as soon as they're made, as Stripe's balance does. Each refund on a profile shows what the payment left you before and after.
- **Disputes** follow Stripe's balance, so money that's likely lost isn't counted: when a dispute opens, Stripe withdraws the disputed amount plus a dispute fee (CA$15 / US$15), and take-home drops by both until the dispute is won. A win returns the amount but usually not the fee. An inquiry withdraws nothing. The amounts come from the dispute's own balance transactions; its evidence (customer details) is never returned by the API.
- **Plan names** come from the invoice line, e.g. "1 × $8 a month (at $12.00 / month)". The price is dropped since each payment shows its amount. A product name that is itself a price (Substack names products like "$8 a month", which can disagree with the actual price) is replaced by the billing interval: "Monthly plan". Failed and canceled payments appear on the profile timeline but don't count toward totals. PaymentIntents the customer never attempted (e.g. an abandoned checkout) are ignored.
- **Customers are merged by email** (case-insensitive) across all accounts. The email is taken from the Customer first, then the invoice's copy of it (which survives if the customer is later deleted), then the charge's billing details, then the receipt email.
- **Currency**: every amount is converted to one reporting currency. By default that's the platform's payout currency, or the first account's when there's no platform key. Set `REPORTING_CURRENCY` to override it. The conversion uses the amount Stripe actually settled, taken from the charge's balance transaction. If a connected account settles in a different currency, its amounts are converted again using the ECB daily rate for the charge date, via [Frankfurter](https://frankfurter.dev). Refunds are converted at the original charge's rate, which is a close approximation.

## Setup

### Configuration
Backend settings live in a single `.env` file at the repo root (see `.env.example`):
```sh
cp .env.example .env   # each setting is explained in the file
```
The API and the scripts load this file with python-dotenv, whatever directory you run them from, so you don't need to `export` or `source` anything. Real environment variables take precedence over values in the file. The frontend's Auth0 settings go in `frontend/.env.local` (see `frontend/.env.example`).

### Auth0
1. Create an **API** (Applications → APIs). Its identifier is the audience: put it in `AUTH0_AUDIENCE` and `VITE_AUTH0_AUDIENCE`. Keep RS256 signing. Turn on **Allow Offline Access**, so the app can use refresh tokens.
2. Create a **Single Page Application**. Put its domain in `AUTH0_DOMAIN` and `VITE_AUTH0_DOMAIN`, and its client ID in `VITE_AUTH0_CLIENT_ID`. Set Allowed Callback URLs, Allowed Logout URLs and Allowed Web Origins to `http://localhost:5173`. Under Refresh Token Rotation, turn on **Allow Refresh Token Rotation**.
3. Access tokens don't include the user's email. To show it, add a Post-Login **Action** and deploy it to the Login flow:
   ```js
   exports.onExecutePostLogin = async (event, api) => {
     if (event.user.email) api.accessToken.setCustomClaim('https://stoke/email', event.user.email)
   }
   ```

### Database
Postgres runs in Docker, as defined in `docker-compose.yml`. You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running: the whale icon should be in the menu bar.

1. Start Postgres from the repo root:
   ```sh
   docker compose up -d
   ```
   The first run downloads the `postgres:17` image, which takes a minute. `-d` runs it in the background, so the terminal is free afterwards. It listens on `127.0.0.1:5432` with user, password and database all `stoke`, which matches the default `DATABASE_URL`.
2. Check that it's up. `STATUS` should say `healthy`:
   ```sh
   docker compose ps
   ```
3. Create or update the tables. Run this the first time, and again whenever you pull new migrations:
   ```sh
   cd backend && uv run alembic upgrade head
   ```

The container keeps running until you stop it. After a reboot, open Docker Desktop and run `docker compose up -d` again. Your data is kept in a Docker volume (`stoke-pg`), so it survives restarts.

| To… | Run (from the repo root) |
|---|---|
| Stop Postgres (keeps data) | `docker compose stop` |
| Start it again | `docker compose up -d` |
| See its logs | `docker compose logs -f db` |
| Open a SQL prompt | `docker compose exec db psql -U stoke` |
| Delete everything and start fresh | `docker compose down -v`, then steps 1 and 3. This deletes all users and stored keys. |

If `docker compose up` says port 5432 is already in use, another Postgres is running on your Mac (for example, from Homebrew: `brew services stop postgresql`). Stop it, or change the port mapping in `docker-compose.yml` and `DATABASE_URL` to match.

After changing `app/db_models.py`, generate a migration with `uv run alembic revision --autogenerate -m "…"` and review it before applying.

### Backend
Start the database first.
```sh
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --reload
```
`--reload` picks up edits to existing files, but after pulling new code or dependencies, stop it (Ctrl+C) and start it again.

### Stripe keys
Sign in, open **Settings**, and add a **restricted, read-only key** (Dashboard → Developers → API keys → Create restricted key) for each account, with **Read** access to:
- PaymentIntents
- Invoices
- Charges
- Customers
- Subscriptions (Anniversaries and Cancellations need it, and say which permission is missing without it. New customers then lists only customers who've paid, not unpaid trials.)
- Balance transactions
- Accounts (Stripe calls this `connected_account_read`). The app still works without it, but it shows "Stripe account" instead of the account's name, and can't tell when the same account is added twice.

**Moving keys out of `.env`.** If your `.env` still has keys in `STRIPE_ACCOUNT_KEYS` or `STRIPE_API_KEY` from before, sign in once, then run the following. It runs each key through the same checks as Settings. Then delete those settings from `.env`.
```sh
cd backend && uv run python scripts/import_env_keys.py --email you@example.com
```

### Seed a sandbox with test customers
1. Put the sandbox's **secret** test key (`sk_test_…`) in `STRIPE_SEED_KEY`. The script refuses live keys.
2. Run the script:
   ```sh
   cd backend
   uv run python scripts/seed_test_data.py
   ```
   It creates one customer per scenario, based on what a Substack creator's account contains, plus cases a small account may not have hit yet:
   - monthly, annual and founding-member subscriptions, and a plan upgrade;
   - failed payments that recovered and ones that never did;
   - full and partial refunds;
   - one-off tips and gift invoices;
   - a reader paying in a foreign currency;
   - a deleted customer;
   - one email on two customer records;
   - payments made without an invoice;
   - a cancellation, a cancellation at period end, and a customer who canceled and came back;
   - a new customer whose first purchase was a one-off coaching session.
   - refunds: two partial refunds on one payment, a refunded tip, a refund that fails, and a refund in a foreign currency;
   - disputes, using Stripe's dispute test cards: lost (accepted), lost on evidence, won, still open, an inquiry, and one on a payment without an invoice.

   To add only some scenarios, name them: `uv run python scripts/seed_test_data.py dispute_won refunded_tip`. `--list` shows them all. Dispute scenarios each wait a few seconds for Stripe to open the dispute.
3. To view the data, add a restricted key for the same sandbox in Settings.

Stripe can't backdate payments, so everything is dated "now" and there are no renewals or anniversaries. Each run adds a new set of customers.

### Frontend
```sh
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api to 127.0.0.1:8000
```

### Tests
```sh
docker compose up -d   # the database tests create and use their own `stoke_test` database
cd backend && uv run pytest
```
Set `TEST_DATABASE_URL` to use a different Postgres server. The tests include `tests/test_response_shape.py`, which fails if card details, addresses, phone numbers, metadata, receipt URLs or Stripe ids ever appear in an API response. `tests/test_credentials.py` likewise fails if a stored key ever appears in a response.

## Security notes
- **Sign-in is through Auth0.** Every API route needs an Auth0 access token, checked against the tenant's signing keys. The checks cover signature (RS256 only), issuer, audience and expiry. Users are created on first sign-in. A user's keys, settings and customer data are only reachable with that user's token, and another user's key id returns 404. Tokens are sent as a bearer header, not a cookie, so there's no CSRF. Requests whose `Host` isn't in `ALLOWED_HOSTS` are refused, which blocks DNS rebinding. Every response is `Cache-Control: no-store`.
- **Stripe keys are encrypted at rest** with envelope encryption (`backend/app/crypto.py`):
  - Each key is encrypted with AES-256-GCM under its own random data key, and that data key is encrypted by a master key. Only ciphertext reaches Postgres, so a database dump or backup alone reveals nothing.
  - Both layers are bound to the key's owner and record, so ciphertext copied onto another row or user won't decrypt.
  - Keys are never returned by the API, only their last four characters. The 422 error for a malformed request doesn't echo its input.
  - Decrypted keys exist only in the backend's memory while it reads from Stripe.
  - **Master key, locally:** `STOKE_ENCRYPTION_KEY`, or else a key generated on first run into `.stoke_encryption_key` at the repo root (gitignored). **Back it up** alongside `.customer_id_secret`: if it's lost, stored keys can't be read, and every user has to add their keys again.
  - **Master key, in production:** set `KEY_CIPHER=aws_kms` and `AWS_KMS_KEY_ID`. The master key then never leaves KMS, and every unwrap is permissioned and logged by CloudTrail. Records name the scheme that sealed them, so moving from `local` to KMS means re-encrypting existing keys (or having users re-add them).
- **URLs carry no PII.** Profile links (and the API path behind them) use an opaque customer id: an HMAC of the email, truncated to 24 hex characters. Neither the email nor any Stripe id appears in URLs, browser history or access logs. The key is a random secret, generated on first run and kept in `.customer_id_secret` at the repo root (gitignored), or `CUSTOMER_ID_SECRET` if set. It's deliberately independent of API keys and of which accounts are connected, so links survive key rotation and creators installing or removing a future Stripe App. Back it up with `.env` and `.stoke_encryption_key`: losing it changes every customer link. Account filters (`?account=acct_…`) still name the creator's own Stripe account, not a customer.
- Responses are built only from the Pydantic models in `backend/app/models.py`, and raw Stripe objects are never returned. Stripe errors are logged on the server and returned as a generic 502.

## Limitations
- Data is read live, so "All time" on a large account can be slow. The upgrade path is syncing charges into a database and keeping it current with Connect webhooks.
- The profile page, Anniversaries and Cancellations (for lifetime value) filter the account's full payment history. It's cached for 5 minutes and shared with the "All time" leaderboard. The first load can be slow on large accounts. Subscriptions are likewise read in full and cached.
- A subscription's plan name comes from its latest invoice. After a plan change, that invoice holds only proration lines, so the name is taken from the price's nickname, else from Stripe's "Remaining time on …" line.
- Charges made without a PaymentIntent (the legacy Charges API) aren't included.
- For payments without an invoice, retries are still grouped together, but the attempt count isn't known, so the timeline doesn't say how many tries it took.
- Stripe test mode can't backdate payments, so seeded data all falls in "Last month" and has no renewals or anniversaries. Period filtering, renewal grouping and anniversaries are covered by unit tests.
