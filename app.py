import asyncio
import json
import logging
import os
import re
import sys
import time
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Generic, Literal, TypeVar
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field


def positive_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class Settings:
    cache_ttl: int = 300
    history_cache_ttl: int = 900
    max_stale: int = 3600
    upstream_timeout: int = 12
    failure_backoff: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            cache_ttl=positive_env("CACHE_TTL_SECONDS", 300),
            history_cache_ttl=positive_env("HISTORY_CACHE_TTL_SECONDS", 900),
            max_stale=positive_env("MAX_STALE_SECONDS", 3600),
            upstream_timeout=positive_env("UPSTREAM_TIMEOUT_SECONDS", 12),
            failure_backoff=positive_env("UPSTREAM_FAILURE_BACKOFF_SECONDS", 30),
        )


class Quote(BaseModel):
    symbol: str
    name: str
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change: float | None
    change_percent: float | None
    volume: int | None = Field(description="成交股數，單位為股")
    turnover: int | None = Field(description="成交金額，單位為新臺幣元")
    transactions: int | None


class Metadata(BaseModel):
    source: str = "臺灣證券交易所 TWSE"
    source_url: str
    retrieved_at: datetime
    cached: bool
    stale: bool
    warning: str | None = None
    timezone: str = "Asia/Taipei"
    price_type: Literal["daily_close"] = "daily_close"


class QuoteResponse(BaseModel):
    data: Quote
    meta: Metadata


class SearchResponse(BaseModel):
    data: list[Quote]
    count: int
    meta: Metadata


class MarketSummary(BaseModel):
    trade_date: date
    securities: int
    advancing: int
    declining: int
    unchanged: int
    unavailable: int
    total_volume: int
    total_turnover: int


class MarketResponse(BaseModel):
    summary: MarketSummary
    featured: list[Quote]
    leaders: list[Quote]
    sort: Literal["volume", "gainers", "losers"]
    meta: Metadata


class HistoryPoint(BaseModel):
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    turnover: int | None
    change: float | None
    transactions: int | None


class HistoryResponse(BaseModel):
    symbol: str
    name: str
    month: str
    data: list[HistoryPoint]
    meta: Metadata


T = TypeVar("T")


class UpstreamError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass
class Entry(Generic[T]):
    data: T
    fetched_at: datetime
    expires: float


@dataclass
class CacheResult(Generic[T]):
    data: T
    fetched_at: datetime
    cached: bool
    stale: bool = False


