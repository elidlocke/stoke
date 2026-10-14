"""The writer's Substack profile, and the links on it Stoke can suggest for Settings.

Substack's public profile (substack.com/@handle) is read from the JSON its own page loads. Its
"chips" are the writer's publications and the links they added (userLinks). Any failure leaves the
writer to add their links by hand, so it's reported as a message, never raised.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from cachetools import TTLCache

from app.models import DEFAULT_PURCHASE, LinkSuggestion

PROFILE_URL = "https://substack.com/api/v1/user/{handle}/public_profile"
TIMEOUT = 10.0
UNAVAILABLE = "Couldn't read your Substack profile right now. You can still add your links by hand."

_HANDLE = re.compile(r"^[a-z0-9_-]{1,64}$")
_PROFILE_LINK = re.compile(r"^(?:https?://)?(?:www\.)?substack\.com/@([^/?#]+)", re.IGNORECASE)

_cache: TTLCache[str, dict] = TTLCache(maxsize=1024, ttl=3600)


class SubstackError(Exception):
    """The handle can't be saved; the message is safe to show the user."""


@dataclass(frozen=True)
class Profile:
    handle: str
    name: str | None
    photo_url: str | None
    links: list[LinkSuggestion] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://substack.com/@{self.handle}"


def parse_handle(text: str) -> str:
    """The handle in "sarahfay", "@sarahfay" or "https://substack.com/@sarahfay"."""
    text = text.strip()
    m = _PROFILE_LINK.match(text)
    handle = (m.group(1) if m else text).removeprefix("@").lower()
    if not _HANDLE.match(handle):
        raise SubstackError("That doesn't look like a Substack handle. It's the part after the @ on your profile.")
    return handle


# ---- Reading the profile ----

class NotFound(Exception):
    pass


class Unavailable(Exception):
    pass


async def _fetch(handle: str, refresh: bool) -> dict:
    if handle in _cache and not refresh:
        return _cache[handle]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0 (Stoke)"}) as client:
            resp = await client.get(PROFILE_URL.format(handle=handle))
    except httpx.HTTPError as exc:
        raise Unavailable() from exc
    if resp.status_code == 404:
        raise NotFound()
    if resp.status_code != 200:
        raise Unavailable()
    try:
        data = resp.json()
    except ValueError as exc:
        raise Unavailable() from exc
    if not isinstance(data, dict):
        raise Unavailable()
    _cache[handle] = data
    return data


async def read(handle: str, refresh: bool = False) -> Profile:
    """The writer's profile and the links on it. Raises NotFound or Unavailable. `refresh` reads it
    again rather than from the last hour's copy (the writer just changed it)."""
    data = await _fetch(handle, refresh)
    try:
        return Profile(
            handle=handle, name=_str(data.get("name")), photo_url=_str(data.get("photo_url")), links=suggestions(data),
        )
    except (AttributeError, TypeError) as exc:  # Substack changed its shape
        raise Unavailable() from exc


def clear_cache() -> None:
    _cache.clear()


def _str(v: object) -> str | None:
    return v if isinstance(v, str) and v else None


# ---- Sorting the links into Stoke's lists ----

# Hosts, matched exactly or as a parent domain, and the kind of link they are.
_REVENUE_HOSTS = {
    "calendly.com": "calendly", "maven.com": "maven", "gumroad.com": "gumroad", "teachable.com": "teachable",
    "circle.so": "circle", "lu.ma": "luma", "luma.com": "luma",
}
_SOCIAL_HOSTS = {
    "x.com": "x", "twitter.com": "x", "instagram.com": "instagram", "linkedin.com": "linkedin",
    "youtube.com": "youtube", "youtu.be": "youtube", "tiktok.com": "tiktok", "threads.net": "threads",
    "threads.com": "threads", "bsky.app": "bluesky", "facebook.com": "facebook",
    "podcasts.apple.com": "podcast", "open.spotify.com": "podcast", "substack.com": "substack",
}
# Substack's own names for a userLink, when its host doesn't say.
_SOCIAL_TYPES = {
    "twitter": "x", "x": "x", "instagram": "instagram", "linkedin": "linkedin", "youtube": "youtube",
    "tiktok": "tiktok", "threads": "threads", "bluesky": "bluesky", "facebook": "facebook",
}
_PLATFORM_NAMES = {
    "calendly": "Calendly", "maven": "Maven", "gumroad": "Gumroad", "teachable": "Teachable", "circle": "Circle",
    "luma": "Luma",
}


def _host_kind(host: str, table: dict[str, str]) -> str | None:
    for domain, kind in table.items():
        if host == domain or host.endswith(f".{domain}"):
            return kind
    return None


def clean_url(url: str) -> str | None:
    """An https link without tracking parameters, or None when it isn't a web link."""
    parts = urlsplit(url.strip() if "://" in url else f"https://{url.strip()}")
    if parts.scheme not in ("http", "https") or "." not in parts.netloc:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")])
    return urlunsplit(("https", parts.netloc.lower(), parts.path, query, ""))


def same_link(a: str, b: str) -> bool:
    """Whether two links go to the same page, ignoring https, www and a trailing slash."""
    def key(url: str) -> str:
        parts = urlsplit(clean_url(url) or url)
        return f"{parts.netloc.removeprefix('www.')}{parts.path.rstrip('/')}?{parts.query}".lower()
    return key(a) == key(b)


def _link(url: str, social_type: str | None = None, name: str | None = None) -> LinkSuggestion | None:
    cleaned = clean_url(url)
    if cleaned is None:
        return None
    host = urlsplit(cleaned).netloc.removeprefix("www.")
    if kind := _host_kind(host, _REVENUE_HOSTS):
        return LinkSuggestion(
            category="revenue_source", kind=kind, name=name or _PLATFORM_NAMES[kind], url=cleaned,
            purchase=DEFAULT_PURCHASE.get(kind, "once"),
        )
    kind = _host_kind(host, _SOCIAL_HOSTS) or _SOCIAL_TYPES.get((social_type or "").lower()) or "website"
    return LinkSuggestion(category="social", kind=kind, name=name, url=cleaned)


def suggestions(data: dict) -> list[LinkSuggestion]:
    """The links on a public profile: the publications the writer runs, then the links they added."""
    pubs = [pu.get("publication") or {} for pu in data.get("publicationUsers") or [] if pu.get("role") == "admin"]
    primary = data.get("primaryPublication")
    if primary and all(p.get("id") != primary.get("id") for p in pubs):
        pubs.insert(0, primary)
    out: list[LinkSuggestion] = []
    for pub in pubs:
        domain = pub.get("custom_domain") or (f"{pub['subdomain']}.substack.com" if pub.get("subdomain") else None)
        if domain:
            out.append(LinkSuggestion(category="social", kind="substack", name=_str(pub.get("name")), url=f"https://{domain}"))
    for ul in data.get("userLinks") or []:
        if isinstance(ul, dict) and isinstance(ul.get("url"), str):
            if link := _link(ul["url"], ul.get("type"), _str(ul.get("label"))):
                out.append(link)
    unique: list[LinkSuggestion] = []
    for link in out:
        if not any(same_link(link.url, u.url) for u in unique):
            unique.append(link)
    return unique
