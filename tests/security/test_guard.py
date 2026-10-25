from __future__ import annotations

from pathlib import Path

import pytest
from _stub import Response, StubServer

from label_notify.config import Config, ConfigError, Rule, load_config
from label_notify.cursor import Cursor
from label_notify.guard import (
    AuthError,
    GitHubClient,
    GuardError,
    RateLimitError,
    post_json,
)
from label_notify.poller import poll_once


def test_non_get_verbs_are_rejected_before_any_socket_opens() -> None:
    with StubServer(lambda request: Response.json([])) as server:
        client = GitHubClient(server.url)
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            with pytest.raises(GuardError, match="zero-write guard"):
                client._request(method, "/repos/o/r/issues")
        assert server.requests == []


def test_get_sends_read_only_headers() -> None:
    with StubServer(lambda request: Response.json({"ok": True})) as server:
        client = GitHubClient(server.url, token="token-123")
        payload, _headers = client.get("/rate_limit")
        assert payload == {"ok": True}
        request = server.requests[0]
        assert request.method == "GET"
        assert request.headers["accept"] == "application/vnd.github+json"
        assert request.headers["authorization"] == "Bearer token-123"
        assert request.headers["user-agent"].startswith("label-notify/")


def test_insecure_api_base_is_rejected() -> None:
    with pytest.raises(GuardError, match="must use https"):
        GitHubClient("http://example.com")


def test_absolute_url_must_stay_on_api_base_origin() -> None:
    client = GitHubClient("https://api.github.com")
    for url in (
        "https://evil.example/x",
        "https://api.github.com.evil.example/x",
        "http://127.0.0.1/x",
    ):
        with pytest.raises(GuardError):
            client.get(url)


def test_token_never_appears_in_auth_error() -> None:
    secret = "ghp_SUPERSECRETVALUE"
    with StubServer(
        lambda request: Response.json({"message": "Bad credentials"}, status=401)
    ) as server:
        client = GitHubClient(server.url, token=secret)
        with pytest.raises(AuthError) as excinfo:
            client.get("/user")
    assert secret not in str(excinfo.value)


def test_token_never_appears_in_rate_limit_error() -> None:
    secret = "ghp_SUPERSECRETVALUE"
    with StubServer(
        lambda request: Response.json(
            {"message": "rate limit"},
            status=403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4102444800"},
        )
    ) as server:
        client = GitHubClient(server.url, token=secret)
        with pytest.raises(RateLimitError) as excinfo:
            client.get("/user")
    assert secret not in str(excinfo.value)
    assert excinfo.value.reset_seconds is not None


def test_redirects_are_refused_for_webhooks() -> None:
    with (
        StubServer(
            lambda request: Response(status=302, headers={"Location": "http://127.0.0.1:1/steal"})
        ) as server,
        pytest.raises(GuardError, match="redirects are not allowed"),
    ):
        post_json(f"{server.url}/hook", {"repo": "o/r"})


def test_redirects_are_refused_for_github() -> None:
    with StubServer(
        lambda request: Response(status=301, headers={"Location": "http://127.0.0.1:1/x"})
    ) as server:
        client = GitHubClient(server.url)
        with pytest.raises(GuardError, match="redirects are not allowed"):
            client.get("/repos/o/r/issues")


def test_webhook_rejects_plain_http() -> None:
    with pytest.raises(GuardError, match="webhook url must use https"):
        post_json("http://example.com/hook", {})


def test_config_rejects_plain_http_webhook(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "repos: [o/r]",
                "rules:",
                "  - name: r",
                "    labels: [bug]",
                "    deliver: [hook]",
                "deliveries:",
                "  hook:",
                "    kind: webhook",
                "    url: http://example.com/hook",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="webhook url must be https"):
        load_config(path)


def test_poll_cycle_issues_only_get_requests() -> None:
    item = {
        "number": 1,
        "title": "t",
        "html_url": "u",
        "labels": [{"name": "bug"}],
        "state": "open",
        "updated_at": "2026-10-25T11:30:00Z",
    }
    with StubServer(lambda request: Response.json([item])) as server:
        client = GitHubClient(server.url)
        rule = Rule("bugs", ("bug",), deliver=("log",))
        poll_once(
            Config(
                repos=("o/r",), rules=(rule,), deliveries={}, state_file=Path("x.json"), max_pages=2
            ),
            Cursor(),
            {"log": lambda event: None},
            client,
        )
        assert {request.method for request in server.requests} == {"GET"}
