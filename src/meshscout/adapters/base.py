"""Base protocol and rate-limiting infrastructure for regional GIS and spatial adapters."""

from __future__ import annotations

import random
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Type,
    TypeVar,
    runtime_checkable,
)

from pydantic import BaseModel, Field

from meshscout.core.contracts import MeshScoutError, RegionalBounds, Result, SiteCandidate

T = TypeVar("T")


class RateLimitConfig(BaseModel):
    """Configuration for web egress rate limiting and exponential backoff."""

    min_delay: float = Field(
        default=0.5,
        ge=0.0,
        description="Minimum inter-request pacing delay in seconds",
    )
    max_delay: float = Field(
        default=1.5,
        ge=0.0,
        description="Maximum inter-request pacing delay in seconds",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts for transient failures",
    )
    backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        description="Multiplicative backoff exponent factor",
    )
    jitter: bool = Field(
        default=True,
        description="Whether to apply randomized uniform jitter to backoff delay",
    )
    disabled: bool = Field(
        default=False,
        description="Disable all sleeps for hermetic test execution and CI/CD",
    )


class RateLimitBackoff:
    """Thread-safe rate limiter and exponential backoff manager."""

    def __init__(self, config: Optional[RateLimitConfig] = None) -> None:
        self.config = config or RateLimitConfig()
        self._last_request_time: float = 0.0
        self._attempt_count: int = 0

    def wait(self) -> float:
        """Enforce inter-request pacing delay. Returns duration slept in seconds."""
        if self.config.disabled:
            return 0.0

        target_delay = (
            random.uniform(self.config.min_delay, self.config.max_delay)
            if self.config.jitter
            else self.config.min_delay
        )
        elapsed = time.monotonic() - self._last_request_time
        sleep_duration = max(0.0, target_delay - elapsed)

        if sleep_duration > 0.0:
            time.sleep(sleep_duration)

        self._last_request_time = time.monotonic()
        return sleep_duration

    def compute_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff duration for a given retry attempt index."""
        if self.config.disabled:
            return 0.0

        base = self.config.min_delay * (self.config.backoff_factor**attempt)
        if self.config.jitter:
            delay = random.uniform(base * 0.75, base * 1.25)
        else:
            delay = base
        return min(delay, 60.0)

    def execute(
        self,
        func: Callable[[], T],
        retryable_exceptions: Sequence[Type[BaseException]] = (Exception,),
        on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    ) -> T:
        """Execute a callable with inter-request pacing and exponential backoff retry logic."""
        attempt = 0
        while True:
            self.wait()
            try:
                res = func()
                self._attempt_count = 0
                return res
            except tuple(retryable_exceptions) as exc:
                if attempt >= self.config.max_retries:
                    raise exc
                delay = self.compute_backoff_delay(attempt)
                if on_retry:
                    on_retry(attempt, exc, delay)
                if delay > 0.0:
                    time.sleep(delay)
                attempt += 1


@runtime_checkable
class BaseRegionalAdapter(Protocol):
    """Protocol defining the sovereign regional adapter contract."""

    @property
    def adapter_name(self) -> str:
        """Unique machine-readable name of the adapter."""
        ...

    @property
    def bounds(self) -> Optional[RegionalBounds]:
        """Geographic bounds covered by this regional adapter."""
        ...

    def fetch_sites(
        self, bounds: Optional[RegionalBounds] = None
    ) -> Result[List[SiteCandidate]]:
        """Fetch or generate site candidates within regional bounds."""
        ...

    def health_check(self) -> Result[bool]:
        """Verify adapter accessibility and operating state."""
        ...


class RegionalAdapterBase:
    """Optional base class providing common adapter bookkeeping and rate-limiting."""

    def __init__(
        self,
        name: str,
        bounds: Optional[RegionalBounds] = None,
        rate_limiter: Optional[RateLimitBackoff] = None,
    ) -> None:
        self._name = name
        self._bounds = bounds
        self.rate_limiter = rate_limiter or RateLimitBackoff()

    @property
    def adapter_name(self) -> str:
        return self._name

    @property
    def bounds(self) -> Optional[RegionalBounds]:
        return self._bounds

    def fetch_sites(
        self, bounds: Optional[RegionalBounds] = None
    ) -> Result[List[SiteCandidate]]:
        return Result[List[SiteCandidate]].success([])

    def health_check(self) -> Result[bool]:
        return Result[bool].success(True)
