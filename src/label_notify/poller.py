from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config
from .cursor import Cursor, RepoState, mark
from .deliver import Handler
from .guard import ApiError, AuthError, GitHubClient, RateLimitError
from .rules import matching_rules, normalize_issue

PER_PAGE = 100


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class PollResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    delivered: int = 0
    failed: int = 0
    repos_polled: int = 0
    rate_limited: bool = False
    reset_seconds: float | None = None
    auth_error: bool = False
    api_errors: int = 0
    notes: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def matched(self) -> int:
        return len(self.events)

    @property
    def exit_code(self) -> int:
        if self.auth_error:
            return 2
        if self.failed:
            return 4
        if self.api_errors:
            return 5
        if self.rate_limited:
            return 3
        return 0


@dataclass
class _RepoScan:
    success_ids: list[str] = field(default_factory=list)
    max_updated: str = ""
    failed: bool = False
    truncated: bool = False


def poll_once(
    config: Config,
    cursor: Cursor,
    handlers: dict[str, Handler],
    client: GitHubClient,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> PollResult:
    """Run one poll cycle over every configured repository."""
    result = PollResult(dry_run=dry_run)
    moment = now or utc_now()
    timestamp = iso(moment)

    for repo in config.repos:
        state = (cursor.repos.get(repo) or RepoState()) if dry_run else cursor.repo(repo)
        since = state.since or iso(moment - timedelta(hours=config.lookback_hours))
        scan = _RepoScan()
        try:
            _scan_repo(
                config, repo, state, since, scan, handlers, client, timestamp, result, dry_run
            )
        except RateLimitError as exc:
            result.rate_limited = True
            result.reset_seconds = exc.reset_seconds
            result.notes.append(f"{repo}: rate limited; stopping this cycle")
            break
        except AuthError as exc:
            result.auth_error = True
            result.notes.append(f"{repo}: {exc}")
            break
        except ApiError as exc:
            result.api_errors += 1
            result.notes.append(f"{repo}: {exc}")
            continue

        result.repos_polled += 1
        if not dry_run:
            for event_id in scan.success_ids:
                mark(cursor, repo, event_id, None)
            if scan.max_updated and not scan.failed:
                state.since = max(state.since or "", scan.max_updated)
        if scan.failed and not dry_run:
            result.notes.append(f"{repo}: delivery failed; cursor held so events retry next cycle")
        if scan.truncated:
            result.notes.append(
                f"{repo}: reached max_pages={config.max_pages}; older events may be skipped"
            )

    return result


def _scan_repo(
    config: Config,
    repo: str,
    state: RepoState,
    since: str,
    scan: _RepoScan,
    handlers: dict[str, Handler],
    client: GitHubClient,
    timestamp: str,
    result: PollResult,
    dry_run: bool,
) -> None:
    for page in range(1, config.max_pages + 1):
        payload, _headers = client.get(
            f"/repos/{repo}/issues",
            {
                "state": "all",
                "sort": "updated",
                "direction": "asc",
                "since": since,
                "per_page": PER_PAGE,
                "page": page,
            },
        )
        if not isinstance(payload, list):
            raise ApiError("GitHub returned an unexpected payload (expected a list)")
        for item in payload:
            if not isinstance(item, dict):
                continue
            _handle_item(config, repo, state, item, scan, handlers, timestamp, result, dry_run)
        if len(payload) < PER_PAGE:
            return
        if page == config.max_pages:
            scan.truncated = True


def _handle_item(
    config: Config,
    repo: str,
    state: RepoState,
    item: dict[str, Any],
    scan: _RepoScan,
    handlers: dict[str, Handler],
    timestamp: str,
    result: PollResult,
    dry_run: bool,
) -> None:
    issue = normalize_issue(repo, item)
    if issue.updated_at and issue.updated_at > scan.max_updated:
        scan.max_updated = issue.updated_at
    if not issue.number:
        result.notes.append(f"{repo}: skipped an issue without a number")
        return
    rules = matching_rules(config.rules, issue)
    if not rules:
        return
    event_id = f"{repo}#{issue.number}@{issue.updated_at}"
    if event_id in state.seen:
        return

    item_failed = False
    for rule in rules:
        event: dict[str, Any] = {
            "ts": timestamp,
            "repo": repo,
            "number": issue.number,
            "title": issue.title,
            "url": issue.url,
            "labels": list(issue.labels),
            "rule": rule.name,
            "deliveries": list(rule.deliver),
        }
        if dry_run:
            event["status"] = "dry-run"
            result.events.append(event)
            continue

        ok = True
        for name in rule.deliver:
            handler = handlers.get(name)
            if handler is None:
                ok = False
                result.failed += 1
                result.notes.append(f"{repo}#{issue.number} {rule.name}: unknown delivery '{name}'")
                continue
            payload = {**event, "delivery": name, "status": "delivered"}
            try:
                handler(payload)
            except Exception as exc:
                ok = False
                result.failed += 1
                result.notes.append(
                    f"{repo}#{issue.number} {rule.name} -> {name}: {type(exc).__name__}: {exc}"
                )
            else:
                result.delivered += 1
        event["status"] = "delivered" if ok else "failed"
        result.events.append(event)
        if not ok:
            item_failed = True
            scan.failed = True

    if not item_failed:
        scan.success_ids.append(event_id)
