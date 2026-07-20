from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .models import Candle
from .power_candle import PowerCandleSignal, detect_first_power_candles


@dataclass(frozen=True, slots=True)
class PowerReactionConfig:
    observation_bars: int = 8


@dataclass(frozen=True, slots=True)
class PowerReaction:
    signal: PowerCandleSignal
    reaction_type: str
    midpoint: Decimal
    observed_bars: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            **self.signal.as_dict(),
            "reactionType": self.reaction_type,
            "midpoint": str(self.midpoint),
            "observedBars": self.observed_bars,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PowerSimulationSummary:
    db_path: str
    instruments: int
    signals: int
    classified: int
    skipped_without_future: int
    counts: dict[str, int]
    examples: list[PowerReaction]

    def as_dict(self) -> dict[str, object]:
        return {
            "dbPath": self.db_path,
            "instruments": self.instruments,
            "signals": self.signals,
            "classified": self.classified,
            "skippedWithoutFuture": self.skipped_without_future,
            "counts": self.counts,
            "examples": [example.as_dict() for example in self.examples],
        }


def simulate_power_reactions(
    db_path: str,
    *,
    bar: str = "15m",
    config: PowerReactionConfig = PowerReactionConfig(),
    max_examples: int = 20,
) -> PowerSimulationSummary:
    instruments = _instrument_ids(db_path, bar)
    examples: list[PowerReaction] = []
    counts: Counter[str] = Counter()
    signals_total = 0
    classified = 0
    skipped_without_future = 0

    for instrument_id in instruments:
        candles = _candles(db_path, instrument_id, bar)
        index_by_ts = {candle.ts: index for index, candle in enumerate(candles)}
        signals = detect_first_power_candles(instrument_id, candles)
        signals_total += len(signals)
        for signal in signals:
            signal_index = index_by_ts[signal.candle_ts]
            observed = candles[signal_index + 1 : signal_index + 1 + config.observation_bars]
            if len(observed) < config.observation_bars:
                skipped_without_future += 1
                continue
            reaction = classify_power_reaction(candles[signal_index], signal, observed)
            counts[reaction.reaction_type] += 1
            classified += 1
            if len(examples) < max_examples:
                examples.append(reaction)

    return PowerSimulationSummary(
        db_path=db_path,
        instruments=len(instruments),
        signals=signals_total,
        classified=classified,
        skipped_without_future=skipped_without_future,
        counts=dict(sorted(counts.items())),
        examples=examples,
    )


def classify_power_reaction(
    signal_candle: Candle,
    signal: PowerCandleSignal,
    observed: list[Candle],
) -> PowerReaction:
    midpoint = (signal_candle.high + signal_candle.low) / Decimal("2")
    if signal.direction == "UP":
        return _classify_up(signal_candle, signal, observed, midpoint)
    return _classify_down(signal_candle, signal, observed, midpoint)


def _classify_up(
    signal_candle: Candle,
    signal: PowerCandleSignal,
    observed: list[Candle],
    midpoint: Decimal,
) -> PowerReaction:
    if any(candle.low < signal_candle.low for candle in observed):
        return PowerReaction(signal, "D", midpoint, len(observed), "broke signal low after bullish power candle")
    if any(candle.low < midpoint for candle in observed):
        return PowerReaction(signal, "C", midpoint, len(observed), "broke signal midpoint after bullish power candle")

    first = observed[0]
    if first.high > signal_candle.high and first.close > first.open:
        return PowerReaction(signal, "B", midpoint, len(observed), "continued immediately after bullish power candle")

    contraction_index = _first_volume_contraction_index(signal_candle, observed)
    if contraction_index is not None:
        later = observed[contraction_index + 1 :]
        if any(candle.close > candle.open or candle.high > signal_candle.high for candle in later):
            return PowerReaction(signal, "A", midpoint, len(observed), "held midpoint, volume contracted, then bullish confirmation")

    return PowerReaction(signal, "UNRESOLVED", midpoint, len(observed), "held midpoint but no PA confirmation")


def _classify_down(
    signal_candle: Candle,
    signal: PowerCandleSignal,
    observed: list[Candle],
    midpoint: Decimal,
) -> PowerReaction:
    if any(candle.high > signal_candle.high for candle in observed):
        return PowerReaction(signal, "D", midpoint, len(observed), "broke signal high after bearish power candle")
    if any(candle.high > midpoint for candle in observed):
        return PowerReaction(signal, "C", midpoint, len(observed), "broke signal midpoint after bearish power candle")

    first = observed[0]
    if first.low < signal_candle.low and first.close < first.open:
        return PowerReaction(signal, "B", midpoint, len(observed), "continued immediately after bearish power candle")

    contraction_index = _first_volume_contraction_index(signal_candle, observed)
    if contraction_index is not None:
        later = observed[contraction_index + 1 :]
        if any(candle.close < candle.open or candle.low < signal_candle.low for candle in later):
            return PowerReaction(signal, "A", midpoint, len(observed), "held midpoint, volume contracted, then bearish confirmation")

    return PowerReaction(signal, "UNRESOLVED", midpoint, len(observed), "held midpoint but no PA confirmation")


def _first_volume_contraction_index(signal_candle: Candle, observed: list[Candle]) -> int | None:
    for index, candle in enumerate(observed):
        if candle.volume < signal_candle.volume:
            return index
    return None


def _instrument_ids(db_path: str, bar: str) -> list[str]:
    with sqlite3.connect(Path(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT instrument_id
            FROM candles
            WHERE bar = ? AND confirmed = 1
            ORDER BY instrument_id
            """,
            (bar,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _candles(db_path: str, instrument_id: str, bar: str) -> list[Candle]:
    with sqlite3.connect(Path(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT ts, open, high, low, close, volume, confirmed
            FROM candles
            WHERE instrument_id = ? AND bar = ? AND confirmed = 1
            ORDER BY ts ASC
            """,
            (instrument_id, bar),
        ).fetchall()
    return [
        Candle(
            ts=int(row[0]),
            open=Decimal(row[1]),
            high=Decimal(row[2]),
            low=Decimal(row[3]),
            close=Decimal(row[4]),
            volume=Decimal(row[5]),
            confirmed=bool(row[6]),
        )
        for row in rows
    ]
