from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .models import RsiHit


DISCORD_DESCRIPTION_LIMIT = 4096
DISCORD_SAFE_DESCRIPTION_LIMIT = 3900
ERROR_BODY_LIMIT = 500


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
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                if response.status >= 400:
                    raise DiscordError(f"Discord webhook failed: HTTP {response.status}")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:ERROR_BODY_LIMIT]
            raise DiscordError(f"Discord webhook failed: HTTP {exc.code}: {detail}") from None


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
        for hit in sorted(hits, key=lambda item: (-item.volume_24h, item.instrument_id))
    ]
    return {
        "username": "OKX RSI Scanner",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"OKX Perp 15m RSI Alert - {len(hits)} hits",
                "description": _description(lines),
                "color": 0xF1C40F,
                "fields": [
                    {"name": "UTC candle", "value": f"{start:%Y-%m-%d %H:%M}", "inline": True},
                    {"name": "KST candle", "value": f"{start.astimezone(kst):%Y-%m-%d %H:%M}", "inline": True},
                ],
                "footer": {"text": "Condition: RSI <= 30 below VWMA100 or RSI >= 70 above VWMA100"},
            }
        ],
    }


def _description(lines: list[str]) -> str:
    selected: list[str] = []
    for line in lines:
        next_description = "\n".join([*selected, line])
        if len(next_description) > DISCORD_SAFE_DESCRIPTION_LIMIT:
            break
        selected.append(line)

    omitted = len(lines) - len(selected)
    if omitted > 0:
        suffix = f"... and {omitted} more"
        while selected and len("\n".join([*selected, suffix])) > DISCORD_DESCRIPTION_LIMIT:
            selected.pop()
        selected.append(suffix)
    return "\n".join(selected)


def _hit_line(hit: RsiHit) -> str:
    threshold = "RSI <= 30" if hit.rsi <= 30 else "RSI >= 70"
    return (
        f"{hit.instrument_id}: RSI {hit.rsi:.2f} ({threshold}), "
        f"24h volume {format_compact_volume(hit.volume_24h)}, "
        f"close {format_compact_number(hit.close)}, "
        f"change {format_percent(hit.change_percent)}, "
        f"{format_vwma_position(hit.vwma_signal)}"
    )


def format_vwma_position(signal: str) -> str:
    if signal in {"CROSS_ABOVE", "ABOVE"}:
        return "above VWMA100"
    if signal in {"CROSS_BELOW", "BELOW"}:
        return "below VWMA100"
    return "at VWMA100"


def format_compact_volume(value: Decimal) -> str:
    magnitude = abs(value)
    if magnitude >= Decimal("1000000"):
        return f"{format_compact_number(value / Decimal('1000000'))}M"
    if magnitude >= Decimal("1000"):
        return f"{format_compact_number(value / Decimal('1000'))}K"
    return format_compact_number(value)


def format_compact_number(value: Decimal) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def format_percent(value: Decimal) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{format_compact_number(value)}%"


def format_volume(value: Decimal) -> str:
    if value == value.to_integral():
        return f"{value:.0f}"
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"
