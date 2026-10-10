"""Fake Jira REST v3 API for adapter integration tests."""

from __future__ import annotations

import uuid
from typing import Any


class FakeJiraAPI:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_next: bool = False
        self._http_status: int = 201
        self._issue_counter: int = 0

    def fail_next(self, http_status: int = 400) -> None:
        self._fail_next = True
        self._http_status = http_status

    def handle_create_issue(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.calls.append(body)

        if self._fail_next:
            status = self._http_status
            self._fail_next = False
            self._http_status = 201
            return status, {"errorMessages": ["Simulated Jira error"], "errors": {}}

        self._issue_counter += 1
        project_key = (body.get("fields") or {}).get("project", {}).get("key", "PROJ")
        issue_num = self._issue_counter
        issue_key = f"{project_key}-{issue_num}"
        issue_id = str(uuid.uuid4())

        return 201, {
            "id": issue_id,
            "key": issue_key,
            "self": f"https://mycompany.atlassian.net/rest/api/3/issue/{issue_id}",
        }

    def last_call(self) -> dict[str, Any]:
        return self.calls[-1] if self.calls else {}

    def reset(self) -> None:
        self.calls.clear()
        self._fail_next = False
        self._http_status = 201
        self._issue_counter = 0
