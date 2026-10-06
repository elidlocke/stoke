from datetime import UTC, datetime

from app import aggregate
from app.aggregate import apply_reporting_currency, normalize_payment, rank_customers
from app.currency import convert_minor
from app.fetch import _covers
from tests.conftest import (
    make_canceled_subscription,
    make_charge,
    make_dispute,
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
    assert out.take_home_reporting == 5000  # this charge's balance transaction has no fees

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
    assert [(r.email, r.take_home, r.payment_count) for r in ranked] == [
        ("ada@example.com", 7825, 2),  # $50 less $1.75 in fees, plus $30
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
        # Two $50 payments, $10 refunded, $1.75 in fees on each (not returned by the refund).
        "take_home": 8650, "gross": 10000, "refunded": 1000, "fees": 350, "disputed": 0, "open_disputes": 0,
        "payments": 2, "failed_payments": 1,
        "first_paid": 100, "last_paid": 300, "current_plan": "Monthly",
    }
    events = aggregate.timeline(payments)
    assert [(e.kind, e.date, e.attempts) for e in events] == [
        ("subscribed", 100, 1),
        ("payment_failed", 200, 4),
        ("renewed", 300, 3),  # paid after 3 attempts
        ("refunded", 350, 0),
    ]
    assert events[1].failure_message == "Your card was declined."
    assert (events[3].amount, events[3].amount_reporting) == (1000, 1000)
    assert (events[3].take_home_before, events[3].take_home, events[3].fees_not_returned) == (4825, 3825, 175)
    assert events[2].amount_reporting == 5000  # before the refund
    assert [(f.description, f.amount) for f in events[2].fees] == [
        ("Substack application fee", 50), ("Stripe processing fees", 125),
    ]
    assert events[2].take_home == 4825
    assert (events[1].fees, events[1].take_home) == ((), None)  # failed: nothing deducted


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
    assert (s.email, s.status, s.plan, s.started) == ("ada@example.com", "canceled", "Monthly", 1_750_000_000)
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
        canceled(id="sub_dee_second", canceled_at=2_200, customer={"email": "dee@x.com"}),
        sub(id="sub_dee_first", start_date=1_000, customer={"email": "dee@x.com"}),  # running alongside
        canceled(id="sub_never", status="incomplete_expired", canceled_at=2_500),  # never started
        sub(id="sub_active"),
    ]
    out = aggregate.cancellations(subs, since=1_500)
    assert [(c.sub.id, c.current.id if c.current else None, c.resubscribed) for c in out] == [
        ("sub_bob_scheduled", None, False),  # still active, but canceling: not a current subscription
        ("sub_new", None, False),
        ("sub_dee_second", "sub_dee_first", False),  # still subscribed, but didn't come back
        ("sub_mid", "sub_cy_again", True),
    ]


