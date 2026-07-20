from __future__ import annotations

import unittest
from decimal import Decimal

from okx_scanner.config import Settings
from okx_scanner.discord import (
    DISCORD_DESCRIPTION_LIMIT,
    _payload,
    _power_payload,
    format_compact_volume,
    format_percent,
    format_volume,
    format_vwma_position,
)
from okx_scanner.models import Candle, Instrument, RsiHit
from okx_scanner.power_candle import PowerCandleSignal
from okx_scanner.service import ScannerService


class FakeMarket:
    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]:
        return [Instrument("BTC-USDT-SWAP", quote_currency, "live", Decimal("10"))]

    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        closes = [Decimal(100)] * 1344 + [Decimal(200)]
        return [
            Candle(
                ts=index * 60_000,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("130" if index == len(closes) - 1 else "100"),
                confirmed=True,
            )
            for index, close in enumerate(closes)
        ]

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        return Decimal("12345.678")

    def get_24h_volumes(self, quote_currency: str) -> dict[str, Decimal]:
        return {"BTC-USDT-SWAP": Decimal("123456.78")}

    def get_24h_turnovers(self, quote_currency: str) -> dict[str, Decimal]:
        return {"BTC-USDT-SWAP": Decimal("10000000")}


class OversoldBelowVwmaMarket(FakeMarket):
    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        closes = [Decimal(100)] * 1344 + [Decimal(1)]
        return [
            Candle(
                ts=index * 60_000,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("130" if index == len(closes) - 1 else "100"),
                confirmed=True,
            )
            for index, close in enumerate(closes)
        ]


class LowRelativeVolumeMarket(FakeMarket):
    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        closes = [Decimal(100)] * 1344 + [Decimal(200)]
        return [
            Candle(
                ts=index * 60_000,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("129" if index == len(closes) - 1 else "100"),
                confirmed=True,
            )
            for index, close in enumerate(closes)
        ]


