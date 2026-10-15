"""Note templates: a subject and body the writer writes once per action, with merge fields.

Every note is the template with its fields filled in the same, deterministic way for everyone: no
per-person text is ever generated. Filled values are returned as separate parts, so the UI can
highlight exactly what changed from person to person.
"""

import re
from dataclasses import dataclass

from app.actions import Candidate, RevenueSource

# {{name}}, or {{name|fallback}}. A field's own fallback (MergeField.fallback) covers anyone with no value; one
# written in the template, e.g. {{first_name|friend}}, overrides it (older templates were saved that way).
FIELD = re.compile(r"\{\{\s*([a-z_]+)\s*(?:\|([^{}]*))?\}\}")

SUBJECT_MAX = 300
BODY_MAX = 10_000


@dataclass(frozen=True)
class MergeField:
    name: str
    description: str
    fallback: str | None = None  # used for anyone with no value, unless the template writes its own
    example: str | None = None  # a reader's value, for previewing a note when the audience is empty


@dataclass(frozen=True)
class Social:
    kind: str  # substack, instagram, ... (LINK_KINDS["social"] in app/models.py)
    name: str | None
    url: str


_FIRST_NAME = MergeField(
    "first_name", "Their first name, from their Stripe customer record or your Substack export, when there is one", fallback="there", example="Sam",
)
_PLAN = MergeField("plan", "Their plan, e.g. “Monthly plan”", example="Monthly plan")
_SUBSTACK = MergeField("substack", "Your Substack link")
_SOCIALS = MergeField("socials", "Your other channels, one per line")
_SINCE = MergeField("since", "When they subscribed, e.g. “March 2025”", example="March 2025")
_RENEWALS = MergeField("renewals", "How many times they've renewed, e.g. “5”", example="5")
_LINK = MergeField("link", "The revenue stream's link")
_LINK_NAME = MergeField("link_name", "The revenue stream's name")

COMMON = [_FIRST_NAME, _PLAN, _SUBSTACK, _SOCIALS]

_EXTRA: dict[str, list[MergeField]] = {
    "anniversary": [MergeField("years", "How long since their first payment, e.g. “2 years”", example="2 years")],
    "founding-upgrade": [_RENEWALS, _SINCE],
    "monthly-to-annual": [_RENEWALS, _SINCE],
    "cross-sell": [_LINK, _LINK_NAME, _SINCE],
    "repeat-booking": [_LINK, _LINK_NAME, MergeField("last", "When they last bought it, e.g. “6 months ago”", example="6 months ago")],
    "free-to-paid": [
        MergeField("free_for", "How long they've been a free subscriber, e.g. “8 months”", example="8 months"), _SINCE,
    ],
    "save": [MergeField("ends", "When their access ends, e.g. “October 20”", example="October 20")],
}

_DEFAULTS: dict[str, tuple[str, str]] = {
    "welcome": (
        "Welcome, and thank you",
        "Hi {{first_name}},\n\nI saw you just became a paid subscriber, and I wanted to say thank you personally. It means a lot.\n\n"
        "If you ever want to reply with what you'd like me to write about, I read everything.\n\n{{socials}}",
    ),
    "anniversary": (
        "{{years}} together",
        "Hi {{first_name}},\n\nIt's been {{years}} since you first supported my writing. I just wanted to say thank you. "
        "Readers like you are why I keep going.",
    ),
    "welcome-back": (
        "Good to have you back",
        "Hi {{first_name}},\n\nI noticed you came back as a paid subscriber, and it made my day. Thank you for giving it another go.",
    ),
    "gift-thanks": (
        "Thank you for the gift",
        "Hi {{first_name}},\n\nI saw you gave someone a subscription to my newsletter. Thank you for sharing my writing: "
        "readers like you are how it grows.\n\nIf there's anything you'd like me to write about, just reply.",
    ),
    "vip": (
        "A small favor?",
        "Hi {{first_name}},\n\nYou've been one of my most loyal supporters, and I'm grateful. Would you write a sentence or two about "
        "what my newsletter means to you? I'd love to share it with readers who are on the fence.",
    ),
    "founding-upgrade": (
        "Would you consider becoming a Founding member?",
        "Hi {{first_name}},\n\nYou've supported my writing since {{since}}, and renewed {{renewals}} times. Thank you.\n\n"
        "If you'd like to do a little more, becoming a Founding member is the biggest help to keep this going: "
        "{{substack}}",
    ),
    "monthly-to-annual": (
        "Save by switching to annual",
        "Hi {{first_name}},\n\nThank you for being a monthly subscriber since {{since}}. If you'd like, you can switch to an annual "
        "plan and pay less over the year: {{substack}}",
    ),
    "free-to-paid": (
        "Thank you for reading",
        "Hi {{first_name}},\n\nYou've been reading my newsletter for {{free_for}} now, and I wanted to say thank you "
        "personally. It means a lot that you keep opening it.\n\nIf it's been worth something to you, would you consider "
        "becoming a paid subscriber? It's what lets me keep writing: {{substack}}/subscribe\n\n"
        "Either way, I'm really glad you're here.",
    ),
    "cross-sell": (
        "Something I think you'd like",
        "Hi {{first_name}},\n\nAs a subscriber since {{since}}, I thought you might like {{link_name}}. Here's the link if you're "
        "curious: {{link}}",
    ),
    "repeat-booking": (
        "Want to book another?",
        "Hi {{first_name}},\n\nIt's been {{last}} since you last booked {{link_name}}. If it would help again, you can book here: "
        "{{link}}",
    ),
    "win-back": (
        "I'd love to have you back",
        "Hi {{first_name}},\n\nI noticed you canceled your subscription recently. No hard feelings at all. If there's anything I "
        "could do better, I'd genuinely like to know. And if you'd like to come back, you're always welcome: "
        "{{substack}}",
    ),
    "save": (
        "Before you go",
        "Hi {{first_name}},\n\nI saw you canceled, and your access ends on {{ends}}. If something made you leave, I'd love to hear "
        "it. If you change your mind, you can keep your subscription from your account settings.",
    ),
    "card-failing": (
        "A heads-up about your payment",
        "Hi {{first_name}},\n\nJust a quick heads-up: the payment for your subscription didn't go through. If you'd like to keep "
        "reading, you can update your card in your account settings. Thanks for being a subscriber!",
    ),
    "dispute-check-in": (
        "About your recent charge",
        "Hi {{first_name}},\n\nI saw your bank flagged a recent charge for my newsletter. Were you having trouble canceling? "
        "I'm happy to cancel and refund you directly. If so, could you withdraw the dispute with your bank?",
    ),
}

