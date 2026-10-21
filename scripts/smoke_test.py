"""Optional live integration check. Run only when the local service is running."""

import argparse
import json
from urllib.parse import quote
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description="Verify the running Market Brief service")
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
    print(json.dumps({
        "status": "passed",
        "trade_date": market["summary"]["trade_date"],
        "securities": market["summary"]["securities"],
        "sample": quote_data["data"],
        "history_points": len(history["data"]),
        "source": quote_data["meta"]["source"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
