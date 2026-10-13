from datetime import UTC, datetime

from app import actions
from app.actions import DAY, RevenueSource
from app.aggregate import Dispute, Payment, Refund, Subscription, normalize_subscription
from tests.conftest import make_subscription

NOW = int(datetime(2026, 10, 13, 12, tzinfo=UTC).timestamp())


def pay(email, days_ago, reason="subscription_cycle", status="succeeded", account="acct_a", take_home=1000, **kw) -> Payment:
    paid = status == "succeeded"
    return Payment(
        id=f"pi_{email}_{days_ago}_{reason}", account_id=account, created=NOW - days_ago * DAY, email=email,
        status=status, description=kw.pop("description", "Monthly plan"), billing_reason=reason, attempts=1,
        failure_message=None, currency="usd", amount=kw.pop("amount", take_home),
        amount_refunded=kw.pop("amount_refunded", 0), refunds=kw.pop("refunds", ()),
        settled_currency="usd" if paid else None, settled_gross=take_home if paid else None,
        settled_net=take_home if paid else None, gross_reporting=take_home if paid else None,
        net_reporting=take_home if paid else None, fees_reporting=() if paid else None,
        dispute_reporting=() if paid else None, take_home_reporting=take_home if paid else None, **kw,
    )


def sub(email, started_days_ago, status="active", account="acct_a", **kw) -> Subscription:
    return Subscription(
        id=f"sub_{email}_{started_days_ago}_{kw.get('price_id', '')}", account_id=account, email=email, status=status,
        plan=kw.pop("plan", "Monthly plan"), started=NOW - started_days_ago * DAY,
        canceled_at=kw.pop("canceled_at", None), ends_at=kw.pop("ends_at", None),
        cancel_reason=kw.pop("cancel_reason", None), cancel_feedback=kw.pop("cancel_feedback", None),
        interval=kw.pop("interval", "month"), interval_count=1, **kw,
    )


def monthly_subscriber(email, months, take_home=1000, **sub_kw):
    """Subscribed `months` months ago and paid every month since."""
    payments = [pay(email, months * 30, "subscription_create", take_home=take_home)]
    payments += [pay(email, (months - i) * 30, take_home=take_home) for i in range(1, months)]
    return payments, sub(email, months * 30, **sub_kw)


def run(payments, subs, sources=(), **kw):
    return {a.action.kind: a for a in actions.audiences(payments, subs, list(sources), NOW, **kw)}


def emails(audience):
    return [c.email for c in audience.candidates]


def test_library_order_and_types():
    src = RevenueSource("l1", "calendly", "Strategy call", "repeat", "acct_b")
    kinds = [(a.action.kind, a.action.type) for a in actions.audiences([], [], [src], NOW)]
    assert kinds == [
        ("welcome", "gratitude"), ("anniversary", "gratitude"), ("welcome-back", "gratitude"), ("vip", "gratitude"),
        ("founding-upgrade", "upgrade"), ("monthly-to-annual", "upgrade"),
        ("cross-sell-l1", "cross_sell"), ("repeat-booking-l1", "cross_sell"),
        ("win-back", "win_back"), ("save", "retention"), ("card-failing", "retention"), ("dispute-check-in", "retention"),
    ]


def test_welcome_is_new_paid_subscribers_only():
    payments = [pay("new@x.com", 5, "subscription_create"), pay("buyer@x.com", 3, "manual")]
    payments += monthly_subscriber("old@x.com", 6)[0]
    subs = [sub("new@x.com", 5), sub("old@x.com", 180), sub("trial@x.com", 2, status="trialing")]
    a = run(payments, subs)["welcome"]
    assert emails(a) == ["new@x.com"]
    assert a.candidates[0].why == "New paid subscriber, 5 days ago"


def test_anniversary_waits_for_the_renewal():
    renewed = [pay("ann@x.com", 375, "subscription_create"), pay("ann@x.com", 10)]
    not_yet = [pay("wait@x.com", 370, "subscription_create"), pay("wait@x.com", 40)]
    a = run(renewed + not_yet, [sub("ann@x.com", 375), sub("wait@x.com", 370)])["anniversary"]
    assert emails(a) == ["ann@x.com"]
    assert a.candidates[0].why.startswith("1 year since their first payment, on ")


