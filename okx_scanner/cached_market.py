from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from .models import Candle, Instrument
from .sqlite_store import SqliteCandleStore


BAR_INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
}


class UpstreamMarket(Protocol):
    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]: ...
    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]: ...
    def get_24h_volume(self, instrument_id: str) -> Decimal: ...
    def get_24h_volumes(self, quote_currency: str) -> dict[str, Decimal]: ...


class CachedMarketClient:
    def __init__(
        self,
        upstream: UpstreamMarket,
        store: SqliteCandleStore,
        *,
        backfill_limit: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.upstream = upstream
        self.store = store
        self.backfill_limit = backfill_limit
        self._clock = clock

    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]:
        return self.upstream.get_perp_instruments(quote_currency)

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        return self.upstream.get_24h_volume(instrument_id)

    def get_24h_volumes(self, quote_currency: str) -> dict[str, Decimal]:
        return self.upstream.get_24h_volumes(quote_currency)

    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        expected_latest_ts = self._expected_latest_completed_ts(bar)
        latest_local_ts = self.store.latest_ts(instrument_id, bar)
        if latest_local_ts is None:
            self.store.upsert_candles(
                instrument_id,
                bar,
                [
                    candle
                    for candle in self.upstream.get_candles(instrument_id, bar, self.backfill_limit)
                    if candle.confirmed
                ],
            )
        elif latest_local_ts < expected_latest_ts:
            self._sync_missing_candles(instrument_id, bar, latest_local_ts, expected_latest_ts)

        return self.store.recent_candles(instrument_id, bar, limit)

    def _expected_latest_completed_ts(self, bar: str) -> int:
        interval_ms = BAR_INTERVAL_MS[bar]
        now_ms = int(self._clock() * 1000)
        return max(0, (now_ms // interval_ms) * interval_ms - interval_ms)

    def _sync_missing_candles(
        self,
        instrument_id: str,
        bar: str,
        latest_local_ts: int,
        target_latest_ts: int,
    ) -> None:
        interval_ms = BAR_INTERVAL_MS[bar]
        missing_count = max(1, (target_latest_ts - latest_local_ts) // interval_ms)
        candles = self.upstream.get_candles(instrument_id, bar, missing_count + 1)
        missing = [
            candle
            for candle in candles
            if candle.confirmed and latest_local_ts < candle.ts <= target_latest_ts
        ]
        self.store.upsert_candles(instrument_id, bar, missing)
