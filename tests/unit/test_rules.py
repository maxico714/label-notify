from __future__ import annotations

from label_notify.config import Rule
from label_notify.rules import Issue, matches, matching_rules, normalize_issue


def item(**overrides):
    data = {
        "number": 7,
        "title": "Crash on start",
        "html_url": "https://github.com/o/r/issues/7",
        "labels": [{"name": "bug"}, {"name": "priority:high"}],
        "state": "open",
        "updated_at": "2026-10-25T10:00:00Z",
    }
    data.update(overrides)
    return data


def test_normalize_issue_from_dict_labels() -> None:
    issue = normalize_issue("o/r", item())
    assert issue.repo == "o/r"
    assert issue.number == 7
    assert issue.labels == ("bug", "priority:high")
    assert issue.is_pr is False
    assert issue.updated_at == "2026-10-25T10:00:00Z"


def test_normalize_issue_accepts_plain_string_labels() -> None:
    issue = normalize_issue("o/r", item(labels=["bug", "  security  ", ""]))
    assert issue.labels == ("bug", "security")


def test_normalize_issue_detects_pull_request() -> None:
    issue = normalize_issue("o/r", item(pull_request={"url": "x"}))
    assert issue.is_pr is True


def test_normalize_issue_survives_hostile_fields() -> None:
    issue = normalize_issue(
        "o/r",
        {
            "number": "not-a-number",
            "title": None,
            "html_url": None,
            "labels": None,
            "state": None,
            "updated_at": None,
        },
    )
    assert issue.number == 0
    assert issue.title == ""
    assert issue.url == ""
    assert issue.labels == ()
    assert issue.state == ""
    assert issue.updated_at == ""


def test_matches_label_any_semantics_case_insensitive() -> None:
    issue = normalize_issue("o/r", item())
    rule = Rule(name="r", labels=("BUG", "security"), deliver=("log",))
    assert matches(rule, issue) is True


def test_matches_requires_a_configured_label() -> None:
    issue = normalize_issue("o/r", item())
    rule = Rule(name="r", labels=("security",), deliver=("log",))
    assert matches(rule, issue) is False


def test_type_filter_issue_and_pr() -> None:
    issue = normalize_issue("o/r", item())
    pr = normalize_issue("o/r", item(number=8, pull_request={"url": "x"}))
    issue_rule = Rule(name="i", labels=("bug",), type="issue", deliver=("log",))
    pr_rule = Rule(name="p", labels=("bug",), type="pr", deliver=("log",))
    assert matches(issue_rule, issue) and not matches(issue_rule, pr)
    assert matches(pr_rule, pr) and not matches(pr_rule, issue)


def test_state_filter() -> None:
    closed = normalize_issue("o/r", item(state="closed"))
    open_rule = Rule(name="o", labels=("bug",), state="open", deliver=("log",))
    closed_rule = Rule(name="c", labels=("bug",), state="closed", deliver=("log",))
    assert not matches(open_rule, closed)
    assert matches(closed_rule, closed)


def test_matching_rules_returns_all_matches_in_order() -> None:
    issue = normalize_issue("o/r", item())
    rules = (
        Rule(name="security", labels=("security",), deliver=("log",)),
        Rule(name="bugs", labels=("bug",), deliver=("log",)),
        Rule(name="open-bugs", labels=("bug",), state="open", deliver=("log",)),
    )
    assert [rule.name for rule in matching_rules(rules, issue)] == ["bugs", "open-bugs"]


def test_issue_dataclass_is_immutable() -> None:
    issue = Issue("o/r", 1, "t", "u", ("bug",), False, "open", "2026-10-25T10:00:00Z")
    try:
        issue.number = 2  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("Issue should be frozen")
