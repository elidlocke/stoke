from datetime import UTC, datetime

from app import aggregate
from app.aggregate import apply_reporting_currency, normalize_payment, rank_customers
from app.currency import convert_minor
from app.fetch import _covers
from tests.conftest import (
    make_canceled_subscription,
    make_charge,
    make_failed_pi,
    make_invoice,
    make_pi,
    make_subscription,
)


def norm(pi, invoice=None, account="acct_a"):
    return normalize_payment(pi, invoice, account)


def usd(payments):
    return apply_reporting_currency(payments, "usd", {})


def test_email_fallback_order():
    charge = make_charge(receipt_email="receipt@x.com")
    charge["billing_details"]["email"] = "billing@x.com"
    pi = make_pi(latest_charge=charge)
    invoice = make_invoice("pi_1", customer_email="snapshot@x.com")
    assert aggregate.resolve_email(pi, invoice) == "ada@example.com"

    pi["customer"] = {"id": "cus_1", "deleted": True}  # deleted customer: no email
    assert aggregate.resolve_email(pi, invoice) == "snapshot@x.com"
    assert aggregate.resolve_email(pi, None) == "billing@x.com"

    charge["billing_details"]["email"] = None
    assert aggregate.resolve_email(pi, None) == "receipt@x.com"

    charge["receipt_email"] = "  "
    assert aggregate.resolve_email(pi, None) is None


def test_retries_collapse_into_one_failed_payment():
    p = norm(make_failed_pi(), make_invoice("pi_1", billing_reason="manual", attempt_count=4))
    assert (p.status, p.attempts, p.failure_message) == ("failed", 4, "Your card was declined.")
    assert not p.countable
    assert (p.settled_gross, p.amount_refunded) == (None, 0)


def test_never_attempted_payment_is_skipped():
    assert norm(make_pi(status="requires_payment_method", latest_charge=None)) is None
    assert norm(make_pi(status="canceled", latest_charge=None)) is None


def test_status_mapping():
    assert norm(make_pi(status="processing")).status == "pending"
    assert norm(make_failed_pi(status="canceled")).status == "canceled"


def test_invoice_context():
    p = norm(make_pi(), make_invoice("pi_1", lines={"data": [{"description": "Monthly"}, {"description": "Tip"}]}))
    assert (p.billing_reason, p.description) == ("subscription_create", "Monthly + 1 more")
    assert norm(make_pi()).description == "Pro plan"  # no invoice: PaymentIntent description


def test_invoices_by_payment_intent():
    inv = make_invoice("pi_9")
    draft = make_invoice("x", payments={"data": []})
    assert aggregate.invoices_by_payment_intent([inv, draft]) == {"pi_9": inv}


def test_refund_netting_in_settlement_currency():
    # Customer paid EUR 100.00; Stripe settled USD 110.00. EUR 25.00 refunded.
    charge = make_charge(
        currency="eur", amount=10000, amount_captured=10000, amount_refunded=2500,
        balance_transaction={"amount": 11000, "currency": "usd"},
        refunds={"data": [
            {"created": 1_760_000_000, "amount": 2500, "status": "succeeded"},
            {"created": 1_760_000_100, "amount": 999, "status": "failed"},
        ]},
    )
    p = norm(make_pi(currency="eur", amount=10000, latest_charge=charge))
    assert (p.settled_currency, p.settled_gross, p.settled_net) == ("usd", 11000, 8250)
    assert p.refunds == (aggregate.Refund(created=1_760_000_000, amount=2500),)


def test_unsettled_payment_uses_presentment_amount():
    p = norm(make_pi(latest_charge=make_charge(balance_transaction=None, amount_refunded=1000)))
    assert (p.settled_currency, p.settled_gross, p.settled_net) == ("usd", 5000, 4000)


def test_convert_minor_handles_zero_decimal():
    assert convert_minor(1000, "jpy", "usd", 0.0067) == 670  # ¥1000 -> $6.70
    assert convert_minor(670, "usd", "jpy", 150) == 1005  # $6.70 -> ¥1005
    assert convert_minor(1000, "kwd", "usd", 3.25) == 325  # 1.000 KWD -> $3.25


def test_mismatched_settlement_currency_converted_with_fx():
    p = norm(make_pi(latest_charge=make_charge(balance_transaction={"amount": 4000, "currency": "gbp"})))
    day = aggregate.rate_date(p.created)
    assert aggregate.needed_rates([p], "usd") == {(day, "gbp")}

    [out] = apply_reporting_currency([p], "usd", {(day, "gbp"): 1.25})
    assert (out.gross_reporting, out.net_reporting) == (5000, 5000)

    [missing] = apply_reporting_currency([p], "usd", {})
    assert missing.net_reporting is None
    assert aggregate.unconverted_count([missing]) == 1
    assert rank_customers([missing], None) == []


