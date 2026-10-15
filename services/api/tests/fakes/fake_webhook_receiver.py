"""Fake HTTPS webhook receiver for adapter integration tests."""

from __future__ import annotations

from typing import Any


class FakeWebhookReceiver:
    """Captures inbound POST requests and returns configurable HTTP responses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response_status: int = 200
        self._fail_next: bool = False

    def fail_next(self, http_status: int = 500) -> None:
        self._fail_next = True
        self._response_status = http_status

    def handle(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, str]:
        self.calls.append({
            "headers": dict(headers),
            "body": body,
        })

        if self._fail_next:
            status = self._response_status
            self._fail_next = False
            self._response_status = 200
            return status, "error"

        return 200, "ok"

    def last_call(self) -> dict[str, Any]:
        return self.calls[-1] if self.calls else {}

    def last_headers(self) -> dict[str, str]:
        call = self.last_call()
        return call.get("headers", {})

    def call_count(self) -> int:
        return len(self.calls)

    def reset(self) -> None:
        self.calls.clear()
        self._response_status = 200
        self._fail_next = False
