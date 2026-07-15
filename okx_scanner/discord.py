from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .models import RsiHit


class DiscordError(RuntimeError):
    """Raised when Discord delivery fails."""


class DiscordWebhook:
    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.url = _with_wait(webhook_url)
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def send_hits(self, hits: list[RsiHit]) -> None:
        if not hits:
            return
        body = json.dumps(_payload(hits), ensure_ascii=False).encode("utf-8")
        request = Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "okx-rsi-scanner/1.0"},
            method="POST",
        )
        with self._opener(request, timeout=self.timeout_seconds) as response:
            if response.status >= 400:
                raise DiscordError(f"Discord webhook failed: HTTP {response.status}")


def _with_wait(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _payload(hits: list[RsiHit]) -> dict[str, object]:
    first_ts = hits[0].candle_ts
    start = datetime.fromtimestamp(first_ts / 1000, tz=UTC)
    kst = timezone(timedelta(hours=9))
    lines = [
        _hit_line(hit)
        for hit in sorted(hits, key=lambda item: (item.state, item.instrument_id))
    ]
    return {
        "username": "OKX RSI Scanner",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"OKX Perp 15m RSI 알림 - {len(hits)}개",
                "description": "\n".join(lines[:80]),
                "color": 0xF1C40F,
                "fields": [
                    {"name": "UTC 봉", "value": f"{start:%Y-%m-%d %H:%M}", "inline": True},
                    {"name": "KST 봉", "value": f"{start.astimezone(kst):%Y-%m-%d %H:%M}", "inline": True},
                ],
                "footer": {"text": "조건: RSI <= 30 또는 RSI >= 70"},
            }
        ],
    }


def _hit_line(hit: RsiHit) -> str:
    threshold = "30 이하" if hit.rsi <= 30 else "70 이상"
    return (
        f"{hit.instrument_id}: RSI {hit.rsi:.2f} ({threshold}), "
        f"24h volume {format_volume(hit.volume_24h)}"
    )


def format_volume(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return f"{normalized:.0f}"
    return f"{normalized:f}"
