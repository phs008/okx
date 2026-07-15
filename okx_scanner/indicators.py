from __future__ import annotations

from decimal import Decimal
from typing import Sequence


def wilder_rsi(closes: Sequence[Decimal], period: int = 14) -> float:
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

    for index in range(period, len(changes)):
        average_gain = (average_gain * (period - 1) + gains[index]) / divisor
        average_loss = (average_loss * (period - 1) + losses[index]) / divisor

    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    if average_gain == 0:
        return 0.0
    relative_strength = average_gain / average_loss
    return float(Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength))
