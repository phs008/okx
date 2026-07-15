from __future__ import annotations

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


class CachedMarketClient:
    def __init__(self, upstream: UpstreamMarket, store: SqliteCandleStore) -> None:
        self.upstream = upstream
        self.store = store

    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]:
        return self.upstream.get_perp_instruments(quote_currency)

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        return self.upstream.get_24h_volume(instrument_id)

    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        latest_remote = self._latest_completed_candle(instrument_id, bar)
        if latest_remote is None:
            return self.store.recent_candles(instrument_id, bar, limit)

        latest_local_ts = self.store.latest_ts(instrument_id, bar)
        if latest_local_ts is None:
            self.store.upsert_candles(
                instrument_id,
                bar,
                [candle for candle in self.upstream.get_candles(instrument_id, bar, limit) if candle.confirmed],
            )
        elif latest_remote.ts > latest_local_ts:
            self._sync_missing_candles(instrument_id, bar, latest_local_ts, latest_remote.ts)

        return self.store.recent_candles(instrument_id, bar, limit)

    def _latest_completed_candle(self, instrument_id: str, bar: str) -> Candle | None:
        candles = self.upstream.get_candles(instrument_id, bar, 2)
        completed = [candle for candle in candles if candle.confirmed]
        return completed[-1] if completed else None

    def _sync_missing_candles(
        self,
        instrument_id: str,
        bar: str,
        latest_local_ts: int,
        latest_remote_ts: int,
    ) -> None:
        interval_ms = BAR_INTERVAL_MS[bar]
        missing_count = max(1, (latest_remote_ts - latest_local_ts) // interval_ms)
        candles = self.upstream.get_candles(instrument_id, bar, missing_count + 1)
        missing = [
            candle
            for candle in candles
            if candle.confirmed and latest_local_ts < candle.ts <= latest_remote_ts
        ]
        self.store.upsert_candles(instrument_id, bar, missing)
