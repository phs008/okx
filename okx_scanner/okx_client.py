from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Candle, DataError, Instrument


class OkxError(RuntimeError):
    """Raised when OKX cannot serve usable market data."""


class OkxClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        attempts: int,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self._opener = opener
        self._sleep = sleeper

    def get_perp_instruments(self, quote_currency: str) -> list[Instrument]:
        data = self._get("/api/v5/public/instruments", {"instType": "SWAP"})
        instruments: list[Instrument] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                instrument = Instrument.from_okx(item)
            except DataError:
                continue
            if instrument.state == "live" and instrument.quote_currency == quote_currency:
                instruments.append(instrument)
        return sorted(instruments, key=lambda item: item.instrument_id)

    def get_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        data = self._get(
            "/api/v5/market/candles",
            {"instId": instrument_id, "bar": bar, "limit": str(limit)},
        )
        candles: dict[int, Candle] = {}
        for row in data:
            if not isinstance(row, list):
                continue
            try:
                candle = Candle.from_okx_row(row)
            except DataError:
                continue
            candles[candle.ts] = candle
        return [candles[ts] for ts in sorted(candles)]

    def _get(self, path: str, params: dict[str, str]) -> list[Any]:
        request = Request(
            f"{self.base_url}{path}?{urlencode(params)}",
            headers={"Accept": "application/json", "User-Agent": "okx-rsi-scanner/1.0"},
            method="GET",
        )
        last_error = "unknown"
        for attempt in range(1, self.attempts + 1):
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                last_error = f"http_{exc.code}"
                if exc.code != 429 and exc.code < 500:
                    raise OkxError(last_error) from None
            except (URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                last_error = type(exc).__name__
            else:
                if not isinstance(payload, dict):
                    raise OkxError("OKX response must be an object")
                if str(payload.get("code")) == "0" and isinstance(payload.get("data"), list):
                    return payload["data"]
                last_error = f"okx_code_{payload.get('code', 'missing')}"
            if attempt < self.attempts:
                self._sleep(min(8.0, 2 ** (attempt - 1)))
        raise OkxError(f"OKX request failed after {self.attempts} attempts: {last_error}")
