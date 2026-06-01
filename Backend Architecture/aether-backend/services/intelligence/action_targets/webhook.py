from services.intelligence.action_targets.base import BaseActionTarget

class WebhookActionTarget(BaseActionTarget):
    target_type = "webhook"
    label = "Webhook"
    description = "Send a signed webhook payload to a tenant-configured endpoint. Simulated in this phase."
    supported_action_types = ("manual", "playbook_step", "manual_or_system_triggered", "webhook")
    supports_cancellation = False

    def external_url(self, dispatch, config):
        return config.default_destination if config else None
