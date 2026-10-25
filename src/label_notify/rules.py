from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Rule


@dataclass(frozen=True)
class Issue:
    repo: str
    number: int
    title: str
    url: str
    labels: tuple[str, ...]
    is_pr: bool
    state: str
    updated_at: str


def normalize_issue(repo: str, item: dict[str, Any]) -> Issue:
    labels: list[str] = []
    for label in item.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.strip():
            labels.append(name.strip())
    try:
        number = int(item.get("number", 0))
    except (TypeError, ValueError):
        number = 0
    return Issue(
        repo=repo,
        number=number,
        title=str(item.get("title") or ""),
        url=str(item.get("html_url") or ""),
        labels=tuple(labels),
        is_pr="pull_request" in item,
        state=str(item.get("state") or ""),
        updated_at=str(item.get("updated_at") or ""),
    )


def matches(rule: Rule, issue: Issue) -> bool:
    if rule.type == "issue" and issue.is_pr:
        return False
    if rule.type == "pr" and not issue.is_pr:
        return False
    if rule.state != "any" and issue.state != rule.state:
        return False
    wanted = {label.lower() for label in rule.labels}
    return any(label.lower() in wanted for label in issue.labels)


def matching_rules(rules: tuple[Rule, ...], issue: Issue) -> list[Rule]:
    return [rule for rule in rules if matches(rule, issue)]
