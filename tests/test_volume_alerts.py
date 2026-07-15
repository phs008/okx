from __future__ import annotations

import unittest
from decimal import Decimal

from okx_scanner.config import Settings
from okx_scanner.discord import (
    DISCORD_DESCRIPTION_LIMIT,
    _payload,
    format_compact_volume,
    format_percent,
    format_volume,
    format_vwma_position,
)
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

    def get_24h_volumes(self, quote_currency: str) -> dict[str, Decimal]:
        return {"BTC-USDT-SWAP": Decimal("12345.678")}


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
        self.assertEqual("100", summary.as_dict()["hits"][0]["changePercent"])
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
            change_percent=Decimal("1.2345"),
            vwma_100=Decimal("51.5"),
            vwma_signal="CROSS_ABOVE",
        )

        payload = _payload([hit])
        description = payload["embeds"][0]["description"]

        self.assertIn("24h volume 12.35K", description)
        self.assertIn("close 101", description)
        self.assertIn("change +1.23%", description)
        self.assertIn("above VWMA100", description)
        self.assertNotIn("51.5", description)

    def test_discord_payload_description_stays_within_limit(self) -> None:
        hits = [
            RsiHit(
                instrument_id=f"LONG-SYMBOL-{index:03d}-USDT-SWAP",
                candle_ts=60_000,
                rsi=75.12345,
                volume_24h=Decimal("123456789.123456789"),
                close=Decimal("98765.123456789"),
                change_percent=Decimal("1.2345"),
                vwma_100=Decimal("12345.123456789123456789"),
                vwma_signal="ABOVE",
            )
            for index in range(200)
        ]

        description = _payload(hits)["embeds"][0]["description"]

        self.assertLessEqual(len(description), DISCORD_DESCRIPTION_LIMIT)
        self.assertIn("more", description)

    def test_discord_payload_sorts_hits_by_24h_volume_descending(self) -> None:
        low = RsiHit(
            instrument_id="LOW-USDT-SWAP",
            candle_ts=60_000,
            rsi=75,
            volume_24h=Decimal("1000"),
            close=Decimal("10"),
            change_percent=Decimal("1"),
            vwma_100=Decimal("9"),
            vwma_signal="ABOVE",
        )
        high = RsiHit(
            instrument_id="HIGH-USDT-SWAP",
            candle_ts=60_000,
            rsi=75,
            volume_24h=Decimal("2000000"),
            close=Decimal("10"),
            change_percent=Decimal("2"),
            vwma_100=Decimal("9"),
            vwma_signal="ABOVE",
        )

        description = _payload([low, high])["embeds"][0]["description"]

        self.assertLess(description.index("HIGH-USDT-SWAP"), description.index("LOW-USDT-SWAP"))

    def test_format_volume_caps_decimal_places(self) -> None:
        self.assertEqual("123.12345679", format_volume(Decimal("123.123456789123456789")))

    def test_format_compact_volume_uses_k_and_m_units(self) -> None:
        self.assertEqual("999.5", format_compact_volume(Decimal("999.5")))
        self.assertEqual("1.5K", format_compact_volume(Decimal("1500")))
        self.assertEqual("2.5M", format_compact_volume(Decimal("2500000")))
        self.assertEqual("12.35K", format_compact_volume(Decimal("12345.678")))

    def test_format_percent_uses_sign_and_two_decimals(self) -> None:
        self.assertEqual("+1.23%", format_percent(Decimal("1.2345")))
        self.assertEqual("-1.23%", format_percent(Decimal("-1.2345")))
        self.assertEqual("0%", format_percent(Decimal("0")))

    def test_format_vwma_position_hides_raw_value(self) -> None:
        self.assertEqual("above VWMA100", format_vwma_position("CROSS_ABOVE"))
        self.assertEqual("above VWMA100", format_vwma_position("ABOVE"))
        self.assertEqual("below VWMA100", format_vwma_position("CROSS_BELOW"))
        self.assertEqual("below VWMA100", format_vwma_position("BELOW"))
        self.assertEqual("at VWMA100", format_vwma_position("TOUCH"))


if __name__ == "__main__":
    unittest.main()
