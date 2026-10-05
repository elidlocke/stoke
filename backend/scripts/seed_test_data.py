"""Seed a Stripe sandbox with customers that look like a Substack creator's account.

Usage (from backend/):
    uv run python scripts/seed_test_data.py

Uses STRIPE_SEED_KEY from the repo-root .env. It must be a sandbox (test mode) secret key;
the script refuses live keys.

Each scenario below is one customer, covering what we've seen in a real Substack account plus
cases a small account may not have hit yet. Everything is created "now": Stripe can't backdate
payments, so there are no renewals ("Renewed" events) and no anniversaries in seeded data.

Each run creates new customers; running it twice doubles the data.
"""

import os
import sys
from collections.abc import Callable
from pathlib import Path

import stripe
from dotenv import load_dotenv

# Repo-root .env, resolved from this file so it loads regardless of how or where the script is run.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

GOOD_CARD = "pm_card_visa"
# Attaches to a customer fine, then every charge on it is declined ("Your card was declined.").
FAILING_CARD = "pm_card_chargeCustomerFail"
INSUFFICIENT_FUNDS_CARD = "pm_card_visa_chargeDeclinedInsufficientFunds"


class Seeder:
    def __init__(self, client: stripe.StripeClient, currency: str):
        self.c = client
        self.currency = currency
        # A second currency to exercise conversion: a reader paying in a currency other than the payout one.
        self.foreign = "eur" if currency == "usd" else "usd"
        self.prices = {
            "monthly": self.price("stoke_monthly", "Monthly subscription", 800, currency, "month"),
            "annual": self.price("stoke_annual", "Annual subscription", 8000, currency, "year"),
            "founding": self.price("stoke_founding", "Founding member", 15000, currency, "year"),
            "monthly_foreign": self.price(
                f"stoke_monthly_{self.foreign}", "Monthly subscription", 600, self.foreign, "month"
            ),
        }

    # ---- building blocks ----

    def price(self, lookup_key, name, amount, currency, interval) -> str:
        existing = self.c.v1.prices.list({"lookup_keys": [lookup_key], "limit": 1}).data
        if existing:
            return existing[0].id
        return self.c.v1.prices.create({
            "lookup_key": lookup_key,
            "product_data": {"name": name},
            "unit_amount": amount,
            "currency": currency,
            "recurring": {"interval": interval},
        }).id

    def customer(self, email, card=GOOD_CARD) -> str:
        cus = self.c.v1.customers.create({"email": email})
        self.set_card(cus.id, card)
        return cus.id

    def set_card(self, customer_id, card) -> str:
        pm = self.c.v1.payment_methods.attach(card, {"customer": customer_id})
        self.c.v1.customers.update(customer_id, {"invoice_settings": {"default_payment_method": pm.id}})
        return pm.id

    def subscribe(self, customer_id, plan):
        # allow_incomplete: a declined first payment leaves an open invoice instead of raising.
        return self.c.v1.subscriptions.create({
            "customer": customer_id,
            "items": [{"price": self.prices[plan]}],
            "payment_behavior": "allow_incomplete",
        })

    def retry(self, invoice_id, payment_method=None) -> bool:
        try:
            self.c.v1.invoices.pay(invoice_id, {"payment_method": payment_method} if payment_method else {})
            return True
        except stripe.CardError:
            return False

    def invoice_payment_intent(self, invoice_id) -> str:
        inv = self.c.v1.invoices.retrieve(invoice_id, {"expand": ["payments"]})
        return inv.payments.data[0].payment.payment_intent

    def one_off_invoice(self, customer_id, description, amount):
        inv = self.c.v1.invoices.create({
            "customer": customer_id,
            "collection_method": "charge_automatically",
            "auto_advance": False,
        })
        self.c.v1.invoice_items.create({
            "customer": customer_id, "invoice": inv.id,
            "amount": amount, "currency": self.currency, "description": description,
        })
        self.c.v1.invoices.finalize_invoice(inv.id)
        self.c.v1.invoices.pay(inv.id)
        return inv

    def payment_intent(self, customer_id, amount, description, card, confirm=True):
        return self.c.v1.payment_intents.create({
            "customer": customer_id,
            "amount": amount,
            "currency": self.currency,
            "description": description,
            "payment_method": card,
            "confirm": confirm,
            "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
        })

    # ---- scenarios: one customer each ----

    def subscriber(self):
        """Subscribed monthly."""
        self.subscribe(self.customer("subscriber@example.com"), "monthly")

    def annual(self):
        """Subscribed annually."""
        self.subscribe(self.customer("annual@example.com"), "annual")

    def founding(self):
        """Founding member: the top tier."""
        self.subscribe(self.customer("founding@example.com"), "founding")

    def upgraded(self):
        """Started monthly, then upgraded to annual (a "Changed plan" event)."""
        sub = self.subscribe(self.customer("upgraded@example.com"), "monthly")
        self.c.v1.subscriptions.update(sub.id, {
            "items": [{"id": sub["items"].data[0].id, "price": self.prices["annual"]}],
            "proration_behavior": "always_invoice",
        })

    def recovered(self):
        """First payment declined 3 times, then succeeded after the reader updated their card."""
        cus = self.customer("recovered@example.com", card=FAILING_CARD)
        invoice = self.subscribe(cus, "monthly").latest_invoice
        self.retry(invoice)
        self.retry(invoice)
        self.retry(invoice, self.set_card(cus, GOOD_CARD))

    def churned(self):
        """Payment declined 3 times and never recovered."""
        invoice = self.subscribe(self.customer("churned@example.com", card=FAILING_CARD), "monthly").latest_invoice
        self.retry(invoice)
        self.retry(invoice)

    def refunded(self):
        """Annual subscription, fully refunded."""
        sub = self.subscribe(self.customer("refunded@example.com"), "annual")
        self.c.v1.refunds.create({"payment_intent": self.invoice_payment_intent(sub.latest_invoice)})

    def partially_refunded(self):
        """Founding member, half refunded."""
        sub = self.subscribe(self.customer("partial-refund@example.com"), "founding")
        self.c.v1.refunds.create({"payment_intent": self.invoice_payment_intent(sub.latest_invoice), "amount": 7500})

    def tipper(self):
        """Monthly subscriber who also tipped and bought a gift subscription (one-off invoices)."""
        cus = self.customer("tipper@example.com")
        self.subscribe(cus, "monthly")
        self.one_off_invoice(cus, "Tip", 500)
        self.one_off_invoice(cus, "Gift subscription (1 year)", 8000)

    def foreign_reader(self):
        """Pays in a different currency than the payout currency, so amounts are converted."""
        self.subscribe(self.customer(f"{self.foreign}-reader@example.com"), "monthly_foreign")

    def deleted(self):
        """Subscribed, then the customer was deleted: the email survives only on the invoice."""
        cus = self.customer("deleted@example.com")
        self.subscribe(cus, "annual")
        self.c.v1.customers.delete(cus)

    def duplicate_email(self):
        """Two customer records with the same email (different case) that should merge into one person."""
        self.subscribe(self.customer("Two-Records@Example.com"), "monthly")
        self.subscribe(self.customer("two-records@example.com"), "annual")

    def cancelled(self):
        """Subscribed monthly, then canceled right away, saying it was too expensive."""
        sub = self.subscribe(self.customer("cancelled@example.com"), "monthly")
        self.c.v1.subscriptions.cancel(sub.id, {"cancellation_details": {"feedback": "too_expensive"}})

    def cancelling(self):
        """Annual subscriber who canceled at period end, so is still active until the year is up."""
        sub = self.subscribe(self.customer("cancelling@example.com"), "annual")
        self.c.v1.subscriptions.update(sub.id, {
            "cancel_at_period_end": True, "cancellation_details": {"feedback": "unused"},
        })

    def won_back(self):
        """Canceled monthly, then came back on annual: a returning subscriber."""
        cus = self.customer("won-back@example.com")
        self.c.v1.subscriptions.cancel(self.subscribe(cus, "monthly").id)
        self.subscribe(cus, "annual")

    def no_invoice(self):
        """Payments made without an invoice: a success, a declined-then-canceled one, and an abandoned one."""
        cus = self.customer("no-invoice@example.com")
        self.payment_intent(cus, 2500, "Merch: tote bag", GOOD_CARD)
        try:
            self.payment_intent(cus, 4000, "Merch: hoodie", INSUFFICIENT_FUNDS_CARD)
        except stripe.CardError as exc:
            self.c.v1.payment_intents.cancel(exc.error.payment_intent.id)
        # Never confirmed, like an abandoned checkout; the app should ignore it.
        self.payment_intent(cus, 1000, "Merch: sticker", GOOD_CARD, confirm=False)


