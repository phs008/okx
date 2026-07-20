from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from .config import Settings
from .models import Instrument
from .power_candle import PowerCandleSignal, detect_first_power_candles


class PowerMarketClient(Protocol):
    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]: ...
    def get_candles(self, instrument_id: str, bar: str, limit: int): ...
    def get_24h_turnovers(self, quote_currency: str) -> dict[str, Decimal]: ...


class PowerNotifier(Protocol):
    def send_power_signals(self, signals: list[PowerCandleSignal]) -> None: ...


@dataclass(frozen=True, slots=True)
class PowerScanSummary:
    started_at: str
    universe: int
    scanned: int
    errors: int
    signals: list[PowerCandleSignal]

    def as_dict(self) -> dict[str, object]:
        return {
            "startedAt": self.started_at,
            "universe": self.universe,
            "scanned": self.scanned,
            "errors": self.errors,
            "powerHitCount": len(self.signals),
            "hits": [signal.as_dict() for signal in self.signals],
        }


class PowerScannerService:
    def __init__(self, settings: Settings, market: PowerMarketClient, notifier: PowerNotifier | None) -> None:
        self.settings = settings
        self.market = market
        self.notifier = notifier
        self._processed_candle_ts: dict[str, int] = {}

    def scan_once(self, *, dry_run: bool = False) -> PowerScanSummary:
        started_at = datetime.now(UTC)
        instruments = self.market.get_perp_instruments(self.settings.quote_currency)
        turnover_24h_by_instrument = self.market.get_24h_turnovers(self.settings.quote_currency)
        signals: list[PowerCandleSignal] = []
        scanned = 0
        errors = 0
        for instrument in instruments:
            try:
                signal = self._scan_instrument(instrument.instrument_id)
            except Exception:
                errors += 1
                continue
            scanned += 1
            if signal is not None:
                try:
                    turnover_24h = turnover_24h_by_instrument[instrument.instrument_id]
                except KeyError:
                    errors += 1
                    continue
                signals.append(replace(signal, turnover_24h=turnover_24h))

        if signals and not dry_run:
            if self.notifier is None:
                raise RuntimeError("Power-candle Discord notifier is not configured")
            self.notifier.send_power_signals(signals)
        return PowerScanSummary(started_at.isoformat(), len(instruments), scanned, errors, signals)

    def run_forever(self, *, dry_run: bool, output) -> None:
        while True:
            output(self.scan_once(dry_run=dry_run))
            time.sleep(self.settings.scan_interval_seconds)

    def _scan_instrument(self, instrument_id: str) -> PowerCandleSignal | None:
        candles = self.market.get_candles(
            instrument_id,
            self.settings.bar,
            self.settings.power_indicator_lookback,
        )
        completed = [candle for candle in candles if candle.confirmed]
        if not completed:
            return None
        latest = completed[-1]
        if self._processed_candle_ts.get(instrument_id) == latest.ts:
            return None
        self._processed_candle_ts[instrument_id] = latest.ts
        return next(
            (
                signal
                for signal in detect_first_power_candles(instrument_id, completed)
                if signal.candle_ts == latest.ts
            ),
            None,
        )
