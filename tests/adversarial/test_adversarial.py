from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from _stub import Response, StubServer

from label_notify import cursor as cursor_mod
from label_notify.config import Config, ConfigError, Delivery, Rule, load_config
from label_notify.cursor import Cursor, CursorError, load, mark, save
from label_notify.deliver import build_deliveries
from label_notify.guard import GitHubClient
from label_notify.poller import poll_once

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
ISSUES = "/repos/o/r/issues"


@pytest.mark.parametrize("payload", ["", "   \n", "just-a-string\n", "[]\n"])
def test_degenerate_config_files_are_rejected(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_deleted_cursor_rescans_from_the_safe_window(tmp_path: Path) -> None:
    path = tmp_path / "cursor.json"
    cursor = Cursor()
    mark(cursor, "o/r", "old", "2026-10-20T00:00:00Z")
    save(path, cursor)
    path.unlink()
    assert load(path).repos == {}


def test_cursor_with_garbage_entries_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cursor.json"
    path.write_text(json.dumps({"repos": {"o/r": {"seen": {"not": "a list"}}}}), encoding="utf-8")
    loaded = load(path)
    assert loaded.repo("o/r").seen == []


def test_corrupt_cursor_is_not_silently_ignored(tmp_path: Path) -> None:
    path = tmp_path / "cursor.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(CursorError):
        load(path)


def test_thousand_label_rule_still_matches(tmp_path: Path) -> None:
    labels = [f"label-{index}" for index in range(999)] + ["needle"]
    data = {
        "repos": ["o/r"],
        "rules": [{"name": "wide", "labels": labels, "deliver": ["log"]}],
        "deliveries": {"log": {"kind": "jsonl", "path": str(tmp_path / "e.jsonl")}},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(path)
    assert len(config.rules[0].labels) == 1000
    assert config.rules[0].labels[-1] == "needle"


def test_unicode_labels_match_case_insensitively() -> None:
    item = {
        "number": 1,
        "title": "ü",
        "html_url": "u",
        "labels": [{"name": "BÜG"}, {"name": "バグ"}],
        "state": "open",
        "updated_at": "2026-10-25T11:30:00Z",
    }
    rule = Rule("unicode", ("büg", "バグ"), deliver=("log",))
    from label_notify.rules import matching_rules, normalize_issue

    assert [r.name for r in matching_rules((rule,), normalize_issue("o/r", item))] == ["unicode"]


def test_hostile_issue_fields_do_not_crash_the_cycle() -> None:
    item = {
        "number": "not-a-number",
        "title": 12,
        "html_url": None,
        "labels": [None, 7, {"name": None}, {"name": "bug"}],
        "state": None,
        "updated_at": None,
    }
    result = poll_once(
        Config(
            repos=("o/r",),
            rules=(Rule("b", ("bug",), deliver=("log",)),),
            deliveries={},
            state_file=Path("x.json"),
        ),
        Cursor(),
        {"log": lambda event: None},
        _client([[item]]),
        now=NOW,
    )
    assert result.matched == 0
    assert any("without a number" in note for note in result.notes)


def test_malformed_json_response_is_an_api_error() -> None:
    with StubServer(lambda request: Response(status=200, body=b"<html>oops</html>")) as server:
        result = poll_once(
            Config(
                repos=("o/r",),
                rules=(Rule("b", ("bug",), deliver=("log",)),),
                deliveries={},
                state_file=Path("x.json"),
            ),
            Cursor(),
            {"log": lambda event: None},
            GitHubClient(server.url),
            now=NOW,
        )
    assert result.api_errors == 1
    assert result.exit_code == 5


def test_slow_webhook_times_out_without_hanging_the_cycle() -> None:
    def responder(request):
        time.sleep(0.6)
        return Response(status=204)

    with StubServer(responder) as server:
        config = Config(
            repos=("o/r",),
            rules=(Rule("b", ("bug",), deliver=("hook",)),),
            deliveries={
                "hook": Delivery(
                    "hook", "webhook", {"url": f"{server.url}/hook", "timeout_seconds": 0.1}
                )
            },
            state_file=Path("x.json"),
        )
        handlers = build_deliveries(config)
        started = time.monotonic()
        result = poll_once(
            config,
            Cursor(),
            handlers,
            _client(
                [
                    [
                        {
                            "number": 1,
                            "title": "t",
                            "html_url": "u",
                            "labels": [{"name": "bug"}],
                            "state": "open",
                            "updated_at": "2026-10-25T11:30:00Z",
                        }
                    ]
                ]
            ),
            now=NOW,
        )
        elapsed = time.monotonic() - started
    assert result.failed == 1
    assert result.exit_code == 4
    assert elapsed < 3


def test_no_secret_or_authorization_header_is_emitted_in_events() -> None:
    events: list[dict] = []
    item = {
        "number": 1,
        "title": "t",
        "html_url": "u",
        "labels": [{"name": "bug"}],
        "state": "open",
        "updated_at": "2026-10-25T11:30:00Z",
    }
    poll_once(
        Config(
            repos=("o/r",),
            rules=(Rule("b", ("bug",), deliver=("log",)),),
            deliveries={},
            state_file=Path("x.json"),
        ),
        Cursor(),
        {"log": events.append},
        _client([[item]]),
        now=NOW,
    )
    serialized = json.dumps(events).lower()
    assert "authorization" not in serialized
    assert "token" not in serialized


def test_seen_set_does_not_grow_past_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cursor_mod, "SEEN_LIMIT", 2)
    cursor = Cursor()
    for index in range(4):
        mark(cursor, "o/r", f"id-{index}", "2026-10-25T00:00:00Z")
    assert cursor.repo("o/r").seen == ["id-2", "id-3"]


def _client(pages: list[list[dict]]) -> object:
    class _Client:
        def get(self, path: str, params=None):
            page = int(dict(params or {}).get("page", 1))
            if page - 1 >= len(pages):
                return [], {}
            return pages[page - 1], {}

    return _Client()