SCENARIOS: list[Callable[[Seeder], None]] = [
    Seeder.subscriber, Seeder.annual, Seeder.founding, Seeder.upgraded,
    Seeder.recovered, Seeder.churned, Seeder.refunded, Seeder.partially_refunded,
    Seeder.tipper, Seeder.foreign_reader, Seeder.deleted, Seeder.duplicate_email, Seeder.no_invoice,
    Seeder.cancelled, Seeder.cancelling, Seeder.won_back,
]


def main():
    load_dotenv(ENV_FILE)
    key = os.environ.get("STRIPE_SEED_KEY", "")
    if not key.startswith(("sk_test_", "rk_test_")):
        sys.exit("STRIPE_SEED_KEY must be a sandbox (test mode) key: sk_test_... or rk_test_...")

    client = stripe.StripeClient(key, max_network_retries=3)
    try:
        me = client.v1.accounts.retrieve_current()
    except stripe.AuthenticationError:
        sys.exit(f"Stripe rejected STRIPE_SEED_KEY. Set a sandbox secret key in {ENV_FILE}.")
    acct = me.to_dict()
    name = ((acct.get("settings") or {}).get("dashboard") or {}).get("display_name") or me.id
    currency = acct.get("default_currency") or "usd"
    print(f"Seeding sandbox {name!r} ({me.id}), currency {currency.upper()}")

    seeder = Seeder(client, currency)
    failed = 0
    for scenario in SCENARIOS:
        label = f"{scenario.__name__}: {scenario.__doc__.strip().splitlines()[0]}"
        try:
            scenario(seeder)
            print(f"  ✓ {label}")
        except stripe.StripeError as exc:
            failed += 1
            print(f"  ✗ {label}\n      {type(exc).__name__}: {exc.user_message or exc}")
    print(f"\n{len(SCENARIOS) - failed} of {len(SCENARIOS)} scenarios seeded.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
