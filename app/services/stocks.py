import logging
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.models import HistoryPoint, Metadata, Quote
from app.services.cache import CacheResult, TTLCache, UpstreamError

SNAPSHOT_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
HISTORY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TAIPEI = ZoneInfo("Asia/Taipei")
logger = logging.getLogger("marketbrief")


def number(raw: object, *, price: bool = False) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("−", "-")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or (price and value <= 0):
        return None
    return value


def as_float(raw: object, *, price: bool = False) -> float | None:
    value = number(raw, price=price)
    return float(value) if value is not None else None


def as_int(raw: object) -> int | None:
    value = number(raw)
    if value is None or value < 0 or value != value.to_integral_value():
        return None
    return int(value)


def parse_date(raw: str) -> date:
    if "/" in raw:
        year, month, day = map(int, raw.split("/"))
    elif re.fullmatch(r"\d{7}", raw):
        year, month, day = int(raw[:3]), int(raw[3:5]), int(raw[5:])
    elif re.fullmatch(r"\d{8}", raw):
        year, month, day = int(raw[:4]), int(raw[4:6]), int(raw[6:])
    else:
        return date.fromisoformat(raw)
    return date(year + 1911 if year < 1911 else year, month, day)


def normalize_query(query: str) -> str:
    return unicodedata.normalize("NFKC", query).strip().casefold()


def parse_quote(row: dict) -> Quote:
    close = number(row.get("ClosingPrice"), price=True)
    change = number(row.get("Change")) if close is not None else None
    previous = close - change if close is not None and change is not None else None
    percent = None
    if previous is not None and previous > 0:
        percent = float((change / previous * 100).quantize(Decimal("0.01"), ROUND_HALF_UP))
    return Quote(
        symbol=str(row["Code"]).strip(),
        name=str(row["Name"]).strip(),
        trade_date=parse_date(str(row["Date"])),
        open=as_float(row.get("OpeningPrice"), price=True),
        high=as_float(row.get("HighestPrice"), price=True),
        low=as_float(row.get("LowestPrice"), price=True),
        close=float(close) if close is not None else None,
        change=float(change) if change is not None else None,
        change_percent=percent,
        volume=as_int(row.get("TradeVolume")),
        turnover=as_int(row.get("TradeValue")),
        transactions=as_int(row.get("Transaction")),
    )


def parse_history_row(row: list) -> HistoryPoint:
    if len(row) < 9:
        raise ValueError("History row has fewer than nine fields")
    return HistoryPoint(
        date=parse_date(str(row[0])),
        volume=as_int(row[1]),
        turnover=as_int(row[2]),
        open=as_float(row[3], price=True),
        high=as_float(row[4], price=True),
        low=as_float(row[5], price=True),
        close=as_float(row[6], price=True),
        change=as_float(row[7]),
        transactions=as_int(row[8]),
    )


def validate_month(month: str | None, today: date | None = None) -> str:
    today = today or datetime.now(TAIPEI).date()
    month = month or today.strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("月份格式須為 YYYY-MM")
    try:
        selected = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise ValueError("請輸入有效月份") from None
    offset = (today.year - selected.year) * 12 + today.month - selected.month
    if not 0 <= offset <= 11:
        raise ValueError("可查詢本月及之前 11 個月的資料")
    return month


class StockService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings
        self.snapshot_cache: TTLCache[dict[str, Quote]] = TTLCache(
            max_entries=1, max_stale=settings.max_stale, backoff=settings.failure_backoff
        )
        self.history_cache: TTLCache[list[HistoryPoint]] = TTLCache(
            max_entries=128, max_stale=settings.max_stale, backoff=settings.failure_backoff
        )

    async def _json(self, url: str, params: dict | None = None):
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", extra={"event": "upstream_timeout"})
            raise UpstreamError("UPSTREAM_TIMEOUT", "證交所回應逾時，請稍後再試。", 504) from None
        except httpx.HTTPStatusError as exc:
            status = 503 if exc.response.status_code == 429 else 502
            logger.warning("upstream_http_error", extra={"event": "upstream_http_error"})
            raise UpstreamError("UPSTREAM_UNAVAILABLE", "證交所服務暫時無法使用，請稍後再試。", status) from None
        except (httpx.RequestError, ValueError):
            logger.warning("upstream_invalid_response", extra={"event": "upstream_invalid_response"})
            raise UpstreamError("UPSTREAM_UNAVAILABLE", "暫時無法取得證交所資料，請稍後再試。") from None

    async def snapshot(self) -> CacheResult[dict[str, Quote]]:
        async def fetch() -> dict[str, Quote]:
            payload = await self._json(SNAPSHOT_URL)
            if not isinstance(payload, list) or not payload:
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所目前未提供有效行情資料。")
            result = {}
            try:
                for row in payload:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid quote row")
                    quote = parse_quote(row)
                    if not re.fullmatch(r"[0-9A-Z]{4,6}", quote.symbol) or not quote.name:
                        raise ValueError("Invalid security identity")
                    result[quote.symbol] = quote
            except (KeyError, TypeError, ValueError):
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所行情格式異常，請稍後再試。") from None
            # Never publish a partial snapshot or combine dates in market statistics.
            latest = max(quote.trade_date for quote in result.values())
            result = {code: quote for code, quote in result.items() if quote.trade_date == latest}
            if latest > datetime.now(TAIPEI).date():
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所交易日期異常，請稍後再試。")
            return result

        return await self.snapshot_cache.get("snapshot", fetch, self.settings.cache_ttl)

    async def history(self, symbol: str, month: str) -> CacheResult[list[HistoryPoint]]:
        async def fetch() -> list[HistoryPoint]:
            payload = await self._json(
                HISTORY_URL,
                {"response": "json", "date": month.replace("-", "") + "01", "stockNo": symbol},
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("stat"), str):
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所歷史行情格式異常。")
            if payload["stat"] != "OK":
                # TWSE explicitly reports an empty month as a non-OK stat string.
                if "沒有符合" in payload["stat"] or "無資料" in payload["stat"]:
                    return []
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所目前未提供此月份的歷史行情。")
            if not isinstance(payload.get("data"), list):
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所歷史行情格式異常。")
            try:
                if any(not isinstance(row, list) for row in payload["data"]):
                    raise ValueError("Invalid history row")
                points = [parse_history_row(row) for row in payload["data"]]
                if any(p.date.strftime("%Y-%m") != month for p in points):
                    raise ValueError("Wrong history month")
                if any(p.date > datetime.now(TAIPEI).date() for p in points):
                    raise ValueError("Future history date")
            except (TypeError, ValueError):
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所歷史行情格式異常。") from None
            return sorted(points, key=lambda point: point.date)

        current_month = datetime.now(TAIPEI).strftime("%Y-%m")
        ttl = self.settings.history_cache_ttl if month == current_month else 86400
        return await self.history_cache.get(f"{symbol}:{month}", fetch, ttl)


def metadata(result: CacheResult, url: str = SNAPSHOT_URL) -> Metadata:
    return Metadata(
        source_url=url,
        retrieved_at=result.fetched_at,
        cached=result.cached,
        stale=result.stale,
        warning="資料來源暫時無法更新，目前顯示先前取得的資料。" if result.stale else None,
    )
