import pytest

from app import templates
from app.actions import Candidate, RevenueSource
from app.templates import Part, Social

SOCIALS = [
    Social("substack", None, "https://me.substack.com"),
    Social("instagram", None, "https://instagram.com/me"),
    Social("x", "Main account", "https://x.com/me"),
]


def candidate(**kw):
    return Candidate(email="a@x.com", account_id="acct_a", why="", plan=kw.pop("plan", "Monthly plan"),
                     lifetime_value=0, date=0, **kw)


def test_fill_keeps_the_writers_text_and_marks_each_value():
    parts = templates.fill("Hi,\n{{plan}} since {{ since }}!", {"plan": "Monthly plan", "since": "March 2025"})
    assert parts == [
        Part("Hi,\n"), Part("Monthly plan", "plan"), Part(" since "), Part("March 2025", "since"), Part("!"),
    ]
    assert templates.text(parts) == "Hi,\nMonthly plan since March 2025!"
    assert templates.missing(templates.fill("{{substack}} {{plan}}", {"plan": "x"})) == ["substack"]


def test_values():
    source = RevenueSource("l1", "calendly", "Strategy call", "repeat", None, url="https://calendly.com/me")
    v = templates.values(candidate(fields={"last": "6 months ago"}), source, SOCIALS)
    assert v == {
        "plan": "Monthly plan", "substack": "https://me.substack.com",
        "socials": "Instagram: https://instagram.com/me\nMain account: https://x.com/me",
        "link": "https://calendly.com/me", "link_name": "Strategy call", "last": "6 months ago",
    }
    assert templates.values(candidate(plan=None), None, [])["plan"] == "your subscription"


def test_unknown_fields_depend_on_the_action():
    assert templates.unknown_fields("{{renewals}} {{plan}}", "founding-upgrade") == []
    assert templates.unknown_fields("{{renewals}} {{name}}", "welcome") == ["name", "renewals"]
    assert templates.unknown_fields("{{link}}", "cross-sell-1234") == []


@pytest.mark.parametrize("kind", [
    "welcome", "anniversary", "welcome-back", "gift-thanks", "vip", "founding-upgrade", "monthly-to-annual", "cross-sell-x",
    "repeat-booking-x", "win-back", "save", "card-failing", "dispute-check-in",
])
def test_every_default_template_uses_only_its_fields(kind):
    subject, body = templates.default(kind)
    assert subject and body
    assert templates.unknown_fields(subject + body, kind) == []


def test_fallbacks_fill_in_for_missing_values():
    parts = templates.fill("Hi {{first_name|there}}, {{ first_name | friend }}", {})
    assert templates.text(parts) == "Hi there, friend"
    assert all(p.fallback for p in parts if p.field) and templates.missing(parts) == []
    assert templates.text(templates.fill("Hi {{first_name|there}}", {"first_name": "Ada"})) == "Hi Ada"
    assert templates.unknown_fields("{{first_name|there}} {{nope|x}}", "welcome") == ["nope"]


def test_fields_fall_back_on_their_own_fallback():
    fallbacks = templates.fallbacks("welcome")
    assert fallbacks == {"first_name": "there"}
    parts = templates.fill("Hi {{first_name}}, {{first_name|friend}}", {}, fallbacks)
    assert templates.text(parts) == "Hi there, friend"  # a fallback written in the template still wins
    assert templates.missing(parts) == []
    assert templates.missing(templates.fill("{{substack}}", {}, fallbacks)) == ["substack"]


def test_free_to_paid_default_fills_how_long_theyve_been_free():
    subject, body = templates.default("free-to-paid")
    assert templates.unknown_fields(subject + body, "free-to-paid") == []
    parts = templates.fill(body, {"free_for": "8 months", "substack": "https://me.substack.com"}, templates.fallbacks("free-to-paid"))
    assert "for 8 months now" in templates.text(parts) and "https://me.substack.com/subscribe" in templates.text(parts)
