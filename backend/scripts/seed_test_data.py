"""Seed a Stripe sandbox with customers that look like a Substack creator's account.

Usage (from backend/):
    uv run python scripts/seed_test_data.py                 # every scenario
    uv run python scripts/seed_test_data.py --list          # list scenario names
    uv run python scripts/seed_test_data.py dispute_lost …  # only these scenarios

Uses STRIPE_SEED_KEY from the repo-root .env. It must be a sandbox (test mode) secret key;
the script refuses live keys.

Each scenario below is one customer, covering what we've seen in a real Substack account plus
cases a small account may not have hit yet. Everything is created "now": Stripe can't backdate
payments, so there are no renewals ("Renewed" events) and no anniversaries in seeded data.

Each run creates new customers; running it twice doubles the data.

Disputes use Stripe's test cards, which open a dispute a few seconds after a successful charge.
In test mode the outcome is chosen by the evidence submitted: "winning_evidence" or
"losing_evidence". https://docs.stripe.com/testing#disputes
"""

import os
import sys
import time
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
# Charges succeed, then the cardholder disputes them: as fraud, as "product not received", or as
# an inquiry (a question from the bank that doesn't withdraw funds unless it escalates).
DISPUTE_FRAUD_CARD = "pm_card_createDispute"
DISPUTE_NOT_RECEIVED_CARD = "pm_card_createDisputeProductNotReceived"
DISPUTE_INQUIRY_CARD = "pm_card_createDisputeInquiry"
# Charges succeed, but refunds on them fail asynchronously.
REFUND_FAILS_CARD = "pm_card_refundFail"

DISPUTE_WAIT_SECONDS = 60


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

    def subscription_payment_intent(self, sub) -> str:
        return self.invoice_payment_intent(sub.latest_invoice)

    def wait_for_dispute(self, payment_intent_id):
        """Stripe opens test-card disputes asynchronously, a few seconds after the charge."""
        deadline = time.monotonic() + DISPUTE_WAIT_SECONDS
        while time.monotonic() < deadline:
            disputes = self.c.v1.disputes.list({"payment_intent": payment_intent_id, "limit": 1}).data
            if disputes:
                return disputes[0]
            time.sleep(2)
        raise TimeoutError(f"no dispute opened within {DISPUTE_WAIT_SECONDS}s")

    def submit_evidence(self, dispute_id, outcome):
        # Test mode resolves the dispute from this magic value, usually within a minute.
        self.c.v1.disputes.update(dispute_id, {
            "evidence": {"uncategorized_text": f"{outcome}_evidence"}, "submit": True,
        })

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

    def coaching_client(self):
        """New customer whose first purchase was a one-off paid coaching session, not a subscription."""
        self.one_off_invoice(self.customer("coaching@example.com"), "1:1 coaching session (60 min)", 15000)

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

    # ---- refunds ----

    def refunded_twice(self):
        """Founding member refunded twice: 20.00 as a goodwill credit, later 30.00 more."""
        pi = self.subscription_payment_intent(self.subscribe(self.customer("refunded-twice@example.com"), "founding"))
        self.c.v1.refunds.create({"payment_intent": pi, "amount": 2000, "reason": "requested_by_customer"})
        self.c.v1.refunds.create({"payment_intent": pi, "amount": 3000, "reason": "requested_by_customer"})

    def refunded_tip(self):
        """Monthly subscriber whose one-off tip was refunded (a duplicate), but not the subscription."""
        cus = self.customer("refunded-tip@example.com")
        self.subscribe(cus, "monthly")
        tip = self.one_off_invoice(cus, "Tip", 1500)
        self.c.v1.refunds.create({"payment_intent": self.invoice_payment_intent(tip.id), "reason": "duplicate"})

    def refund_failed(self):
        """Annual subscriber whose refund failed (e.g. the card was closed): the money stays with the creator."""
        sub = self.subscribe(self.customer("refund-failed@example.com", card=REFUND_FAILS_CARD), "annual")
        self.c.v1.refunds.create({"payment_intent": self.subscription_payment_intent(sub)})

    def foreign_refund(self):
        """Pays in a foreign currency and was half refunded, so the refund is converted too."""
        sub = self.subscribe(self.customer(f"{self.foreign}-refunded@example.com"), "monthly_foreign")
        self.c.v1.refunds.create({"payment_intent": self.subscription_payment_intent(sub), "amount": 300})

    # ---- disputes ----

    def dispute_lost(self):
        """Monthly subscriber disputed the charge as fraud; the creator accepted it (lost): amount and fee withdrawn."""
        sub = self.subscribe(self.customer("dispute-lost@example.com", card=DISPUTE_FRAUD_CARD), "monthly")
        self.c.v1.disputes.close(self.wait_for_dispute(self.subscription_payment_intent(sub)).id)

    def dispute_lost_with_evidence(self):
        """Annual subscriber disputed as "product not received"; the evidence lost."""
        sub = self.subscribe(self.customer("dispute-lost-evidence@example.com", card=DISPUTE_NOT_RECEIVED_CARD), "annual")
        self.submit_evidence(self.wait_for_dispute(self.subscription_payment_intent(sub)).id, "losing")

    def dispute_won(self):
        """Founding member disputed as fraud; the evidence won, so the funds come back (the fee may not)."""
        sub = self.subscribe(self.customer("dispute-won@example.com", card=DISPUTE_FRAUD_CARD), "founding")
        self.submit_evidence(self.wait_for_dispute(self.subscription_payment_intent(sub)).id, "winning")

    def dispute_open(self):
        """Annual subscriber with a fraud dispute still awaiting a response: funds withdrawn, outcome unknown."""
        sub = self.subscribe(self.customer("dispute-open@example.com", card=DISPUTE_FRAUD_CARD), "annual")
        self.wait_for_dispute(self.subscription_payment_intent(sub))

    def dispute_inquiry(self):
        """Monthly subscriber's bank sent an inquiry: a warning, no funds withdrawn yet."""
        sub = self.subscribe(self.customer("dispute-inquiry@example.com", card=DISPUTE_INQUIRY_CARD), "monthly")
        self.wait_for_dispute(self.subscription_payment_intent(sub))

    def dispute_one_off(self):
        """One-off purchase without an invoice, disputed as "product not received" and still open."""
        # (A partly refunded charge that's later disputed can't be staged: test cards open the dispute
        # as soon as the charge succeeds, and Stripe refuses refunds on a disputed charge.)
        cus = self.customer("dispute-one-off@example.com", card=DISPUTE_NOT_RECEIVED_CARD)
        pi = self.payment_intent(cus, 6000, "Workshop ticket", DISPUTE_NOT_RECEIVED_CARD)
        self.wait_for_dispute(pi.id)


