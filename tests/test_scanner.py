from __future__ import annotations

import unittest
import os
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from okx_scanner.config import ConfigError, Settings
from okx_scanner.models import Candle, Instrument
from okx_scanner.service import ScannerService


def candles_for_rsi(values: list[int], *, start_ts: int = 1_700_000_000_000) -> list[Candle]:
    return [
        Candle(
            ts=start_ts + index * 900_000,
            open=Decimal(value),
            high=Decimal(value),
            low=Decimal(value),
            close=Decimal(value),
            volume=Decimal(1),
            confirmed=True,
        )
        for index, value in enumerate(values)
    ]


class FakeMarket:
    def __init__(self, candles: dict[str, list[Candle]]) -> None:
        self.candles = candles
        self.instrument_requests: list[tuple[str]] = []

    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]:
        self.instrument_requests.append((quote_currency,))
        return [
            Instrument("DOWN-USDT-SWAP", quote_currency, "live"),
            Instrument("MID-USDT-SWAP", quote_currency, "live"),
            Instrument("UP-USDT-SWAP", quote_currency, "live"),
        ]

    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        return self.candles[instrument_id]

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        return Decimal("1000")

    def get_24h_volumes(self, quote_currency: str) -> dict[str, Decimal]:
        return {
            "DOWN-USDT-SWAP": Decimal("1000"),
            "MID-USDT-SWAP": Decimal("1000"),
            "UP-USDT-SWAP": Decimal("1000"),
        }


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[list[str]] = []

    def send_hits(self, hits) -> None:
        self.sent.append([hit.instrument_id for hit in hits])


class ScannerTests(unittest.TestCase):
    def test_scan_filters_only_rsi_extremes(self) -> None:
        settings = Settings(candle_limit=101, indicator_lookback=101)
        market = FakeMarket(
            {
                "DOWN-USDT-SWAP": candles_for_rsi([100] * 100 + [1]),
                "MID-USDT-SWAP": candles_for_rsi([100] * 101),
                "UP-USDT-SWAP": candles_for_rsi([100] * 100 + [200]),
            }
        )
        notifier = FakeNotifier()
        logs: list[str] = []

        summary = ScannerService(settings, market, notifier, logger=logs.append).scan_once(dry_run=False)

        self.assertEqual([hit.instrument_id for hit in summary.hits], ["DOWN-USDT-SWAP", "UP-USDT-SWAP"])
        self.assertEqual(notifier.sent, [["DOWN-USDT-SWAP", "UP-USDT-SWAP"]])
        self.assertEqual(market.instrument_requests, [("USDT",)])
        self.assertIn("candle sync progress 1/3 instrument=DOWN-USDT-SWAP", logs)
        self.assertIn("candle sync progress 3/3 instrument=UP-USDT-SWAP", logs)
        self.assertNotIn("discord send started hit_count=2", logs)
        self.assertNotIn("discord send completed hit_count=2", logs)

    def test_dry_run_does_not_send_discord(self) -> None:
        settings = Settings(candle_limit=101, indicator_lookback=101)
        market = FakeMarket(
            {
                "DOWN-USDT-SWAP": candles_for_rsi([100] * 100 + [1]),
                "MID-USDT-SWAP": candles_for_rsi([100] * 100 + [1]),
                "UP-USDT-SWAP": candles_for_rsi([100] * 100 + [1]),
            }
        )
        notifier = FakeNotifier()

        summary = ScannerService(settings, market, notifier).scan_once(dry_run=True)

        self.assertEqual(len(summary.hits), 3)
        self.assertEqual(notifier.sent, [])

    def test_bar_is_fixed_to_15m(self) -> None:
        settings = replace(Settings(), bar="5m")
        with self.assertRaises(ConfigError):
            settings.validate(require_webhook=False)

    def test_settings_load_discord_webhook_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/1/token'\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                current = os.getcwd()
                os.chdir(directory)
                try:
                    settings = Settings.from_env(require_webhook=True)
                finally:
                    os.chdir(current)

        self.assertEqual(
            settings.discord_webhook_url,
            "https://discord.com/api/webhooks/1/token",
        )

    def test_exported_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("RSI_OVERSOLD=20\n", encoding="utf-8")
            with patch.dict(os.environ, {"RSI_OVERSOLD": "25"}, clear=True):
                current = os.getcwd()
                os.chdir(directory)
                try:
                    settings = Settings.from_env(require_webhook=False)
                finally:
                    os.chdir(current)

        self.assertEqual(settings.rsi_oversold, 25.0)


if __name__ == "__main__":
    unittest.main()
