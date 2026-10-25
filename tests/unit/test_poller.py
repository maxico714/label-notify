from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from label_notify.config import Config, Rule
from label_notify.cursor import Cursor
from label_notify.guard import ApiError, AuthError, RateLimitError
from label_notify.poller import poll_once

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
ISSUES = "/repos/o/r/issues"


def item(**overrides):
    data = {
        "number": 7,
        "title": "Crash on start",
        "html_url": "https://github.com/o/r/issues/7",
        "labels": [{"name": "bug"}],
        "state": "open",
        "updated_at": "2026-10-25T11:30:00Z",
    }
    data.update(overrides)
    return data


def make_config(*rules: Rule, repos=("o/r",), max_pages: int = 5) -> Config:
    return Config(
        repos=tuple(repos),
        rules=tuple(rules),
        deliveries={},
        max_pages=max_pages,
        lookback_hours=24,
        state_file=Path("unused.json"),
    )


class FakeClient:
    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params=None):
        params = dict(params or {})
        self.calls.append((path, params))
        value = self.responses[path]
        if isinstance(value, BaseException):
            raise value
        page = int(params.get("page", 1))
        if isinstance(value, list) and value and isinstance(value[0], list):
            return value[page - 1], {}
        return value, {}


def recorder(fail: bool = False) -> tuple[list[dict], object]:
    calls: list[dict] = []

    def handler(event: dict) -> None:
        if fail:
            raise RuntimeError("channel down")
        calls.append(event)

    return calls, handler


def test_matched_event_is_delivered_and_cursor_advances() -> None:
    client = FakeClient({ISSUES: [[item()]]})
    calls, handler = recorder()
    cursor = Cursor()
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("log",))),
        cursor,
        {"log": handler},
        client,
        now=NOW,
    )

    assert result.exit_code == 0
    assert (result.matched, result.delivered, result.failed) == (1, 1, 0)
    assert result.repos_polled == 1
    assert calls[0]["repo"] == "o/r"
    assert calls[0]["number"] == 7
    assert calls[0]["rule"] == "bugs"
    assert calls[0]["delivery"] == "log"
    assert calls[0]["status"] == "delivered"
    assert calls[0]["ts"] == "2026-10-25T12:00:00Z"

    state = cursor.repo("o/r")
    assert state.since == "2026-10-25T11:30:00Z"
    assert state.seen == ["o/r#7@2026-10-25T11:30:00Z"]

    path, params = client.calls[0]
    assert path == ISSUES
    assert params["state"] == "all"
    assert params["sort"] == "updated"
    assert params["direction"] == "asc"
    assert params["per_page"] == 100
    assert params["since"] == "2026-10-24T12:00:00Z"


def test_second_poll_does_not_repeat_delivery() -> None:
    cursor = Cursor()
    calls, handler = recorder()
    config = make_config(Rule("bugs", ("bug",), deliver=("log",)))

    first = poll_once(config, cursor, {"log": handler}, FakeClient({ISSUES: [[item()]]}), now=NOW)
    assert first.delivered == 1

    second = poll_once(config, cursor, {"log": handler}, FakeClient({ISSUES: [[item()]]}), now=NOW)
    assert second.delivered == 0
    assert second.matched == 0
    assert len(calls) == 1


def test_delivery_failure_holds_cursor_and_retries_next_cycle() -> None:
    cursor = Cursor()
    config = make_config(Rule("bugs", ("bug",), deliver=("log",)))

    failed = poll_once(
        config, cursor, {"log": recorder(fail=True)[1]}, FakeClient({ISSUES: [[item()]]}), now=NOW
    )
    assert failed.failed == 1
    assert failed.exit_code == 4
    assert failed.events[0]["status"] == "failed"
    assert cursor.repo("o/r").since is None
    assert cursor.repo("o/r").seen == []
    assert any("channel down" in note for note in failed.notes)

    calls, handler = recorder()
    retried = poll_once(config, cursor, {"log": handler}, FakeClient({ISSUES: [[item()]]}), now=NOW)
    assert retried.delivered == 1
    assert retried.exit_code == 0
    assert cursor.repo("o/r").since == "2026-10-25T11:30:00Z"
    assert len(calls) == 1


def test_dry_run_delivers_nothing_and_leaves_cursor_untouched() -> None:
    calls, handler = recorder()
    cursor = Cursor()
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("log",))),
        cursor,
        {"log": handler},
        FakeClient({ISSUES: [[item()]]}),
        dry_run=True,
        now=NOW,
    )
    assert result.dry_run is True
    assert result.delivered == 0
    assert result.matched == 1
    assert result.events[0]["status"] == "dry-run"
    assert calls == []
    assert cursor.repos == {}


def test_unknown_delivery_counts_as_failure() -> None:
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("ghost",))),
        Cursor(),
        {},
        FakeClient({ISSUES: [[item()]]}),
        now=NOW,
    )
    assert result.failed == 1
    assert result.exit_code == 4
    assert any("unknown delivery 'ghost'" in note for note in result.notes)


