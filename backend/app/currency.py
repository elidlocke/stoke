"""Minor-unit handling. Stripe amounts are integers in the currency's smallest unit."""

# https://docs.stripe.com/currencies#zero-decimal
ZERO_DECIMAL = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
}
# https://docs.stripe.com/currencies#three-decimal
THREE_DECIMAL = {"bhd", "jod", "kwd", "omr", "tnd"}


def exponent(currency: str) -> int:
    currency = currency.lower()
    if currency in ZERO_DECIMAL:
        return 0
    if currency in THREE_DECIMAL:
        return 3
    return 2


def convert_minor(amount: int, from_currency: str, to_currency: str, rate: float) -> int:
    """Convert a minor-unit amount using `rate` (units of to_currency per 1 from_currency)."""
    major = amount / 10 ** exponent(from_currency)
    return round(major * rate * 10 ** exponent(to_currency))
