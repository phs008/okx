from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from . import __version__
from .cached_market import CachedMarketClient
from .config import ConfigError, Settings
from .discord import DiscordWebhook
from .okx_client import OkxClient
from .service import ScannerService
from .sqlite_store import SqliteCandleStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="okx-scanner",
        description="Scan OKX USDT perpetual swaps every 15 minutes for 15m RSI extremes.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    once = subparsers.add_parser("scan-once", help="Run one RSI scan")
    once.add_argument("--dry-run", action="store_true", help="Print results without Discord")

    daemon = subparsers.add_parser("daemon", help="Run one scan every 15 minutes")
    daemon.add_argument("--dry-run", action="store_true", help="Print results without Discord")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = bool(args.dry_run)

    try:
        settings = Settings.from_env(require_webhook=not dry_run)
    except ConfigError as exc:
        _print({"ok": False, "error": str(exc)}, stream=sys.stderr)
        return 2

    upstream_market = OkxClient(
        settings.okx_base_url,
        timeout_seconds=settings.request_timeout_seconds,
        attempts=settings.request_attempts,
    )
    market = CachedMarketClient(
        upstream_market,
        SqliteCandleStore(settings.db_path),
        backfill_limit=settings.candle_limit,
    )
    notifier = (
        DiscordWebhook(settings.discord_webhook_url, timeout_seconds=settings.request_timeout_seconds)
        if settings.discord_webhook_url
        else None
    )
    service = ScannerService(settings, market, notifier, logger=_log)

    if args.command == "scan-once":
        _print(service.scan_once(dry_run=dry_run).as_dict())
        return 0
    if args.command == "daemon":
        try:
            service.run_forever(dry_run=dry_run, output=lambda summary: _print(summary.as_dict()))
        except KeyboardInterrupt:
            return 130
    return 2


def _print(value: object, *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), file=stream or sys.stdout, flush=True)


def _log(message: str) -> None:
    timestamp = datetime.now(UTC).isoformat()
    print(f"{timestamp} {message}", flush=True)
