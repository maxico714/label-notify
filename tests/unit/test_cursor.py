from __future__ import annotations

import json
from pathlib import Path

import pytest

from label_notify import cursor as cursor_mod
from label_notify.cursor import Cursor, CursorError, RepoState, load, mark, save


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    cursor = load(tmp_path / "absent.json")
    assert cursor.repos == {}


def test_load_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "cursor.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CursorError, match="corrupt cursor") as excinfo:
        load(path)
    assert excinfo.value.code == "E_CURSOR"


@pytest.mark.parametrize("payload", ["[]", '{"repos": []}', '{"repos": "x"}'])
def test_load_rejects_wrong_shapes(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "cursor.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CursorError):
        load(path)


def test_load_coerces_entries(tmp_path: Path) -> None:
    path = tmp_path / "cursor.json"
    path.write_text(
        json.dumps(
            {
                "repos": {
                    "o/r": {"since": "2026-10-25T00:00:00Z", "seen": ["a", 7, None]},
                    "o/bad": "not-an-object",
                }
            }
        ),
        encoding="utf-8",
    )
    cursor = load(path)
    assert cursor.repos["o/r"].seen == ["a", "7", "None"]
    assert "o/bad" not in cursor.repos


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "cursor.json"
    cursor = Cursor()
    mark(cursor, "o/r", "o/r#1@2026-10-25T00:00:00Z", "2026-10-25T00:00:00Z")
    save(path, cursor)
    reloaded = load(path)
    assert reloaded.repos["o/r"].since == "2026-10-25T00:00:00Z"
    assert reloaded.repos["o/r"].seen == ["o/r#1@2026-10-25T00:00:00Z"]
    assert list(path.parent.glob(".cursor-*")) == []


def test_save_is_atomic_replacing_old_content(tmp_path: Path) -> None:
    path = tmp_path / "cursor.json"
    path.write_text("old", encoding="utf-8")
    cursor = Cursor()
    mark(cursor, "o/r", "id", "2026-10-25T00:00:00Z")
    save(path, cursor)
    assert json.loads(path.read_text(encoding="utf-8"))["repos"]["o/r"]["seen"] == ["id"]


def test_mark_deduplicates_and_keeps_max_since() -> None:
    cursor = Cursor()
    mark(cursor, "o/r", "a", "2026-10-24T00:00:00Z")
    mark(cursor, "o/r", "a", "2026-10-23T00:00:00Z")
    mark(cursor, "o/r", "b", "2026-10-25T00:00:00Z")
    mark(cursor, "o/r", "c", None)
    state = cursor.repo("o/r")
    assert state.seen == ["a", "b", "c"]
    assert state.since == "2026-10-25T00:00:00Z"


def test_mark_trims_seen_to_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cursor_mod, "SEEN_LIMIT", 3)
    cursor = Cursor()
    for index in range(5):
        mark(cursor, "o/r", f"id-{index}", None)
    assert cursor.repos["o/r"].seen == ["id-2", "id-3", "id-4"]


def test_save_trims_seen_on_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cursor_mod, "SEEN_LIMIT", 2)
    path = tmp_path / "cursor.json"
    cursor = Cursor(repos={"o/r": RepoState(since=None, seen=["a", "b", "c"])})
    save(path, cursor)
    assert json.loads(path.read_text(encoding="utf-8"))["repos"]["o/r"]["seen"] == ["b", "c"]


def test_repo_state_created_on_demand() -> None:
    cursor = Cursor()
    assert cursor.repo("o/new") == RepoState()
    assert "o/new" in cursor.repos
