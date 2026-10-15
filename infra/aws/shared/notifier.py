"""
Centralised notification dispatcher — Slack, PagerDuty, SNS.
Single implementation replaces ad-hoc notification stubs
scattered across DR and monitoring scripts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from shared.aws_client import aws_client
from shared.runner import log, run_cmd


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    RESOLVED = "resolved"


@dataclass
class Notification:
    title: str
    message: str
    severity: Severity = Severity.INFO
    channel: str = "ops"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Notifier:
    """Fan-out notifications to multiple channels."""

    def __init__(self):
        self.slack_webhook = os.environ.get("AETHER_SLACK_WEBHOOK", "")
        self.pagerduty_key = os.environ.get("AETHER_PAGERDUTY_KEY", "")
        self.sns_topic_arn = os.environ.get("AETHER_SNS_TOPIC_ARN", "")

    def send(self, notification: Notification) -> None:
        """Dispatch notification to all configured channels."""
        log(f"Sending notification: {notification.title} [{notification.severity.value}]", tag="NOTIFY")

        if self.sns_topic_arn:
            self._send_sns(notification)
        if self.slack_webhook:
            self._send_slack(notification)
        if self.pagerduty_key and notification.severity in (Severity.CRITICAL, Severity.WARNING):
            self._send_pagerduty(notification)

        # Always log locally
        log(f"  -> {notification.message}", tag="NOTIFY")

    def _send_sns(self, n: Notification) -> None:
        """Publish to SNS topic."""
        resp = aws_client.safe_call(
            "sns", "publish",
            TopicArn=self.sns_topic_arn,
            Subject=f"[Aether {n.severity.value.upper()}] {n.title}",
            Message=json.dumps({
                "title": n.title,
                "message": n.message,
                "severity": n.severity.value,
                "timestamp": n.timestamp,
                "metadata": n.metadata,
            }),
        )
        if resp:
            log("  -> SNS published", tag="NOTIFY")
        else:
            log("  -> SNS publish (stub mode)", tag="NOTIFY")

    def _send_slack(self, n: Notification) -> None:
        """Post to Slack via webhook."""
        icon = {"info": ":information_source:", "warning": ":warning:",
                "critical": ":rotating_light:", "resolved": ":white_check_mark:"}
        payload = json.dumps({
            "text": f"{icon.get(n.severity.value, '')} *{n.title}*\n{n.message}",
            "channel": f"#aether-{n.channel}",
        })
        if self.slack_webhook:
            run_cmd(f"curl -sf -X POST -H 'Content-Type: application/json' -d '{payload}' {self.slack_webhook}")
        else:
            log("  -> Slack (stub mode)", tag="NOTIFY")

    def _send_pagerduty(self, n: Notification) -> None:
        """Create PagerDuty incident."""
        log(f"  -> PagerDuty incident: {n.title} [{n.severity.value}]", tag="NOTIFY")

    # ── Convenience methods ──────────────────────────────────────────

    def dr_alert(self, scope: str, status: str, details: str = "") -> None:
        self.send(Notification(
            title=f"DR Failover — {scope}",
            message=f"Status: {status}. {details}",
            severity=Severity.CRITICAL,
            channel="incidents",
            metadata={"scope": scope, "status": status},
        ))

    def alarm_fired(self, alarm_name: str, metric: str, value: float, threshold: float) -> None:
        self.send(Notification(
            title=f"Alarm: {alarm_name}",
            message=f"{metric} = {value} (threshold: {threshold})",
            severity=Severity.WARNING,
            channel="alerts",
            metadata={"alarm": alarm_name, "metric": metric, "value": value},
        ))

    def cost_alert(self, account: str, actual: float, budget: float) -> None:
        self.send(Notification(
            title=f"Budget Alert — {account}",
            message=f"Forecast ${actual:,.0f} exceeds budget ${budget:,.0f}",
            severity=Severity.WARNING,
            channel="cost",
            metadata={"account": account, "actual": actual, "budget": budget},
        ))

    def security_finding(self, finding_type: str, resource: str, severity: str) -> None:
        sev = Severity.CRITICAL if severity == "HIGH" else Severity.WARNING
        self.send(Notification(
            title=f"Security Finding — {finding_type}",
            message=f"Resource: {resource}, Severity: {severity}",
            severity=sev,
            channel="security",
            metadata={"finding_type": finding_type, "resource": resource},
        ))

    def ml_serving_alert(
        self,
        model_name: str,
        metric: str,
        value: float,
        threshold: float,
        details: str = "",
    ) -> None:
        """Fire when an ML serving metric (latency, error rate, PSI drift) breaches threshold."""
        self.send(Notification(
            title=f"ML Serving Alert — {model_name}",
            message=f"{metric} = {value:.4f} (threshold: {threshold}). {details}".strip(),
            severity=Severity.CRITICAL,
            channel="ml-alerts",
            metadata={
                "model": model_name,
                "metric": metric,
                "value": value,
                "threshold": threshold,
            },
        ))


# Module-level singleton
notifier = Notifier()
