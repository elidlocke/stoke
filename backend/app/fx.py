"""Historical FX rates (ECB reference rates via Frankfurter; free, no API key).

Only needed when a connected account settles in a currency other than the platform's.
"""

import asyncio
import logging

import httpx

from app.aggregate import Rates

log = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"

# Historical rates don't change, so this cache never expires.
_rates: dict[tuple[str, str, str], float] = {}


async def _fetch(client: httpx.AsyncClient, date: str, base: str, target: str) -> None:
    try:
        resp = await client.get(
            f"{FRANKFURTER_URL}/{date}",
            params={"base": base.upper(), "symbols": target.upper()},
        )
        resp.raise_for_status()
        _rates[(date, base, target)] = float(resp.json()["rates"][target.upper()])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        # E.g. a currency the ECB doesn't publish. Those transactions stay unconverted.
        log.warning("No FX rate for %s->%s on %s: %s", base, target, date, exc)


async def get_rates(pairs: set[tuple[str, str]], target: str) -> Rates:
    missing = [(d, c) for d, c in pairs if (d, c, target) not in _rates]
    if missing:
        async with httpx.AsyncClient(timeout=10) as client:
            await asyncio.gather(*(_fetch(client, d, c, target) for d, c in missing))
    return {(d, c): _rates[(d, c, target)] for d, c in pairs if (d, c, target) in _rates}
