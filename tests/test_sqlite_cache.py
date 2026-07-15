from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from okx_scanner.cached_market import CachedMarketClient
from okx_scanner.models import Candle, Instrument
from okx_scanner.sqlite_store import SqliteCandleStore


def candle(ts: int, close: str = "1") -> Candle:
    price = Decimal(close)
    return Candle(
        ts=ts,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(1),
        confirmed=True,
    )


class FakeUpstream:
    def __init__(self, candles_by_limit: dict[int, list[Candle]]) -> None:
        self.candles_by_limit = candles_by_limit
        self.candle_requests: list[tuple[str, int]] = []

    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]:
        return [Instrument("BTC-USDT-SWAP", quote_currency, "live")]

    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        self.candle_requests.append((instrument_id, limit))
        return self.candles_by_limit[limit]

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        return Decimal("10")


class SqliteCacheTests(unittest.TestCase):
    def test_backfills_when_sqlite_file_has_no_candles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteCandleStore(str(Path(directory) / "candles.sqlite3"))
            upstream = FakeUpstream({
                2: [candle(900_000), candle(1_800_000)],
                5: [candle(index * 900_000) for index in range(1, 6)],
            })
            market = CachedMarketClient(upstream, store, backfill_limit=5)

            candles = market.get_candles("BTC-USDT-SWAP", "15m", 5)

            self.assertEqual(5, len(candles))
            self.assertEqual([2, 5], [request[1] for request in upstream.candle_requests])
            self.assertEqual(5 * 900_000, store.latest_ts("BTC-USDT-SWAP", "15m"))

    def test_fetches_all_missing_gap_candles_after_latest_local_candle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteCandleStore(str(Path(directory) / "candles.sqlite3"))
            store.upsert_candles("BTC-USDT-SWAP", "15m", [candle(900_000), candle(1_800_000)])
            upstream = FakeUpstream({
                2: [candle(3_600_000), candle(4_500_000)],
                4: [candle(1_800_000), candle(2_700_000), candle(3_600_000), candle(4_500_000)],
            })
            market = CachedMarketClient(upstream, store, backfill_limit=5)

            candles = market.get_candles("BTC-USDT-SWAP", "15m", 5)

            self.assertEqual([2, 4], [request[1] for request in upstream.candle_requests])
            self.assertEqual([900_000, 1_800_000, 2_700_000, 3_600_000, 4_500_000], [item.ts for item in candles])
            self.assertEqual(4_500_000, store.latest_ts("BTC-USDT-SWAP", "15m"))

    def test_fetches_only_latest_candle_when_local_is_previous_candle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteCandleStore(str(Path(directory) / "candles.sqlite3"))
            store.upsert_candles("BTC-USDT-SWAP", "15m", [candle(900_000), candle(1_800_000)])
            upstream = FakeUpstream({
                2: [candle(1_800_000), candle(2_700_000)],
                2 + 1: [candle(1_800_000), candle(2_700_000)],
            })
            market = CachedMarketClient(upstream, store, backfill_limit=5)

            candles = market.get_candles("BTC-USDT-SWAP", "15m", 3)

            self.assertEqual([2, 2], [request[1] for request in upstream.candle_requests])
            self.assertEqual([900_000, 1_800_000, 2_700_000], [item.ts for item in candles])

    def test_backfill_limit_can_be_larger_than_requested_calculation_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteCandleStore(str(Path(directory) / "candles.sqlite3"))
            upstream = FakeUpstream({
                2: [candle(900_000), candle(1_800_000)],
                5: [candle(index * 900_000) for index in range(1, 6)],
            })
            market = CachedMarketClient(upstream, store, backfill_limit=5)

            candles = market.get_candles("BTC-USDT-SWAP", "15m", 3)

            self.assertEqual([2, 5], [request[1] for request in upstream.candle_requests])
            self.assertEqual([2_700_000, 3_600_000, 4_500_000], [item.ts for item in candles])
            self.assertEqual(4_500_000, store.latest_ts("BTC-USDT-SWAP", "15m"))


if __name__ == "__main__":
    unittest.main()
