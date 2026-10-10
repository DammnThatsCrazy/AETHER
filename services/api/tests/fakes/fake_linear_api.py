"""Fake Linear GraphQL API for adapter integration tests."""

from __future__ import annotations

import uuid
from typing import Any


class FakeLinearAPI:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_next: bool = False
        self._error_message: str = ""

    def fail_next(self, message: str = "Unauthorized") -> None:
        self._fail_next = True
        self._error_message = message

    def handle_graphql(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.calls.append(body)

        if self._fail_next:
            msg = self._error_message
            self._fail_next = False
            self._error_message = ""
            return 200, {"errors": [{"message": msg}]}

        issue_id = str(uuid.uuid4())
        issue_identifier = f"ENG-{len(self.calls)}"
        variables = body.get("variables", {})
        title = (variables.get("input") or {}).get("title", "Aether Notification")

        return 200, {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": issue_id,
                        "identifier": issue_identifier,
                        "url": f"https://linear.app/team/issue/{issue_identifier}",
                        "title": title,
                    },
                }
            }
        }

    def last_call(self) -> dict[str, Any]:
        return self.calls[-1] if self.calls else {}

    def reset(self) -> None:
        self.calls.clear()
        self._fail_next = False
        self._error_message = ""