class OverboughtAlreadyAboveVwmaMarket(FakeMarket):
    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        closes = [Decimal(100)] * 1343 + [Decimal(160), Decimal(200)]
        return [
            Candle(
                ts=index * 60_000,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("130" if index == len(closes) - 1 else "100"),
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
            Settings(vwma_period=100),
            FakeMarket(),
            notifier,
        )

        summary = service.scan_once()

        self.assertEqual(1, len(summary.hits))
        self.assertEqual(Decimal("123456.78"), summary.hits[0].volume_24h)
        self.assertEqual(Decimal("10000000"), summary.hits[0].turnover_24h)
        self.assertEqual(Decimal("1300"), summary.hits[0].signal_volume)
        self.assertEqual(summary.hits, notifier.hits)
        self.assertEqual("123456.78", summary.as_dict()["hits"][0]["volume24h"])
        self.assertEqual("10000000", summary.as_dict()["hits"][0]["turnover24h"])
        self.assertEqual("1300", summary.as_dict()["hits"][0]["signalVolume"])
        self.assertEqual("100", summary.as_dict()["hits"][0]["changePercent"])
        self.assertEqual("CROSS_ABOVE", summary.as_dict()["hits"][0]["vwmaSignal"])

    def test_scan_does_not_filter_rsi_hits_below_24h_turnover(self) -> None:
        class LowTurnoverMarket(FakeMarket):
            def get_24h_turnovers(self, quote_currency: str) -> dict[str, Decimal]:
                return {"BTC-USDT-SWAP": Decimal("9999999.99")}

        notifier = RecordingNotifier()
        service = ScannerService(
            Settings(vwma_period=100),
            LowTurnoverMarket(),
            notifier,
        )

        summary = service.scan_once()

        self.assertEqual(1, len(summary.hits))
        self.assertEqual(summary.hits, notifier.hits)
        self.assertEqual(1, summary.scanned)

    def test_scan_includes_oversold_hit_only_when_close_is_below_vwma(self) -> None:
        service = ScannerService(
            Settings(vwma_period=100),
            OversoldBelowVwmaMarket(),
            RecordingNotifier(),
        )

        summary = service.scan_once()

        self.assertEqual(1, len(summary.hits))
        self.assertLessEqual(summary.hits[0].rsi, 30)
        self.assertLess(summary.hits[0].close, summary.hits[0].vwma_100)
        self.assertEqual("CROSS_BELOW", summary.hits[0].vwma_signal)

    def test_scan_filters_overbought_hit_when_price_was_already_above_vwma(self) -> None:
        notifier = RecordingNotifier()
        service = ScannerService(
            Settings(vwma_period=100),
            OverboughtAlreadyAboveVwmaMarket(),
            notifier,
        )

        summary = service.scan_once()

        self.assertEqual([], summary.hits)
        self.assertEqual([], notifier.hits)

    def test_scan_skips_already_processed_latest_candle(self) -> None:
        notifier = RecordingNotifier()
        service = ScannerService(
            Settings(vwma_period=100),
            FakeMarket(),
            notifier,
        )

        first = service.scan_once()
        second = service.scan_once()

        self.assertEqual(1, len(first.hits))
        self.assertEqual(0, len(second.hits))

    def test_scan_ignores_14_day_volume_sma_surge_for_rsi_vwma_hits(self) -> None:
        notifier = RecordingNotifier()
        service = ScannerService(
            Settings(vwma_period=100),
            LowRelativeVolumeMarket(),
            notifier,
        )

        summary = service.scan_once()

        self.assertEqual(1, len(summary.hits))
        self.assertEqual(summary.hits, notifier.hits)

    def test_discord_payload_renders_24h_volume(self) -> None:
        hit = RsiHit(
            instrument_id="BTC-USDT-SWAP",
            candle_ts=60_000,
            rsi=25.123,
            rsi_wma=30.456,
            volume_24h=Decimal("12345.678"),
            turnover_24h=Decimal("2780000000"),
            signal_volume=Decimal("2500000"),
            close=Decimal("101"),
            change_percent=Decimal("1.2345"),
            vwma_100=Decimal("51.5"),
            vwma_signal="CROSS_ABOVE",
        )

        payload = _payload([hit])
        description = payload["embeds"][0]["description"]

        self.assertTrue(description.startswith("항목 설명\nRSI: 현재 RSI14 값 / 기준선: RSI WMA50"))
        self.assertLess(description.index("종가/등락률"), description.index("BTC-USDT-SWAP"))
        self.assertIn("24시간 거래량 12.35K", description)
        self.assertIn("24시간 거래대금 2.78B", description)
        self.assertIn("신호봉 거래량 2.5M", description)
        self.assertIn("기준선 30.46", description)
        self.assertIn("종가 101", description)
        self.assertIn("등락률 +1.23%", description)
        self.assertIn("VWMA100 상향 돌파", description)
        self.assertNotIn("24h volume", description)
        self.assertNotIn("signal volume", description)
        self.assertNotIn("change ", description)
        self.assertNotIn("51.5", description)

    def test_power_candle_payload_renders_signal_metrics(self) -> None:
        signal = PowerCandleSignal(
            instrument_id="BTC-USDT-SWAP",
            candle_ts=60_000,
            direction="UP",
            body_percent=Decimal("2.5"),
            body_ratio=Decimal("3"),
            volume=Decimal("2500000"),
            volume_ratio=Decimal("4"),
            range_percent=Decimal("3"),
            close_position_percent=Decimal("90"),
            breakout_level=Decimal("100"),
            close=Decimal("102"),
            turnover_24h=Decimal("2780000000"),
        )

        payload = _power_payload([signal])
        embed = payload["embeds"][0]
        description = embed["description"]

        self.assertNotIn("username", payload)
        self.assertNotIn("footer", embed)
        self.assertTrue(description.startswith("항목 설명\n몸통: 신호봉의 시가 대비 몸통 크기"))
        self.assertLess(description.index("돌파 기준가:"), description.index("BTC-USDT-SWAP"))
        self.assertIn("BTC-USDT-SWAP", description)
        self.assertIn("양봉", description)
        self.assertIn("몸통 +2.5%", description)
        self.assertIn("거래량 2.5M", description)
        self.assertIn("24시간 거래대금 2.78B", description)
        self.assertIn("거래량 배율 4x", description)
        self.assertIn("돌파 기준가 100", description)
        self.assertNotIn("body ", description)
        self.assertNotIn("volume ratio", description)

    def test_discord_payload_description_stays_within_limit(self) -> None:
        hits = [
            RsiHit(
                instrument_id=f"LONG-SYMBOL-{index:03d}-USDT-SWAP",
                candle_ts=60_000,
                rsi=75.12345,
                rsi_wma=70,
                volume_24h=Decimal("123456789.123456789"),
                turnover_24h=Decimal("2780000000"),
                signal_volume=Decimal("1234567"),
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
            rsi_wma=70,
            volume_24h=Decimal("1000"),
            turnover_24h=Decimal("1000"),
            signal_volume=Decimal("100"),
            close=Decimal("10"),
            change_percent=Decimal("1"),
            vwma_100=Decimal("9"),
            vwma_signal="ABOVE",
        )
        high = RsiHit(
            instrument_id="HIGH-USDT-SWAP",
            candle_ts=60_000,
            rsi=75,
            rsi_wma=70,
            volume_24h=Decimal("2000000"),
            turnover_24h=Decimal("2000000"),
            signal_volume=Decimal("200"),
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
        self.assertEqual("2.78B", format_compact_volume(Decimal("2780000000")))
        self.assertEqual("12.35K", format_compact_volume(Decimal("12345.678")))

    def test_format_percent_uses_sign_and_two_decimals(self) -> None:
        self.assertEqual("+1.23%", format_percent(Decimal("1.2345")))
        self.assertEqual("-1.23%", format_percent(Decimal("-1.2345")))
        self.assertEqual("0%", format_percent(Decimal("0")))

    def test_format_vwma_position_hides_raw_value(self) -> None:
        self.assertEqual("VWMA100 상향 돌파", format_vwma_position("CROSS_ABOVE"))
        self.assertEqual("VWMA100 위", format_vwma_position("ABOVE"))
        self.assertEqual("VWMA100 하향 돌파", format_vwma_position("CROSS_BELOW"))
        self.assertEqual("VWMA100 아래", format_vwma_position("BELOW"))
        self.assertEqual("VWMA100 동일", format_vwma_position("TOUCH"))


if __name__ == "__main__":
    unittest.main()
