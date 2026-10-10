"""Fake Slack Web API server for adapter integration tests.

Simulates chat.postMessage — returns a real-looking `ts` field.
"""

from __future__ import annotations

import json
import time
from typing import Any


class FakeSlackAPI:
    """In-memory Slack API stub — captures requests, returns configurable responses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_next: bool = False
        self._rate_limit_next: bool = False
        self._error_code: str = ""

    def fail_next(self, error_code: str = "channel_not_found") -> None:
        self._fail_next = True
        self._error_code = error_code

    def rate_limit_next(self) -> None:
        self._rate_limit_next = True

    def handle_post_message(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.calls.append(body)

        if self._rate_limit_next:
            self._rate_limit_next = False
            return 429, {"ok": False, "error": "ratelimited"}

        if self._fail_next:
            code = self._error_code
            self._fail_next = False
            self._error_code = ""
            return 200, {"ok": False, "error": code}

        ts = str(time.time())
        channel = body.get("channel", "#general")
        return 200, {
            "ok": True,
            "channel": channel,
            "ts": ts,
            "message": {"ts": ts, "text": body.get("text", ""), "type": "message"},
        }

    def last_call(self) -> dict[str, Any]:
        return self.calls[-1] if self.calls else {}

    def call_count(self) -> int:
        return len(self.calls)

    def reset(self) -> None:
        self.calls.clear()
        self._fail_next = False
        self._rate_limit_next = False
        self._error_code = ""
