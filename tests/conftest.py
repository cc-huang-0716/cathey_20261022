from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def quote_row(symbol="2330", name="台積電", **overrides):
    row = {
        "Date": "1151020", "Code": symbol, "Name": name,
        "OpeningPrice": "100.00", "HighestPrice": "110.00", "LowestPrice": "98.00",
        "ClosingPrice": "110.00", "Change": "10.00", "TradeVolume": "1000000",
        "TradeValue": "105000000", "Transaction": "2000",
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
            year, number = int(month[:4]) - 1911, month[4:6]
            return httpx.Response(200, json={
                "stat": "OK", "date": month,
                "data": [[f"{year}/{number}/01", "1,000", "100,000", "100", "110", "99", "105", "+5", "30", ""]],
            })

        def tracked_handler(request):
            calls.append(request)
            return (handler or default_handler)(request)

        client = TestClient(create_app(Settings(**settings), httpx.MockTransport(tracked_handler)))
        clients.append(client)
        client.__enter__()
        return client, calls

    yield factory
    for client in clients:
        client.__exit__(None, None, None)
