from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from .models import Candle


class SqliteCandleStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def upsert_candles(self, instrument_id: str, bar: str, candles: Iterable[Candle]) -> int:
        rows = [
            (
                instrument_id,
                bar,
                candle.ts,
                str(candle.open),
                str(candle.high),
                str(candle.low),
                str(candle.close),
                str(candle.volume),
                1 if candle.confirmed else 0,
            )
            for candle in candles
        ]
        if not rows:
            return 0
        with closing(self._connect()) as connection:
            with connection:
                connection.executemany(
                    """
                    INSERT INTO candles (
                        instrument_id, bar, ts, open, high, low, close, volume, confirmed
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(instrument_id, bar, ts) DO UPDATE SET
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume,
                        confirmed = excluded.confirmed
                    """,
                    rows,
                )
        return len(rows)

    def latest_ts(self, instrument_id: str, bar: str) -> int | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT MAX(ts)
                FROM candles
                WHERE instrument_id = ? AND bar = ? AND confirmed = 1
                """,
                (instrument_id, bar),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def recent_candles(self, instrument_id: str, bar: str, limit: int) -> list[Candle]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT ts, open, high, low, close, volume, confirmed
                FROM candles
                WHERE instrument_id = ? AND bar = ? AND confirmed = 1
                ORDER BY ts DESC
                LIMIT ?
                """,
                (instrument_id, bar, limit),
            ).fetchall()
        return [
            Candle(
                ts=int(row["ts"]),
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row["volume"]),
                confirmed=bool(row["confirmed"]),
            )
            for row in reversed(rows)
        ]

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS candles (
                        instrument_id TEXT NOT NULL,
                        bar TEXT NOT NULL,
                        ts INTEGER NOT NULL,
                        open TEXT NOT NULL,
                        high TEXT NOT NULL,
                        low TEXT NOT NULL,
                        close TEXT NOT NULL,
                        volume TEXT NOT NULL,
                        confirmed INTEGER NOT NULL,
                        PRIMARY KEY (instrument_id, bar, ts)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_candles_lookup
                    ON candles (instrument_id, bar, confirmed, ts)
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection
