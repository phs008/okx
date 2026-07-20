from __future__ import annotations

import json
import unittest
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from okx_scanner.indicators import vwma, weighted_moving_average, wilder_rsi_series
from okx_scanner.models import Candle, Instrument
from okx_scanner.okx_client import OkxClient


class FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class CandleAndVwmaTests(unittest.TestCase):
    def test_candle_parses_volume(self) -> None:
        candle = Candle.from_okx_row(["1", "10", "11", "9", "10.5", "42", "441", "441", "1"])

        self.assertEqual(Decimal("10"), candle.open)
        self.assertEqual(Decimal("11"), candle.high)
        self.assertEqual(Decimal("9"), candle.low)
        self.assertEqual(Decimal("10.5"), candle.close)
        self.assertEqual(Decimal("42"), candle.volume)

    def test_instrument_parses_contract_value(self) -> None:
        instrument = Instrument.from_okx(
            {
                "instId": "XPL-USDT-SWAP",
                "settleCcy": "USDT",
                "state": "live",
                "ctVal": "10",
            }
        )

        self.assertEqual(Decimal("10"), instrument.contract_value)

    def test_vwma_weights_recent_closes_by_volume(self) -> None:
        result = vwma(
            [Decimal("10"), Decimal("20"), Decimal("30")],
            [Decimal("1"), Decimal("2"), Decimal("3")],
            3,
        )

        self.assertEqual(Decimal("140") / Decimal("6"), result)

    def test_weighted_moving_average_weights_newer_values_more(self) -> None:
        result = weighted_moving_average([10.0, 20.0, 30.0], 3)

        self.assertEqual((10 * 1 + 20 * 2 + 30 * 3) / 6, result)

    def test_wilder_rsi_series_returns_latest_rsi_values(self) -> None:
        values = wilder_rsi_series([Decimal(100)] * 14 + [Decimal(101), Decimal(102)], 14)

        self.assertEqual([100.0, 100.0], values)

    def test_get_candles_pages_until_requested_limit(self) -> None:
        requested_urls: list[str] = []

        def opener(request, timeout: float) -> FakeResponse:
            requested_urls.append(request.full_url)
            query = parse_qs(urlparse(request.full_url).query)
            limit = int(query["limit"][0])
            after = int(query.get("after", ["900"])[0])
            rows = [
                [str(after - index), "1", "1", "1", "1", "1", "1", "1", "1"]
                for index in range(limit)
            ]
            return FakeResponse({"code": "0", "data": rows})

        client = OkxClient("https://example.test", timeout_seconds=1, attempts=1, opener=opener)

        candles = client.get_candles("BTC-USDT-SWAP", "15m", 650)

        self.assertEqual(650, len(candles))
        self.assertEqual(["300", "300", "52"], [parse_qs(urlparse(url).query)["limit"][0] for url in requested_urls])
        self.assertIn("after", parse_qs(urlparse(requested_urls[1]).query))

    def test_get_candles_falls_back_to_history_candles(self) -> None:
        requested_urls: list[str] = []

        def opener(request, timeout: float) -> FakeResponse:
            requested_urls.append(request.full_url)
            parsed = urlparse(request.full_url)
            query = parse_qs(parsed.query)
            limit = int(query["limit"][0])
            after = int(query.get("after", ["900"])[0])
            if parsed.path.endswith("/candles") and "after" in query:
                return FakeResponse({"code": "0", "data": []})
            rows = [
                [str(after - index), "1", "1", "1", "1", "1", "1", "1", "1"]
                for index in range(limit)
            ]
            return FakeResponse({"code": "0", "data": rows})

        client = OkxClient("https://example.test", timeout_seconds=1, attempts=1, opener=opener)

        candles = client.get_candles("BTC-USDT-SWAP", "15m", 350)

        self.assertEqual(350, len(candles))
        self.assertTrue(any(urlparse(url).path.endswith("/history-candles") for url in requested_urls))

    def test_get_24h_volumes_uses_bulk_tickers_endpoint(self) -> None:
        requested_urls: list[str] = []

        def opener(request, timeout: float) -> FakeResponse:
            requested_urls.append(request.full_url)
            return FakeResponse(
                {
                    "code": "0",
                    "data": [
                        {"instId": "BTC-USDT-SWAP", "vol24h": "12345.678", "volCcy24h": "123456.78", "last": "2"},
                        {"instId": "ETH-USDT-SWAP", "vol24h": "98765", "volCcy24h": "987650", "last": "3"},
                        {"instId": "BTC-USDC-SWAP", "vol24h": "1", "volCcy24h": "10", "last": "4"},
                    ],
                }
            )

        client = OkxClient("https://example.test", timeout_seconds=1, attempts=1, opener=opener)

        volumes = client.get_24h_volumes("USDT")

        self.assertEqual(
            {"BTC-USDT-SWAP": Decimal("123456.78"), "ETH-USDT-SWAP": Decimal("987650")},
            volumes,
        )
        self.assertEqual("/api/v5/market/tickers", urlparse(requested_urls[0]).path)
        self.assertEqual("SWAP", parse_qs(urlparse(requested_urls[0]).query)["instType"][0])

    def test_get_24h_turnovers_uses_quote_turnover_when_available(self) -> None:
        requested_urls: list[str] = []

        def opener(request, timeout: float) -> FakeResponse:
            requested_urls.append(request.full_url)
            return FakeResponse(
                {
                    "code": "0",
                    "data": [
                        {"instId": "BTC-USDT-SWAP", "volCcy24h": "100", "volCcyQuote24h": "2780000000", "last": "1"},
                        {"instId": "XPL-USDT-SWAP", "volCcy24h": "162291310", "last": "0.08186"},
                        {"instId": "BTC-USDC-SWAP", "volCcy24h": "10", "last": "4"},
                    ],
                }
            )

        client = OkxClient("https://example.test", timeout_seconds=1, attempts=1, opener=opener)

        turnovers = client.get_24h_turnovers("USDT")

        self.assertEqual(Decimal("2780000000"), turnovers["BTC-USDT-SWAP"])
        self.assertEqual(Decimal("162291310") * Decimal("0.08186"), turnovers["XPL-USDT-SWAP"])
        self.assertNotIn("BTC-USDC-SWAP", turnovers)
        self.assertEqual("/api/v5/market/tickers", urlparse(requested_urls[0]).path)


if __name__ == "__main__":
    unittest.main()