SCENARIOS: list[Callable[[Seeder], None]] = [
    Seeder.subscriber, Seeder.annual, Seeder.founding, Seeder.upgraded,
    Seeder.recovered, Seeder.churned, Seeder.refunded, Seeder.partially_refunded,
    Seeder.tipper, Seeder.foreign_reader, Seeder.deleted, Seeder.duplicate_email, Seeder.no_invoice,
    Seeder.cancelled, Seeder.cancelling, Seeder.won_back, Seeder.coaching_client,
    Seeder.refunded_twice, Seeder.refunded_tip, Seeder.refund_failed, Seeder.foreign_refund,
    Seeder.dispute_lost, Seeder.dispute_lost_with_evidence, Seeder.dispute_won, Seeder.dispute_open,
    Seeder.dispute_inquiry, Seeder.dispute_one_off,
]


def _summary(scenario: Callable[[Seeder], None]) -> str:
    return f"{scenario.__name__}: {scenario.__doc__.strip().splitlines()[0]}"


def selected_scenarios(names: list[str]) -> list[Callable[[Seeder], None]]:
    by_name = {s.__name__: s for s in SCENARIOS}
    if unknown := [n for n in names if n not in by_name]:
        sys.exit(f"Unknown scenario(s): {', '.join(unknown)}. Run with --list to see them.")
    return [by_name[n] for n in names] or SCENARIOS


def main():
    args = sys.argv[1:]
    if "--list" in args:
        print("\n".join(_summary(s) for s in SCENARIOS))
        return
    scenarios = selected_scenarios(args)

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
    for scenario in scenarios:
        label = _summary(scenario)
        try:
            scenario(seeder)
            print(f"  ✓ {label}")
        except (stripe.StripeError, TimeoutError) as exc:
            failed += 1
            message = exc.user_message or exc if isinstance(exc, stripe.StripeError) else exc
            print(f"  ✗ {label}\n      {type(exc).__name__}: {message}")
    print(f"\n{len(scenarios) - failed} of {len(scenarios)} scenarios seeded.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
