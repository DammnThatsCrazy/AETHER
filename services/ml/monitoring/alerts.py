"""Alerting via CloudWatch, SNS, and Slack webhooks."""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger("aether.alerts")


# =============================================================================
# ALERT DATA STRUCTURES
# =============================================================================


class AlertSeverity(Enum):
    """Alert severity levels, from least to most urgent."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """A single alert instance."""

    title: str
    message: str
    severity: AlertSeverity
    model: str
    metric: str | None = None
    value: float | None = None
    threshold: float | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the alert to a plain dictionary."""
        return {
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "model": self.model,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# CLOUDWATCH REPORTER
# =============================================================================


class CloudWatchReporter:
    """Publishes custom metrics to AWS CloudWatch.

    Requires valid AWS credentials in the environment or an IAM role
    attached to the compute instance.
    """

    def __init__(
        self, namespace: str = "AetherML", region: str = "us-east-1"
    ) -> None:
        self.namespace = namespace
        self.region = region
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazily initialise the CloudWatch client."""
        if self._client is None:
            import boto3

            self._client = boto3.client("cloudwatch", region_name=self.region)
        return self._client

    def put_metric(
        self,
        metric_name: str,
        value: float,
        dimensions: dict[str, str] | None = None,
    ) -> None:
        """Publish a single custom metric to CloudWatch.

        Args:
            metric_name: Name of the CloudWatch metric.
            value: Numeric value.
            dimensions: Optional key-value pairs for metric dimensions.
        """
        if dimensions is None:
            dimensions = {}

        cw_dimensions = [
            {"Name": k, "Value": v} for k, v in dimensions.items()
        ]

        try:
            client = self._get_client()
            client.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        "MetricName": metric_name,
                        "Value": value,
                        "Unit": "None",
                        "Dimensions": cw_dimensions,
                    }
                ],
            )
            logger.debug(f"Published CloudWatch metric: {metric_name}={value}")
        except Exception as exc:
            logger.error(f"Failed to publish CloudWatch metric '{metric_name}': {exc}")

    def put_model_metrics(
        self, model_name: str, metrics: dict[str, float]
    ) -> None:
        """Publish a batch of metrics for a specific model.

        Each metric is tagged with a Model dimension set to *model_name*.

        Args:
            model_name: Identifier for the model.
            metrics: Mapping of metric_name -> value.
        """
        metric_data: list[dict[str, Any]] = []
        dimensions = [{"Name": "Model", "Value": model_name}]

        for name, value in metrics.items():
            metric_data.append(
                {
                    "MetricName": name,
                    "Value": value,
                    "Unit": "None",
                    "Dimensions": dimensions,
                }
            )

        if not metric_data:
            return

        try:
            client = self._get_client()
            # CloudWatch accepts at most 1000 metrics per call; batch if needed
            batch_size = 1000
            for i in range(0, len(metric_data), batch_size):
                batch = metric_data[i : i + batch_size]
                client.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=batch,
                )
            logger.info(
                f"Published {len(metric_data)} CloudWatch metrics for model '{model_name}'"
            )
        except Exception as exc:
            logger.error(
                f"Failed to publish CloudWatch metrics for '{model_name}': {exc}"
            )


# =============================================================================
# SNS ALERTER
# =============================================================================


class SNSAlerter:
    """Sends alerts via AWS SNS (Simple Notification Service).

    Requires the target SNS topic ARN and valid AWS credentials.
    """

    def __init__(self, topic_arn: str, region: str = "us-east-1") -> None:
        self.topic_arn = topic_arn
        self.region = region
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazily initialise the SNS client."""
        if self._client is None:
            import boto3

            self._client = boto3.client("sns", region_name=self.region)
        return self._client

    def send_alert(self, alert: Alert) -> bool:
        """Publish an alert to the configured SNS topic.

        Args:
            alert: The Alert to send.

        Returns:
            True if the message was published successfully, False otherwise.
        """
        subject = (
            f"[{alert.severity.value.upper()}] Aether ML: {alert.title}"
        )
        # SNS subject has a 100-character limit
        subject = subject[:100]

        body = json.dumps(alert.to_dict(), indent=2)

        try:
            client = self._get_client()
            client.publish(
                TopicArn=self.topic_arn,
                Subject=subject,
                Message=body,
                MessageAttributes={
                    "severity": {
                        "DataType": "String",
                        "StringValue": alert.severity.value,
                    },
                    "model": {
                        "DataType": "String",
                        "StringValue": alert.model,
                    },
                },
            )
            logger.info(f"SNS alert sent: {alert.title}")
            return True
        except Exception as exc:
            logger.error(f"SNS alert failed: {exc}")
            return False


# =============================================================================
# SLACK ALERTER
# =============================================================================


class SlackAlerter:
    """Sends alerts to Slack via an incoming webhook URL.

    Uses Slack Block Kit for rich message formatting.
    """

    SEVERITY_COLORS: dict[AlertSeverity, str] = {
        AlertSeverity.INFO: "#36a64f",
        AlertSeverity.WARNING: "#ffa500",
        AlertSeverity.CRITICAL: "#ff0000",
    }

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send_alert(self, alert: Alert) -> bool:
        """Post an alert to Slack.

        Args:
            alert: The Alert to send.

        Returns:
            True if the webhook responded with HTTP 200, False otherwise.
        """
        payload = self._format_message(alert)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            urllib.request.urlopen(req, timeout=10)
            logger.info(f"Slack alert sent: {alert.title}")
            return True
        except Exception as exc:
            logger.error(f"Slack alert failed: {exc}")
            return False

    def _format_message(self, alert: Alert) -> dict[str, Any]:
        """Build a Slack Block Kit payload for the alert.

        Args:
            alert: The Alert to format.

        Returns:
            Dictionary suitable for posting to a Slack webhook.
        """
        severity_label = alert.severity.value.upper()
        color = self.SEVERITY_COLORS.get(alert.severity, "#808080")

        fields: list[dict[str, Any]] = [
            {"type": "mrkdwn", "text": f"*Severity:*\n{severity_label}"},
            {"type": "mrkdwn", "text": f"*Model:*\n{alert.model}"},
        ]
        if alert.metric is not None:
            fields.append(
                {"type": "mrkdwn", "text": f"*Metric:*\n{alert.metric}"}
            )
        if alert.value is not None:
            fields.append(
                {"type": "mrkdwn", "text": f"*Value:*\n{alert.value:.4f}"}
            )
        if alert.threshold is not None:
            fields.append(
                {"type": "mrkdwn", "text": f"*Threshold:*\n{alert.threshold}"}
            )
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*Time:*\n{alert.timestamp.isoformat()}",
            }
        )

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Aether ML Alert: {alert.title}",
                },
            },
            {
                "type": "section",
                "fields": fields,
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": alert.message},
            },
        ]

        return {
            "attachments": [{"color": color, "blocks": blocks}],
        }


