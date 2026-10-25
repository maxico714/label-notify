from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SEEN_LIMIT = 10_000


class CursorError(ValueError):
    code = "E_CURSOR"


@dataclass
class RepoState:
    since: str | None = None
    seen: list[str] = field(default_factory=list)


@dataclass
class Cursor:
    repos: dict[str, RepoState] = field(default_factory=dict)

    def repo(self, name: str) -> RepoState:
        return self.repos.setdefault(name, RepoState())


def load(path: Path) -> Cursor:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Cursor()
    except OSError as exc:
        raise CursorError(f"cannot read cursor '{path}': {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CursorError(f"corrupt cursor file '{path}': {exc}") from exc
    if not isinstance(data, dict):
        raise CursorError(f"corrupt cursor file '{path}': root must be an object")
    cursor = Cursor()
    repos = data.get("repos", {})
    if not isinstance(repos, dict):
        raise CursorError(f"corrupt cursor file '{path}': repos must be an object")
    for name, raw in repos.items():
        if not isinstance(raw, dict):
            continue
        since = raw.get("since")
        seen = raw.get("seen", [])
        cursor.repos[str(name)] = RepoState(
            since=str(since) if since else None,
            seen=[str(item) for item in seen] if isinstance(seen, list) else [],
        )
    return cursor


def save(path: Path, cursor: Cursor) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "repos": {
            name: {"since": state.since, "seen": state.seen[-SEEN_LIMIT:]}
            for name, state in cursor.repos.items()
        }
    }
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".cursor-", suffix=".tmp", delete=False
        ) as handle:
            tmp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        assert tmp_path is not None
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def mark(cursor: Cursor, repo: str, event_id: str, since: str | None) -> None:
    state = cursor.repo(repo)
    if event_id not in state.seen:
        state.seen.append(event_id)
    if len(state.seen) > SEEN_LIMIT:
        state.seen = state.seen[-SEEN_LIMIT:]
    if since and (state.since is None or since > state.since):
        state.since = since
