from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .cursor import CursorError, load, save
from .deliver import DeliveryError, build_deliveries
from .guard import ApiError, AuthError, GitHubClient, GuardError, RateLimitError
from .poller import PollResult, poll_once


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="label-notify",
        description="Label-scoped GitHub notifications via read-only polling.",
    )
    parser.add_argument("--version", action="version", version=f"label-notify {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="poll repositories and deliver matched events")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--once", action="store_true", help="run one cycle and exit")
    run.add_argument("--dry-run", action="store_true", help="log matches without delivering")

    validate = sub.add_parser("validate", help="validate a config file")
    validate.add_argument("--config", required=True, type=Path)

    doctor = sub.add_parser("doctor", help="check config, credentials, state and API access")
    doctor.add_argument("--config", required=True, type=Path)
    return parser


def _print_result(result: PollResult) -> None:
    mode = "dry-run" if result.dry_run else "cycle"
    print(
        f"{mode}: {result.matched} matched, {result.delivered} delivered, "
        f"{result.failed} failed (repos {result.repos_polled})"
    )
    for event in result.events:
        deliveries = ", ".join(event["deliveries"])
        print(
            f"  [{event['status']}] {event['repo']}#{event['number']} "
            f"{event['rule']} -> {deliveries}"
        )
    for note in result.notes:
        print(f"note: {note}", file=sys.stderr)


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    handlers = build_deliveries(config)
    client = GitHubClient(config.api_base, config.token(), timeout=config.timeout_seconds)
    cursor = load(config.state_file)

    while True:
        result = poll_once(config, cursor, handlers, client, dry_run=args.dry_run)
        _print_result(result)
        if not args.dry_run:
            save(config.state_file, cursor)
        if args.once:
            return result.exit_code
        delay = float(config.interval_seconds)
        if result.rate_limited and result.reset_seconds is not None:
            delay = min(result.reset_seconds + 5.0, 900.0)
        time.sleep(delay)


def _validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(
        f"config OK: {len(config.repos)} repos, {len(config.rules)} rules, "
        f"{len(config.deliveries)} deliveries"
    )
    return 0


def _doctor(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(f"config: OK ({len(config.repos)} repos, {len(config.rules)} rules)")
    print(f"token: {'present' if config.token() else 'absent'} (env {config.token_env})")
    try:
        config.state_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"state: OK ({config.state_file})")
    except OSError as exc:
        print(f"state: NOT WRITABLE ({exc})", file=sys.stderr)

    client = GitHubClient(config.api_base, config.token(), timeout=config.timeout_seconds)
    try:
        payload, headers = client.get("/rate_limit")
    except AuthError as exc:
        print(f"api: auth rejected ({exc})", file=sys.stderr)
        return 2
    except RateLimitError as exc:
        print(f"api: rate limited (reset in {exc.reset_seconds}s)", file=sys.stderr)
        return 3
    except ApiError as exc:
        print(f"api: unreachable ({exc})", file=sys.stderr)
        return 0

    remaining = headers.get("x-ratelimit-remaining", "unknown")
    limit = headers.get("x-ratelimit-limit", "unknown")
    core = payload.get("resources", {}).get("core", {}) if isinstance(payload, dict) else {}
    if isinstance(core, dict) and core.get("remaining") is not None:
        remaining = str(core["remaining"])
        limit = str(core.get("limit", limit))
    print(f"api: reachable (rate limit {remaining}/{limit} remaining)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "doctor":
            return _doctor(args)
    except (ConfigError, CursorError, DeliveryError, GuardError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 0
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