def test_ranking_merges_email_case_across_accounts_and_ignores_failures():
    other = make_charge(balance_transaction={"amount": 7000, "currency": "usd"})
    payments = usd([
        norm(make_pi(id="pi_a")),
        norm(make_pi(id="pi_b", created=1_760_000_000, customer={"email": "ADA@example.com "},
                     latest_charge=make_charge(balance_transaction={"amount": 3000, "currency": "usd"})), None, "acct_b"),
        norm(make_pi(id="pi_c", customer={"email": "bob@x.com"}, latest_charge=other)),
        norm(make_failed_pi(id="pi_d")),
        norm(make_pi(id="pi_e", customer=None)),  # no email anywhere: ignored
    ])
    ranked = rank_customers(payments, None)
    assert [(r.email, r.net_total, r.payment_count) for r in ranked] == [
        ("ada@example.com", 8000, 2),
        ("bob@x.com", 7000, 1),
    ]
    assert ranked[0].accounts == {"acct_a", "acct_b"}
    assert ranked[0].last_seen == 1_760_000_000


def test_ranking_respects_period():
    payments = usd([norm(make_pi(id="old", created=1_000)), norm(make_pi(id="new", created=2_000))])
    [r] = rank_customers(payments, since=1_500)
    assert r.payment_count == 1


def test_period_start_calendar_months():
    now = datetime(2026, 3, 31, 12, tzinfo=UTC)
    assert aggregate.period_start("1m", now) == int(datetime(2026, 2, 28, 12, tzinfo=UTC).timestamp())
    assert aggregate.period_start("12m", now) == int(datetime(2025, 3, 31, 12, tzinfo=UTC).timestamp())
    assert aggregate.period_start("6m", datetime(2026, 1, 15, tzinfo=UTC)) == int(
        datetime(2025, 7, 15, tzinfo=UTC).timestamp()
    )
    assert aggregate.period_start("all", now) is None


def test_summary_and_timeline_tell_the_story():
    refunded = make_charge(amount_refunded=1000, refunds={"data": [{"created": 350, "amount": 1000, "status": "succeeded"}]})
    payments = usd(aggregate.customer_payments([
        norm(make_pi(id="pi_renew", created=300, latest_charge=refunded),
             make_invoice("pi_renew", billing_reason="subscription_cycle", attempt_count=3)),
        norm(make_pi(id="pi_start", created=100), make_invoice("pi_start")),
        norm(make_failed_pi(id="pi_fail", created=200), make_invoice("pi_fail", billing_reason="manual", attempt_count=4)),
        norm(make_pi(id="pi_other", customer={"email": "other@x.com"})),
    ], "ada@example.com"))

    assert aggregate.customer_summary(payments) == {
        "net": 9000, "gross": 10000, "refunded": 1000, "payments": 2, "failed_payments": 1,
        "first_paid": 100, "last_paid": 300, "current_plan": "1 × Monthly (at $8.00 / month)",
    }
    events = aggregate.timeline(payments)
    assert [(e.kind, e.date, e.attempts) for e in events] == [
        ("subscribed", 100, 1),
        ("payment_failed", 200, 4),
        ("renewed", 300, 3),  # paid after 3 attempts
        ("refunded", 350, 0),
    ]
    assert events[1].failure_message == "Your card was declined."
    assert (events[3].amount, events[3].amount_reporting) == (1000, None)
    assert events[2].amount_reporting == 5000  # before the refund


def test_long_description_truncated():
    p = norm(make_pi(description="x" * 500))
    assert len(p.description) == aggregate.DESCRIPTION_MAX


def test_cache_window_coverage():
    assert _covers(None, 100)  # all-time covers anything
    assert _covers(50, 100)
    assert not _covers(100, 50)
    assert not _covers(100, None)


def ts(*args) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


def sub(account="acct_a", **overrides):
    return aggregate.normalize_subscription(make_subscription(**overrides), account)


def canceled(account="acct_a", **overrides):
    return aggregate.normalize_subscription(make_canceled_subscription(**overrides), account)


def test_window_start():
    now = datetime(2026, 3, 31, 12, tzinfo=UTC)
    assert aggregate.window_start("7d", now) == ts(2026, 3, 24, 12)
    assert aggregate.window_start("1m", now) == ts(2026, 2, 28, 12)
    assert aggregate.window_start("3m", now) == ts(2025, 12, 31, 12)


def test_normalize_subscription():
    s = canceled()
    assert (s.email, s.status, s.plan, s.started) == ("ada@example.com", "canceled", "1 × Monthly (at $8.00 / month)", 1_750_000_000)
    assert (s.canceled_at, s.ends_at, s.cancel_reason, s.cancel_feedback) == (
        1_760_000_000, 1_760_000_000, "cancellation_requested", "too_expensive",
    )
    assert not s.current

    # Deleted customer: the email comes from the latest invoice.
    assert sub(customer={"id": "cus_1", "deleted": True}).email == "ada@example.com"
    # Scheduled to cancel at period end: still active, ends at cancel_at.
    scheduled = sub(canceled_at=1_760_000_000, cancel_at=1_762_000_000, cancel_at_period_end=True)
    assert (scheduled.current, scheduled.ends_at) == (True, 1_762_000_000)


