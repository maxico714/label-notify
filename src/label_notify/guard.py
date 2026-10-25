from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any


class GuardError(RuntimeError):
    """Blocked by the zero-write or transport policy."""


class AuthError(RuntimeError):
    code = "E_AUTH"


class RateLimitError(RuntimeError):
    code = "E_RATELIMIT"

    def __init__(self, message: str, reset_seconds: float | None = None) -> None:
        super().__init__(message)
        self.reset_seconds = reset_seconds


class ApiError(RuntimeError):
    code = "E_API"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so an allow-listed URL cannot pivot to another host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise GuardError(f"redirects are not allowed (HTTP {code})")


_OPENER = urllib.request.build_opener(_NoRedirect())


class GitHubClient:
    """GET-only GitHub client. Any other verb is rejected before a socket opens."""

    def __init__(
        self,
        api_base: str = "https://api.github.com",
        token: str | None = None,
        timeout: float = 10.0,
        user_agent: str = "label-notify/0.1",
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self._token = token
        self.timeout = timeout
        self.user_agent = user_agent
        self._check_base(self.api_base)

    @staticmethod
    def _check_base(url: str) -> None:
        local = url.startswith(
            ("http://127.0.0.1", "http://localhost", "https://127.0.0.1", "https://localhost")
        )
        if not (url.startswith("https://") or local):
            raise GuardError("api_base must use https (localhost is allowed for tests)")

    def _check_same_origin(self, url: str) -> None:
        base = urllib.parse.urlsplit(self.api_base)
        target = urllib.parse.urlsplit(url)
        if (target.scheme, target.hostname, target.port) != (
            base.scheme,
            base.hostname,
            base.port,
        ):
            raise GuardError("absolute URLs must stay on the configured api_base host")

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
        return self._request("GET", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        body: bytes | None = None,
    ) -> tuple[Any, dict[str, str]]:
        if method != "GET":
            raise GuardError(f"zero-write guard: {method} to GitHub is not allowed")
        if path.startswith("http"):
            self._check_same_origin(path)
            url = path
        else:
            url = f"{self.api_base}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        self._check_base(url)
        if path.startswith("http"):
            self._check_same_origin(url)

        request = urllib.request.Request(url, method="GET")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("User-Agent", self.user_agent)
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")

        try:
            with _OPENER.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "null")
                headers = {key.lower(): value for key, value in response.headers.items()}
                return payload, headers
        except urllib.error.HTTPError as exc:
            headers = (
                {key.lower(): value for key, value in exc.headers.items()} if exc.headers else {}
            )
            remaining = headers.get("x-ratelimit-remaining")
            reset = headers.get("x-ratelimit-reset")
            if exc.code in (403, 429) and remaining == "0":
                seconds = None
                if reset and reset.isdigit():
                    import time

                    seconds = max(0.0, float(reset) - time.time())
                raise RateLimitError("GitHub rate limit exhausted", reset_seconds=seconds) from None
            if exc.code in (401, 403):
                raise AuthError(f"GitHub rejected the request (HTTP {exc.code})") from None
            raise ApiError(f"GitHub request failed (HTTP {exc.code})") from None
        except urllib.error.URLError as exc:
            raise ApiError(f"cannot reach GitHub: {exc.reason}") from None
        except json.JSONDecodeError:
            raise ApiError("GitHub returned a non-JSON response") from None


def post_json(url: str, payload: Mapping[str, Any], timeout: float = 10.0) -> None:
    """Deliver a webhook payload. HTTPS only (localhost is allowed for tests)."""
    local = url.startswith(("http://127.0.0.1", "http://localhost"))
    if not (url.startswith("https://") or local):
        raise GuardError("webhook url must use https (localhost is allowed for tests)")
    data = json.dumps(dict(payload)).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "label-notify/0.1")
    try:
        with _OPENER.open(request, timeout=timeout):
            return
    except urllib.error.HTTPError as exc:
        raise ApiError(f"webhook returned HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise ApiError(f"webhook delivery failed: {exc}") from None