def test_welcome_back():
    gone = sub("back@x.com", 400, status="canceled", canceled_at=NOW - 100 * DAY, ends_at=NOW - 90 * DAY)
    again = sub("back@x.com", 20)
    a = run([], [gone, again])["welcome-back"]
    assert emails(a) == ["back@x.com"]
    assert a.candidates[0].why == "Came back 2 weeks ago, after canceling in Jul 2026"


def test_founding_detected_from_the_highest_yearly_price():
    subs = [
        sub("annual@x.com", 400, interval="year", price_id="p_annual", price_amount=8000, price_currency="usd", plan="Yearly plan"),
        sub("founder@x.com", 400, interval="year", price_id="p_founding", price_amount=25000, price_currency="usd", plan="Yearly plan"),
    ]
    assert actions.founding_prices(subs) == {"p_founding"}
    assert actions.is_founding(sub("n@x.com", 1, plan="Founding member · yearly"), set())
    vip = run([], subs)["vip"]
    assert "founder@x.com" in emails(vip)


def test_founding_upgrade_needs_renewals_clean_payments_and_a_founding_plan():
    loyal_p, loyal = monthly_subscriber("loyal@x.com", 4)
    new_p, new = monthly_subscriber("new@x.com", 2)  # one renewal
    flaky_p, flaky = monthly_subscriber("flaky@x.com", 6)
    flaky_p.append(pay("flaky@x.com", 50, status="failed"))
    founder = sub("founder@x.com", 400, plan="Founding member · yearly", interval="year")
    payments, subs = loyal_p + new_p + flaky_p, [loyal, new, flaky, founder]

    a = run(payments, subs)["founding-upgrade"]
    assert emails(a) == ["loyal@x.com"]
    assert a.candidates[0].why == "3 renewals since Jun 2026, no failed payments"

    none = run(payments, [loyal, new, flaky])["founding-upgrade"]
    assert none.candidates == [] and none.unavailable


def test_monthly_to_annual():
    m_p, m = monthly_subscriber("monthly@x.com", 5)
    y_p, y = monthly_subscriber("yearly@x.com", 5, interval="year")
    legacy_p, legacy = monthly_subscriber("legacy@x.com", 5, interval=None, plan="Monthly plan")  # stored before prices
    a = run(m_p + y_p + legacy_p, [m, y, legacy])["monthly-to-annual"]
    assert sorted(emails(a)) == ["legacy@x.com", "monthly@x.com"]


def test_cross_sell_tiers_and_past_buyers():
    big_p, big = monthly_subscriber("big@x.com", 6, take_home=5000)
    small_p, small = monthly_subscriber("small@x.com", 6, take_home=500)
    buyer_p, buyer = monthly_subscriber("buyer@x.com", 6, take_home=3000)
    buyer_p.append(pay("buyer@x.com", 100, "manual", account="acct_b", take_home=20000))
    fresh_p, fresh = [pay("fresh@x.com", 10, "subscription_create")], sub("fresh@x.com", 10)
    payments, subs = big_p + small_p + buyer_p + fresh_p, [big, small, buyer, fresh]

    call = RevenueSource("call", "calendly", "Strategy call", "repeat", "acct_b")
    found = run(payments, subs, [call])
    # Expensive: top by lifetime value with enough renewals; the past buyer is left out.
    assert emails(found["cross-sell-call"]) == ["big@x.com", "small@x.com"]
    assert found["cross-sell-call"].candidates[0].why == "#2 by lifetime take-home, 5 renewals"

    guide = RevenueSource("guide", "gumroad", "Guide", "once", None)
    # Cheap: every paid subscriber 30+ days in; nobody's known to have bought it.
    assert sorted(emails(run(payments, subs, [guide])["cross-sell-guide"])) == ["big@x.com", "buyer@x.com", "small@x.com"]

    community = RevenueSource("club", "circle", "Club", "subscription", None)
    annual = sub("annual@x.com", 500, interval="year", plan="Yearly plan")
    assert emails(run(payments, subs + [annual], [community])["cross-sell-club"]) == ["annual@x.com"]


