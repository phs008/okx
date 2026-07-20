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


def candles_for_rsi(
    values: list[int],
    *,
    start_ts: int = 1_700_000_000_000,
    latest_volume: str = "130",
) -> list[Candle]:
    return [
        Candle(
            ts=start_ts + index * 900_000,
            open=Decimal(value),
            high=Decimal(value),
            low=Decimal(value),
            close=Decimal(value),
            volume=Decimal(latest_volume if index == len(values) - 1 else "100"),
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

    def get_24h_turnovers(self, quote_currency: str) -> dict[str, Decimal]:
        return {
            "DOWN-USDT-SWAP": Decimal("10000000"),
            "MID-USDT-SWAP": Decimal("10000000"),
            "UP-USDT-SWAP": Decimal("10000000"),
        }


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[list[str]] = []

    def send_hits(self, hits) -> None:
        self.sent.append([hit.instrument_id for hit in hits])


class ScannerTests(unittest.TestCase):
    def test_scan_filters_only_rsi_extremes(self) -> None:
        settings = Settings()
        market = FakeMarket(
            {
                "DOWN-USDT-SWAP": candles_for_rsi([100] * 1344 + [1]),
                "MID-USDT-SWAP": candles_for_rsi([100] * 1345),
                "UP-USDT-SWAP": candles_for_rsi([100] * 1344 + [200]),
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
        settings = Settings()
        market = FakeMarket(
            {
                "DOWN-USDT-SWAP": candles_for_rsi([100] * 1344 + [1]),
                "MID-USDT-SWAP": candles_for_rsi([100] * 1344 + [1]),
                "UP-USDT-SWAP": candles_for_rsi([100] * 1344 + [1]),
            }
        )
        notifier = FakeNotifier()

        summary = ScannerService(settings, market, notifier).scan_once(dry_run=True)

        self.assertEqual(len(summary.hits), 3)
        self.assertEqual(notifier.sent, [])

    def test_bar_is_fixed_to_15m(self) -> None:
        settings = replace(Settings(), bar="5m")
        with self.assertRaises(ConfigError):
            settings.validate()

    def test_settings_load_discord_webhook_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "DISCORD_WEBHOOK_RSIVWMA='https://discord.com/api/webhooks/1/token'\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                current = os.getcwd()
                os.chdir(directory)
                try:
                    settings = Settings.from_env(require_rsi_vwma_webhook=True)
                finally:
                    os.chdir(current)

        self.assertEqual(
            settings.discord_webhook_rsi_vwma_url,
            "https://discord.com/api/webhooks/1/token",
        )

    def test_settings_loads_separate_db_paths_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "DB_PATH_RSIVWMA=okx_rsi.sqlite3\n"
                "DB_PATH_SIGNAL=okx_signal.sqlite3\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                current = os.getcwd()
                os.chdir(directory)
                try:
                    settings = Settings.from_env()
                finally:
                    os.chdir(current)

        self.assertEqual("okx_rsi.sqlite3", settings.db_path)
        self.assertEqual("okx_signal.sqlite3", settings.signal_db_path)

    def test_legacy_db_path_is_still_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("DB_PATH=legacy.sqlite3\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                current = os.getcwd()
                os.chdir(directory)
                try:
                    settings = Settings.from_env()
                finally:
                    os.chdir(current)

        self.assertEqual("legacy.sqlite3", settings.db_path)
        self.assertEqual("legacy.sqlite3", settings.signal_db_path)

    def test_exported_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("RSI_OVERSOLD=20\n", encoding="utf-8")
            with patch.dict(os.environ, {"RSI_OVERSOLD": "25"}, clear=True):
                current = os.getcwd()
                os.chdir(directory)
                try:
                    settings = Settings.from_env()
                finally:
                    os.chdir(current)

        self.assertEqual(settings.rsi_oversold, 25.0)

    def test_power_indicator_lookback_defaults_to_14_days_plus_latest_candle(self) -> None:
        self.assertEqual(1345, Settings().power_indicator_lookback)

    def test_power_indicator_lookback_must_cover_14_day_volume_sma(self) -> None:
        with self.assertRaisesRegex(ConfigError, "POWER_INDICATOR_LOOKBACK"):
            replace(Settings(), power_indicator_lookback=1344).validate()


if __name__ == "__main__":
    unittest.main()
