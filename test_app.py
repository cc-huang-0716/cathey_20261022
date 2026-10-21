import argparse
import asyncio
import json
import subprocess
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import httpx
import pytest
from fastapi.testclient import TestClient

from app import (
    TAIPEI,
    Settings,
    TTLCache,
    UpstreamError,
    as_float,
    as_int,
    create_app,
    parse_date,
    parse_quote,
    validate_month,
)


def quote_row(symbol="2330", name="台積電", **overrides):
    row = {
        "Date": "1151020",
        "Code": symbol,
        "Name": name,
        "OpeningPrice": "100.00",
        "HighestPrice": "110.00",
        "LowestPrice": "98.00",
        "ClosingPrice": "110.00",
        "Change": "10.00",
        "TradeVolume": "1000000",
        "TradeValue": "105000000",
        "Transaction": "2000",
    }
    return row | overrides


@pytest.fixture
def snapshot():
    return [
        quote_row(),
        quote_row("2317", "鴻海", ClosingPrice="95", Change="-5", TradeVolume="2000000"),
        quote_row("2882", "國泰金", ClosingPrice="50", Change="0", TradeVolume="500000"),
        quote_row("0050", "元大台灣50", ClosingPrice="--", Change="--", TradeVolume="0"),
    ]


@pytest.fixture
def make_client(snapshot):
    clients = []

    def factory(handler=None, **settings):
        calls = []

        def default_handler(request):
            if request.url.host == "openapi.twse.com.tw":
                return httpx.Response(200, json=deepcopy(snapshot))
            month = request.url.params.get("date", "20261001")
            year, number = (int(month[:4]) - 1911, month[4:6])
            return httpx.Response(
                200,
                json={
                    "stat": "OK",
                    "date": month,
                    "data": [
                        [
                            f"{year}/{number}/01",
                            "1,000",
                            "100,000",
                            "100",
                            "110",
                            "99",
                            "105",
                            "+5",
                            "30",
                            "",
                        ]
                    ],
                },
            )

        def tracked_handler(request):
            calls.append(request)
            return (handler or default_handler)(request)

        client = TestClient(create_app(Settings(**settings), httpx.MockTransport(tracked_handler)))
        clients.append(client)
        client.__enter__()
        return (client, calls)

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1151020", date(2026, 10, 20)),
        ("115/10/20", date(2026, 10, 20)),
        ("20261020", date(2026, 10, 20)),
        ("2026-10-20", date(2026, 10, 20)),
    ],
)
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
    assert all((result.data == {"value": 123} for result in results))
    assert sum((not result.cached for result in results)) == 1


async def test_cache_capacity_is_bounded():
    cache = TTLCache(max_entries=2)

    async def fetch():
        return 1

    for key in ["a", "b", "c"]:
        await cache.get(key, fetch, 30)
    assert list(cache.entries) == ["b", "c"]


def test_home_health_openapi_and_static_do_not_call_provider(make_client):
    client, calls = make_client()
    assert client.get("/health").json()["status"] == "ok"
    home = client.get("/")
    assert home.status_code == 200
    assert "股日" in home.text
    assert "<style>" in home.text and "<script>" in home.text
    assert client.get("/docs").status_code == 200
    assert "/api/stocks/{symbol}/history" in client.get("/openapi.json").json()["paths"]
    assert not calls


def test_quote_normalizes_values_date_and_reference_change(make_client):
    client, _ = make_client()
    response = client.get("/api/stocks/2330")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trade_date"] == "2026-10-20"
    assert data["close"] == 110
    assert data["change_percent"] == 10
    assert data["volume"] == 1000000
    assert response.json()["meta"]["price_type"] == "daily_close"
    assert response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "query,expected",
    [("台積", "2330"), ("國泰金", "2882"), (" ２３３０ ", "2330"), ("0050", "0050")],
)
def test_search_by_chinese_or_normalized_symbol(make_client, query, expected):
    client, _ = make_client()
    assert client.get("/api/stocks", params={"q": query}).json()["data"][0]["symbol"] == expected


