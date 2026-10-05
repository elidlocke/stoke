# Stoke

A home base for a creator's customers across one or more Stripe accounts. It's aimed at creators who sell through platforms like Substack or Maven.

## Views
- **Overview** (`/`): a card for each list below, covering the past month.
- **Top customers** (`/top`): customers ranked by net paid over a period.
- **New subscribers** (`/new`): subscriptions started recently, most recent first. A subscriber is marked *Returning* if an earlier subscription of theirs had ended before this one started. Trials are included.
- **Anniversaries** (`/anniversaries`): customers whose first successful payment had an anniversary recently, with which one it was (1 year, 2 years, …). It shows whether they're still subscribed or when they last paid.
- **Cancellations** (`/cancellations`): canceled subscriptions, most recent cancellation first. This includes subscriptions canceled at period end, which stay active until then. It shows Stripe's reason: the customer's chosen feedback (e.g. "Too expensive"), or *Payment failed* or *Disputed* for involuntary churn. It also shows the customer's lifetime value and whether they've since resubscribed. The customer's free-text cancellation comment is never returned.
- **Customer profile** (`/customers/:id`): the full transaction history for one email. The id is opaque (see Security notes), so URLs never contain the email.

The three event lists can be filtered to the past week, month or 3 months, and by account.

## How it reaches Stripe accounts
A creator doesn't own the platform they sell through. What they have is their own Stripe account, connected to the platform. The app supports two kinds of access, and both can be used together:

| Setting | Access | When |
|---|---|---|
| `STRIPE_ACCOUNT_KEYS` | One key per creator, issued from that creator's own Stripe account | The real-world path. Later, a Stripe App with OAuth would replace hand-issued keys. |
| `STRIPE_PLATFORM_KEY` | Your own Connect platform, reading its connected accounts | Development and simulation |

**What a creator can see depends on how the platform charges:**
- **Direct charges.** Substack works this way: creators connect a Standard account, and the platform takes an application fee. Customers and emails live in the creator's account, so the app works.
- **Destination charges.** This is typical with Express accounts. The platform charges customers on its own account and transfers money to the creator, so the creator's account has no customer data. The app can't rank these accounts' customers: they'll show no paying customers.

- `backend/`: FastAPI. Reads live from the Stripe API and caches results in memory for 5 minutes.
- `frontend/`: React (Vite, React Router, TanStack Query).

## How the numbers work
- **A payment is one PaymentIntent.** Every retry of the same payment attaches to it, so a card that's declined 4 times is one failed payment, not 4. Each payment is matched to its invoice, when it has one. The invoice supplies the plan name, whether the payment was a new subscription, a renewal or a one-off, and the number of attempts.
- **Net paid** is successful payments minus refunds, before Stripe fees. Failed and canceled payments appear on the profile timeline but don't count toward totals. PaymentIntents the customer never attempted (e.g. an abandoned checkout) are ignored.
- **Customers are merged by email** (case-insensitive) across all accounts. The email is taken from the Customer first, then the invoice's copy of it (which survives if the customer is later deleted), then the charge's billing details, then the receipt email.
- **Currency**: every amount is converted to one reporting currency. By default that's the platform's payout currency, or the first account's when there's no platform key. Set `REPORTING_CURRENCY` to override it. The conversion uses the amount Stripe actually settled, taken from the charge's balance transaction. If a connected account settles in a different currency, its amounts are converted again using the ECB daily rate for the charge date, via [Frankfurter](https://frankfurter.dev). Refunds are converted at the original charge's rate, which is a close approximation.

## Setup

### Configuration
All settings live in a single `.env` file at the repo root (see `.env.example`):
```sh
cp .env.example .env   # then fill in the keys; each setting is explained in the file
```
The API and the seed script both load this file with python-dotenv, whatever directory you run them from, so you don't need to `export` or `source` anything. Real environment variables take precedence over values in the file.

### Backend
```sh
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --reload
```

For the API keys, use **restricted, read-only test keys** (Dashboard → Developers → API keys → Create restricted key) with **Read** access to:
- PaymentIntents
- Invoices
- Charges
- Customers
- Subscriptions (New subscribers, Anniversaries and Cancellations need it. Without it, those views say which permission is missing.)
- Balance transactions
- Accounts (Stripe calls this `connected_account_read`). The app still works without it, but it shows "Account 1" instead of the account's name.

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
   - a cancellation, a cancellation at period end, and a customer who canceled and came back.
3. To view the data, point `STRIPE_API_KEY` at the same sandbox and restart the backend.

Stripe can't backdate payments, so everything is dated "now" and there are no renewals or anniversaries. Each run adds a new set of customers.

### Frontend
```sh
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api to 127.0.0.1:8000
```

### Tests
```sh
cd backend && uv run pytest
```
The tests include `tests/test_response_shape.py`, which fails if card details, addresses, phone numbers, metadata, receipt URLs or Stripe ids ever appear in an API response.

## Security notes
- **There is no authentication.** Anyone who can reach the backend can see every customer's email and payment history. The backend is bound to `127.0.0.1` for that reason. Add auth before deploying.
- **URLs carry no PII.** Profile links (and the API path behind them) use an opaque customer id: an HMAC of the email, truncated to 24 hex characters. Neither the email nor any Stripe id appears in URLs, browser history or access logs. The key is a random secret, generated on first run and kept in `.customer_id_secret` at the repo root (gitignored), or `CUSTOMER_ID_SECRET` if set. It's deliberately independent of API keys and of which accounts are connected, so links survive key rotation and creators installing or removing a future Stripe App. Back it up with `.env`: losing it changes every customer link. Account filters (`?account=acct_…`) still name the creator's own Stripe account, not a customer.
- Responses are built only from the Pydantic models in `backend/app/models.py`, and raw Stripe objects are never returned. Stripe errors are logged on the server and returned as a generic 502.

## Limitations
- Data is read live, so "All time" on a large account can be slow. The upgrade path is syncing charges into a database and keeping it current with Connect webhooks.
- The profile page, Anniversaries and Cancellations (for lifetime value) filter the account's full payment history. It's cached for 5 minutes and shared with the "All time" leaderboard. The first load can be slow on large accounts. Subscriptions are likewise read in full and cached.
- A subscription's plan name comes from its latest invoice. After a plan change, that invoice holds only proration lines, so the name is taken from the price's nickname, else from Stripe's "Remaining time on …" line.
- Charges made without a PaymentIntent (the legacy Charges API) aren't included.
- For payments without an invoice, retries are still grouped together, but the attempt count isn't known, so the timeline doesn't say how many tries it took.
- Stripe test mode can't backdate payments, so seeded data all falls in "Last month" and has no renewals or anniversaries. Period filtering, renewal grouping and anniversaries are covered by unit tests.
