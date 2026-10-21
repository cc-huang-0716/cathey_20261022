from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


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
