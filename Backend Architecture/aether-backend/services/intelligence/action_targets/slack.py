from services.intelligence.action_targets.base import BaseActionTarget

class SlackActionTarget(BaseActionTarget):
    target_type = "slack"
    label = "Slack notification"
    description = "Post an approved action into a configured Slack channel. Simulated in this phase."
    supported_action_types = ("manual", "playbook_step", "manual_or_system_triggered", "notification")
    supports_cancellation = False

    def external_url(self, dispatch, config):
        return f"https://slack.example.local/{config.default_destination or 'channel'}/{dispatch.dispatch_id}" if config else None
