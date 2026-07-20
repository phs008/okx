from __future__ import annotations

import io
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from okx_scanner.cli import _print_scan_result, main
from okx_scanner.models import RsiHit
from okx_scanner.service import ScanSummary


class CliOutputTests(unittest.TestCase):
    def test_print_scan_result_hides_hits_after_discord_send(self) -> None:
        stream = io.StringIO()
        summary = ScanSummary(
            started_at="2026-07-15T00:00:00+00:00",
            universe=1,
            scanned=1,
            errors=0,
            hits=[
                RsiHit(
                    instrument_id="BTC-USDT-SWAP",
                    candle_ts=1,
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
            ],
        )

        _print_scan_result(summary, dry_run=False, stream=stream)

        self.assertEqual("Send discord condition message complete\n", stream.getvalue())

    def test_scan_power_does_not_require_discord_webhook(self) -> None:
        settings = SimpleNamespace(
            okx_base_url="https://example.com",
            request_timeout_seconds=10,
            request_attempts=1,
            db_path=":memory:",
            signal_db_path="signal.sqlite3",
            candle_limit=300,
            discord_webhook_rsi_vwma_url=None,
            discord_webkook_signal_url=None,
        )
        with (
            patch("okx_scanner.cli.Settings.from_env", return_value=settings) as from_env,
            patch("okx_scanner.cli.OkxClient"),
            patch("okx_scanner.cli.SqliteCandleStore") as sqlite_store,
            patch("okx_scanner.cli.CachedMarketClient", return_value=MagicMock()),
            patch("okx_scanner.cli.PowerScannerService") as power_scanner_service,
            patch("okx_scanner.cli._print"),
        ):
            result = main(["scan-power", "--dry-run"])

        self.assertEqual(0, result)
        from_env.assert_called_once_with(
            require_rsi_vwma_webhook=False,
            require_signal_webhook=False,
        )
        sqlite_store.assert_called_once_with("signal.sqlite3")
        power_scanner_service.assert_called_once()


if __name__ == "__main__":
    unittest.main()
