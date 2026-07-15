from __future__ import annotations

import json
import unittest
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from okx_scanner.indicators import vwma
from okx_scanner.models import Candle
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

    def test_vwma_weights_recent_closes_by_volume(self) -> None:
        result = vwma(
            [Decimal("10"), Decimal("20"), Decimal("30")],
            [Decimal("1"), Decimal("2"), Decimal("3")],
            3,
        )

        self.assertEqual(Decimal("140") / Decimal("6"), result)

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


if __name__ == "__main__":
    unittest.main()
