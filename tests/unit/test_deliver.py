from __future__ import annotations

import json
from pathlib import Path

import pytest
from _stub import Response, StubServer

from label_notify import deliver as deliver_mod
from label_notify.config import Config, Delivery
from label_notify.deliver import DeliveryError, build_deliveries
from label_notify.guard import ApiError, GuardError


def event() -> dict:
    return {
        "ts": "2026-10-25T12:00:00Z",
        "repo": "o/r",
        "number": 7,
        "title": "Crash",
        "url": "https://github.com/o/r/issues/7",
        "labels": ["bug"],
        "rule": "bugs",
        "deliveries": ["log"],
        "delivery": "log",
        "status": "delivered",
    }


def config_for(delivery: Delivery) -> Config:
    return Config(repos=("o/r",), rules=(), deliveries={delivery.name: delivery})


def test_jsonl_appends_one_json_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "events.jsonl"
    handlers = build_deliveries(config_for(Delivery("log", "jsonl", {"path": str(path)})))
    handlers["log"](event())
    handlers["log"]({**event(), "number": 8})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["number"] == 7
    assert json.loads(lines[1])["number"] == 8


def test_webhook_posts_json() -> None:
    received: list[dict] = []

    def responder(request):
        received.append(json.loads(request.body))
        return Response(status=204)

    with StubServer(responder) as server:
        handlers = build_deliveries(
            config_for(
                Delivery("hook", "webhook", {"url": f"{server.url}/hook", "timeout_seconds": 5})
            )
        )
        handlers["hook"](event())
        assert [request.method for request in server.requests] == ["POST"]
        assert server.requests[0].headers["content-type"] == "application/json"
    assert received[0]["repo"] == "o/r"


def test_webhook_rejects_plain_http() -> None:
    handlers = build_deliveries(
        config_for(Delivery("hook", "webhook", {"url": "http://example.com/hook"}))
    )
    with pytest.raises(GuardError):
        handlers["hook"](event())


def test_webhook_http_error_becomes_api_error() -> None:
    with StubServer(lambda request: Response(status=500)) as server:
        handlers = build_deliveries(
            config_for(Delivery("hook", "webhook", {"url": f"{server.url}/hook"}))
        )
        with pytest.raises(ApiError, match="HTTP 500"):
            handlers["hook"](event())


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[object] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None:
        self.started = True

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: object) -> None:
        self.sent.append(message)


def test_email_builds_message_and_logs_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(deliver_mod.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASS", "secret")
    delivery = Delivery(
        "mail",
        "email",
        {
            "smtp_host": "smtp.example.com",
            "smtp_port": 2525,
            "sender": "bot@example.com",
            "recipients": "a@example.com, b@example.com",
            "username_env": "SMTP_USER",
            "password_env": "SMTP_PASS",
        },
    )
    handlers = build_deliveries(config_for(delivery))
    handlers["mail"](event())

    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 2525)
    assert smtp.started is True
    assert smtp.login_args == ("user", "secret")
    message = smtp.sent[0]
    assert message["Subject"] == "[bugs] o/r#7"
    assert message["To"] == "a@example.com, b@example.com"
    assert "https://github.com/o/r/issues/7" in message.get_content()


def test_email_without_credentials_skips_login(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(deliver_mod.smtplib, "SMTP", FakeSMTP)
    delivery = Delivery(
        "mail",
        "email",
        {"smtp_host": "smtp.example.com", "sender": "a@b.c", "recipients": ["a@b.c"]},
    )
    build_deliveries(config_for(delivery))["mail"](event())
    assert FakeSMTP.instances[0].login_args is None


def test_unsupported_kind_raises() -> None:
    with pytest.raises(DeliveryError, match="unsupported delivery kind"):
        build_deliveries(config_for(Delivery("x", "carrier-pigeon", {})))
