from __future__ import annotations

from decimal import Decimal
from typing import Sequence


VOLUME_SMA_PERIOD_14D_15M = 14 * 24 * 4
VOLUME_SURGE_MULTIPLIER = Decimal("1.3")


def wilder_rsi(closes: Sequence[Decimal], period: int = 14) -> float:
    return wilder_rsi_series(closes, period)[-1]


def wilder_rsi_series(closes: Sequence[Decimal], period: int = 14) -> list[float]:
    if period <= 0:
        raise ValueError("RSI period must be positive")
    if len(closes) < period + 1:
        raise ValueError(f"RSI({period}) needs at least {period + 1} closes")

    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [max(-change, Decimal(0)) for change in changes]
    divisor = Decimal(period)

    average_gain = sum(gains[:period], Decimal(0)) / divisor
    average_loss = sum(losses[:period], Decimal(0)) / divisor
    values = [_rsi_from_averages(average_gain, average_loss)]

    for index in range(period, len(changes)):
        average_gain = (average_gain * (period - 1) + gains[index]) / divisor
        average_loss = (average_loss * (period - 1) + losses[index]) / divisor
        values.append(_rsi_from_averages(average_gain, average_loss))

    return values


def weighted_moving_average(values: Sequence[float], period: int) -> float:
    if period <= 0:
        raise ValueError("WMA period must be positive")
    if len(values) < period:
        raise ValueError(f"WMA({period}) needs at least {period} values")

    recent_values = values[-period:]
    weights = range(1, period + 1)
    weighted_sum = sum(value * weight for value, weight in zip(recent_values, weights, strict=True))
    return weighted_sum / sum(weights)


def _rsi_from_averages(average_gain: Decimal, average_loss: Decimal) -> float:
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    if average_gain == 0:
        return 0.0
    relative_strength = average_gain / average_loss
    return float(Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength))


def vwma(closes: Sequence[Decimal], volumes: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0:
        raise ValueError("VWMA period must be positive")
    if len(closes) != len(volumes):
        raise ValueError("VWMA closes and volumes must have the same length")
    if len(closes) < period:
        raise ValueError(f"VWMA({period}) needs at least {period} candles")

    recent_closes = closes[-period:]
    recent_volumes = volumes[-period:]
    volume_sum = sum(recent_volumes, Decimal(0))
    if volume_sum <= 0:
        raise ValueError("VWMA volume sum must be positive")
    weighted_price_sum = sum(
        close * volume for close, volume in zip(recent_closes, recent_volumes, strict=True)
    )
    return weighted_price_sum / volume_sum


def latest_volume_is_above_sma(
    volumes: Sequence[Decimal],
    *,
    period: int = VOLUME_SMA_PERIOD_14D_15M,
    multiplier: Decimal = VOLUME_SURGE_MULTIPLIER,
) -> bool:
    if period <= 0:
        raise ValueError("Volume SMA period must be positive")
    if len(volumes) < period + 1:
        raise ValueError(f"Volume SMA({period}) needs at least {period + 1} candles")

    previous_volumes = volumes[-period - 1 : -1]
    average_volume = sum(previous_volumes, Decimal(0)) / Decimal(period)
    if average_volume <= 0:
        return False
    return volumes[-1] >= average_volume * multiplier
