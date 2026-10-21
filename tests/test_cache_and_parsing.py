import asyncio
from datetime import date

import pytest

from app.services.cache import TTLCache, UpstreamError
from app.services.stocks import as_float, as_int, parse_date, parse_quote, validate_month
from conftest import quote_row


@pytest.mark.parametrize("raw,expected", [("1151020", date(2026, 10, 20)), ("115/10/20", date(2026, 10, 20)), ("20261020", date(2026, 10, 20)), ("2026-10-20", date(2026, 10, 20))])
def test_source_dates(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["--", "NaN", "Infinity", "X0.00", None, "0", "-10"])
def test_invalid_or_no_trade_price_is_missing(raw):
    assert as_float(raw, price=True) is None


def test_decimal_change_and_integer_units():
    quote = parse_quote(quote_row(ClosingPrice="10.10", Change="0.10"))
    assert quote.change_percent == 1
    assert as_int("1,234") == 1234
    assert as_int("1.5") is None


def test_month_window_includes_year_boundary():
    today = date(2026, 1, 15)
    assert validate_month(None, today) == "2026-01"
    assert validate_month("2025-02", today) == "2025-02"
    with pytest.raises(ValueError):
        validate_month("2025-01", today)


async def test_simultaneous_refreshes_share_one_upstream_request():
    cache = TTLCache()
    calls = 0
    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"value": 123}
    results = await asyncio.gather(*(cache.get("same", fetch, 30) for _ in range(20)))
    assert calls == 1
    assert all(result.data == {"value": 123} for result in results)
    assert sum(not result.cached for result in results) == 1


async def test_cache_capacity_is_bounded():
    cache = TTLCache(max_entries=2)
    async def fetch():
        return 1
    for key in ["a", "b", "c"]:
        await cache.get(key, fetch, 30)
    assert list(cache.entries) == ["b", "c"]
