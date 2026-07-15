from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence


class DataError(ValueError):
    """Raised when OKX data cannot be parsed."""


def _decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DataError(f"invalid decimal field: {field}") from exc
    if not parsed.is_finite():
        raise DataError(f"non-finite decimal field: {field}")
    return parsed


@dataclass(frozen=True, slots=True)
class Candle:
    ts: int
    close: Decimal
    confirmed: bool

    @classmethod
    def from_okx_row(cls, row: Sequence[Any]) -> "Candle":
        if isinstance(row, (str, bytes)) or len(row) != 9:
            raise DataError("OKX candle rows must contain 9 fields")
        try:
            ts = int(str(row[0]))
        except ValueError as exc:
            raise DataError("invalid candle timestamp") from exc
        close = _decimal(row[4], "close")
        confirmed = str(row[8]) == "1"
        if ts < 0 or close < 0:
            raise DataError("invalid candle values")
        return cls(ts=ts, close=close, confirmed=confirmed)


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    quote_currency: str
    state: str

    @classmethod
    def from_okx(cls, item: dict[str, Any]) -> "Instrument":
        inst_id = item.get("instId")
        state = item.get("state")
        quote_currency = item.get("quoteCcy") or item.get("settleCcy")
        if not all(isinstance(value, str) and value for value in (inst_id, state, quote_currency)):
            raise DataError("invalid instrument object")
        return cls(inst_id, quote_currency, state)


@dataclass(frozen=True, slots=True)
class Ticker:
    instrument_id: str
    volume_24h: Decimal

    @classmethod
    def from_okx(cls, item: dict[str, Any]) -> "Ticker":
        inst_id = item.get("instId")
        if not isinstance(inst_id, str) or not inst_id:
            raise DataError("invalid ticker object")
        return cls(inst_id, _decimal(item.get("vol24h"), "vol24h"))


@dataclass(frozen=True, slots=True)
class RsiHit:
    instrument_id: str
    candle_ts: int
    rsi: float
    volume_24h: Decimal

    @property
    def state(self) -> str:
        return "OVERSOLD" if self.rsi <= 30 else "OVERBOUGHT"

    def as_dict(self) -> dict[str, object]:
        return {
            "instrumentId": self.instrument_id,
            "candleTs": self.candle_ts,
            "rsi": round(self.rsi, 4),
            "volume24h": str(self.volume_24h),
            "state": self.state,
        }
