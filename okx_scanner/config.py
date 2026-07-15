from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when configuration is invalid."""


DEFAULT_OKX_BASE_URL = "https://www.okx.com"
DEFAULT_QUOTE_CCY = "USDT"
DEFAULT_BAR = "15m"
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_OVERSOLD = 30.0
DEFAULT_RSI_OVERBOUGHT = 70.0
DEFAULT_CANDLE_LIMIT = 100
DEFAULT_SCAN_INTERVAL_SECONDS = 900
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_REQUEST_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class Settings:
    okx_base_url: str = DEFAULT_OKX_BASE_URL
    quote_currency: str = DEFAULT_QUOTE_CCY
    bar: str = DEFAULT_BAR
    rsi_period: int = DEFAULT_RSI_PERIOD
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT
    candle_limit: int = DEFAULT_CANDLE_LIMIT
    scan_interval_seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    request_attempts: int = DEFAULT_REQUEST_ATTEMPTS
    discord_webhook_url: str | None = None

    @classmethod
    def from_env(cls, *, require_webhook: bool) -> "Settings":
        values = {**_load_env_file(Path(".env")), **os.environ}
        settings = cls(
            okx_base_url=values.get("OKX_BASE_URL", DEFAULT_OKX_BASE_URL).rstrip("/"),
            quote_currency=values.get("QUOTE_CCY", DEFAULT_QUOTE_CCY).upper(),
            bar=values.get("BAR", DEFAULT_BAR),
            rsi_period=_int(values, "RSI_PERIOD", DEFAULT_RSI_PERIOD),
            rsi_oversold=_float(values, "RSI_OVERSOLD", DEFAULT_RSI_OVERSOLD),
            rsi_overbought=_float(values, "RSI_OVERBOUGHT", DEFAULT_RSI_OVERBOUGHT),
            candle_limit=_int(values, "CANDLE_LIMIT", DEFAULT_CANDLE_LIMIT),
            scan_interval_seconds=_int(values, "SCAN_INTERVAL_SECONDS", DEFAULT_SCAN_INTERVAL_SECONDS),
            request_timeout_seconds=_float(values, "REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS),
            request_attempts=_int(values, "REQUEST_ATTEMPTS", DEFAULT_REQUEST_ATTEMPTS),
            discord_webhook_url=values.get("DISCORD_WEBHOOK_URL") or None,
        )
        settings.validate(require_webhook=require_webhook)
        return settings

    def validate(self, *, require_webhook: bool) -> None:
        parsed = urlparse(self.okx_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError("OKX_BASE_URL must be an http(s) URL")
        if self.bar != "15m":
            raise ConfigError("this scanner is intentionally fixed to BAR=15m")
        if not self.quote_currency:
            raise ConfigError("QUOTE_CCY cannot be empty")
        if self.rsi_period <= 0:
            raise ConfigError("RSI_PERIOD must be positive")
        if not 0 <= self.rsi_oversold < self.rsi_overbought <= 100:
            raise ConfigError("RSI thresholds must satisfy 0 <= oversold < overbought <= 100")
        if self.candle_limit < self.rsi_period + 1 or self.candle_limit > 300:
            raise ConfigError("CANDLE_LIMIT must cover RSI history and be <= 300")
        if self.scan_interval_seconds <= 0:
            raise ConfigError("SCAN_INTERVAL_SECONDS must be positive")
        if self.request_timeout_seconds <= 0 or self.request_attempts <= 0:
            raise ConfigError("request settings must be positive")
        if require_webhook and not self.discord_webhook_url:
            raise ConfigError("DISCORD_WEBHOOK_URL is required unless --dry-run is used")


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ConfigError(f".env line {line_number} must be KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f".env line {line_number} has an empty key")
        values[key] = _clean_env_value(value.strip())
    return values


def _clean_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _int(values: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _float(values: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(values.get(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} must be numeric") from exc
