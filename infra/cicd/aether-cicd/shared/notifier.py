"""
Aether CI/CD -- Notification System
Sends pipeline events to Slack, PagerDuty, and stdout.
All notification logic in one place -- no scattered curl calls.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum

from shared.runner import log, run_cmd


class NotifyEvent(str, Enum):
    CI_STARTED = "ci_started"
    CI_PASSED = "ci_passed"
    CI_FAILED = "ci_failed"
    CD_STARTED = "cd_started"
    CD_STAGE_PASSED = "cd_stage_passed"
    CD_STAGE_FAILED = "cd_stage_failed"
    CD_SUCCESS = "cd_success"
    ROLLBACK = "rollback"
    SDK_RELEASED = "sdk_released"
    DRIFT_DETECTED = "drift_detected"


# Icon map for Slack messages
_ICONS: dict[NotifyEvent, str] = {
    NotifyEvent.CI_STARTED:      ":gear:",
    NotifyEvent.CI_PASSED:       ":white_check_mark:",
    NotifyEvent.CI_FAILED:       ":x:",
    NotifyEvent.CD_STARTED:      ":rocket:",
    NotifyEvent.CD_STAGE_PASSED: ":white_check_mark:",
    NotifyEvent.CD_STAGE_FAILED: ":x:",
    NotifyEvent.CD_SUCCESS:      ":tada:",
    NotifyEvent.ROLLBACK:        ":rotating_light:",
    NotifyEvent.SDK_RELEASED:    ":package:",
    NotifyEvent.DRIFT_DETECTED:  ":warning:",
}


@dataclass
class Notifier:
    """
    Centralised notifier.  Reads webhook URLs from environment variables
    so secrets never appear in code.
    """

    slack_webhook_env: str = "SLACK_WEBHOOK"
    pagerduty_key_env: str = "PAGERDUTY_ROUTING_KEY"
    dry_run: bool = False

    # -- Slack ----------------------------------------------------------------

    def _slack_webhook(self) -> str | None:
        return os.environ.get(self.slack_webhook_env)

    def slack(
        self,
        event: NotifyEvent,
        message: str,
        channel: str | None = None,
        fields: dict[str, str] | None = None,
    ) -> bool:
        """Send a Slack notification via incoming webhook."""
        webhook = self._slack_webhook()
        if not webhook:
            log("Slack webhook not configured, skipping notification", stage="NOTIFY")
            return False

        icon = _ICONS.get(event, ":bell:")
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{icon} *{event.value.upper()}*\n{message}"},
            }
        ]

        if fields:
            field_blocks = [
                {"type": "mrkdwn", "text": f"*{k}:* {v}"}
                for k, v in fields.items()
            ]
            blocks.append({"type": "section", "fields": field_blocks})

        payload = json.dumps({"blocks": blocks})

        if self.dry_run:
            log(f"[DRY RUN] Slack: {event.value} -- {message}", stage="NOTIFY")
            return True

        result = run_cmd(
            f"curl -sf -X POST {webhook} -H 'Content-type: application/json' "
            f"-d '{payload}'",
            timeout=10,
        )
        return result.success

    # -- PagerDuty ------------------------------------------------------------

    def pagerduty(
        self,
        summary: str,
        severity: str = "critical",
        source: str = "aether-cicd",
        dedup_key: str | None = None,
    ) -> bool:
        """Trigger a PagerDuty event via Events API v2."""
        routing_key = os.environ.get(self.pagerduty_key_env)
        if not routing_key:
            log("PagerDuty routing key not configured", stage="NOTIFY")
            return False

        payload = json.dumps({
            "routing_key": routing_key,
            "event_action": "trigger",
            "dedup_key": dedup_key or "",
            "payload": {
                "summary": summary,
                "severity": severity,
                "source": source,
            },
        })

        if self.dry_run:
            log(f"[DRY RUN] PagerDuty: {severity} -- {summary}", stage="NOTIFY")
            return True

        result = run_cmd(
            f"curl -sf -X POST https://events.pagerduty.com/v2/enqueue "
            f"-H 'Content-Type: application/json' -d '{payload}'",
            timeout=10,
        )
        return result.success

    # -- Convenience helpers --------------------------------------------------

    def ci_result(self, passed: bool, commit_sha: str, summary: str) -> None:
        event = NotifyEvent.CI_PASSED if passed else NotifyEvent.CI_FAILED
        self.slack(event, summary, fields={"commit": commit_sha[:8]})
        if not passed:
            self.pagerduty(
                f"Aether CI failed for {commit_sha[:8]}: {summary}",
                severity="warning",
                dedup_key=f"ci-{commit_sha[:8]}",
            )

    def cd_rollback(self, version: str, reason: str) -> None:
        self.slack(
            NotifyEvent.ROLLBACK,
            f"Deployment *{version}* rolled back",
            fields={"reason": reason},
        )
        self.pagerduty(
            f"Aether ROLLBACK: {version} -- {reason}",
            severity="critical",
            dedup_key=f"rollback-{version}",
        )

    def cd_success(self, version: str, environment: str) -> None:
        self.slack(
            NotifyEvent.CD_SUCCESS,
            f"Deployment *{version}* successful to *{environment}*",
            fields={"environment": environment, "version": version},
        )

    def drift_detected(self, environment: str, details: str) -> None:
        self.slack(
            NotifyEvent.DRIFT_DETECTED,
            f"Terraform drift detected in *{environment}*",
            fields={"details": details[:200]},
        )