# =============================================================================
# ALERT MANAGER
# =============================================================================


class AlertManager:
    """Manages alert routing, deduplication, and cooldown logic.

    Maintains a list of notification channels and ensures the same alert
    is not fired repeatedly within a configurable cooldown window.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.channels: list[Any] = []  # SNSAlerter, SlackAlerter, CloudWatchReporter, etc.
        self.alert_history: list[Alert] = []
        self.cooldowns: dict[str, datetime] = {}  # dedupe_key -> last alert time

    def add_channel(self, channel: Any) -> None:
        """Register a notification channel (SNSAlerter, SlackAlerter, etc.).

        Args:
            channel: Any object that exposes a ``send_alert(alert)`` method.
        """
        self.channels.append(channel)
        logger.info(f"Alert channel registered: {type(channel).__name__}")

    def fire(self, alert: Alert) -> bool:
        """Fire an alert through all registered channels.

        The alert is suppressed if an identical alert (same model + metric +
        severity) was fired within the cooldown window.

        Args:
            alert: The Alert to fire.

        Returns:
            True if the alert was dispatched, False if it was suppressed.
        """
        cooldown_minutes = self.config.get("cooldown_minutes", 30)

        if self._should_suppress(alert, cooldown_minutes=cooldown_minutes):
            logger.debug(
                f"Alert suppressed (cooldown): {alert.title} for model={alert.model}"
            )
            return False

        sent_any = False
        for channel in self.channels:
            try:
                if hasattr(channel, "send_alert"):
                    channel.send_alert(alert)
                    sent_any = True
            except Exception as exc:
                logger.error(
                    f"Failed to send alert via {type(channel).__name__}: {exc}"
                )

        # Record in history and update cooldown
        self.alert_history.append(alert)
        dedupe_key = self._dedupe_key(alert)
        self.cooldowns[dedupe_key] = alert.timestamp

        logger.info(
            f"Alert fired [{alert.severity.value}]: {alert.title} "
            f"(model={alert.model}, dispatched_to={len(self.channels)} channels)"
        )
        return sent_any or len(self.channels) == 0

    def _should_suppress(
        self, alert: Alert, cooldown_minutes: int = 30
    ) -> bool:
        """Check whether the alert should be suppressed due to cooldown.

        Args:
            alert: The candidate alert.
            cooldown_minutes: Minimum minutes between duplicate alerts.

        Returns:
            True if the alert should be suppressed.
        """
        dedupe_key = self._dedupe_key(alert)
        last_fired = self.cooldowns.get(dedupe_key)

        if last_fired is None:
            return False

        elapsed = alert.timestamp - last_fired
        return elapsed < timedelta(minutes=cooldown_minutes)

    @staticmethod
    def _dedupe_key(alert: Alert) -> str:
        """Generate a deduplication key from the alert's identifying fields."""
        return f"{alert.model}:{alert.metric}:{alert.severity.value}"
