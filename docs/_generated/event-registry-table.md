<!-- DO NOT EDIT — generated from packages/shared/contracts/event-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Event Registry (248 types, contract v8.10.0)

| Event Type | Family | Required Purposes | Privacy Class | Description |
|---|---|---|---|---|
| `track` | `core` | analytics | behavioral | Custom application event via aether.track() |
| `page` | `core` | analytics | behavioral | Page/screen view from aether.pageView() + SPA hooks |
| `screen` | `core` | analytics | behavioral | Native screen view from screenView() |
| `heartbeat` | `core` | analytics | behavioral | Session liveness heartbeat from session manager |
| `error` | `core` | analytics | behavioral | Client-side error capture |
| `performance` | `core` | analytics | behavioral | Web Vitals and performance metrics |
| `experiment` | `core` | marketing | behavioral | Experiment variant exposure |
| `journey_started` | `journey` | analytics | behavioral | Journey lifecycle start |
| `journey_paused` | `journey` | analytics | behavioral | Journey paused by user or system |
| `journey_resumed` | `journey` | analytics | behavioral | Journey resumed from paused state |
| `journey_continued` | `journey` | analytics | behavioral | Journey step progression |
| `journey_completed` | `journey` | analytics | behavioral | Journey reached completion |
| `journey_abandoned` | `journey` | analytics | behavioral | Journey abandoned without completion |
| `journey_checkpoint` | `journey` | analytics | behavioral | Journey milestone checkpoint |
| `identify` | `identity` | analytics | identity | Identity hydration from aether.hydrateIdentity() |
| `consent` | `consent` | — | governance | Consent state change — always allowed regardless of consent state |
| `conversion` | `commerce` | marketing | behavioral | Conversion event for marketing attribution |
| `payment_initiated` | `commerce` | commerce | financial | Payment initiation observed |
| `payment_completed` | `commerce` | commerce | financial | Payment completion observed |
| `payment_failed` | `commerce` | commerce | financial | Payment failure observed |
| `approval_requested` | `commerce` | commerce | financial | Approval workflow initiated |
| `approval_resolved` | `commerce` | commerce | financial | Approval workflow resolved |
| `entitlement_granted` | `commerce` | commerce | financial | Entitlement granted to actor |
| `entitlement_revoked` | `commerce` | commerce | financial | Entitlement revoked from actor |
| `access_granted` | `commerce` | commerce | financial | Resource access granted |
| `access_denied` | `commerce` | commerce | financial | Resource access denied |
| `wallet` | `wallet` | web3 | financial | Wallet connect/disconnect observation |
| `transaction` | `wallet` | web3 | financial | On-chain transaction observation |
| `contract_action` | `wallet` | web3 | financial | Smart contract action observation |
| `agent_task` *(deprecated)* | `agent` | agent | behavioral | [Legacy] Agent task — prefer agent_task_created/started/completed |
| `agent_decision` *(deprecated)* | `agent` | agent | behavioral | [Legacy] Agent decision — prefer agent_policy_evaluated |
| `a2h_interaction` *(deprecated)* | `agent` | agent | behavioral | [Legacy] Agent-to-human interaction — prefer agent_escalated_to_human |
| `agent_registered` | `agent` | agent | behavioral | Agent registered in the system |
| `agent_updated` | `agent` | agent | behavioral | Agent configuration updated |
| `agent_authorized` | `agent` | agent | behavioral | Agent authorization granted |
| `agent_deauthorized` | `agent` | agent | behavioral | Agent authorization revoked |
| `agent_capability_granted` | `agent` | agent | behavioral | Agent capability grant |
| `agent_capability_revoked` | `agent` | agent | behavioral | Agent capability revocation |
| `agent_task_created` | `agent` | agent | behavioral | Agent task created |
| `agent_task_decomposed` | `agent` | agent | behavioral | Agent task decomposed into subtasks |
| `agent_task_started` | `agent` | agent | behavioral | Agent task execution started |
| `agent_task_completed` | `agent` | agent | behavioral | Agent task completed successfully |
| `agent_task_failed` | `agent` | agent | behavioral | Agent task failed |
| `agent_tool_called` | `agent` | agent | behavioral | Agent called an external tool |
| `agent_resource_requested` | `agent` | agent | behavioral | Agent requested a resource |
| `agent_delegated_task` | `agent` | agent | behavioral | Agent delegated task to another agent |
| `agent_subagent_spawned` | `agent` | agent | behavioral | Agent spawned a subagent |
| `agent_policy_evaluated` | `agent` | agent | behavioral | Policy evaluated for agent action |
| `agent_handoff` | `agent` | agent | behavioral | Agent handed off to another system |
| `agent_escalated_to_human` | `agent` | agent | behavioral | Agent escalated task to human |
| `agent_outcome_recorded` | `agent` | agent | behavioral | Agent outcome recorded |
| `reward_action_queued` | `reward` | commerce | financial | Reward eligibility action queued — emitted by Aether, not the tenant |
| `reward_proof_generated` | `reward` | commerce | financial | Reward cryptographic proof generated |
| `reward_delivered` | `reward` | commerce | financial | Reward delivered to recipient |
| `reward_claim_submitted` | `reward` | commerce | financial | Reward claim submitted by recipient |
| `x402_payment` *(deprecated)* | `x402` | commerce | financial | [Legacy] x402 payment — prefer x402_payment_submitted/settled |
| `x402_resource_requested` | `x402` | commerce | financial | x402 resource access requested |
| `x402_payment_required` | `x402` | commerce | financial | x402 402 response received |
| `x402_quote_received` | `x402` | commerce | financial | x402 payment quote received |
| `x402_authorization_requested` | `x402` | commerce | financial | x402 authorization requested |
| `x402_authorization_resolved` | `x402` | commerce | financial | x402 authorization resolved |
| `x402_payment_intent_created` | `x402` | commerce | financial | x402 payment intent created |
| `x402_payment_submitted` | `x402` | commerce | financial | x402 payment submitted on-chain |
| `x402_payment_settled` | `x402` | commerce | financial | x402 payment confirmed settled |
| `x402_payment_failed` | `x402` | commerce | financial | x402 payment failed |
| `x402_payment_timeout` | `x402` | commerce | financial | x402 payment timed out |
| `x402_receipt_verified` | `x402` | commerce | financial | x402 receipt verified |
| `x402_access_granted` | `x402` | commerce | financial | x402 resource access granted |
| `x402_access_denied` | `x402` | commerce | financial | x402 resource access denied |
| `x402_refund_or_reversal` | `x402` | commerce | financial | x402 refund or reversal observed |
| `agentic_account_observed` | `agent` | agent | behavioral | Agentic account state observed |
| `agentic_account_connected_observed` | `agent` | agent | behavioral | Agentic account connected |
| `agentic_account_disconnected_observed` | `agent` | agent | behavioral | Agentic account disconnected |
| `agent_budget_observed` | `agent` | agent | behavioral | Agent budget state observed |
| `agent_budget_changed_observed` | `agent` | agent | behavioral | Agent budget changed |
| `agent_permission_observed` | `agent` | agent | behavioral | Agent permission state observed |
| `agent_mcp_connection_observed` | `agent` | agent | behavioral | Agent MCP connection observed |
| `agent_tool_observed` | `agent` | agent | behavioral | Agent tool availability observed |
| `agent_tool_invocation_observed` | `agent` | agent | behavioral | Agent tool invocation observed |
| `agent_activity_observed` | `agent` | agent | behavioral | General agent activity observed |
| `agent_risk_signal_observed` | `agent` | agent | behavioral | Agent risk signal observed |
| `agent_notification_observed` | `agent` | agent | behavioral | Agent notification observed |
| `agent_strategy_observed` | `agent` | agent | behavioral | Agent strategy state observed |
| `agent_trade_intent_observed` | `agent` | agent | behavioral | Agent trade intent observed |
| `agent_trade_order_observed` | `agent` | agent | behavioral | Agent trade order observed |
| `agent_trade_fill_observed` | `agent` | agent | behavioral | Agent trade fill observed |
| `agent_trade_rejection_observed` | `agent` | agent | behavioral | Agent trade rejection observed |
| `agent_position_observed` | `agent` | agent | behavioral | Agent position snapshot observed |
| `agent_portfolio_snapshot_observed` | `agent` | agent | behavioral | Agent portfolio snapshot observed |
| `agent_performance_snapshot_observed` | `agent` | agent | behavioral | Agent performance snapshot observed |
| `agent_disconnect_observed` | `agent` | agent | behavioral | Agent disconnected |
| `agent_inbox_observed` | `agent` | agent | behavioral | Agent inbox state observed |
| `agent_email_address_observed` | `agent` | agent | behavioral | Agent email address observed |
| `agent_thread_observed` | `agent` | agent | behavioral | Agent message thread observed |
| `agent_message_received_observed` | `agent` | agent | behavioral | Agent received a message |
| `agent_message_sent_observed` | `agent` | agent | behavioral | Agent sent a message |
| `agent_reply_observed` | `agent` | agent | behavioral | Agent reply observed |
| `agent_attachment_observed` | `agent` | agent | behavioral | Agent attachment observed |
| `agent_attachment_parsed_observed` | `agent` | agent | behavioral | Agent attachment parsed |
| `agent_otp_detected_observed` | `agent` | agent | sensitive | Agent OTP detected (structural metadata only, not the OTP value) |
| `agent_invoice_detected_observed` | `agent` | agent | financial | Agent invoice detected (structural metadata only) |
| `agent_receipt_detected_observed` | `agent` | agent | financial | Agent receipt detected (structural metadata only) |
| `agent_calendar_intent_observed` | `agent` | agent | behavioral | Agent calendar intent observed |
| `agent_support_route_observed` | `agent` | agent | behavioral | Agent support routing observed |
| `agent_semantic_search_observed` | `agent` | agent | behavioral | Agent semantic search observed |
| `agent_data_extraction_observed` | `agent` | agent | behavioral | Agent data extraction observed |
| `x402_resource_request_observed` | `x402` | commerce | financial | x402 resource request observed from external perspective |
| `x402_challenge_observed` | `x402` | commerce | financial | x402 challenge observed |
| `x402_payment_requirement_observed` | `x402` | commerce | financial | x402 payment requirement observed |
| `x402_signature_observed` | `x402` | commerce | financial | x402 signature observed |
| `x402_verification_observed` | `x402` | commerce | financial | x402 verification result observed |
| `x402_settlement_observed` | `x402` | commerce | financial | x402 settlement observed |
| `x402_resource_access_observed` | `x402` | commerce | financial | x402 resource access observed |
| `x402_resource_access_denied_observed` | `x402` | commerce | financial | x402 resource access denied observed |
| `x402_failure_observed` | `x402` | commerce | financial | x402 protocol failure observed |
| `x402_replay_risk_observed` | `x402` | commerce | financial | x402 replay risk signal observed |
| `x402_provider_observed` | `x402` | commerce | financial | x402 provider state observed |
| `content_impression` | `exposure` | analytics, personalization | behavioral | Content item was displayed to the user |
| `recommendation_exposed` | `exposure` | analytics, personalization | behavioral | Recommendation was displayed to the user |
| `offer_exposed` | `exposure` | analytics, personalization | behavioral | Offer was presented to the user |
| `feature_exposed` | `exposure` | analytics | behavioral | Product feature was exposed to the user |
| `search_result_exposed` | `exposure` | analytics | behavioral | Search result was shown to the user |
| `ad_exposed` | `exposure` | marketing | behavioral | Advertisement was displayed to the user |
| `notification_presented` | `exposure` | analytics | behavioral | In-app notification was presented |
| `decision_observed` | `exposure` | analytics | behavioral | System decision presented to or observed by user |
| `outcome_observed` | `outcome` | analytics | behavioral | Business outcome observed |
| `goal_achieved` | `outcome` | analytics | behavioral | User or agent achieved a defined goal |
| `goal_failed` | `outcome` | analytics | behavioral | User or agent failed to achieve a goal |
| `recommendation_accepted` | `outcome` | analytics, personalization | behavioral | User accepted a recommendation |
| `recommendation_rejected` | `outcome` | analytics, personalization | behavioral | User rejected a recommendation |
| `feedback_submitted` | `outcome` | analytics | behavioral | User submitted feedback |
| `retention_observed` | `outcome` | analytics | behavioral | User retention signal observed |
| `churn_observed` | `outcome` | analytics | behavioral | User churn signal observed |
| `human_override_observed` | `outcome` | analytics | behavioral | Human overrode an agent or system recommendation |
| `organization_observed` | `b2b` | analytics | behavioral | Organization state observed |
| `workspace_created` | `b2b` | analytics | behavioral | Workspace created |
| `workspace_updated` | `b2b` | analytics | behavioral | Workspace updated |
| `member_invited` | `b2b` | analytics | behavioral | Member invited to organization or workspace |
| `member_joined` | `b2b` | analytics | behavioral | Member joined organization or workspace |
| `member_removed` | `b2b` | analytics | behavioral | Member removed from organization or workspace |
| `role_changed` | `b2b` | analytics | behavioral | Member role changed |
| `seat_assigned` | `b2b` | analytics, commerce | behavioral | Seat assigned to a member |
| `seat_released` | `b2b` | analytics, commerce | behavioral | Seat released |
| `integration_connected` | `b2b` | analytics | behavioral | Third-party integration connected |
| `integration_disconnected` | `b2b` | analytics | behavioral | Third-party integration disconnected |
| `service_account_created` | `b2b` | analytics | behavioral | Service account created (reference only, not credentials) |
| `service_account_revoked` | `b2b` | analytics | behavioral | Service account revoked |
| `api_key_created` | `b2b` | analytics | behavioral | API key created (key ID reference only) |
| `api_key_revoked` | `b2b` | analytics | behavioral | API key revoked |
| `project_created` | `b2b` | analytics | behavioral | Project created |
| `project_archived` | `b2b` | analytics | behavioral | Project archived |
| `workflow_started` | `b2b` | analytics | behavioral | Workflow started |
| `workflow_completed` | `b2b` | analytics | behavioral | Workflow completed |
| `workflow_failed` | `b2b` | analytics | behavioral | Workflow failed |
| `product_viewed` | `ecommerce` | commerce | behavioral | Product detail viewed |
| `cart_item_added` | `ecommerce` | commerce | behavioral | Item added to cart |
| `cart_item_removed` | `ecommerce` | commerce | behavioral | Item removed from cart |
| `cart_updated` | `ecommerce` | commerce | behavioral | Cart contents updated |
| `coupon_applied` | `ecommerce` | commerce | behavioral | Coupon or discount code applied |
| `checkout_started` | `ecommerce` | commerce | behavioral | Checkout flow started |
| `checkout_step_completed` | `ecommerce` | commerce | behavioral | Individual checkout step completed |
| `order_completed` | `ecommerce` | commerce | financial | Order completed and confirmed |
| `order_cancelled` | `ecommerce` | commerce | financial | Order cancelled |
| `order_refunded` | `ecommerce` | commerce | financial | Order refunded |
| `chargeback_observed` | `ecommerce` | commerce | financial | Chargeback observed (host-reported) |
| `subscription_started` | `ecommerce` | commerce | financial | Subscription started |
| `trial_started` | `ecommerce` | commerce | financial | Trial subscription started |
| `trial_converted` | `ecommerce` | commerce | financial | Trial converted to paid subscription |
| `subscription_renewed` | `ecommerce` | commerce | financial | Subscription renewed |
| `subscription_upgrade_observed` | `ecommerce` | commerce | financial | Subscription plan upgraded |
| `subscription_downgrade_observed` | `ecommerce` | commerce | financial | Subscription plan downgraded |
| `subscription_cancelled` | `ecommerce` | commerce | financial | Subscription cancelled |
| `invoice_issued` | `ecommerce` | commerce | financial | Invoice issued |
| `invoice_paid` | `ecommerce` | commerce | financial | Invoice paid |
| `invoice_failed` | `ecommerce` | commerce | financial | Invoice payment failed |
| `dunning_started` | `ecommerce` | commerce | financial | Dunning process started for failed payment |
| `dunning_resolved` | `ecommerce` | commerce | financial | Dunning process resolved |
| `dead_click_observed` | `friction` | analytics | behavioral | Dead click observed (DOM-level, web only auto-capture) |
| `rage_click_observed` | `friction` | analytics | behavioral | Rage click observed (multiple rapid clicks, web only auto-capture) |
| `scroll_depth_observed` | `friction` | analytics | behavioral | Scroll depth milestone reached |
| `form_started` | `friction` | analytics | behavioral | Form interaction started (structural metadata only — no values) |
| `form_field_interaction` | `friction` | analytics | behavioral | Form field interaction (field type and metadata only — no entered values) |
| `form_validation_failed` | `friction` | analytics | behavioral | Form validation failed (category and count, not values) |
| `form_submitted` | `friction` | analytics | behavioral | Form submitted |
| `form_abandoned` | `friction` | analytics | behavioral | Form abandoned without submission |
| `search_reformulated` | `friction` | analytics | behavioral | Search query reformulated (hash/category, not raw query) |
| `retry_observed` | `friction` | analytics | behavioral | User or system retry observed |
| `journey_stalled` | `friction` | analytics | behavioral | Journey stalled at a step |
| `backtrack_observed` | `friction` | analytics | behavioral | User backtracked to a previous step |
| `api_request_observed` | `server` | analytics | behavioral | API request observed from server-side (no request/response body) |
| `webhook_delivery_observed` | `server` | analytics | behavioral | Webhook delivery attempt observed |
| `connector_sync_started` | `server` | analytics | behavioral | Connector sync started |
| `connector_sync_completed` | `server` | analytics | behavioral | Connector sync completed |
| `connector_sync_failed` | `server` | analytics | behavioral | Connector sync failed |
| `job_started` | `server` | analytics | behavioral | Background job started |
| `job_completed` | `server` | analytics | behavioral | Background job completed |
| `job_failed` | `server` | analytics | behavioral | Background job failed |
| `rate_limit_observed` | `server` | analytics | behavioral | Rate limit encountered |
| `dependency_failure_observed` | `server` | analytics | behavioral | External dependency failure observed |
| `export_completed` | `server` | analytics | behavioral | Data export completed |
| `signup_started` | `identity_lc` | analytics | identity | Signup flow started |
| `signup_completed` | `identity_lc` | analytics | identity | Signup completed |
| `login_succeeded` | `identity_lc` | analytics | identity | Login succeeded |
| `login_failed` | `identity_lc` | analytics | identity | Login failed |
| `logout_observed` | `identity_lc` | analytics | identity | Logout observed |
| `sso_observed` | `identity_lc` | analytics | identity | SSO authentication observed |
| `mfa_challenge_observed` | `identity_lc` | analytics | identity | MFA challenge observed (method metadata only) |
| `identity_verified` | `identity_lc` | analytics | identity | Identity verification completed |
| `alias_link_requested` | `identity_lc` | analytics | identity | Identity alias link requested |
| `alias_link_confirmed` | `identity_lc` | analytics | identity | Identity alias link confirmed |
| `alias_revoked` | `identity_lc` | analytics | identity | Identity alias revoked |
| `account_recovery_started` | `identity_lc` | analytics | identity | Account recovery flow started |
| `account_recovery_completed` | `identity_lc` | analytics | identity | Account recovery completed |
| `device_registered` | `identity_lc` | analytics | identity | Device registered for authentication |
| `device_revoked` | `identity_lc` | analytics | identity | Device revoked |
| `agent_evaluation_observed` | `agent` | agent | behavioral | Agent evaluation result observed |
| `agent_cost_observed` | `agent` | agent | behavioral | Agent inference or tool cost observed |
| `agent_grounding_observed` | `agent` | agent | behavioral | Agent grounding evidence observed |
| `agent_guardrail_observed` | `agent` | agent | behavioral | Agent guardrail evaluation observed |
| `agent_human_override_observed` | `agent` | agent | behavioral | Human override of agent action observed |
| `transaction_pending_observed` | `web3_lc` | web3 | financial | Transaction in pending/mempool state observed |
| `transaction_confirmed_observed` | `web3_lc` | web3 | financial | Transaction confirmed on-chain observed |
| `transaction_reverted_observed` | `web3_lc` | web3 | financial | Transaction reverted observed |
| `transaction_reorged_observed` | `web3_lc` | web3 | financial | Transaction affected by chain reorg observed |
| `token_approval_observed` | `web3_lc` | web3 | financial | Token approval transaction observed |
| `allowance_changed_observed` | `web3_lc` | web3 | financial | Token allowance changed observed |
| `bridge_transfer_observed` | `web3_lc` | web3 | financial | Cross-chain bridge transfer observed |
| `settlement_finality_observed` | `web3_lc` | web3 | financial | Settlement finality confirmed |
| `notification_delivered` | `comms` | analytics | behavioral | Notification delivered to device |
| `notification_opened` | `comms` | analytics | behavioral | Notification opened by user |
| `notification_clicked` | `comms` | analytics | behavioral | Notification clicked |
| `email_delivered` | `comms` | marketing | behavioral | Email delivered |
| `email_opened` | `comms` | marketing | behavioral | Email opened |
| `email_clicked` | `comms` | marketing | behavioral | Email link clicked |
| `email_bounced` | `comms` | marketing | behavioral | Email bounced |
| `message_received_observed` | `comms` | analytics | behavioral | Message received (structural metadata only — no content) |
| `message_sent_observed` | `comms` | analytics | behavioral | Message sent (structural metadata only — no content) |
| `message_replied_observed` | `comms` | analytics | behavioral | Message replied to |
| `unsubscribe_observed` | `comms` | marketing | behavioral | User unsubscribed from a channel |
| `support_case_created` | `comms` | analytics | behavioral | Support case created |
| `support_case_resolved` | `comms` | analytics | behavioral | Support case resolved |
| `support_case_escalated` | `comms` | analytics | behavioral | Support case escalated |
| `support_sla_breached` | `comms` | analytics | behavioral | Support SLA breached |
| `credit_signal_observed` | `credit` | credit | sensitive_financial | Credit signal observed — requires explicit credit opt-in |
| `credit_account_observed` | `credit` | credit | sensitive_financial | Credit account state observed — requires explicit credit opt-in |
| `credit_decision_observed` | `credit` | credit | sensitive_financial | Credit decision observed — requires explicit credit opt-in. Host-observed only; Aether does not make credit decisions. |
| `location_observed` | `location` | location | sensitive_location | Location observation — requires explicit location opt-in |
| `geofence_transition_observed` | `location` | location | sensitive_location | Geofence entry/exit — requires explicit location opt-in |
