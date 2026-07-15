from __future__ import annotations

import unittest
from decimal import Decimal

from okx_scanner.config import Settings
from okx_scanner.discord import _payload
from okx_scanner.models import Candle, Instrument, RsiHit
from okx_scanner.service import ScannerService


class FakeMarket:
    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]:
        return [Instrument("BTC-USDT-SWAP", quote_currency, "live")]

    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        closes = [Decimal(100)] * 100 + [Decimal(200)]
        return [
            Candle(
                ts=index * 60_000,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal(1),
                confirmed=True,
            )
            for index, close in enumerate(closes)
        ]

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        return Decimal("12345.678")


class OversoldBelowVwmaMarket(FakeMarket):
    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        closes = [Decimal(100)] * 100 + [Decimal(1)]
        return [
            Candle(
                ts=index * 60_000,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal(1),
                confirmed=True,
            )
            for index, close in enumerate(closes)
        ]


class RecordingNotifier:
    def __init__(self) -> None:
        self.hits: list[RsiHit] = []

    def send_hits(self, hits: list[RsiHit]) -> None:
        self.hits = hits


class VolumeAlertTests(unittest.TestCase):
    def test_scan_includes_24h_volume_in_hit_and_notifier(self) -> None:
        notifier = RecordingNotifier()
        service = ScannerService(
            Settings(candle_limit=101, vwma_period=100, indicator_lookback=101),
            FakeMarket(),
            notifier,
        )

        summary = service.scan_once()

        self.assertEqual(1, len(summary.hits))
        self.assertEqual(Decimal("12345.678"), summary.hits[0].volume_24h)
        self.assertEqual(summary.hits, notifier.hits)
        self.assertEqual("12345.678", summary.as_dict()["hits"][0]["volume24h"])
        self.assertEqual("CROSS_ABOVE", summary.as_dict()["hits"][0]["vwmaSignal"])

    def test_scan_includes_oversold_hit_only_when_close_is_below_vwma(self) -> None:
        service = ScannerService(
            Settings(candle_limit=101, vwma_period=100, indicator_lookback=101),
            OversoldBelowVwmaMarket(),
            RecordingNotifier(),
        )

        summary = service.scan_once()

        self.assertEqual(1, len(summary.hits))
        self.assertLessEqual(summary.hits[0].rsi, 30)
        self.assertLess(summary.hits[0].close, summary.hits[0].vwma_100)

    def test_scan_skips_already_processed_latest_candle(self) -> None:
        notifier = RecordingNotifier()
        service = ScannerService(
            Settings(candle_limit=101, vwma_period=100, indicator_lookback=101),
            FakeMarket(),
            notifier,
        )

        first = service.scan_once()
        second = service.scan_once()

        self.assertEqual(1, len(first.hits))
        self.assertEqual(0, len(second.hits))

    def test_discord_payload_renders_24h_volume(self) -> None:
        hit = RsiHit(
            instrument_id="BTC-USDT-SWAP",
            candle_ts=60_000,
            rsi=25.123,
            volume_24h=Decimal("12345.678"),
            close=Decimal("101"),
            vwma_100=Decimal("51.5"),
            vwma_signal="CROSS_ABOVE",
        )

        payload = _payload([hit])
        description = payload["embeds"][0]["description"]

        self.assertIn("24h volume 12345.678", description)
        self.assertIn("VWMA100 51.5 (CROSS_ABOVE)", description)


if __name__ == "__main__":
    unittest.main()
