from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml
from _stub import Response, StubServer

from label_notify.cli import main


def issue(**overrides):
    data = {
        "number": 42,
        "title": "Something broke",
        "html_url": "https://github.com/o/r/issues/42",
        "labels": [{"name": "bug"}],
        "state": "open",
        "updated_at": "2026-10-25T11:30:00Z",
    }
    data.update(overrides)
    return data


def make_responder(pages: dict[str, list[list[dict]]] | None = None):
    pages = pages or {"o/r": [[issue()]]}

    def responder(request):
        if request.path == "/rate_limit":
            return Response.json({"resources": {"core": {"remaining": 4999, "limit": 5000}}})
        for repo, repo_pages in pages.items():
            if request.path == f"/repos/{repo}/issues":
                page = int(request.param("page") or 1)
                payload = repo_pages[page - 1] if page <= len(repo_pages) else []
                return Response.json(payload)
        return Response.json({"message": "Not Found"}, status=404)

    return responder


def write_config(
    tmp_path: Path, api_base: str, extra_deliveries: dict | None = None
) -> tuple[Path, Path, Path]:
    events = tmp_path / "logs" / "events.jsonl"
    state = tmp_path / "state" / "cursor.json"
    deliveries = {"log": {"kind": "jsonl", "path": str(events)}}
    deliveries.update(extra_deliveries or {})
    data = {
        "github": {"api_base": api_base, "token_env": "GITHUB_TOKEN"},
        "poll": {"interval_seconds": 1, "lookback_hours": 24, "timeout_seconds": 5},
        "state_file": str(state),
        "repos": ["o/r"],
        "rules": [
            {"name": "bugs", "labels": ["bug"], "type": "any", "state": "any", "deliver": ["log"]}
        ],
        "deliveries": deliveries,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path, events, state


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def test_validate_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _events, _state = write_config(tmp_path, "https://api.github.com")
    assert main(["validate", "--config", str(path)]) == 0
    assert "config OK: 1 repos, 1 rules, 1 deliveries" in capsys.readouterr().out


def test_validate_invalid_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("repos: []\n", encoding="utf-8")
    assert main(["validate", "--config", str(path)]) == 1
    assert "error:" in capsys.readouterr().err


def test_dry_run_logs_without_delivering(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with StubServer(make_responder()) as server:
        path, events, state = write_config(tmp_path, server.url)
        assert main(["run", "--config", str(path), "--once", "--dry-run"]) == 0
        output = capsys.readouterr().out
        assert "dry-run: 1 matched, 0 delivered" in output
        assert "[dry-run] o/r#42 bugs -> log" in output
        assert not events.exists()
        assert not state.exists()
        assert [(request.method, request.path) for request in server.requests] == [
            ("GET", "/repos/o/r/issues")
        ]


def test_real_run_delivers_jsonl_and_persists_cursor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with StubServer(make_responder()) as server:
        path, events, state = write_config(tmp_path, server.url)
        assert main(["run", "--config", str(path), "--once"]) == 0
        output = capsys.readouterr().out
        assert "cycle: 1 matched, 1 delivered, 0 failed" in output

        record = json.loads(events.read_text(encoding="utf-8").strip())
        assert record["repo"] == "o/r"
        assert record["number"] == 42
        assert record["rule"] == "bugs"
        assert record["delivery"] == "log"
        assert record["status"] == "delivered"

        cursor = json.loads(state.read_text(encoding="utf-8"))
        assert cursor["repos"]["o/r"]["since"] == "2026-10-25T11:30:00Z"
        assert cursor["repos"]["o/r"]["seen"] == ["o/r#42@2026-10-25T11:30:00Z"]


def test_second_run_is_deduplicated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with StubServer(make_responder()) as server:
        path, events, _state = write_config(tmp_path, server.url)
        assert main(["run", "--config", str(path), "--once"]) == 0
        assert main(["run", "--config", str(path), "--once"]) == 0
        output = capsys.readouterr().out
        assert "cycle: 0 matched, 0 delivered, 0 failed" in output
        assert len(events.read_text(encoding="utf-8").splitlines()) == 1


def test_doctor_reports_api(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with StubServer(make_responder()) as server:
        path, _events, state = write_config(tmp_path, server.url)
        assert main(["doctor", "--config", str(path)]) == 0
        output = capsys.readouterr().out
        assert "config: OK (1 repos, 1 rules)" in output
        assert "token: absent" in output
        assert f"state: OK ({state})" in output
        assert "api: reachable (rate limit 4999/5000 remaining)" in output


def test_doctor_auth_failure_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with StubServer(
        lambda request: Response.json({"message": "Bad credentials"}, status=401)
    ) as server:
        path, _events, _state = write_config(tmp_path, server.url)
        assert main(["doctor", "--config", str(path)]) == 2
        assert "auth rejected" in capsys.readouterr().err


def test_run_auth_failure_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with StubServer(
        lambda request: Response.json({"message": "Bad credentials"}, status=401)
    ) as server:
        path, events, _state = write_config(tmp_path, server.url)
        assert main(["run", "--config", str(path), "--once"]) == 2
        assert not events.exists()


def test_run_rate_limit_exits_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reset = str(int(time.time()) + 60)

    def responder(request):
        return Response.json(
            {"message": "API rate limit exceeded"},
            status=403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset},
        )

    with StubServer(responder) as server:
        path, _events, _state = write_config(tmp_path, server.url)
        assert main(["run", "--config", str(path), "--once"]) == 3
        assert "rate limited" in capsys.readouterr().err


def test_partial_delivery_exits_4(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with (
        StubServer(make_responder()) as github,
        StubServer(lambda request: Response(status=500)) as hook,
    ):
        path, events, _state = write_config(
            tmp_path,
            github.url,
            {"hook": {"kind": "webhook", "url": f"{hook.url}/hook", "timeout_seconds": 5}},
        )
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        config["rules"][0]["deliver"] = ["log", "hook"]
        path.write_text(yaml.safe_dump(config), encoding="utf-8")

        assert main(["run", "--config", str(path), "--once"]) == 4
        assert "1 failed" in capsys.readouterr().out
        assert len(events.read_text(encoding="utf-8").splitlines()) == 1


def test_corrupt_cursor_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with StubServer(make_responder()) as server:
        path, _events, state = write_config(tmp_path, server.url)
        state.parent.mkdir(parents=True)
        state.write_text("{broken", encoding="utf-8")
        assert main(["run", "--config", str(path), "--once"]) == 1
        assert "corrupt cursor" in capsys.readouterr().err


def test_missing_config_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--config", str(tmp_path / "absent.yaml"), "--once"]) == 1
    assert "cannot read config" in capsys.readouterr().err
