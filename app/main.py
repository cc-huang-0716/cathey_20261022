import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.models import HistoryResponse, MarketResponse, MarketSummary, QuoteResponse, SearchResponse
from app.services.cache import UpstreamError
from app.services.stocks import HISTORY_URL, StockService, metadata, normalize_query, validate_month

STATIC = Path(__file__).parent / "static"
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
            headers={"User-Agent": "MarketBrief/1.0 (educational stock dashboard)", "Accept": "application/json"},
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
        logger.info("http_request", extra={
            "request_id": request.state.request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        })
        return response

    def error_response(request: Request, code: str, message: str, status: int):
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": message, "request_id": request.state.request_id}},
        )

    @application.exception_handler(UpstreamError)
    async def upstream_error(request: Request, exc: UpstreamError):
        response = error_response(request, exc.code, exc.message, exc.status)
        response.headers["Retry-After"] = str(settings.failure_backoff)
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, "INVALID_REQUEST", "查詢參數格式不正確，請參考 API 文件。", 422)

    @application.get("/", include_in_schema=False)
    async def homepage():
        return FileResponse(STATIC / "index.html")

    @application.get("/health", tags=["System"])
    async def health():
        """Liveness check; intentionally independent of the external data provider."""
        return {"status": "ok", "service": "market-brief", "version": "1.0.0"}

    @application.get("/api/market", response_model=MarketResponse, tags=["Market"])
    async def market(
        request: Request, sort: Literal["volume", "gainers", "losers"] = "volume"
    ):
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
            leaders = sorted(eligible, key=lambda quote: quote.change_percent, reverse=sort == "gainers")
        return MarketResponse(
            summary=MarketSummary(
                trade_date=max(quote.trade_date for quote in quotes),
                securities=len(quotes),
                advancing=sum(quote.change > 0 for quote in comparable),
                declining=sum(quote.change < 0 for quote in comparable),
                unchanged=sum(quote.change == 0 for quote in comparable),
                unavailable=len(quotes) - len(comparable),
                total_volume=sum(quote.volume or 0 for quote in quotes),
                total_turnover=sum(quote.turnover or 0 for quote in quotes),
            ),
            featured=[result.data[code] for code in FEATURED if code in result.data],
            leaders=leaders[:10],
            sort=sort,
            meta=metadata(result),
        )

    @application.get("/api/stocks", response_model=SearchResponse, tags=["Stocks"])
    async def search(
        request: Request,
        q: str = Query(default="", max_length=40, description="股票代號或公司名稱，例如 2330、台積電"),
        limit: int = Query(default=10, ge=1, le=20),
    ):
        result = await request.app.state.stocks.snapshot()
        query = normalize_query(q)
        matches = [
            quote for quote in result.data.values()
            if query in normalize_query(quote.symbol) or query in normalize_query(quote.name)
        ]
        matches.sort(key=lambda quote: (
            normalize_query(quote.symbol) != query and normalize_query(quote.name) != query,
            not normalize_query(quote.symbol).startswith(query),
            quote.symbol,
        ))
        return SearchResponse(data=matches[:limit], count=len(matches), meta=metadata(result))

    async def find_quote(request: Request, symbol: str):
        result = await request.app.state.stocks.snapshot()
        quote = result.data.get(symbol.upper())
        return result, quote

    @application.get("/api/stocks/{symbol}/history", response_model=HistoryResponse, tags=["Stocks"])
    async def history(
        request: Request,
        symbol: str,
        month: str | None = Query(default=None, description="YYYY-MM；預設本月，最多查詢最近 12 個月"),
    ):
        try:
            selected_month = validate_month(month)
        except ValueError as exc:
            return error_response(request, "INVALID_MONTH", str(exc), 422)
        if len(symbol) > 6 or not symbol.isascii() or not symbol.isalnum():
            return error_response(request, "INVALID_SYMBOL", "請輸入有效的上市證券代號。", 422)
        _, quote = await find_quote(request, symbol)
        if quote is None:
            return error_response(request, "STOCK_NOT_FOUND", "查無此上市證券，請確認名稱或代號。", 404)
        result = await request.app.state.stocks.history(quote.symbol, selected_month)
        return HistoryResponse(
            symbol=quote.symbol, name=quote.name, month=selected_month,
            data=result.data, meta=metadata(result, HISTORY_URL),
        )

    @application.get("/api/stocks/{symbol}", response_model=QuoteResponse, tags=["Stocks"])
    async def quote(request: Request, symbol: str):
        if len(symbol) > 6 or not symbol.isascii() or not symbol.isalnum():
            return error_response(request, "INVALID_SYMBOL", "請輸入有效的上市證券代號。", 422)
        result, item = await find_quote(request, symbol)
        if item is None:
            return error_response(request, "STOCK_NOT_FOUND", "查無此上市證券，請確認名稱或代號。", 404)
        return QuoteResponse(data=item, meta=metadata(result))

    application.mount("/static", StaticFiles(directory=STATIC), name="static")
    return application


app = create_app()
