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
from .power_service import PowerScannerService
from .power_simulation import PowerReactionConfig, simulate_power_reactions
from .service import ScanSummary, ScannerService
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

    power_once = subparsers.add_parser("scan-power", help="Find completed 15m power candles")
    power_once.add_argument("--dry-run", action="store_true", help="Print results without Discord")

    power_daemon = subparsers.add_parser("power-daemon", help="Monitor 15m power candles")
    power_daemon.add_argument("--dry-run", action="store_true", help="Print results without Discord")

    simulate_power = subparsers.add_parser("simulate-power", help="Classify historical power candles")
    simulate_power.add_argument("--observation-bars", type=int, default=8)
    simulate_power.add_argument("--max-examples", type=int, default=20)

    daemon = subparsers.add_parser("daemon", help="Run one scan every 15 minutes")
    daemon.add_argument("--dry-run", action="store_true", help="Print results without Discord")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = bool(getattr(args, "dry_run", False))

    try:
        settings = Settings.from_env(
            require_rsi_vwma_webhook=args.command in {"scan-once", "daemon"} and not dry_run,
            require_signal_webhook=args.command in {"scan-power", "power-daemon"} and not dry_run,
        )
    except ConfigError as exc:
        _print({"ok": False, "error": str(exc)}, stream=sys.stderr)
        return 2

    if args.command == "simulate-power":
        _print(
            simulate_power_reactions(
                settings.signal_db_path,
                bar=settings.bar,
                config=PowerReactionConfig(observation_bars=args.observation_bars),
                max_examples=args.max_examples,
            ).as_dict()
        )
        return 0

    upstream_market = OkxClient(
        settings.okx_base_url,
        timeout_seconds=settings.request_timeout_seconds,
        attempts=settings.request_attempts,
    )
    market = CachedMarketClient(
        upstream_market,
        SqliteCandleStore(_db_path_for_command(args.command, settings)),
        backfill_limit=settings.candle_limit,
    )
    notifier = (
        DiscordWebhook(settings.discord_webhook_rsi_vwma_url, timeout_seconds=settings.request_timeout_seconds)
        if settings.discord_webhook_rsi_vwma_url
        else None
    )
    power_notifier = (
        DiscordWebhook(settings.discord_webkook_signal_url, timeout_seconds=settings.request_timeout_seconds)
        if settings.discord_webkook_signal_url
        else None
    )
    service = ScannerService(settings, market, notifier, logger=_log)

    if args.command == "scan-once":
        _print_scan_result(service.scan_once(dry_run=dry_run), dry_run=dry_run)
        return 0
    if args.command == "scan-power":
        _print(PowerScannerService(settings, market, power_notifier).scan_once(dry_run=dry_run).as_dict())
        return 0
    if args.command == "power-daemon":
        try:
            PowerScannerService(settings, market, power_notifier).run_forever(
                dry_run=dry_run,
                output=lambda summary: _print(summary.as_dict()),
            )
        except KeyboardInterrupt:
            return 130
        return 0
    if args.command == "daemon":
        try:
            service.run_forever(dry_run=dry_run, output=lambda summary: _print_scan_result(summary, dry_run=dry_run))
        except KeyboardInterrupt:
            return 130
    return 2


def _print_scan_result(summary: ScanSummary, *, dry_run: bool, stream=None) -> None:
    if summary.hits and not dry_run:
        print("Send discord condition message complete", file=stream or sys.stdout, flush=True)
        return
    _print(summary.as_dict(), stream=stream)


def _print(value: object, *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), file=stream or sys.stdout, flush=True)


def _db_path_for_command(command: str, settings: Settings) -> str:
    if command in {"scan-power", "power-daemon"}:
        return settings.signal_db_path
    return settings.db_path


def _log(message: str) -> None:
    timestamp = datetime.now(UTC).isoformat()
    print(f"{timestamp} {message}", flush=True)
