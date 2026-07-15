from __future__ import annotations

import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Candle, DataError, Instrument, Ticker


class OkxError(RuntimeError):
    """Raised when OKX cannot serve usable market data."""


class OkxClient:
    max_candle_page_size = 300
    max_history_candle_page_size = 100

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
        candles: dict[int, Candle] = {}
        self._collect_candle_pages(
            "/api/v5/market/candles",
            instrument_id,
            bar,
            limit,
            self.max_candle_page_size,
            candles,
            cursor=None,
        )
        if len(candles) < limit:
            self._collect_candle_pages(
                "/api/v5/market/history-candles",
                instrument_id,
                bar,
                limit,
                self.max_history_candle_page_size,
                candles,
                cursor=min(candles) if candles else None,
            )
        return [candles[ts] for ts in sorted(candles)]

    def _collect_candle_pages(
        self,
        path: str,
        instrument_id: str,
        bar: str,
        limit: int,
        max_page_size: int,
        candles: dict[int, Candle],
        *,
        cursor: int | None,
    ) -> None:
        while len(candles) < limit:
            remaining = limit - len(candles)
            page_limit = min(max_page_size, remaining + (1 if cursor is not None else 0))
            params = {"instId": instrument_id, "bar": bar, "limit": str(page_limit)}
            if cursor is not None:
                params["after"] = str(cursor)
            data = self._get(path, params)
            if not data:
                break

            before_count = len(candles)
            for row in data:
                if not isinstance(row, list):
                    continue
                try:
                    candle = Candle.from_okx_row(row)
                except DataError:
                    continue
                candles[candle.ts] = candle
            if len(candles) == before_count:
                break
            cursor = min(candles)

    def get_24h_volume(self, instrument_id: str) -> Decimal:
        data = self._get("/api/v5/market/ticker", {"instId": instrument_id})
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                ticker = Ticker.from_okx(item)
            except DataError:
                continue
            if ticker.instrument_id == instrument_id:
                return ticker.volume_24h
        raise OkxError(f"missing ticker volume for {instrument_id}")

    def get_24h_volumes(self, quote_currency: str) -> dict[str, Decimal]:
        data = self._get("/api/v5/market/tickers", {"instType": "SWAP"})
        suffix = f"-{quote_currency}-SWAP"
        volumes: dict[str, Decimal] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                ticker = Ticker.from_okx(item)
            except DataError:
                continue
            if ticker.instrument_id.endswith(suffix):
                volumes[ticker.instrument_id] = ticker.volume_24h
        return volumes

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
