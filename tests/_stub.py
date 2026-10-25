from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def param(self, name: str) -> str | None:
        values = self.query.get(name)
        return values[0] if values else None


@dataclass
class Response:
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    @classmethod
    def json(
        cls, payload: Any, status: int = 200, headers: dict[str, str] | None = None
    ) -> Response:
        return cls(
            status=status,
            headers={"Content-Type": "application/json", **(headers or {})},
            body=json.dumps(payload).encode("utf-8"),
        )


Responder = Callable[[Request], Response]


class StubServer:
    def __init__(self, responder: Responder) -> None:
        self.requests: list[Request] = []
        self._responder = responder
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                split = urlsplit(self.path)
                request = Request(
                    method=self.command,
                    path=split.path,
                    query=parse_qs(split.query),
                    headers={key.lower(): value for key, value in self.headers.items()},
                    body=body,
                )
                outer.requests.append(request)
                try:
                    response = outer._responder(request)
                except Exception as exc:  # noqa: BLE001 - surfaced as a 500 to the client
                    response = Response.json({"error": repr(exc)}, status=500)
                self.send_response(response.status)
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response.body)))
                self.end_headers()
                if response.body:
                    self.wfile.write(response.body)

            def do_GET(self) -> None:
                self._handle()

            def do_POST(self) -> None:
                self._handle()

            def do_PATCH(self) -> None:
                self._handle()

            def do_PUT(self) -> None:
                self._handle()

            def do_DELETE(self) -> None:
                self._handle()

            def log_message(self, *args: Any) -> None:
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> StubServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
