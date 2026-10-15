# Connecting Stripe: Stripe App setup

Writers connect their Stripe accounts by installing Stoke's Stripe App, through Stripe's OAuth install flow. On Settings → Stripe, **Connect with Stripe** sends them to Stripe. There they pick an account and approve the app's read-only permissions, then come back to Stoke. The app is defined in `stripe-app/stripe-app.json`, and the backend side is in `backend/app/stripe_app.py`.

This uses two Stripe accounts, kept separate:
- **Stoke**: the app's own account (the "developer" account). It owns the app, its secret key and the webhook endpoint, and never holds writer data.
- **A writer's account**: for testing, your Substack test account. It installs the app from Stoke's Settings like any writer would.

Until the app is published to the Stripe App Marketplace, it's in **external testing**: only test-mode installs from the External test tab, which is enough for local development and the Render test URL.

## 1. Create the Stoke account

In the Stripe Dashboard, open the account switcher (top left) → **New account**, and name it `Stoke`. Steps 2–5 all happen in this account.

## 2. Install the Stripe CLI and log in as Stoke

```sh
brew install stripe-cli        # or `brew upgrade stripe-cli`: versions before about 1.50 can't install the apps plugin
stripe plugin install apps
stripe login
```

`stripe login` opens the browser to approve. **Choose the Stoke account** on that page, not your Substack test account. To check, run `stripe config --list`. The `account_id` it shows should be Stoke's (the Dashboard shows it under Settings → Business → Account details).

## 3. Upload the app

```sh
cd stripe-app
stripe apps upload --live
```

This creates the app, named Stoke, under the Stoke account. `--live` uploads to the account itself rather than a sandbox. Nothing is published: until the app passes Stripe's review, it can only be installed from the External test links. The CLI packages the app as a Node project, so `stripe-app/` has a `package.json` and `package-lock.json` even though the app has no dependencies or Dashboard UI. The upload includes:
- **Permissions:** read-only access to payments, charges and refunds, disputes, invoices, subscriptions, customers, balance transactions, events, and the account's name.
- **Redirect URLs:** `https://localhost:5173/api/stripe/callback` and `https://stoke-y4sf.onrender.com/api/stripe/callback`. Stripe requires https for every redirect URL, even in test mode, but accepts `https://localhost`. That's why the local frontend runs on `https://localhost:5173`, with a self-signed certificate your browser asks you to trust once.

If Stripe says the app id `com.stoke.stoke` is taken, change `id` in `stripe-app.json` and upload again. Upload again after any change to the manifest, such as new redirect URLs when you add a domain.

## 4. Copy the install link

In the Stoke account, go to **Apps** (dashboard.stripe.com/apps) → **Stoke** → **External test** → **Get started**. Under **Test OAuth**, copy the **test mode** link. It starts with `https://marketplace.stripe.com/oauth/v2/` and contains `client_id=ca_…`. Stoke adds its own `redirect_uri` and `state` to it.

If Stripe asks you to add testers, add your Substack test account.

## 5. Copy the secret key

In the Stoke account, in test mode, go to **Developers → API keys** and reveal the **Secret key** (`sk_test_…`). It must be the Stoke account's key, in the same mode as the install link: Stripe only exchanges a test-mode install for the developer account's test-mode key.

## 6. Configure Stoke locally

In the repo-root `.env`:
```
STRIPE_APP_INSTALL_URL=https://marketplace.stripe.com/oauth/v2/…
STRIPE_APP_SECRET_KEY=sk_test_…
```

For webhooks, keep this running in a second terminal while you work. The CLI must still be logged in as Stoke:
```sh
stripe listen --all-snapshot --forward-connect-to localhost:8000/api/stripe/webhook
```
It prints a signing secret (`whsec_…`). Set it as `STRIPE_WEBHOOK_SECRET` in `.env`; it stays the same between runs.

Then start Stoke with `./dev.sh`, which applies migration `0009_stripe_app_connections`.

## 7. Configure Render

1. Register the webhook endpoint on the Stoke account, using the `.env` from step 6:
   ```sh
   cd backend
   uv run python scripts/register_webhook.py --url https://stoke-y4sf.onrender.com/api/stripe/webhook
   ```
   It prints which account it created the endpoint on (check it's Stoke), and a signing secret. This creates one "connected accounts" endpoint in test mode, which receives events from every account that installed the app, including uninstalls.
2. In Render, go to **stoke → Environment** and set:
   - `STRIPE_APP_INSTALL_URL`: the same link as locally.
   - `STRIPE_APP_SECRET_KEY`: the same key as locally.
   - `STRIPE_WEBHOOK_SECRET`: the secret the script printed. This is not the one `stripe listen` printed.

## 8. Connect as a writer

1. In the Dashboard, switch to your **Substack test account**.
2. In Stoke, go to Settings → Stripe → **Connect with Stripe**. If the account is already there with a key, use **Switch to the Stripe app** on its row instead. That converts it in place, keeping its name and the links paid through it.
3. On Stripe's page, pick the Substack test account and approve.
4. You land back on Settings with "Stripe connected", and the account shows **Stripe app** under Connection while Stoke imports its history.

To check webhooks, make a test payment in the Substack test account and watch it arrive in the `stripe listen` terminal.

To check uninstalls, uninstall Stoke from the Substack test account's installed apps. The row then shows **Disconnected in Stripe** with **Reconnect**.

## Notes

- **Tokens.** Stripe's access tokens last an hour. The refresh token is rolled on every refresh, and Stoke saves each new one, encrypted, before using the access token that came with it. If a refresh fails at the wrong moment, the account shows as disconnected and **Reconnect** fixes it.
- **Removing an account in Stoke** doesn't uninstall the app in Stripe. Uninstall it from the Dashboard's installed apps to stop Stoke's access entirely.
- **Missing permissions.** If Settings shows "Missing …" after connecting, the manifest lacks a permission Stoke needs. Add it to `stripe-app.json`, upload again, and connect again.
- **Sandboxes.** If the writer's account is a Stripe *sandbox* rather than test mode, it needs the External test tab's sandbox link, and the code exchange needs the app's managed sandbox key (and `"sandbox_install_compatible": true` in the manifest). This setup covers test mode only.
- **Going live** needs:
  - your production domain in `allowed_redirect_uris`, `ALLOWED_HOSTS` and `CORS_ORIGIN`;
  - the app submitted for review and published;
  - its public install link in `STRIPE_APP_INSTALL_URL`;
  - the Stoke account's live secret key;
  - a live-mode webhook endpoint, registered by running the script with that live key.
