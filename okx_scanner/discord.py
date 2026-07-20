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
from .power_candle import PowerCandleSignal


DISCORD_DESCRIPTION_LIMIT = 4096
DISCORD_SAFE_DESCRIPTION_LIMIT = 3900
ERROR_BODY_LIMIT = 500
RSI_DESCRIPTION_HEADER = [
    "항목 설명",
    "RSI: 현재 RSI14 값 / 기준선: RSI WMA50",
    "24시간 거래량: OKX 차트 기준 24시간 거래량",
    "24시간 거래대금: USDT 기준 24시간 거래대금",
    "신호봉 거래량: 조건이 발생한 15분봉 거래량",
    "종가/등락률: 신호봉 종가와 직전 봉 대비 변화율",
]
POWER_DESCRIPTION_HEADER = [
    "항목 설명",
    "몸통: 신호봉의 시가 대비 몸통 크기",
    "몸통 배율: 직전 20봉 평균 몸통 대비 배율",
    "거래량: 신호봉 거래량",
    "24시간 거래대금: USDT 기준 24시간 거래대금",
    "거래량 배율: 직전 20봉 평균 거래량 대비 배율",
    "돌파 기준가: 양봉은 직전 20봉 고점, 음봉은 직전 20봉 저점",
]


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
        self._send(_payload(hits))

    def send_power_signals(self, signals: list[PowerCandleSignal]) -> None:
        if not signals:
            return
        self._send(_power_payload(signals))

    def _send(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
                "title": f"OKX 무기한 15분봉 RSI 알림 - {len(hits)}개",
                "description": _description([*RSI_DESCRIPTION_HEADER, "", *lines]),
                "color": 0xF1C40F,
                "fields": [
                    {"name": "UTC 봉", "value": f"{start:%Y-%m-%d %H:%M}", "inline": True},
                    {"name": "KST 봉", "value": f"{start.astimezone(kst):%Y-%m-%d %H:%M}", "inline": True},
                ],
                "footer": {"text": "조건: RSI14와 종가가 기준선을 같은 방향으로 돌파"},
            }
        ],
    }


def _power_payload(signals: list[PowerCandleSignal]) -> dict[str, object]:
    first_ts = signals[0].candle_ts
    start = datetime.fromtimestamp(first_ts / 1000, tz=UTC)
    kst = timezone(timedelta(hours=9))
    lines = [
        (
            f"{signal.instrument_id}: {_power_direction_label(signal.direction)}, "
            f"몸통 {format_percent(signal.body_percent)}, "
            f"몸통 배율 {format_compact_number(signal.body_ratio)}x, "
            f"거래량 {format_compact_volume(signal.volume)}, "
            f"24시간 거래대금 {_format_optional_compact_volume(signal.turnover_24h)}, "
            f"거래량 배율 {format_compact_number(signal.volume_ratio)}x, "
            f"돌파 기준가 {format_compact_number(signal.breakout_level)}"
        )
        for signal in sorted(signals, key=lambda item: item.instrument_id)
    ]
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"OKX Perp 15m Power Candle Alert - {len(signals)} hits",
                "description": _description([*POWER_DESCRIPTION_HEADER, "", *lines]),
                "color": 0x2ECC71,
                "fields": [
                    {"name": "UTC candle", "value": f"{start:%Y-%m-%d %H:%M}", "inline": True},
                    {"name": "KST candle", "value": f"{start.astimezone(kst):%Y-%m-%d %H:%M}", "inline": True},
                ],
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
    return (
        f"{hit.instrument_id}: RSI {hit.rsi:.2f} / 기준선 {hit.rsi_wma:.2f}, "
        f"24시간 거래량 {format_compact_volume(hit.volume_24h)}, "
        f"24시간 거래대금 {format_compact_volume(hit.turnover_24h)}, "
        f"신호봉 거래량 {format_compact_volume(hit.signal_volume)}, "
        f"종가 {format_compact_number(hit.close)}, "
        f"등락률 {format_percent(hit.change_percent)}, "
        f"{format_vwma_position(hit.vwma_signal)}"
    )


def format_vwma_position(signal: str) -> str:
    if signal == "CROSS_ABOVE":
        return "VWMA100 상향 돌파"
    if signal == "ABOVE":
        return "VWMA100 위"
    if signal == "CROSS_BELOW":
        return "VWMA100 하향 돌파"
    if signal == "BELOW":
        return "VWMA100 아래"
    return "VWMA100 동일"


def _power_direction_label(direction: str) -> str:
    if direction == "UP":
        return "양봉"
    if direction == "DOWN":
        return "음봉"
    return direction


def format_compact_volume(value: Decimal) -> str:
    magnitude = abs(value)
    if magnitude >= Decimal("1000000000"):
        return f"{format_compact_number(value / Decimal('1000000000'))}B"
    if magnitude >= Decimal("1000000"):
        return f"{format_compact_number(value / Decimal('1000000'))}M"
    if magnitude >= Decimal("1000"):
        return f"{format_compact_number(value / Decimal('1000'))}K"
    return format_compact_number(value)


def _format_optional_compact_volume(value: Decimal | None) -> str:
    return format_compact_volume(value) if value is not None else "n/a"


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
