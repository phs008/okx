from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Sequence

from .indicators import VOLUME_SMA_PERIOD_14D_15M, latest_volume_is_above_sma
from .models import Candle


@dataclass(frozen=True, slots=True)
class FirstPowerCandleConfig:
    lookback: int = 20
    body_avg_ratio: Decimal = Decimal("1.8")
    volume_avg_ratio: Decimal = Decimal("2.0")
    volume_sma_period: int = VOLUME_SMA_PERIOD_14D_15M
    close_top_percent: Decimal = Decimal("25")
    body_min_percent: Decimal = Decimal("1.0")
    range_min_percent: Decimal = Decimal("1.5")
    cooldown: int = 20


@dataclass(frozen=True, slots=True)
class PowerCandleSignal:
    instrument_id: str
    candle_ts: int
    direction: Literal["UP", "DOWN"]
    body_percent: Decimal
    body_ratio: Decimal
    volume: Decimal
    volume_ratio: Decimal
    range_percent: Decimal
    close_position_percent: Decimal
    breakout_level: Decimal
    close: Decimal
    turnover_24h: Decimal | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "instrumentId": self.instrument_id,
            "candleTs": self.candle_ts,
            "direction": self.direction,
            "bodyPercent": str(self.body_percent),
            "bodyRatio": str(self.body_ratio),
            "volume": str(self.volume),
            "turnover24h": str(self.turnover_24h) if self.turnover_24h is not None else None,
            "volumeRatio": str(self.volume_ratio),
            "rangePercent": str(self.range_percent),
            "closePositionPercent": str(self.close_position_percent),
            "breakoutLevel": str(self.breakout_level),
            "close": str(self.close),
        }


def detect_first_power_candles(
    instrument_id: str,
    candles: Sequence[Candle],
    config: FirstPowerCandleConfig = FirstPowerCandleConfig(),
) -> list[PowerCandleSignal]:
    completed = [candle for candle in candles if candle.confirmed]
    signals: list[PowerCandleSignal] = []
    last_hit_index_by_direction: dict[str, int] = {}

    for index in range(max(config.lookback, config.volume_sma_period), len(completed)):
        candle = completed[index]
        previous = completed[index - config.lookback : index]
        if not latest_volume_is_above_sma(
            [item.volume for item in completed[index - config.volume_sma_period : index + 1]],
            period=config.volume_sma_period,
        ):
            continue

        body_percent = _body_percent(candle)
        range_percent = _range_percent(candle)
        body_average = sum((_body_percent(item) for item in previous), Decimal(0)) / len(previous)
        volume_average = sum((item.volume for item in previous), Decimal(0)) / len(previous)
        if body_average <= 0 or volume_average <= 0:
            continue

        body_ratio = body_percent / body_average
        volume_ratio = candle.volume / volume_average
        if body_percent < config.body_min_percent or range_percent < config.range_min_percent:
            continue
        if body_ratio < config.body_avg_ratio or volume_ratio < config.volume_avg_ratio:
            continue

        close_position_percent = _close_position_percent(candle)
        if candle.close > candle.open:
            direction: Literal["UP", "DOWN"] = "UP"
            breakout_level = max(item.high for item in previous)
            if close_position_percent < Decimal(100) - config.close_top_percent or candle.high <= breakout_level:
                continue
        elif candle.close < candle.open:
            direction = "DOWN"
            breakout_level = min(item.low for item in previous)
            if close_position_percent > config.close_top_percent or candle.low >= breakout_level:
                continue
        else:
            continue

        last_hit_index = last_hit_index_by_direction.get(direction)
        if last_hit_index is not None and index - last_hit_index <= config.cooldown:
            continue
        last_hit_index_by_direction[direction] = index
        signals.append(
            PowerCandleSignal(
                instrument_id=instrument_id,
                candle_ts=candle.ts,
                direction=direction,
                body_percent=body_percent if direction == "UP" else -body_percent,
                body_ratio=body_ratio,
                volume=candle.volume,
                volume_ratio=volume_ratio,
                range_percent=range_percent,
                close_position_percent=close_position_percent,
                breakout_level=breakout_level,
                close=candle.close,
            )
        )
    return signals


def _body_percent(candle: Candle) -> Decimal:
    if candle.open == 0:
        return Decimal(0)
    return abs(candle.close - candle.open) / candle.open * Decimal(100)


def _range_percent(candle: Candle) -> Decimal:
    if candle.open == 0:
        return Decimal(0)
    return (candle.high - candle.low) / candle.open * Decimal(100)


def _close_position_percent(candle: Candle) -> Decimal:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return Decimal(50)
    return (candle.close - candle.low) / candle_range * Decimal(100)
