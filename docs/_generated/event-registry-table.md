<!-- DO NOT EDIT — generated from packages/shared/contracts/event-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Event Registry (398 types, contract v8.12.0)

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
| `navigation_intent` | `journey` | analytics | behavioral | Permitted click expected to navigate; carries navigation ID and sanitized destination for intent/arrival correlation |
| `navigation_arrival` | `journey` | analytics | behavioral | Page or SPA route arrival correlated to a prior navigation_intent by navigation ID |
| `deep_link_opened` | `journey` | analytics | behavioral | Native deep link opened; carries canonical acquisition evidence (destination domain, aether_ref, UTM, click IDs) |
| `app_install_attributed` | `journey` | analytics | behavioral | First app launch attributed via platform install evidence (Play Install Referrer or verified handoff) |
| `deferred_attribution_resolved` | `journey` | analytics | behavioral | Pending pre-install source handoff deterministically reconciled after first launch |
| `qr_code_scanned` | `journey` | analytics | behavioral | Host app decoded a QR code; the decoded URL is parsed through the canonical acquisition-evidence parser (entry method qr_code) |
| `nfc_tag_read` | `journey` | analytics | behavioral | Host app read an NFC tag URI; the URI is parsed through the canonical acquisition-evidence parser (entry method nfc) |
| `app_clip_invoked` | `journey` | analytics | behavioral | iOS App Clip invocation URL observed and parsed through the canonical acquisition-evidence parser; first-touch persisted for full-app handoff |
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
| `agent_trade_order_observed` | `agent` | financial_activity | behavioral | Agent trade order observed |
| `agent_trade_fill_observed` | `agent` | financial_activity | behavioral | Agent trade fill observed |
| `agent_trade_rejection_observed` | `agent` | agent | behavioral | Agent trade rejection observed |
| `agent_position_observed` | `agent` | financial_activity | behavioral | Agent position snapshot observed |
| `agent_portfolio_snapshot_observed` | `agent` | financial_activity | behavioral | Agent portfolio snapshot observed |
| `agent_performance_snapshot_observed` | `agent` | financial_activity | behavioral | Agent performance snapshot observed |
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
| `surface_entered` | `interaction` | analytics | behavioral | Actor entered a surface (route, screen, view, modal, API surface) |
| `surface_exited` | `interaction` | analytics | behavioral | Actor exited a surface; closes the surface interval |
| `interaction_observed` | `interaction` | analytics | behavioral | Canonical interaction on a control (typed via the interaction vocabulary) |
| `ui_interaction_observed` | `interaction` | analytics | behavioral | Native UI control interaction observed by the SDK (metadata-only: stable control id, type, action, screen; no control text unless explicitly enabled) |
| `feature_started` | `interaction` | analytics | behavioral | Feature usage began (distinct from exposure) |
| `feature_completed` | `interaction` | analytics | behavioral | Feature usage reached its defined completion |
| `feature_abandoned` | `interaction` | analytics | behavioral | Feature usage abandoned before completion |
| `action_attempted` | `interaction` | analytics | behavioral | Domain action attempted (interaction truth, not outcome truth) |
| `action_succeeded` | `interaction` | analytics | behavioral | Domain action reported success by its owning system |
| `action_failed` | `interaction` | analytics | behavioral | Domain action reported failure by its owning system |
| `action_cancelled` | `interaction` | analytics | behavioral | Domain action cancelled before completion |
| `active_interval_observed` | `interaction` | analytics | behavioral | Bounded active/visible/idle interval evidence for a surface |
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
| `ai_invocation_observed` | `agent` | agent | behavioral | AI model invocation observed — identity, usage, cost, latency, quality, and outcome correlation; no raw prompt or completion content |
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
| `email_queued` | `comms` | marketing | behavioral | Email accepted by provider queue (lifecycle state) |
| `email_processed` | `comms` | marketing | behavioral | Email processed by provider (lifecycle state) |
| `email_sent` | `comms` | marketing | behavioral | Email handed to recipient MTA by provider |
| `email_deferred` | `comms` | marketing | behavioral | Email delivery deferred by recipient MTA |
| `email_dropped` | `comms` | marketing | behavioral | Email dropped by provider before send |
| `email_replied` | `comms` | marketing | behavioral | Inbound human reply to a sent email |
| `email_spam_complaint` | `comms` | marketing | behavioral | Recipient marked email as spam |
| `email_suppressed` | `comms` | marketing | behavioral | Send suppressed by provider suppression list |
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
| `trading_account_connected` | `derivatives` | financial_activity | sensitive_financial | Trading account connected to Aether observation — requires financial_activity opt-in |
| `trading_account_disconnected` | `derivatives` | financial_activity | sensitive_financial | Trading account disconnected from Aether observation — requires financial_activity opt-in |
| `trading_account_authorized` | `derivatives` | financial_activity | sensitive_financial | Trading account explicitly authorized for read-only observation — requires financial_activity opt-in |
| `trading_account_deauthorized` | `derivatives` | financial_activity | sensitive_financial | Trading account deauthorized; observation ceases — requires financial_activity opt-in |
| `trading_agent_enabled` | `derivatives` | financial_activity, agent | sensitive_financial | Agent enabled for a trading account — requires financial_activity and agent opt-in |
| `trading_agent_disabled` | `derivatives` | financial_activity, agent | sensitive_financial | Agent disabled on a trading account — requires financial_activity and agent opt-in |
| `trade_intent_created` | `derivatives` | financial_activity | sensitive_financial | Trade intent created by agent or human — observation only; execution_by_aether is always false |
| `trade_approval_requested` | `derivatives` | financial_activity | sensitive_financial | Human approval requested before trade execution — observation only |
| `trade_approval_resolved` | `derivatives` | financial_activity | sensitive_financial | Human trade approval approved or rejected — observation only |
| `risk_policy_updated` | `derivatives` | financial_activity | governance | Risk policy updated for a trading account — requires financial_activity opt-in |
| `human_trade_override_recorded` | `derivatives` | financial_activity | sensitive_financial | Human manually overrode an agent trade decision — observation only; execution_by_aether is always false |
| `stablecoin_transfer_observed` | `stablecoin` | economic_observability | financial | Stablecoin transfer observed on-chain or via provider evidence |
| `stablecoin_payment_observed` | `stablecoin` | economic_observability | financial | Stablecoin payment observed (transfer classified as payment) |
| `stablecoin_mint_observed` | `stablecoin` | economic_observability | financial | Stablecoin mint observed |
| `stablecoin_burn_observed` | `stablecoin` | economic_observability | financial | Stablecoin burn observed |
| `stablecoin_bridge_outbound_observed` | `stablecoin` | economic_observability | financial | Stablecoin bridge departure leg observed |
| `stablecoin_bridge_inbound_observed` | `stablecoin` | economic_observability | financial | Stablecoin bridge arrival leg observed |
| `stablecoin_swap_observed` | `stablecoin` | economic_observability | financial | Stablecoin swap observed |
| `stablecoin_x402_settlement_observed` | `stablecoin` | economic_observability | financial | x402 settlement observed in stablecoin |
| `stablecoin_treasury_movement_observed` | `stablecoin` | economic_observability | financial | Treasury stablecoin movement observed |
| `stablecoin_payout_observed` | `stablecoin` | economic_observability | financial | Stablecoin payout observed |
| `stablecoin_venue_deposit_observed` | `stablecoin` | economic_observability | financial | Stablecoin deposit to a venue observed |
| `stablecoin_venue_withdrawal_observed` | `stablecoin` | economic_observability | financial | Stablecoin withdrawal from a venue observed |
| `stablecoin_balance_snapshot_observed` | `stablecoin` | economic_observability | financial | Wallet or account stablecoin balance snapshot observed |
| `stablecoin_supply_snapshot_observed` | `stablecoin` | economic_observability | governance | Deployment supply snapshot observed |
| `stablecoin_holder_concentration_observed` | `stablecoin` | economic_observability | governance | Holder concentration metric observed for a deployment |
| `stablecoin_valuation_observed` | `stablecoin` | economic_observability | governance | Stablecoin USD valuation and peg deviation observed |
| `stablecoin_depeg_detected` | `stablecoin` | economic_observability | governance | Peg deviation beyond threshold detected |
| `stablecoin_depeg_resolved` | `stablecoin` | economic_observability | governance | Previously detected peg deviation resolved |
| `stablecoin_finality_confirmed` | `stablecoin` | economic_observability | financial | Observation crossed the chain confirmation horizon |
| `stablecoin_reorg_detected` | `stablecoin` | economic_observability | financial | Chain reorganization invalidated provisional observations |
| `stablecoin_observation_corrected` | `stablecoin` | economic_observability | financial | Correction row appended for a prior observation |
| `stablecoin_reconciliation_run_completed` | `stablecoin` | economic_observability | governance | Stablecoin reconciliation run completed |
| `stablecoin_reconciliation_variance_detected` | `stablecoin` | economic_observability | financial | Reconciliation variance detected between sources |
| `stablecoin_reconciliation_variance_resolved` | `stablecoin` | economic_observability | financial | Reconciliation variance resolved |
| `stablecoin_asset_registered` | `stablecoin` | economic_observability | governance | Canonical stablecoin asset registered |
| `stablecoin_deployment_registered` | `stablecoin` | economic_observability | governance | Stablecoin deployment registered for a chain |
| `stablecoin_support_asserted` | `stablecoin` | economic_observability | governance | Entity support capability asserted for a deployment |
| `stablecoin_support_revoked` | `stablecoin` | economic_observability | governance | Entity support capability revoked or degraded |
| `stablecoin_flow_aggregate_materialized` | `stablecoin` | economic_observability | governance | Windowed stablecoin flow aggregate materialized |
| `stablecoin_checkpoint_advanced` | `stablecoin` | economic_observability | governance | Stablecoin finality checkpoint advanced |
| `derivatives_venue_registered` | `derivatives` | financial_activity | governance | Trading venue registered in the canonical registry |
| `derivatives_venue_deployment_registered` | `derivatives` | financial_activity | governance | Venue deployment registered |
| `derivatives_instrument_registered` | `derivatives` | financial_activity | governance | Canonical derivative instrument registered |
| `derivatives_market_registered` | `derivatives` | financial_activity | governance | Venue market registered and resolved to an instrument |
| `derivatives_strategy_registered` | `derivatives` | financial_activity | financial | Trading strategy registered |
| `derivatives_strategy_version_registered` | `derivatives` | financial_activity | financial | Trading strategy version registered (versions never overwrite) |
| `derivatives_risk_policy_registered` | `derivatives` | financial_activity | governance | Risk policy registered or revised |
| `derivatives_account_linked` | `derivatives` | financial_activity | financial | Read-only trading account link observed |
| `derivatives_account_link_revoked` | `derivatives` | financial_activity | financial | Trading account link revoked |
| `derivatives_balance_snapshot_observed` | `derivatives` | financial_activity | financial | Account balance snapshot observed |
| `derivatives_collateral_change_observed` | `derivatives` | financial_activity | financial | Collateral change observed |
| `derivatives_margin_snapshot_observed` | `derivatives` | financial_activity | financial | Margin state snapshot observed |
| `derivatives_order_observed` | `derivatives` | financial_activity | financial | Order observed from venue or tenant evidence |
| `derivatives_order_updated_observed` | `derivatives` | financial_activity | financial | Order state update observed |
| `derivatives_order_cancelled_observed` | `derivatives` | financial_activity | financial | Order cancellation observed |
| `derivatives_order_rejected_observed` | `derivatives` | financial_activity | financial | Order rejection observed |
| `derivatives_order_expired_observed` | `derivatives` | financial_activity | financial | Order expiry observed |
| `derivatives_fill_observed` | `derivatives` | financial_activity | financial | Trade fill observed |
| `derivatives_fill_corrected` | `derivatives` | financial_activity | financial | Correction row appended for a prior fill |
| `derivatives_position_opened_observed` | `derivatives` | financial_activity | sensitive_financial | Position opening observed |
| `derivatives_position_increased_observed` | `derivatives` | financial_activity | sensitive_financial | Position increase observed |
| `derivatives_position_reduced_observed` | `derivatives` | financial_activity | sensitive_financial | Position reduction observed |
| `derivatives_position_closed_observed` | `derivatives` | financial_activity | sensitive_financial | Position close observed |
| `derivatives_position_liquidated_observed` | `derivatives` | financial_activity | sensitive_financial | Position liquidation observed |
| `derivatives_position_adl_observed` | `derivatives` | financial_activity | sensitive_financial | Auto-deleveraging event observed |
| `derivatives_position_settled_observed` | `derivatives` | financial_activity | sensitive_financial | Position settlement observed |
| `derivatives_position_corrected` | `derivatives` | financial_activity | sensitive_financial | Correction row appended for a prior position fact |
| `derivatives_funding_payment_observed` | `derivatives` | financial_activity | financial | Funding payment observed |
| `derivatives_fee_observed` | `derivatives` | financial_activity | financial | Trading fee observed |
| `derivatives_pnl_snapshot_materialized` | `derivatives` | financial_activity | sensitive_financial | Realized/unrealized P&L snapshot materialized |
| `derivatives_exposure_snapshot_materialized` | `derivatives` | financial_activity | sensitive_financial | Cross-venue exposure snapshot materialized |
| `derivatives_price_observation_recorded` | `derivatives` | financial_activity | governance | Mark/index/oracle price observation recorded |
| `derivatives_market_status_changed` | `derivatives` | financial_activity | governance | Market status change observed |
| `derivatives_stream_gap_detected` | `derivatives` | financial_activity | governance | Market stream sequence gap detected |
| `derivatives_stream_gap_recovered` | `derivatives` | financial_activity | governance | Market stream sequence gap recovered |
| `derivatives_stream_checkpoint_advanced` | `derivatives` | financial_activity | governance | Stream/connector checkpoint advanced |
| `derivatives_adapter_conformance_run` | `derivatives` | financial_activity | governance | Adapter conformance suite executed |
| `derivatives_reconciliation_run_completed` | `derivatives` | financial_activity | governance | Derivatives reconciliation run completed |
| `derivatives_reconciliation_variance_detected` | `derivatives` | financial_activity | financial | Reconciliation variance detected |
| `derivatives_reconciliation_variance_resolved` | `derivatives` | financial_activity | financial | Reconciliation variance resolved |
| `derivatives_risk_threshold_breached` | `derivatives` | financial_activity | sensitive_financial | Configured risk threshold breached (observation only) |
| `interop_provider_registered` | `interop` | cross_chain_observability | governance | Interoperability provider registered |
| `interop_gateway_registered` | `interop` | cross_chain_observability | governance | Provider gateway registered on a network |
| `interop_path_registered` | `interop` | cross_chain_observability | governance | Cross-network path registered |
| `interop_application_registered` | `interop` | cross_chain_observability | governance | Cross-network application registered |
| `interop_verification_actor_registered` | `interop` | cross_chain_observability | governance | Verification actor registered |
| `interop_message_discovered` | `interop` | cross_chain_observability | financial | Cross-network message discovered |
| `interop_message_sent_observed` | `interop` | cross_chain_observability | financial | Message dispatch observed on source network |
| `interop_message_source_confirmed` | `interop` | cross_chain_observability | financial | Source transaction crossed the confirmation horizon |
| `interop_message_verification_observed` | `interop` | cross_chain_observability | financial | Verification observation recorded |
| `interop_message_verified` | `interop` | cross_chain_observability | financial | Message verification completed |
| `interop_message_delivery_attempt_observed` | `interop` | cross_chain_observability | financial | Delivery attempt observed |
| `interop_message_delivered` | `interop` | cross_chain_observability | financial | Message delivery observed on destination network |
| `interop_message_executed_observed` | `interop` | cross_chain_observability | financial | Destination application execution observed |
| `interop_message_settled` | `interop` | cross_chain_observability | financial | Message reached settled terminal state |
| `interop_message_failed` | `interop` | cross_chain_observability | financial | Message failed |
| `interop_message_timeout` | `interop` | cross_chain_observability | financial | Message timed out |
| `interop_message_expired` | `interop` | cross_chain_observability | financial | Message expired |
| `interop_message_cancelled` | `interop` | cross_chain_observability | financial | Message cancelled |
| `interop_message_refunded_observed` | `interop` | cross_chain_observability | financial | Refund observed for a failed or expired message |
| `interop_message_recovered` | `interop` | cross_chain_observability | financial | Previously failed message recovered |
| `interop_message_reorged` | `interop` | cross_chain_observability | financial | Chain reorganization invalidated message evidence |
| `interop_message_corrected` | `interop` | cross_chain_observability | financial | Correction row appended for a prior message fact |
| `interop_message_correlated` | `interop` | cross_chain_observability | governance | Source and destination legs correlated by canonical reference |
| `interop_intent_observed` | `interop` | cross_chain_observability | financial | Cross-network intent observed |
| `interop_intent_fulfilled_observed` | `interop` | cross_chain_observability | financial | Intent fulfillment observed |
| `interop_asset_leg_locked_observed` | `interop` | cross_chain_observability | financial | Asset lock leg observed |
| `interop_asset_leg_burned_observed` | `interop` | cross_chain_observability | financial | Asset burn leg observed |
| `interop_asset_leg_minted_observed` | `interop` | cross_chain_observability | financial | Asset mint leg observed |
| `interop_asset_leg_released_observed` | `interop` | cross_chain_observability | financial | Asset release leg observed |
| `interop_fee_observed` | `interop` | cross_chain_observability | financial | Cross-network fee observed |
| `interop_security_policy_snapshot_recorded` | `interop` | cross_chain_observability | governance | Security policy snapshot captured for a path |
| `interop_security_policy_changed` | `interop` | cross_chain_observability | governance | Security policy drift detected between snapshots |
| `interop_verification_quorum_observed` | `interop` | cross_chain_observability | governance | Verification quorum composition observed |
| `interop_provider_checkpoint_advanced` | `interop` | cross_chain_observability | governance | Provider scan checkpoint advanced |
| `interop_stream_gap_detected` | `interop` | cross_chain_observability | governance | Provider observation gap detected |
| `interop_stream_gap_recovered` | `interop` | cross_chain_observability | governance | Provider observation gap recovered |
| `interop_reconciliation_run_completed` | `interop` | cross_chain_observability | governance | Interop reconciliation run completed |
| `interop_reconciliation_variance_detected` | `interop` | cross_chain_observability | financial | Reconciliation variance detected (incl. provider disagreement) |
| `interop_reconciliation_variance_resolved` | `interop` | cross_chain_observability | financial | Reconciliation variance resolved |
