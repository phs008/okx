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
        return [
            Candle(ts=index * 60_000, close=Decimal(100 - index), confirmed=True)
            for index in range(15)
        ]

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        return Decimal("12345.678")


class RecordingNotifier:
    def __init__(self) -> None:
        self.hits: list[RsiHit] = []

    def send_hits(self, hits: list[RsiHit]) -> None:
        self.hits = hits


class VolumeAlertTests(unittest.TestCase):
    def test_scan_includes_24h_volume_in_hit_and_notifier(self) -> None:
        notifier = RecordingNotifier()
        service = ScannerService(Settings(), FakeMarket(), notifier)

        summary = service.scan_once()

        self.assertEqual(1, len(summary.hits))
        self.assertEqual(Decimal("12345.678"), summary.hits[0].volume_24h)
        self.assertEqual(summary.hits, notifier.hits)
        self.assertEqual("12345.678", summary.as_dict()["hits"][0]["volume24h"])

    def test_discord_payload_renders_24h_volume(self) -> None:
        hit = RsiHit(
            instrument_id="BTC-USDT-SWAP",
            candle_ts=60_000,
            rsi=25.123,
            volume_24h=Decimal("12345.678"),
        )

        payload = _payload([hit])
        description = payload["embeds"][0]["description"]

        self.assertIn("24h volume 12345.678", description)


if __name__ == "__main__":
    unittest.main()
