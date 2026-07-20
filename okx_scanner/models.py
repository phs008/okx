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
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    confirmed: bool

    @classmethod
    def from_okx_row(cls, row: Sequence[Any]) -> "Candle":
        if isinstance(row, (str, bytes)) or len(row) != 9:
            raise DataError("OKX candle rows must contain 9 fields")
        try:
            ts = int(str(row[0]))
        except ValueError as exc:
            raise DataError("invalid candle timestamp") from exc
        open_price = _decimal(row[1], "open")
        high = _decimal(row[2], "high")
        low = _decimal(row[3], "low")
        close = _decimal(row[4], "close")
        volume = _decimal(row[5], "volume")
        confirmed = str(row[8]) == "1"
        if ts < 0 or min(open_price, high, low, close, volume) < 0:
            raise DataError("invalid candle values")
        return cls(
            ts=ts,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            confirmed=confirmed,
        )


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    quote_currency: str
    state: str
    contract_value: Decimal = Decimal("1")

    @classmethod
    def from_okx(cls, item: dict[str, Any]) -> "Instrument":
        inst_id = item.get("instId")
        state = item.get("state")
        quote_currency = item.get("quoteCcy") or item.get("settleCcy")
        if not all(isinstance(value, str) and value for value in (inst_id, state, quote_currency)):
            raise DataError("invalid instrument object")
        contract_value = _decimal(item.get("ctVal") or "1", "ctVal")
        if contract_value <= 0:
            raise DataError("invalid instrument contract value")
        return cls(inst_id, quote_currency, state, contract_value)


@dataclass(frozen=True, slots=True)
class Ticker:
    instrument_id: str
    volume_24h: Decimal
    turnover_24h: Decimal

    @classmethod
    def from_okx(cls, item: dict[str, Any]) -> "Ticker":
        inst_id = item.get("instId")
        if not isinstance(inst_id, str) or not inst_id:
            raise DataError("invalid ticker object")
        volume_24h = _decimal(item.get("volCcy24h"), "volCcy24h")
        turnover = _turnover_24h(item, volume_24h)
        return cls(inst_id, volume_24h, turnover)


def _turnover_24h(item: dict[str, Any], volume_24h: Decimal) -> Decimal:
    for field in ("volCcyQuote24h", "turnover24h"):
        value = item.get(field)
        if value is not None:
            return _decimal(value, field)
    return volume_24h * _decimal(item.get("last"), "last")


@dataclass(frozen=True, slots=True)
class RsiHit:
    instrument_id: str
    candle_ts: int
    rsi: float
    rsi_wma: float
    volume_24h: Decimal
    turnover_24h: Decimal
    signal_volume: Decimal
    close: Decimal
    change_percent: Decimal
    vwma_100: Decimal
    vwma_signal: str

    @property
    def state(self) -> str:
        return "BULLISH" if self.vwma_signal == "CROSS_ABOVE" else "BEARISH"

    def as_dict(self) -> dict[str, object]:
        return {
            "instrumentId": self.instrument_id,
            "candleTs": self.candle_ts,
            "rsi": round(self.rsi, 4),
            "rsiWma": round(self.rsi_wma, 4),
            "volume24h": str(self.volume_24h),
            "turnover24h": str(self.turnover_24h),
            "signalVolume": str(self.signal_volume),
            "close": str(self.close),
            "changePercent": str(self.change_percent),
            "vwma100": str(self.vwma_100),
            "vwmaSignal": self.vwma_signal,
            "state": self.state,
        }
