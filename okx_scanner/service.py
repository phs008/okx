from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from .config import Settings
from .indicators import vwma, weighted_moving_average, wilder_rsi_series
from .models import Candle, Instrument, RsiHit


class MarketClient(Protocol):
    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]: ...
    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]: ...
    def get_24h_volumes(self, quote_currency: str) -> dict[str, Decimal]: ...
    def get_24h_turnovers(self, quote_currency: str) -> dict[str, Decimal]: ...


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
        self._processed_candle_ts: dict[str, int] = {}

    def scan_once(self, *, dry_run: bool = False) -> ScanSummary:
        started_at = datetime.now(UTC)
        started = time.monotonic()
        self._log(f"scan started dry_run={dry_run}")
        instruments = self.market.get_perp_instruments(self.settings.quote_currency)
        self._log(f"loaded {len(instruments)} perp instruments quote={self.settings.quote_currency}")
        volume_24h_by_instrument = self.market.get_24h_volumes(self.settings.quote_currency)
        self._log(f"loaded {len(volume_24h_by_instrument)} ticker 24h volumes quote={self.settings.quote_currency}")
        turnover_24h_by_instrument = self.market.get_24h_turnovers(self.settings.quote_currency)
        self._log(f"loaded {len(turnover_24h_by_instrument)} ticker 24h turnovers quote={self.settings.quote_currency}")
        hits: list[RsiHit] = []
        scanned = 0
        errors = 0

        total = len(instruments)
        for index, instrument in enumerate(instruments, start=1):
            try:
                self._log(f"candle sync progress {index}/{total} instrument={instrument.instrument_id}")
                hit = self._scan_instrument(instrument, volume_24h_by_instrument, turnover_24h_by_instrument)
            except Exception:
                errors += 1
                continue
            scanned += 1
            if hit is not None:
                hits.append(hit)

        if hits and not dry_run:
            if self.notifier is None:
                raise RuntimeError("Discord notifier is not configured")
            try:
                self.notifier.send_hits(hits)
            except Exception as exc:
                self._log(f"discord send failed error={type(exc).__name__}")
                raise
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

    def _scan_instrument(
        self,
        instrument: Instrument,
        volume_24h_by_instrument: dict[str, Decimal],
        turnover_24h_by_instrument: dict[str, Decimal],
    ) -> RsiHit | None:
        instrument_id = instrument.instrument_id
        candles = self.market.get_candles(
            instrument_id,
            self.settings.bar,
            self.settings.indicator_lookback,
        )
        completed = [candle for candle in candles if candle.confirmed]
        minimum_candles = max(
            self.settings.rsi_period + self.settings.rsi_wma_period + 1,
            self.settings.vwma_period + 1,
        )
        if len(completed) < minimum_candles:
            return None
        latest = completed[-1]
        if self._processed_candle_ts.get(instrument_id) == latest.ts:
            return None
        closes = [candle.close for candle in completed]
        volumes = [candle.volume for candle in completed]
        rsi_values = wilder_rsi_series(closes, self.settings.rsi_period)
        rsi = rsi_values[-1]
        latest_rsi_wma = weighted_moving_average(rsi_values, self.settings.rsi_wma_period)
        previous_rsi_wma = weighted_moving_average(rsi_values[:-1], self.settings.rsi_wma_period)
        rsi_signal = _rsi_wma_signal(rsi_values[-2], previous_rsi_wma, rsi, latest_rsi_wma)
        latest_vwma = vwma(closes, volumes, self.settings.vwma_period)
        previous_vwma = vwma(closes[:-1], volumes[:-1], self.settings.vwma_period)
        vwma_signal = _vwma_signal(completed[-2].close, previous_vwma, latest.close, latest_vwma)
        if rsi_signal == vwma_signal and vwma_signal in {"CROSS_ABOVE", "CROSS_BELOW"}:
            try:
                volume_24h = volume_24h_by_instrument[instrument_id]
                turnover_24h = turnover_24h_by_instrument[instrument_id]
            except KeyError as exc:
                raise RuntimeError(f"missing 24h ticker value for {instrument_id}") from exc
            self._processed_candle_ts[instrument_id] = latest.ts
            return RsiHit(
                instrument_id=instrument_id,
                candle_ts=latest.ts,
                rsi=rsi,
                rsi_wma=latest_rsi_wma,
                volume_24h=volume_24h,
                turnover_24h=turnover_24h,
                signal_volume=latest.volume * instrument.contract_value,
                close=latest.close,
                change_percent=_price_change_percent(completed[-2].close, latest.close),
                vwma_100=latest_vwma,
                vwma_signal=vwma_signal,
            )
        self._processed_candle_ts[instrument_id] = latest.ts
        return None

    def _log(self, message: str) -> None:
        if self._logger is not None:
            self._logger(message)


def _vwma_signal(previous_close: Decimal, previous_vwma: Decimal, latest_close: Decimal, latest_vwma: Decimal) -> str:
    if previous_close <= previous_vwma and latest_close > latest_vwma:
        return "CROSS_ABOVE"
    if previous_close >= previous_vwma and latest_close < latest_vwma:
        return "CROSS_BELOW"
    return "ABOVE" if latest_close > latest_vwma else "BELOW" if latest_close < latest_vwma else "TOUCH"


def _rsi_wma_signal(previous_rsi: float, previous_wma: float, latest_rsi: float, latest_wma: float) -> str:
    if previous_rsi <= previous_wma and latest_rsi > latest_wma:
        return "CROSS_ABOVE"
    if previous_rsi >= previous_wma and latest_rsi < latest_wma:
        return "CROSS_BELOW"
    return "ABOVE" if latest_rsi > latest_wma else "BELOW" if latest_rsi < latest_wma else "TOUCH"


def _price_change_percent(previous_close: Decimal, latest_close: Decimal) -> Decimal:
    if previous_close == 0:
        return Decimal(0)
    return (latest_close - previous_close) / previous_close * Decimal(100)