class TTLCache(Generic[T]):
    def __init__(
        self,
        max_entries: int = 128,
        max_stale: int = 3600,
        backoff: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.entries: OrderedDict[str, Entry[T]] = OrderedDict()
        self.failures: OrderedDict[str, tuple[float, UpstreamError]] = OrderedDict()
        self.lock = asyncio.Lock()
        self.max_entries = max_entries
        self.max_stale = max_stale
        self.backoff = backoff
        self.clock = clock

    def _result(self, key: str, entry: Entry[T], stale: bool = False) -> CacheResult[T]:
        self.entries.move_to_end(key)
        return CacheResult(entry.data, entry.fetched_at, cached=True, stale=stale)

    async def get(self, key: str, fetch: Callable[[], Awaitable[T]], ttl: int) -> CacheResult[T]:
        entry = self.entries.get(key)
        if entry and self.clock() < entry.expires:
            return self._result(key, entry)
        async with self.lock:
            now = self.clock()
            entry = self.entries.get(key)
            if entry and now < entry.expires:
                return self._result(key, entry)
            failure = self.failures.get(key)
            if failure and now < failure[0]:
                if entry and now < entry.expires + self.max_stale:
                    return self._result(key, entry, stale=True)
                raise failure[1]
            try:
                data = await fetch()
            except UpstreamError as exc:
                now = self.clock()
                self.failures[key] = (now + self.backoff, exc)
                self.failures.move_to_end(key)
                while len(self.failures) > self.max_entries:
                    self.failures.popitem(last=False)
                if entry and now < entry.expires + self.max_stale:
                    return self._result(key, entry, stale=True)
                raise
            entry = Entry(data, datetime.now(timezone.utc), self.clock() + ttl)
            self.entries[key] = entry
            self.entries.move_to_end(key)
            self.failures.pop(key, None)
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)
            return CacheResult(data, entry.fetched_at, cached=False)


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
    elif re.fullmatch("\\d{7}", raw):
        year, month, day = (int(raw[:3]), int(raw[3:5]), int(raw[5:]))
    elif re.fullmatch("\\d{8}", raw):
        year, month, day = (int(raw[:4]), int(raw[4:6]), int(raw[6:]))
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
    if not re.fullmatch("\\d{4}-\\d{2}", month):
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
            raise UpstreamError(
                "UPSTREAM_UNAVAILABLE", "證交所服務暫時無法使用，請稍後再試。", status
            ) from None
        except (httpx.RequestError, ValueError):
            logger.warning(
                "upstream_invalid_response", extra={"event": "upstream_invalid_response"}
            )
            raise UpstreamError(
                "UPSTREAM_UNAVAILABLE", "暫時無法取得證交所資料，請稍後再試。"
            ) from None

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
                    if not re.fullmatch("[0-9A-Z]{4,6}", quote.symbol) or not quote.name:
                        raise ValueError("Invalid security identity")
                    result[quote.symbol] = quote
            except (KeyError, TypeError, ValueError):
                raise UpstreamError(
                    "UPSTREAM_INVALID_DATA", "證交所行情格式異常，請稍後再試。"
                ) from None
            latest = max((quote.trade_date for quote in result.values()))
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
                if "沒有符合" in payload["stat"] or "無資料" in payload["stat"]:
                    return []
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所目前未提供此月份的歷史行情。")
            if not isinstance(payload.get("data"), list):
                raise UpstreamError("UPSTREAM_INVALID_DATA", "證交所歷史行情格式異常。")
            try:
                if any((not isinstance(row, list) for row in payload["data"])):
                    raise ValueError("Invalid history row")
                points = [parse_history_row(row) for row in payload["data"]]
                if any((p.date.strftime("%Y-%m") != month for p in points)):
                    raise ValueError("Wrong history month")
                if any((p.date > datetime.now(TAIPEI).date() for p in points)):
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


INDEX = Path(__file__).with_name("index.html")
FEATURED = ("2330", "2317", "2454", "2882", "0050", "2308")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "event"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