def test_repeat_booking():
    payments = [
        pay("lapsed@x.com", 400, "manual", account="acct_b"), pay("lapsed@x.com", 200, "manual", account="acct_b"),
        pay("recent@x.com", 30, "manual", account="acct_b"),
        pay("elsewhere@x.com", 300, "manual", account="acct_a"),
    ]
    call = RevenueSource("call", "calendly", "Strategy call", "repeat", "acct_b")
    a = run(payments, [], [call])["repeat-booking-call"]
    assert emails(a) == ["lapsed@x.com"]
    assert a.candidates[0].why == "Bought 2 times, last 6 months ago"
    # Not paid through Stripe, or not bookable again: no repeat-booking action.
    assert "repeat-booking-x" not in run([], [], [RevenueSource("x", "calendly", "Call", "repeat", None)])


def test_win_back_is_voluntary_ended_and_not_back():
    def gone(email, **kw):
        return sub(email, 300, status="canceled", canceled_at=NOW - 20 * DAY, ends_at=NOW - 10 * DAY, **kw)
    subs = [
        gone("pricey@x.com", cancel_reason="cancellation_requested", cancel_feedback="too_expensive"),
        gone("card@x.com", cancel_reason="payment_failed"),
        gone("back@x.com", cancel_reason="cancellation_requested"), sub("back@x.com", 5),
        sub("ending@x.com", 300, canceled_at=NOW - 5 * DAY, ends_at=NOW + 10 * DAY),  # still active
    ]
    a = run([], subs)["win-back"]
    assert emails(a) == ["pricey@x.com"]
    assert a.candidates[0].why == "Canceled 2 weeks ago: too expensive"


def test_retention_actions_split_at_risk():
    canceling = sub("leaving@x.com", 300, canceled_at=NOW - 2 * DAY, ends_at=NOW + 9 * DAY, cancel_feedback="unused")
    failing = sub("card@x.com", 300, status="past_due", next_retry=NOW + 2 * DAY, invoice_created=NOW - 3 * DAY)
    dispute = Dispute(created=NOW - DAY, status="needs_response", reason="product_not_received", amount=1000,
                      respond_by=NOW + 7 * DAY, movements=())
    payments = [pay("angry@x.com", 30, dispute=dispute)]
    found = run(payments, [canceling, failing])
    assert found["save"].candidates[0].why == "Canceling, access ends in 9 days: not using it"
    assert found["save"].candidates[0].deadline == NOW + 9 * DAY
    assert found["card-failing"].candidates[0].why.endswith("next retry in 2 days")
    [d] = found["dispute-check-in"].candidates
    assert d.email == "angry@x.com" and "(product not received)" in d.why


def test_open_disputes_and_full_refunds_are_left_out_except_for_dispute_check_in():
    dispute = Dispute(created=NOW - DAY, status="needs_response", reason=None, amount=1000, respond_by=None, movements=())
    payments = [
        pay("disputer@x.com", 10, "subscription_create", dispute=dispute),
        pay("refunded@x.com", 10, "subscription_create", amount=1000, amount_refunded=1000,
            refunds=(Refund(created=NOW - 5 * DAY, amount=1000),)),
        pay("ok@x.com", 10, "subscription_create"),
    ]
    subs = [sub("disputer@x.com", 10), sub("refunded@x.com", 10), sub("ok@x.com", 10)]
    found = run(payments, subs)
    assert emails(found["welcome"]) == ["ok@x.com"]
    assert emails(found["dispute-check-in"]) == ["disputer@x.com"]


def test_without_subscriptions_access():
    found = run([], [], subscriptions_available=False)
    assert found["welcome"].unavailable and found["welcome"].candidates == []
    assert found["dispute-check-in"].unavailable is None


def test_highest_value_first_and_one_entry_per_person():
    a_p, a = monthly_subscriber("a@x.com", 4, take_home=100)
    b_p, b = monthly_subscriber("b@x.com", 4, take_home=900)
    second = sub("b@x.com", 100, plan="Founding member · yearly", interval="year")
    vip = run(a_p + b_p, [a, b, second])["vip"]
    assert emails(vip) == ["b@x.com", "a@x.com"]


def test_subscription_price_is_normalized():
    raw = make_subscription(items={"data": [{"price": {
        "id": "price_9", "nickname": None, "unit_amount": 15000, "currency": "usd",
        "recurring": {"interval": "year", "interval_count": 1},
    }}]})
    s = normalize_subscription(raw, "acct_a")
    assert (s.price_id, s.price_amount, s.price_currency, s.interval, s.interval_count) == ("price_9", 15000, "usd", "year", 1)
    old = normalize_subscription(make_subscription(), "acct_a")
    assert (old.price_amount, old.interval) == (None, None)
