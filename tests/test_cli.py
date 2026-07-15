from __future__ import annotations

import io
import unittest
from decimal import Decimal

from okx_scanner.cli import _print_scan_result
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
                    volume_24h=Decimal("1000"),
                    close=Decimal("10"),
                    change_percent=Decimal("1"),
                    vwma_100=Decimal("9"),
                    vwma_signal="ABOVE",
                )
            ],
        )

        _print_scan_result(summary, dry_run=False, stream=stream)

        self.assertEqual("Send discord condition message complete\n", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
