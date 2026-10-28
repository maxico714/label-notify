from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from label_notify.config import Config, ConfigError, load_config


def base_config() -> dict:
    return {
        "repos": ["o/r"],
        "rules": [{"name": "r", "labels": ["bug"], "deliver": ["log"]}],
        "deliveries": {"log": {"kind": "jsonl", "path": "events.jsonl"}},
    }


def write_config(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_valid_config_and_defaults(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, base_config()))
    assert isinstance(config, Config)
    assert config.repos == ("o/r",)
    assert config.rules[0].labels == ("bug",)
    assert config.rules[0].deliver == ("log",)
    assert config.api_base == "https://api.github.com"
    assert config.token_env == "GITHUB_TOKEN"
    assert config.interval_seconds == 300
    assert config.lookback_hours == 24
    assert config.max_pages == 5
    assert config.state_file.name == "cursor.json"


def test_full_config_values(tmp_path: Path) -> None:
    data = base_config()
    data["github"] = {"api_base": "https://ghe.example.com/api/v3/", "token_env": "GH_PAT"}
    data["poll"] = {
        "interval_seconds": 60,
        "lookback_hours": 6,
        "timeout_seconds": 3,
        "max_pages": 2,
    }
    data["state_file"] = str(tmp_path / "state.json")
    config = load_config(write_config(tmp_path, data))
    assert config.api_base == "https://ghe.example.com/api/v3"
    assert config.token_env == "GH_PAT"
    assert (config.interval_seconds, config.lookback_hours) == (60, 6)
    assert (config.timeout_seconds, config.max_pages) == (3.0, 2)
    assert config.state_file == tmp_path / "state.json"


def test_labels_are_trimmed_and_deduplicated_shape(tmp_path: Path) -> None:
    data = base_config()
    data["rules"][0]["labels"] = [" bug ", "security"]
    config = load_config(write_config(tmp_path, data))
    assert config.rules[0].labels == ("bug", "security")


def test_token_reads_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config(write_config(tmp_path, base_config()))
    monkeypatch.setenv("GITHUB_TOKEN", "value")
    assert config.token() == "value"
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    assert config.token() is None
    monkeypatch.delenv("GITHUB_TOKEN")
    assert config.token() is None


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda data: data.pop("repos"), "repos"),
        (lambda data: data.update(repos=[]), "repos must be a non-empty list"),
        (lambda data: data.update(repos=["noslash"]), "must look like owner/name"),
        (lambda data: data["rules"][0].update(labels=[]), "labels"),
        (lambda data: data["rules"][0].update(labels=["  "]), "labels"),
        (lambda data: data["rules"][0].update(type="discussion"), "type must be"),
        (lambda data: data["rules"][0].update(state="merged"), "state must be"),
        (lambda data: data["rules"][0].update(deliver=[]), "deliver must be"),
        (lambda data: data["rules"][0].update(deliver=["missing"]), "unknown delivery"),
        (lambda data: data["deliveries"]["log"].update(kind="pager"), "unsupported kind"),
        (lambda data: data["deliveries"]["log"].pop("path"), "missing required field 'path'"),
        (
            lambda data: data.update(
                deliveries={"hook": {"kind": "webhook", "url": "http://example.com/hook"}}
            ),
            "webhook url must be https",
        ),
        (
            lambda data: data.update(
                deliveries={"mail": {"kind": "email", "sender": "a@b.c", "recipients": ["a@b.c"]}}
            ),
            "smtp_host",
        ),
        (lambda data: data.update(poll={"interval_seconds": 0}), "interval_seconds"),
        (lambda data: data.update(poll={"lookback_hours": 0}), "lookback_hours"),
        (lambda data: data.update(poll={"timeout_seconds": 0}), "timeout_seconds"),
        (lambda data: data.update(poll={"max_pages": 0}), "max_pages"),
        (lambda data: data.update(github={"api_base": "http://example.com"}), "api_base"),
        (
            lambda data: data.update(github={"api_base": "http://localhost.evil.example"}),
            "api_base",
        ),
        (
            lambda data: data.update(github={"api_base": "http://127.0.0.1@evil.example"}),
            "api_base",
        ),
        (lambda data: data.update(github=[1]), "github must be a mapping"),
        (lambda data: data.update(poll=[1]), "poll must be a mapping"),
        (lambda data: data.update(poll={"interval_seconds": "nope"}), "must be an integer"),
        (lambda data: data.update(poll={"timeout_seconds": "nope"}), "must be a number"),
        (lambda data: data.update(poll={"timeout_seconds": float("nan")}), "finite"),
        (lambda data: data.update(poll={"timeout_seconds": float("inf")}), "finite"),
        (lambda data: data.update(poll={"interval_seconds": True}), "must be an integer"),
    ],
)
def test_invalid_configs_raise(tmp_path: Path, mutate, message: str) -> None:
    data = base_config()
    mutate(data)
    with pytest.raises(ConfigError) as excinfo:
        load_config(write_config(tmp_path, data))
    assert message in str(excinfo.value)
    assert excinfo.value.code == "E_CONFIG"


def test_rule_must_be_mapping(tmp_path: Path) -> None:
    data = base_config()
    data["rules"] = ["bug"]
    with pytest.raises(ConfigError, match="rule #1 must be a mapping"):
        load_config(write_config(tmp_path, data))


def test_root_must_be_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="root must be a mapping"):
        load_config(path)


def test_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("repos: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read config"):
        load_config(tmp_path / "absent.yaml")


def test_webhook_localhost_allowed(tmp_path: Path) -> None:
    data = base_config()
    data["deliveries"]["hook"] = {"kind": "webhook", "url": "http://127.0.0.1:9/hook"}
    data["rules"][0]["deliver"] = ["hook"]
    config = load_config(write_config(tmp_path, data))
    assert config.deliveries["hook"].kind == "webhook"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost.evil.example/hook",
        "http://127.0.0.1.evil.example/hook",
        "http://127.0.0.1@evil.example/hook",
    ],
)
def test_webhook_loopback_lookalikes_are_rejected(tmp_path: Path, url: str) -> None:
    data = base_config()
    data["deliveries"]["hook"] = {"kind": "webhook", "url": url}
    data["rules"][0]["deliver"] = ["hook"]
    with pytest.raises(ConfigError, match="webhook url must be https"):
        load_config(write_config(tmp_path, data))