def test_one_repo_failure_does_not_stop_others() -> None:
    client = FakeClient(
        {
            "/repos/o/bad/issues": ApiError("boom"),
            "/repos/o/good/issues": [[item()]],
        }
    )
    calls, handler = recorder()
    config = make_config(Rule("bugs", ("bug",), deliver=("log",)), repos=("o/bad", "o/good"))
    result = poll_once(config, Cursor(), {"log": handler}, client, now=NOW)
    assert result.api_errors == 1
    assert result.exit_code == 5
    assert result.repos_polled == 1
    assert result.delivered == 1
    assert any("boom" in note for note in result.notes)


def test_auth_error_stops_the_cycle() -> None:
    client = FakeClient(
        {
            "/repos/o/r/issues": AuthError("bad credentials"),
            "/repos/o/s/issues": [[item()]],
        }
    )
    config = make_config(Rule("bugs", ("bug",), deliver=("log",)), repos=("o/r", "o/s"))
    result = poll_once(config, Cursor(), {}, client, now=NOW)
    assert result.auth_error is True
    assert result.exit_code == 2
    assert result.repos_polled == 0
    assert len(client.calls) == 1


def test_rate_limit_stops_the_cycle_and_reports_reset() -> None:
    client = FakeClient(
        {
            "/repos/o/r/issues": RateLimitError("limit", reset_seconds=42.0),
            "/repos/o/s/issues": [[item()]],
        }
    )
    config = make_config(Rule("bugs", ("bug",), deliver=("log",)), repos=("o/r", "o/s"))
    result = poll_once(config, Cursor(), {}, client, now=NOW)
    assert result.rate_limited is True
    assert result.reset_seconds == 42.0
    assert result.exit_code == 3
    assert len(client.calls) == 1


def test_pagination_follows_full_pages() -> None:
    first_page = [item(number=number, labels=[{"name": "other"}]) for number in range(1, 101)]
    second_page = [item(number=101)]
    client = FakeClient({ISSUES: [first_page, second_page]})
    calls, handler = recorder()
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("log",))),
        Cursor(),
        {"log": handler},
        client,
        now=NOW,
    )
    assert [params["page"] for _, params in client.calls] == [1, 2]
    assert result.delivered == 1
    assert not any("max_pages" in note for note in result.notes)


def test_max_pages_truncation_is_reported() -> None:
    first_page = [item(number=number, labels=[{"name": "other"}]) for number in range(1, 101)]
    client = FakeClient({ISSUES: [first_page, [item(number=101)]]})
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("log",)), max_pages=1),
        Cursor(),
        {},
        client,
        now=NOW,
    )
    assert [params["page"] for _, params in client.calls] == [1]
    assert any("max_pages=1" in note for note in result.notes)


def test_pull_request_type_filter() -> None:
    client = FakeClient({ISSUES: [[item(pull_request={"url": "x"})]]})
    calls, handler = recorder()
    result = poll_once(
        make_config(Rule("issues", ("bug",), type="issue", deliver=("log",))),
        Cursor(),
        {"log": handler},
        client,
        now=NOW,
    )
    assert result.matched == 0
    assert calls == []


def test_multiple_rules_deliver_independently() -> None:
    config = make_config(
        Rule("bugs", ("bug",), deliver=("a",)),
        Rule("open-bugs", ("bug",), state="open", deliver=("b",)),
    )
    calls_a, handler_a = recorder()
    calls_b, handler_b = recorder()
    result = poll_once(
        config,
        Cursor(),
        {"a": handler_a, "b": handler_b},
        FakeClient({ISSUES: [[item()]]}),
        now=NOW,
    )
    assert result.matched == 2
    assert result.delivered == 2
    assert [event["rule"] for event in result.events] == ["bugs", "open-bugs"]
    assert len(calls_a) == 1 and len(calls_b) == 1


def test_missing_number_is_skipped_with_note() -> None:
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("log",))),
        Cursor(),
        {},
        FakeClient({ISSUES: [[item(number=None)]]}),
        now=NOW,
    )
    assert result.matched == 0
    assert any("without a number" in note for note in result.notes)


def test_issue_without_updated_at_still_matches() -> None:
    calls, handler = recorder()
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("log",))),
        Cursor(),
        {"log": handler},
        FakeClient({ISSUES: [[item(updated_at=None)]]}),
        now=NOW,
    )
    assert result.delivered == 1
    assert calls[0]["number"] == 7


def test_non_list_payload_is_an_api_error() -> None:
    result = poll_once(
        make_config(Rule("bugs", ("bug",), deliver=("log",))),
        Cursor(),
        {},
        FakeClient({ISSUES: {"message": "nope"}}),
        now=NOW,
    )
    assert result.api_errors == 1
    assert result.exit_code == 5
    assert result.repos_polled == 0