def test_plan_skips_proration_lines():
    unused = {
        "description": "Unused time on Monthly after 30 Sep 2026", "amount": -800,
        "parent": {"subscription_item_details": {"proration": True}},
    }
    remaining = {"description": "Remaining time on Annual subscription after 30 Sep 2026", "amount": 8000, "proration": True}
    regular = {"description": "1 × Annual"}
    assert sub(latest_invoice=make_invoice("x", lines={"data": [unused, remaining, regular]})).plan == "1 × Annual"

    # A plan change's invoice: only prorations. The price's nickname wins, else the charged line's plan.
    plan_change = make_invoice("x", lines={"data": [unused, remaining]})
    items = {"data": [{"price": {"nickname": "Annual"}}]}
    assert sub(latest_invoice=plan_change, items=items).plan == "Annual"
    assert sub(latest_invoice=plan_change).plan == "Annual subscription"
    other_wording = {**remaining, "description": "Temps restant sur Annuel"}
    assert sub(latest_invoice=make_invoice("x", lines={"data": [unused, other_wording]})).plan == "Temps restant sur Annuel"
    assert sub(latest_invoice=None, items=items).plan == "Annual"
    assert sub(latest_invoice=None).plan is None


def test_cancellations_most_recent_first_and_flag_resubscribed():
    subs = [
        canceled(id="sub_old", canceled_at=1_000),
        canceled(id="sub_new", canceled_at=3_000, customer={"email": "bob@x.com"}),
        canceled(id="sub_mid", canceled_at=2_000, customer={"email": "cy@x.com"}),
        sub(id="sub_cy_again", customer={"email": "cy@x.com"}),  # resubscribed
        sub(id="sub_bob_scheduled", customer={"email": "bob@x.com"}, canceled_at=3_500, cancel_at=9_000),
        canceled(id="sub_never", status="incomplete_expired", canceled_at=2_500),  # never started
        sub(id="sub_active"),
    ]
    out = aggregate.cancellations(subs, since=1_500)
    assert [(c.sub.id, c.resubscribed) for c in out] == [
        ("sub_bob_scheduled", False),  # still active, but canceling: doesn't count as resubscribed
        ("sub_new", False),
        ("sub_mid", True),
    ]


def test_new_subscriptions_flag_returning():
    subs = [
        canceled(id="sub_first", start_date=1_000, canceled_at=1_500, ended_at=1_500),
        sub(id="sub_back", start_date=5_000),
        sub(id="sub_trial", status="trialing", start_date=4_000, customer={"email": "bob@x.com"}),
        sub(id="sub_failed", status="incomplete", start_date=6_000, customer={"email": "cy@x.com"}),
        # Two subscriptions at once (e.g. two customer records): neither is returning.
        sub(id="sub_dee_1", start_date=3_000, customer={"email": "dee@x.com"}),
        sub(id="sub_dee_2", start_date=3_005, customer={"email": "dee@x.com"}),
    ]
    out = aggregate.new_subscriptions(subs, since=2_000)
    assert [(n.sub.id, n.returning) for n in out] == [
        ("sub_back", True), ("sub_trial", False), ("sub_dee_2", False), ("sub_dee_1", False),
    ]


def test_latest_anniversary():
    first = ts(2023, 6, 15)
    assert aggregate.latest_anniversary(first, ts(2024, 6, 14)) is None
    assert aggregate.latest_anniversary(first, ts(2024, 6, 15)) == (1, ts(2024, 6, 15))
    assert aggregate.latest_anniversary(first, ts(2026, 6, 1)) == (2, ts(2025, 6, 15))
    # Leap day: the anniversary falls on 28 February in non-leap years.
    assert aggregate.latest_anniversary(ts(2024, 2, 29), ts(2025, 3, 1)) == (1, ts(2025, 2, 28))
    assert aggregate.latest_anniversary(ts(2024, 2, 29), ts(2028, 3, 1)) == (4, ts(2028, 2, 29))


def test_anniversaries_in_window():
    now = ts(2026, 10, 4)
    payments = usd([
        norm(make_pi(id="pi_a1", created=ts(2024, 9, 20))),  # 2nd anniversary on 20 Sep 2026
        norm(make_pi(id="pi_a2", created=ts(2026, 1, 1))),
        norm(make_pi(id="pi_b", created=ts(2025, 9, 30), customer={"email": "bob@x.com"})),  # 1st, 30 Sep
        norm(make_pi(id="pi_c", created=ts(2025, 6, 1), customer={"email": "cy@x.com"})),  # anniversary not in window
        norm(make_pi(id="pi_d", created=ts(2026, 1, 1), customer={"email": "dee@x.com"})),  # not a year yet
    ])
    ranks = rank_customers(payments, None)
    subs = [sub(), canceled(customer={"email": "bob@x.com"})]

    out = aggregate.anniversaries(ranks, subs, since=ts(2026, 9, 4), now=now)
    assert [(a.customer.email, a.years, a.date, a.subscribed) for a in out] == [
        ("bob@x.com", 1, ts(2025, 9, 30) + 365 * 86400, False),
        ("ada@example.com", 2, ts(2026, 9, 20), True),
    ]
    assert out[1].customer.first_seen == ts(2024, 9, 20)