_SOCIAL_NAMES = {
    "x": "X", "linkedin": "LinkedIn", "youtube": "YouTube", "tiktok": "TikTok", "bluesky": "Bluesky",
}


def base_kind(kind: str) -> str:
    """The template family of an action: one per revenue source shares its type's ("cross-sell-<id>" -> "cross-sell")."""
    for prefix in ("cross-sell", "repeat-booking"):
        if kind.startswith(prefix + "-"):
            return prefix
    return kind


def fields_for(kind: str) -> list[MergeField]:
    return COMMON + _EXTRA.get(base_kind(kind), [])


def fallbacks(kind: str) -> dict[str, str]:
    return {f.name: f.fallback for f in fields_for(kind) if f.fallback is not None}


def default(kind: str) -> tuple[str, str]:
    return _DEFAULTS.get(base_kind(kind), ("", "Hi {{first_name}},\n\n"))


def unknown_fields(text: str, kind: str) -> list[str]:
    known = {f.name for f in fields_for(kind)}
    return sorted({m.group(1) for m in FIELD.finditer(text)} - known)


@dataclass(frozen=True)
class Part:
    text: str
    field: str | None = None  # set for a filled merge field
    fallback: bool = False  # the field had no value for this person, so its fallback was used


def fill(template: str, values: dict[str, str], fallbacks: dict[str, str] | None = None) -> list[Part]:
    """The template as parts: the writer's own text, and each merge field's value (its fallback, or
    empty, if the person has none). `fallbacks` are the fields' own, used where the template writes none."""
    parts, at = [], 0
    for m in FIELD.finditer(template):
        if m.start() > at:
            parts.append(Part(template[at:m.start()]))
        name = m.group(1)
        fallback = m.group(2) if m.group(2) is not None else (fallbacks or {}).get(name)
        value = values.get(name, "")
        if not value and fallback is not None:
            parts.append(Part(fallback.strip(), name, fallback=True))
        else:
            parts.append(Part(value, name))
        at = m.end()
    if at < len(template):
        parts.append(Part(template[at:]))
    return parts


def text(parts: list[Part]) -> str:
    return "".join(p.text for p in parts)


def missing(parts: list[Part]) -> list[str]:
    """Merge fields with no value for this person, e.g. {{substack}} before a Substack link is added."""
    return sorted({p.field for p in parts if p.field and not p.text and not p.fallback})


def _writer_values(source: RevenueSource | None, socials: list[Social]) -> dict[str, str]:
    """The fields that come from the writer's settings, the same for every reader."""
    substack = next((s.url for s in socials if s.kind == "substack"), "")
    others = [s for s in socials if s.kind != "substack"]
    out = {
        "substack": substack,
        "socials": "\n".join(f"{s.name or _SOCIAL_NAMES.get(s.kind, s.kind.capitalize())}: {s.url}" for s in others),
    }
    if source is not None:
        out |= {"link": source.url, "link_name": source.name}
    return out


def values(c: Candidate, source: RevenueSource | None, socials: list[Social]) -> dict[str, str]:
    return _writer_values(source, socials) | {"plan": c.plan or "your subscription"} | c.fields


def example_values(kind: str, source: RevenueSource | None, socials: list[Social]) -> dict[str, str]:
    """An example reader's values, for previewing an action with nobody in it: the writer's own settings are real."""
    return {f.name: f.example for f in fields_for(kind) if f.example} | _writer_values(source, socials)