def test_new_customers():
    def paid(id, created, email, reason=None, description="Coaching session"):
        pi = make_pi(id=id, created=created, customer={"email": email}, description=description)
        return norm(pi, make_invoice(id, billing_reason=reason) if reason else None)

    payments = usd([
        paid("pi_coach", 5_000, "coach@x.com"),  # first ever: a one-off coaching session
        paid("pi_coach_sub", 6_010, "coach@x.com", "subscription_create"),  # ...then subscribed
        paid("pi_sub", 4_010, "sub@x.com", "subscription_create"),  # subscribed; first payment seconds later
        paid("pi_old", 1_000, "old@x.com"),  # bought before the window...
        paid("pi_old_sub", 5_010, "old@x.com", "subscription_create"),  # ...so subscribing now isn't new
        norm(make_failed_pi(id="pi_fail", created=5_000, customer={"email": "failed@x.com"})),  # never paid
    ])
    subs = [
        sub(id="sub_coach", start_date=6_000, customer={"email": "coach@x.com"}),
        sub(id="sub_sub", start_date=4_000, customer={"email": "sub@x.com"}),
        sub(id="sub_old", start_date=5_000, customer={"email": "old@x.com"}),
        sub(id="sub_trial", status="trialing", start_date=7_000, customer={"email": "trial@x.com"}),  # nothing paid
        sub(id="sub_failed", status="incomplete_expired", start_date=5_000, customer={"email": "failed@x.com"}),
        canceled(id="sub_back_1", start_date=500, customer={"email": "back@x.com"}),  # returning, not new
        sub(id="sub_back_2", start_date=5_500, customer={"email": "back@x.com"}),
    ]

    out = aggregate.new_customers(payments, subs, since=2_000)
    assert [(n.email, n.first_seen, n.started_with, n.description, n.subscription_status) for n in out] == [
        ("trial@x.com", 7_000, "subscription", "Monthly", "trialing"),
        ("coach@x.com", 5_000, "purchase", "Coaching session", "active"),
        ("sub@x.com", 4_000, "subscription", "Monthly", "active"),
    ]
    assert [n.take_home for n in out] == [0, 2 * 4825, 4825]

    # Without Subscriptions access, paying customers are still found from their payments.
    assert [(n.email, n.started_with) for n in aggregate.new_customers(payments, [], since=2_000)] == [
        ("coach@x.com", "purchase"), ("sub@x.com", "subscription"),
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


def test_fees_converted_and_netted_from_take_home():
    # Paid GBP 40.00 (settled as such); GBP 10.00 refunded; fees GBP 4.00 + GBP 1.50.
    bt = {"amount": 4000, "currency": "gbp", "fee_details": [
        {"type": "application_fee", "amount": 400, "description": "Substack application fee"},
        {"type": "stripe_fee", "amount": 150, "description": "Stripe processing fees"},
    ]}
    p = norm(make_pi(latest_charge=make_charge(
        currency="gbp", amount=4000, amount_captured=4000, amount_refunded=1000, balance_transaction=bt,
    )))
    [out] = apply_reporting_currency([p], "usd", {(aggregate.rate_date(p.created), "gbp"): 1.25})
    assert [f.amount for f in out.fees_reporting] == [500, 188]
    assert (out.gross_reporting, out.net_reporting, out.take_home_reporting) == (5000, 3750, 3750 - 688)


def test_unsettled_payment_has_no_known_fees():
    p = usd([norm(make_pi(latest_charge=make_charge(balance_transaction=None)))])[0]
    assert (p.fees_reporting, p.take_home_reporting) == ((), 5000)


def test_plan_label():
    label = aggregate.plan_label
    assert label("1 × $8 a month (at $12.00 / month)") == "Monthly plan"  # Substack's price-named product
    assert label("1 × $80 a year (at $120.00 / year)") == "Yearly plan"
    assert label("1 × Founding member (at $150.00 / year)") == "Founding member · yearly"
    assert label("1 × Monthly subscription (at $8.00 / month)") == "Monthly subscription"
    assert label("1 × Annual subscription (at $80.00 / year)") == "Annual subscription"
    assert label("2 × Seat (at $5.00 / month)") == "2 × Seat · monthly"
    assert label("1 × $30 a quarter (at $30.00 / every 3 months)") == "Plan billed every 3 months"
    assert label("1 × Pro (at €9.00 / every 3 months)") == "Pro · every 3 months"
    assert label("Tip") == "Tip"  # not a plan line
    assert label("Unused time on Monthly after 30 Sep 2026") == "Unused time on Monthly after 30 Sep 2026"


def disputed(status="lost", returned=False, **charge):
    """A $50 payment ($1.75 fees) disputed for its full amount, with a $15 dispute fee."""
    pi = make_pi(latest_charge=make_charge(dispute=make_dispute(status, returned), **charge))
    return usd([norm(pi)])[0]


def test_disputes_count_as_lost_until_won():
    lost, open_, won, inquiry = disputed("lost"), disputed("needs_response"), disputed("won", returned=True), disputed("warning_needs_response")
    assert lost.take_home_reporting == 5000 - 175 - 5000 - 1500  # the amount and the fee are gone
    assert open_.take_home_reporting == lost.take_home_reporting  # like Stripe's balance: lost until won
    assert won.take_home_reporting == 5000 - 175 - 1500  # funds back, but not the dispute fee
    assert inquiry.take_home_reporting == 5000 - 175  # nothing withdrawn yet

    summary = aggregate.customer_summary([lost, open_, inquiry])
    assert (summary["disputed"], summary["open_disputes"]) == (2 * 6500, 2)
    assert summary["take_home"] == 3 * 4825 - 2 * 6500
    assert rank_customers([won], None)[0].take_home == 3325


def test_dispute_timeline():
    events = aggregate.timeline([disputed("won", returned=True)])
    assert [(e.kind, e.amount_reporting, [f.amount for f in e.fees], e.take_home_before, e.take_home) for e in events] == [
        ("purchased", 5000, [50, 125], None, 4825),
        ("disputed", 5000, [1500], 4825, -1675),
        ("dispute_won", 5000, [], -1675, 3325),
    ]
    assert (events[1].dispute_status, events[1].dispute_reason, events[1].respond_by) == ("won", "fraudulent", 1_761_500_000)

    [_, inquiry] = aggregate.timeline([disputed("warning_needs_response")])
    assert (inquiry.kind, inquiry.amount, inquiry.take_home_before, inquiry.take_home) == ("dispute_inquiry", 5000, 4825, 4825)


def test_refund_events_show_what_is_not_kept():
    charge = make_charge(amount_refunded=3000, refunds={"data": [
        {"created": 1_750_000_400, "amount": 1000, "status": "succeeded"},
        {"created": 1_750_000_300, "amount": 2000, "status": "succeeded"},
        {"created": 1_750_000_500, "amount": 999, "status": "failed"},  # ignored, as Stripe's amount_refunded does
        {"created": 1_750_000_600, "amount": 1, "status": "pending"},
    ]})
    charge["amount_refunded"] = 3001
    [p] = usd([norm(make_pi(latest_charge=charge))])
    events = aggregate.timeline([p])
    assert [(e.kind, e.amount_reporting, e.take_home_before, e.take_home, e.fees_not_returned, e.pending) for e in events] == [
        ("purchased", 5000, None, 4825, None, False),
        ("refunded", 2000, 4825, 2825, 175, False),
        ("refunded", 1000, 2825, 1825, 175, False),
        ("refunded", 1, 1825, 1824, 175, True),
    ]
    assert events[-1].take_home == p.take_home_reporting  # the timeline ends where the totals do


def test_refund_shares_add_up_after_conversion():
    # A third refunded, converted at an awkward rate: the shares still sum to what totals subtract.
    charge = make_charge(amount=1000, amount_captured=1000, amount_refunded=1000, balance_transaction={
        "amount": 1000, "currency": "gbp", "fee_details": [],
    }, refunds={"data": [{"created": 1_750_000_000 + t, "amount": a, "status": "succeeded"} for t, a in [(1, 333), (2, 333), (3, 334)]]})
    p = norm(make_pi(amount=1000, latest_charge=charge))
    [out] = apply_reporting_currency([p], "usd", {(aggregate.rate_date(p.created), "gbp"): 1.2345})
    assert sum(aggregate.refund_shares(out)) == out.gross_reporting - out.net_reporting
    assert aggregate.timeline([out])[-1].take_home == out.take_home_reporting == 0


def test_at_risk():
    now = 10_000_000
    day = 86400
    due = make_invoice("x", created=now - day, amount_due=800, currency="usd", attempt_count=2, next_payment_attempt=now + 3 * day)
    subs = [
        sub(id="sub_due", status="past_due", latest_invoice=due),
        sub(id="sub_unpaid", status="unpaid", customer={"email": "un@x.com"},
            latest_invoice={**due, "next_payment_attempt": None}),
        sub(id="sub_unpaid_old", status="unpaid", customer={"email": "old@x.com"},
            latest_invoice={**due, "created": now - 200 * day}),  # long gone
        sub(id="sub_ending", customer={"email": "end@x.com"}, canceled_at=now - day, cancel_at=now + 5 * day,
            cancellation_details={"reason": "cancellation_requested", "feedback": "too_expensive"}),
        # Canceling a second plan while keeping another: staying.
        sub(id="sub_second", customer={"email": "two@x.com"}, canceled_at=now - day, cancel_at=now + day),
        sub(id="sub_main", customer={"email": "two@x.com"}),
        canceled(id="sub_lapsed", customer={"email": "lap@x.com"}, canceled_at=now - 2 * day,
                 cancellation_details={"reason": "payment_failed"}),
        canceled(id="sub_lapsed_back", customer={"email": "back@x.com"}, canceled_at=now - 2 * day,
                 cancellation_details={"reason": "payment_failed"}),
        sub(id="sub_came_back", customer={"email": "back@x.com"}),
        canceled(id="sub_lapsed_old", customer={"email": "lo@x.com"}, canceled_at=now - 60 * day,
                 cancellation_details={"reason": "payment_failed"}),
        canceled(id="sub_chose_to_leave", customer={"email": "bye@x.com"}, canceled_at=now - day),
    ]
    failed = norm(make_failed_pi(created=now - day))
    open_dispute = norm(make_pi(id="pi_d", customer={"email": "dp@x.com"}, latest_charge=make_charge(
        dispute=make_dispute("needs_response", evidence_details={"due_by": now + day}))))
    answered = norm(make_pi(id="pi_r", customer={"email": "dr@x.com"}, latest_charge=make_charge(
        dispute=make_dispute("under_review"))))  # already responded: nothing to do

    out = aggregate.at_risk([failed, open_dispute, answered], subs, now)
    assert [(r.kind, r.email, r.deadline) for r in out] == [
        ("dispute", "dp@x.com", now + day),
        ("payment_failing", "ada@example.com", now + 3 * day),
        ("canceling", "end@x.com", now + 5 * day),
        ("retries_exhausted", "un@x.com", None),  # no deadline: most recent first
        ("lapsed", "lap@x.com", None),
    ]
    failing = out[1]
    assert (failing.amount, failing.currency, failing.attempts, failing.failure_message) == (
        800, "usd", 2, "Your card was declined.",
    )
    assert out[2].feedback == "too_expensive"
    assert (out[0].amount, out[0].dispute_reason) == (5000, "fraudulent")


def test_month_starts():
    assert aggregate.month_starts(3, datetime(2026, 1, 15, tzinfo=UTC)) == [ts(2025, 11, 1), ts(2025, 12, 1), ts(2026, 1, 1)]


def test_churn_dates():
    subs = [
        canceled(id="sub_left", customer={"email": "left@x.com"}, ended_at=ts(2026, 3, 5)),
        # Changed plan: the old one ended while the new one was already running.
        canceled(id="sub_old_plan", customer={"email": "switch@x.com"}, ended_at=ts(2026, 3, 5)),
        sub(id="sub_new_plan", customer={"email": "switch@x.com"}, start_date=ts(2026, 3, 5)),
        # Left, then came back later: still churned when they left.
        canceled(id="sub_first", customer={"email": "back@x.com"}, ended_at=ts(2026, 3, 5)),
        sub(id="sub_again", customer={"email": "back@x.com"}, start_date=ts(2026, 5, 1)),
        # Two plans ending at different times: churned only when the last one ends.
        canceled(id="sub_a", customer={"email": "two@x.com"}, start_date=ts(2026, 1, 1), ended_at=ts(2026, 3, 1)),
        canceled(id="sub_b", customer={"email": "two@x.com"}, start_date=ts(2026, 1, 1), ended_at=ts(2026, 4, 1)),
        canceled(id="sub_never", customer={"email": "never@x.com"}, status="incomplete_expired"),
        sub(id="sub_scheduled", customer={"email": "soon@x.com"}, canceled_at=ts(2026, 3, 1), cancel_at=ts(2026, 9, 1)),
    ]
    assert sorted(aggregate.churn_dates(subs)) == [
        ("back@x.com", ts(2026, 3, 5)), ("left@x.com", ts(2026, 3, 5)), ("two@x.com", ts(2026, 4, 1)),
    ]


def test_trends():
    now = datetime(2026, 3, 20, tzinfo=UTC)
    paid = [
        norm(make_pi(id="pi_old", created=ts(2025, 6, 1))),  # before the window: ada isn't new in it
        norm(make_pi(id="pi_feb", created=ts(2026, 2, 10))),
        norm(make_pi(id="pi_bo", created=ts(2026, 3, 2), customer={"email": "bo@x.com"})),
        norm(make_failed_pi(id="pi_fail", created=ts(2026, 3, 3))),  # doesn't count
    ]
    subs = [canceled(id="sub_gone", customer={"email": "cy@x.com"}, start_date=ts(2026, 1, 3), ended_at=ts(2026, 3, 9))]
    months = aggregate.trends(usd(paid), subs, now, months=3)
    assert [(m.start, m.partial, m.new_customers, m.churned, m.take_home) for m in months] == [
        (ts(2026, 1, 1), False, 1, 0, 0),  # cy subscribed
        (ts(2026, 2, 1), False, 0, 0, 4825),
        (ts(2026, 3, 1), True, 1, 1, 4825),  # bo is new; cy left
    ]
