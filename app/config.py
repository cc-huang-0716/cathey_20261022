import os
from dataclasses import dataclass


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