def test_empty_search_and_unknown_symbol(make_client):
    client, _ = make_client()
    assert client.get("/api/stocks?q=不存在的公司").json()["data"] == []
    response = client.get("/api/stocks/9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STOCK_NOT_FOUND"


@pytest.mark.parametrize(
    "path",
    [
        "/api/stocks?limit=21",
        "/api/stocks?limit=0",
        "/api/market?sort=invalid",
        "/api/stocks/2330/history?month=2026-13",
        "/api/stocks/2330/history?month=2020-01",
        "/api/stocks/2330/history?month=2099-01",
        "/api/stocks/not-a-symbol",
    ],
)
def test_bad_parameters_are_rejected(make_client, path):
    client, calls = make_client()
    response = client.get(path)
    assert response.status_code == 422
    assert not calls


def test_missing_prices_are_null_and_not_a_zero_return(make_client):
    client, _ = make_client()
    quote = client.get("/api/stocks/0050").json()["data"]
    assert quote["close"] is None
    assert quote["change"] is None
    assert quote["change_percent"] is None


def test_market_summary_and_rankings(make_client):
    client, calls = make_client()
    data = client.get("/api/market").json()
    assert data["summary"] == {
        "trade_date": "2026-10-20",
        "securities": 4,
        "advancing": 1,
        "declining": 1,
        "unchanged": 1,
        "unavailable": 1,
        "total_volume": 3500000,
        "total_turnover": 420000000,
    }
    assert data["leaders"][0]["symbol"] == "2317"
    assert client.get("/api/market?sort=gainers").json()["leaders"][0]["symbol"] == "2330"
    assert client.get("/api/market?sort=losers").json()["leaders"][0]["symbol"] == "2317"
    assert len(calls) == 1


def test_cache_reuses_snapshot_across_endpoints(make_client):
    client, calls = make_client()
    assert client.get("/api/stocks/2330").json()["meta"]["cached"] is False
    assert client.get("/api/stocks/2317").json()["meta"]["cached"] is True
    client.get("/api/stocks?q=國泰")
    client.get("/api/market")
    assert len(calls) == 1


def test_monthly_history_uses_correct_parameters_and_normalizes_data(make_client):
    client, calls = make_client()
    month = datetime.now(TAIPEI).strftime("%Y-%m")
    response = client.get("/api/stocks/2330/history", params={"month": month})
    assert response.status_code == 200
    assert response.json()["data"][0]["volume"] == 1000
    assert response.json()["data"][0]["date"] == f"{month}-01"
    assert calls[-1].url.params["stockNo"] == "2330"
    assert calls[-1].url.params["date"] == month.replace("-", "") + "01"
    client.get("/api/stocks/2330/history", params={"month": month})
    assert len(calls) == 2


def test_no_trading_data_for_month_is_an_empty_series(make_client, snapshot):

    def handler(request):
        return httpx.Response(
            200,
            json=snapshot
            if request.url.host == "openapi.twse.com.tw"
            else {"stat": "很抱歉，沒有符合條件的資料!"},
        )

    client, _ = make_client(handler)
    assert client.get("/api/stocks/2330/history").json()["data"] == []


def test_unknown_history_symbol_does_not_query_history_provider(make_client):
    client, calls = make_client()
    assert client.get("/api/stocks/9999/history").status_code == 404
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure,status,code",
    [
        ("timeout", 504, "UPSTREAM_TIMEOUT"),
        ("connection", 502, "UPSTREAM_UNAVAILABLE"),
        ("html", 502, "UPSTREAM_UNAVAILABLE"),
        ("rate_limit", 503, "UPSTREAM_UNAVAILABLE"),
        ("malformed", 502, "UPSTREAM_INVALID_DATA"),
    ],
)
def test_upstream_errors_are_safe_and_backed_off(make_client, failure, status, code):

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream details", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private upstream details", request=request)
        if failure == "html":
            return httpx.Response(200, text="<html>maintenance</html>")
        if failure == "rate_limit":
            return httpx.Response(429)
        return httpx.Response(200, json=["malformed row"])

    client, calls = make_client(handler)
    response = client.get("/api/stocks/2330")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private" not in response.text
    assert response.headers["Retry-After"] == "30"
    client.get("/api/market")
    assert len(calls) == 1
    assert client.get("/health").status_code == 200


def test_stale_snapshot_is_explicit_and_expires(make_client, snapshot):
    failing = False
    now = [0.0]

    def handler(request):
        if failing:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json=snapshot)

    client, calls = make_client(handler, cache_ttl=10, max_stale=20, failure_backoff=5)
    client.app.state.stocks.snapshot_cache.clock = lambda: now[0]
    client.get("/api/market")
    failing = True
    now[0] = 11
    response = client.get("/api/market")
    assert response.status_code == 200
    assert response.json()["meta"]["stale"] is True
    assert response.json()["meta"]["warning"]
    client.get("/api/market")
    assert len(calls) == 2
    now[0] = 31
    assert client.get("/api/market").status_code == 502


def test_snapshot_does_not_combine_different_trading_dates(make_client):
    rows = [quote_row(), quote_row("2317", "鴻海", Date="1151019")]
    client, _ = make_client(lambda request: httpx.Response(200, json=rows))
    summary = client.get("/api/market").json()["summary"]
    assert summary["securities"] == 1
    assert summary["trade_date"] == "2026-10-20"


ROOT = Path(__file__).resolve().parent


def check_repository():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    if not tracked:
        raise SystemExit("No tracked source files found.")
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        input=tracked,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise SystemExit(result.stderr.decode("utf-8", errors="replace"))
    unexpected = [path.decode("utf-8") for path in result.stdout.split(b"\x00") if path]
    if unexpected:
        raise SystemExit("Ignored files are tracked by Git:\n" + "\n".join(unexpected))
    count = len([path for path in tracked.split(b"\x00") if path])
    print(f"Repository hygiene: {count} tracked files; no ignored paths are tracked.")


def live_check():
    parser = argparse.ArgumentParser(description="Verify the running Market Brief service")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    def get(path):
        with urlopen(f"{base}{path}", timeout=30) as response:
            return json.load(response)

    assert get("/health")["status"] == "ok"
    market = get("/api/market")
    assert market["summary"]["securities"] > 0
    quote_data = get("/api/stocks/2330")
    assert quote_data["data"]["name"] == "台積電"
    search = get("/api/stocks?q=" + quote("台積電"))
    assert search["data"][0]["symbol"] == "2330"
    history = get("/api/stocks/2330/history")
    assert isinstance(history["data"], list)
    print(
        json.dumps(
            {
                "status": "passed",
                "trade_date": market["summary"]["trade_date"],
                "securities": market["summary"]["securities"],
                "sample": quote_data["data"],
                "history_points": len(history["data"]),
                "source": quote_data["meta"]["source"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        check_repository()
    elif "--live" in sys.argv:
        live_check()
    else:
        raise SystemExit(pytest.main(["-q", "--asyncio-mode=auto", __file__]))