logger = logging.getLogger("marketbrief")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_app(settings: Settings | None = None, transport=None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.upstream_timeout, connect=5),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={
                "User-Agent": "MarketBrief/1.0 (educational stock dashboard)",
                "Accept": "application/json",
            },
            transport=transport,
            follow_redirects=True,
        ) as client:
            application.state.stocks = StockService(client, settings)
            yield

    application = FastAPI(
        title="Market Brief｜股日 API",
        description="臺灣上市證券日行情。資料為證交所公布之最新交易日資料，非盤中即時報價。金額單位：新臺幣元；成交量單位：股。",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_log(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "http_request",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    def error_response(request: Request, code: str, message: str, status: int):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message, "request_id": request.state.request_id}
            },
        )

    @application.exception_handler(UpstreamError)
    async def upstream_error(request: Request, exc: UpstreamError):
        response = error_response(request, exc.code, exc.message, exc.status)
        response.headers["Retry-After"] = str(settings.failure_backoff)
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(
            request, "INVALID_REQUEST", "查詢參數格式不正確，請參考 API 文件。", 422
        )

    @application.get("/", include_in_schema=False)
    async def homepage():
        return FileResponse(INDEX)

    @application.get("/health", tags=["System"])
    async def health():
        return {"status": "ok", "service": "market-brief", "version": "1.0.0"}

    @application.get("/api/market", response_model=MarketResponse, tags=["Market"])
    async def market(request: Request, sort: Literal["volume", "gainers", "losers"] = "volume"):
        result = await request.app.state.stocks.snapshot()
        quotes = list(result.data.values())
        priced = [quote for quote in quotes if quote.close is not None]
        comparable = [quote for quote in priced if quote.change is not None]
        if sort == "volume":
            leaders = sorted(priced, key=lambda quote: quote.volume or 0, reverse=True)
        else:
            eligible = [quote for quote in priced if quote.change_percent is not None]
            if sort == "gainers":
                eligible = [quote for quote in eligible if quote.change_percent > 0]
            else:
                eligible = [quote for quote in eligible if quote.change_percent < 0]
            leaders = sorted(
                eligible, key=lambda quote: quote.change_percent, reverse=sort == "gainers"
            )
        return MarketResponse(
            summary=MarketSummary(
                trade_date=max((quote.trade_date for quote in quotes)),
                securities=len(quotes),
                advancing=sum((quote.change > 0 for quote in comparable)),
                declining=sum((quote.change < 0 for quote in comparable)),
                unchanged=sum((quote.change == 0 for quote in comparable)),
                unavailable=len(quotes) - len(comparable),
                total_volume=sum((quote.volume or 0 for quote in quotes)),
                total_turnover=sum((quote.turnover or 0 for quote in quotes)),
            ),
            featured=[result.data[code] for code in FEATURED if code in result.data],
            leaders=leaders[:10],
            sort=sort,
            meta=metadata(result),
        )

    @application.get("/api/stocks", response_model=SearchResponse, tags=["Stocks"])
    async def search(
        request: Request,
        q: str = Query(
            default="", max_length=40, description="股票代號或公司名稱，例如 2330、台積電"
        ),
        limit: int = Query(default=10, ge=1, le=20),
    ):
        result = await request.app.state.stocks.snapshot()
        query = normalize_query(q)
        matches = [
            quote
            for quote in result.data.values()
            if query in normalize_query(quote.symbol) or query in normalize_query(quote.name)
        ]
        matches.sort(
            key=lambda quote: (
                normalize_query(quote.symbol) != query and normalize_query(quote.name) != query,
                not normalize_query(quote.symbol).startswith(query),
                quote.symbol,
            )
        )
        return SearchResponse(data=matches[:limit], count=len(matches), meta=metadata(result))

    async def find_quote(request: Request, symbol: str):
        result = await request.app.state.stocks.snapshot()
        quote = result.data.get(symbol.upper())
        return (result, quote)

    @application.get(
        "/api/stocks/{symbol}/history", response_model=HistoryResponse, tags=["Stocks"]
    )
    async def history(
        request: Request,
        symbol: str,
        month: str | None = Query(
            default=None, description="YYYY-MM；預設本月，最多查詢最近 12 個月"
        ),
    ):
        try:
            selected_month = validate_month(month)
        except ValueError as exc:
            return error_response(request, "INVALID_MONTH", str(exc), 422)
        if len(symbol) > 6 or not symbol.isascii() or (not symbol.isalnum()):
            return error_response(request, "INVALID_SYMBOL", "請輸入有效的上市證券代號。", 422)
        _, quote = await find_quote(request, symbol)
        if quote is None:
            return error_response(
                request, "STOCK_NOT_FOUND", "查無此上市證券，請確認名稱或代號。", 404
            )
        result = await request.app.state.stocks.history(quote.symbol, selected_month)
        return HistoryResponse(
            symbol=quote.symbol,
            name=quote.name,
            month=selected_month,
            data=result.data,
            meta=metadata(result, HISTORY_URL),
        )

    @application.get("/api/stocks/{symbol}", response_model=QuoteResponse, tags=["Stocks"])
    async def quote(request: Request, symbol: str):
        if len(symbol) > 6 or not symbol.isascii() or (not symbol.isalnum()):
            return error_response(request, "INVALID_SYMBOL", "請輸入有效的上市證券代號。", 422)
        result, item = await find_quote(request, symbol)
        if item is None:
            return error_response(
                request, "STOCK_NOT_FOUND", "查無此上市證券，請確認名稱或代號。", 404
            )
        return QuoteResponse(data=item, meta=metadata(result))

    return application


app = create_app()
