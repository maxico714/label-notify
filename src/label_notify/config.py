from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    code = "E_CONFIG"


@dataclass(frozen=True)
class Delivery:
    name: str
    kind: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    name: str
    labels: tuple[str, ...]
    type: str = "any"
    state: str = "any"
    deliver: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    repos: tuple[str, ...]
    rules: tuple[Rule, ...]
    deliveries: dict[str, Delivery]
    api_base: str = "https://api.github.com"
    token_env: str = "GITHUB_TOKEN"
    interval_seconds: int = 300
    lookback_hours: int = 24
    timeout_seconds: float = 10.0
    max_pages: int = 5
    state_file: Path = field(
        default_factory=lambda: Path("~/.local/state/label-notify/cursor.json").expanduser()
    )

    def token(self) -> str | None:
        value = os.environ.get(self.token_env, "").strip()
        return value or None


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"{where}: missing required field '{key}'")
    return mapping[key]


def _delivery(name: str, raw: dict[str, Any]) -> Delivery:
    kind = str(_require(raw, "kind", f"delivery '{name}'")).lower()
    options = {key: value for key, value in raw.items() if key != "kind"}
    if kind == "jsonl":
        _require(options, "path", f"delivery '{name}'")
    elif kind == "webhook":
        url = str(_require(options, "url", f"delivery '{name}'"))
        if not (
            url.startswith("https://")
            or url.startswith("http://127.0.0.1")
            or url.startswith("http://localhost")
        ):
            raise ConfigError(
                f"delivery '{name}': webhook url must be https (or localhost for tests)"
            )
    elif kind == "email":
        for key in ("smtp_host", "sender", "recipients"):
            _require(options, key, f"delivery '{name}'")
    else:
        raise ConfigError(f"delivery '{name}': unsupported kind '{kind}'")
    return Delivery(name=name, kind=kind, options=options)


def _rule(name: str, raw: dict[str, Any]) -> Rule:
    labels = _require(raw, "labels", f"rule '{name}'")
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ConfigError(f"rule '{name}': labels must be a non-empty list of strings")
    cleaned = tuple(item.strip() for item in labels if item.strip())
    if not cleaned:
        raise ConfigError(f"rule '{name}': labels must be a non-empty list of strings")
    rule_type = str(raw.get("type", "any")).lower()
    if rule_type not in {"issue", "pr", "any"}:
        raise ConfigError(f"rule '{name}': type must be issue, pr, or any")
    state = str(raw.get("state", "any")).lower()
    if state not in {"open", "closed", "any"}:
        raise ConfigError(f"rule '{name}': state must be open, closed, or any")
    deliver = raw.get("deliver", [])
    if (
        not isinstance(deliver, list)
        or not deliver
        or not all(isinstance(item, str) for item in deliver)
    ):
        raise ConfigError(f"rule '{name}': deliver must be a non-empty list of delivery names")
    return Rule(name=name, labels=cleaned, type=rule_type, state=state, deliver=tuple(deliver))


def load_config(path: Path) -> Config:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config '{path}': {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in '{path}': {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")

    repos_raw = _require(data, "repos", "config")
    if not isinstance(repos_raw, list) or not repos_raw:
        raise ConfigError("config: repos must be a non-empty list")
    repos: list[str] = []
    for item in repos_raw:
        repo = str(item).strip()
        parts = repo.split("/")
        if len(parts) != 2 or not all(parts):
            raise ConfigError(f"config: repo '{repo}' must look like owner/name")
        repos.append(repo)

    deliveries_raw = data.get("deliveries", {}) or {}
    if not isinstance(deliveries_raw, dict):
        raise ConfigError("config: deliveries must be a mapping")
    deliveries = {
        str(name): _delivery(str(name), raw if isinstance(raw, dict) else {})
        for name, raw in deliveries_raw.items()
    }

    rules_raw = _require(data, "rules", "config")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ConfigError("config: rules must be a non-empty list")
    rules: list[Rule] = []
    for index, raw in enumerate(rules_raw):
        if not isinstance(raw, dict):
            raise ConfigError(f"config: rule #{index + 1} must be a mapping")
        name = str(raw.get("name", f"rule-{index + 1}"))
        rule = _rule(name, raw)
        for delivery_name in rule.deliver:
            if delivery_name not in deliveries:
                raise ConfigError(f"rule '{rule.name}': unknown delivery '{delivery_name}'")
        rules.append(rule)

    github = data.get("github", {}) or {}
    poll = data.get("poll", {}) or {}
    state_file = Path(
        str(data.get("state_file", "~/.local/state/label-notify/cursor.json"))
    ).expanduser()

    api_base = str(github.get("api_base", "https://api.github.com")).rstrip("/")
    if not (
        api_base.startswith("https://")
        or api_base.startswith(("http://127.0.0.1", "http://localhost"))
    ):
        raise ConfigError("github.api_base must use https (localhost is allowed for tests)")

    interval = int(poll.get("interval_seconds", 300))
    lookback = int(poll.get("lookback_hours", 24))
    timeout = float(poll.get("timeout_seconds", 10))
    max_pages = int(poll.get("max_pages", 5))
    if interval <= 0:
        raise ConfigError("poll.interval_seconds must be positive")
    if lookback <= 0:
        raise ConfigError("poll.lookback_hours must be positive")
    if timeout <= 0:
        raise ConfigError("poll.timeout_seconds must be positive")
    if max_pages < 1:
        raise ConfigError("poll.max_pages must be at least 1")

    return Config(
        repos=tuple(repos),
        rules=tuple(rules),
        deliveries=deliveries,
        api_base=api_base,
        token_env=str(github.get("token_env", "GITHUB_TOKEN")),
        interval_seconds=interval,
        lookback_hours=lookback,
        timeout_seconds=timeout,
        max_pages=max_pages,
        state_file=state_file,
    )
