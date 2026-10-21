"""Bounded, process-local TTL cache with single-flight refresh and stale-on-error."""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar

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

    async def get(
        self, key: str, fetch: Callable[[], Awaitable[T]], ttl: int
    ) -> CacheResult[T]:
        entry = self.entries.get(key)
        if entry and self.clock() < entry.expires:
            return self._result(key, entry)

        # A second check inside the lock coalesces simultaneous refresh requests.
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
