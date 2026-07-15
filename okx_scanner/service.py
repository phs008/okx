from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .config import Settings
from .indicators import wilder_rsi
from .models import Candle, Instrument, RsiHit


class MarketClient(Protocol):
    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]: ...
    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]: ...


class Notifier(Protocol):
    def send_hits(self, hits: list[RsiHit]) -> None: ...


@dataclass(frozen=True, slots=True)
class ScanSummary:
    started_at: str
    universe: int
    scanned: int
    errors: int
    hits: list[RsiHit]

    def as_dict(self) -> dict[str, object]:
        return {
            "startedAt": self.started_at,
            "universe": self.universe,
            "scanned": self.scanned,
            "errors": self.errors,
            "hitCount": len(self.hits),
            "hits": [hit.as_dict() for hit in self.hits],
        }


class ScannerService:
    def __init__(
        self,
        settings: Settings,
        market: MarketClient,
        notifier: Notifier | None,
        *,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.market = market
        self.notifier = notifier
        self._logger = logger

    def scan_once(self, *, dry_run: bool = False) -> ScanSummary:
        started_at = datetime.now(UTC)
        started = time.monotonic()
        self._log(f"scan started dry_run={dry_run}")
        instruments = self.market.get_perp_instruments(self.settings.quote_currency)
        self._log(f"loaded {len(instruments)} perp instruments quote={self.settings.quote_currency}")
        hits: list[RsiHit] = []
        scanned = 0
        errors = 0

        for instrument in instruments:
            try:
                hit = self._scan_instrument(instrument.instrument_id)
            except Exception:
                errors += 1
                continue
            scanned += 1
            if hit is not None:
                hits.append(hit)

        if hits and not dry_run:
            if self.notifier is None:
                raise RuntimeError("Discord notifier is not configured")
            self._log(f"discord send started hit_count={len(hits)}")
            try:
                self.notifier.send_hits(hits)
            except Exception as exc:
                self._log(f"discord send failed error={type(exc).__name__}")
                raise
            self._log(f"discord send completed hit_count={len(hits)}")
        elif hits:
            self._log(f"dry-run skipped discord hit_count={len(hits)}")
        else:
            self._log("no RSI hits; discord send skipped")

        duration = time.monotonic() - started
        self._log(
            f"scan completed scanned={scanned} errors={errors} hit_count={len(hits)} duration_seconds={duration:.3f}"
        )

        return ScanSummary(
            started_at=started_at.isoformat(),
            universe=len(instruments),
            scanned=scanned,
            errors=errors,
            hits=hits,
        )

    def run_forever(self, *, dry_run: bool, output) -> None:
        self._log(f"daemon started interval_seconds={self.settings.scan_interval_seconds}")
        while True:
            output(self.scan_once(dry_run=dry_run))
            self._log(f"sleeping seconds={self.settings.scan_interval_seconds}")
            time.sleep(self.settings.scan_interval_seconds)

    def _scan_instrument(self, instrument_id: str) -> RsiHit | None:
        candles = self.market.get_candles(
            instrument_id,
            self.settings.bar,
            self.settings.candle_limit,
        )
        completed = [candle for candle in candles if candle.confirmed]
        if len(completed) < self.settings.rsi_period + 1:
            return None
        latest = completed[-1]
        rsi = wilder_rsi([candle.close for candle in completed], self.settings.rsi_period)
        if rsi <= self.settings.rsi_oversold or rsi >= self.settings.rsi_overbought:
            return RsiHit(instrument_id=instrument_id, candle_ts=latest.ts, rsi=rsi)
        return None

    def _log(self, message: str) -> None:
        if self._logger is not None:
            self._logger(message)
