from __future__ import annotations

import json
import os
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .config import Config, Delivery
from .guard import post_json


class DeliveryError(RuntimeError):
    code = "E_DELIVERY"


Handler = Callable[[dict[str, Any]], None]


def _jsonl(options: dict[str, Any]) -> Handler:
    path = Path(str(options["path"])).expanduser()

    def send(event: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    return send


def _webhook(options: dict[str, Any]) -> Handler:
    url = str(options["url"])
    timeout = float(options.get("timeout_seconds", 10))

    def send(event: dict[str, Any]) -> None:
        post_json(url, event, timeout=timeout)

    return send


def _email(options: dict[str, Any]) -> Handler:
    host = str(options["smtp_host"])
    port = int(options.get("smtp_port", 587))
    sender = str(options["sender"])
    recipients = options["recipients"]
    if isinstance(recipients, str):
        recipients = [item.strip() for item in recipients.split(",") if item.strip()]
    starttls = bool(options.get("starttls", True))
    user_env = options.get("username_env")
    pass_env = options.get("password_env")
    timeout = float(options.get("timeout_seconds", 15))

    def send(event: dict[str, Any]) -> None:
        message = EmailMessage()
        message["Subject"] = f"[{event.get('rule')}] {event.get('repo')}#{event.get('number')}"
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(
            f"{event.get('title')}\n{event.get('url')}\n\n"
            f"Labels: {', '.join(event.get('labels', []))}"
        )
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            if starttls:
                smtp.starttls()
            if user_env and pass_env:
                username = os.environ.get(str(user_env))
                password = os.environ.get(str(pass_env))
                if username and password:
                    smtp.login(username, password)
            smtp.send_message(message)

    return send


def build_deliveries(config: Config) -> dict[str, Handler]:
    handlers: dict[str, Handler] = {}
    for name, delivery in config.deliveries.items():
        handlers[name] = _handler(delivery)
    return handlers


def _handler(delivery: Delivery) -> Handler:
    if delivery.kind == "jsonl":
        return _jsonl(delivery.options)
    if delivery.kind == "webhook":
        return _webhook(delivery.options)
    if delivery.kind == "email":
        return _email(delivery.options)
    raise DeliveryError(f"unsupported delivery kind '{delivery.kind}'")
