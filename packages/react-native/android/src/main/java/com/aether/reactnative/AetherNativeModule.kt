package com.aether.reactnative

import com.aether.sdk.Aether
import com.aether.sdk.AetherConfig
import com.aether.sdk.IdentityData
import com.aether.sdk.ModuleConfig
import com.aether.sdk.PrivacyConfig
import com.facebook.react.bridge.*
import com.facebook.react.modules.core.DeviceEventManagerModule

class AetherNativeModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

    override fun getName(): String = "AetherNative"

    private var resolveEndpoint: String = ""

    @ReactMethod
    fun initialize(config: ReadableMap) {
        val application = reactContext.applicationContext as? android.app.Application ?: return

        val modules = config.getMap("modules")
        val privacy = config.getMap("privacy")

        val aetherConfig = AetherConfig(
            apiKey = config.getString("apiKey") ?: "",
            environment = when (config.getString("environment")) {
                "staging" -> AetherConfig.Environment.STAGING
                "development" -> AetherConfig.Environment.DEVELOPMENT
                else -> AetherConfig.Environment.PRODUCTION
            },
            debug = if (config.hasKey("debug")) config.getBoolean("debug") else false,
            endpoint = (config.getString("endpoint") ?: "https://api.aether.network").also { resolveEndpoint = it },
            modules = ModuleConfig(
                activityTracking = modules?.getBoolean("screenTracking") ?: true,
                deepLinkAttribution = modules?.getBoolean("deepLinkAttribution") ?: true,
                pushTracking = modules?.getBoolean("pushTracking") ?: true,
                walletTracking = modules?.getBoolean("walletTracking") ?: false,
                experiments = modules?.getBoolean("experiments") ?: true
            ),
            privacy = PrivacyConfig(
                gdprMode = privacy?.getBoolean("gdprMode") ?: false,
                anonymizeIP = privacy?.getBoolean("anonymizeIP") ?: true
            )
        )

        Aether.initialize(application, aetherConfig)
    }

    @ReactMethod
    fun track(event: String, properties: ReadableMap) {
        Aether.track(event, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun screenView(screenName: String, properties: ReadableMap) {
        Aether.screenView(screenName, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun conversion(event: String, value: Double, properties: ReadableMap) {
        Aether.conversion(event, value, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun hydrateIdentity(data: ReadableMap) {
        val traits = data.getMap("traits")?.toHashMap()?.mapValues { it.value } ?: emptyMap()
        Aether.hydrateIdentity(IdentityData(
            userId = data.getString("userId"),
            walletAddress = data.getString("walletAddress"),
            walletType = data.getString("walletType"),
            chainId = if (data.hasKey("chainId")) data.getInt("chainId") else null,
            traits = traits
        ))

        // Emit identity change event
        sendEvent("AetherIdentityChanged", Arguments.createMap().apply {
            putString("anonymousId", Aether.getAnonymousId())
            putString("userId", Aether.getUserId())
        })
    }


    @ReactMethod
    fun startJourney(nameOrType: String, properties: ReadableMap) {
        Aether.startJourney(nameOrType, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun pauseJourney(reason: String, properties: ReadableMap) {
        Aether.pauseJourney(reason, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun resumeJourney(reason: String, properties: ReadableMap) {
        Aether.resumeJourney(reason, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun continueJourney(stepIdOrName: String, properties: ReadableMap) {
        Aether.continueJourney(stepIdOrName, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun completeJourney(reason: String, properties: ReadableMap) {
        Aether.completeJourney(reason, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun abandonJourney(reason: String, properties: ReadableMap) {
        Aether.abandonJourney(reason, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun checkpointJourney(stepIdOrName: String, properties: ReadableMap) {
        Aether.checkpointJourney(stepIdOrName, properties.toHashMap().mapValues { it.value })
    }

    @ReactMethod
    fun getCurrentJourney(promise: Promise) {
        val current = Aether.getCurrentJourney()
        if (current == null) promise.resolve(null) else promise.resolve(Arguments.makeNativeMap(current))
    }

    @ReactMethod
    fun getIdentity(promise: Promise) {
        val result = Arguments.createMap().apply {
            putString("anonymousId", Aether.getAnonymousId())
            putString("userId", Aether.getUserId())
            putMap("traits", Arguments.createMap())
        }
        promise.resolve(result)
    }

    @ReactMethod
    fun reset() {
        Aether.reset()
    }

    @ReactMethod
    fun flush() {
        Aether.flush()
    }

    @ReactMethod
    fun handleDeepLink(url: String) {
        Aether.handleDeepLink(url)
    }

    @ReactMethod
    fun trackPushOpened(data: ReadableMap) {
        Aether.trackPushOpened(data.toHashMap().mapValues { it.value?.toString() ?: "" })
    }

    @ReactMethod
    fun walletConnect(address: String, options: ReadableMap) {
        val walletType = options.getString("type") ?: "unknown"
        val chainId = if (options.hasKey("chainId")) options.getInt("chainId").toString() else "unknown"
        Aether.walletConnected(address, walletType, chainId)
        resolveWalletIdentity(address, walletType, chainId)
    }

    private fun resolveWalletIdentity(address: String, walletType: String, chainId: String) {
        if (resolveEndpoint.isEmpty()) return
        Thread {
            try {
                val url = java.net.URL("$resolveEndpoint/sdk/identity/resolve")
                val bodyJson = org.json.JSONObject().apply {
                    put("wallets", org.json.JSONArray().apply {
                        put(org.json.JSONObject().apply {
                            put("address", address)
                            put("type", walletType)
                            put("chainId", chainId)
                        })
                    })
                    put("anonymousId", Aether.getAnonymousId())
                    put("deviceFingerprint", Aether.getFingerprintId())
                }.toString().toByteArray(Charsets.UTF_8)

                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json")
                conn.doOutput = true
                conn.outputStream.use { it.write(bodyJson) }

                if (conn.responseCode == 200) {
                    val response = conn.inputStream.bufferedReader().readText()
                    val json = org.json.JSONObject(response)
                    if (json.optBoolean("resolved", false)) {
                        val identity = json.getJSONObject("identity")
                        val params = Arguments.createMap().apply {
                            if (identity.has("userId")) putString("userId", identity.getString("userId"))
                            if (identity.has("anonymousId")) putString("anonymousId", identity.getString("anonymousId"))
                        }
                        sendEvent("AetherJourneyResumed", params)
                    }
                }
                conn.disconnect()
            } catch (_: Exception) { }
        }.start()
    }

    @ReactMethod
    fun walletDisconnect(address: String) {
        Aether.walletDisconnected(address)
    }

    @ReactMethod
    fun walletTransaction(txHash: String, options: ReadableMap) {
        val chainId = options.getString("chainId") ?: "unknown"
        val value = options.getString("value")
        Aether.walletTransaction(txHash, chainId, value, options.toHashMap().mapValues { it.value as? Any })
    }


    @ReactMethod
    fun contractAction(contract: String, action: String, options: ReadableMap) {
        val vm = options.getString("vm") ?: "evm"
        Aether.contractAction(contract, action, vm, options.toHashMap().mapValues { it.value })
    }

    @ReactMethod fun paymentInitiated(paymentId: String, amount: Double, currency: String, properties: ReadableMap) { Aether.paymentInitiated(paymentId, amount, currency, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun paymentCompleted(paymentId: String, amount: Double, currency: String, properties: ReadableMap) { Aether.paymentCompleted(paymentId, amount, currency, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun paymentFailed(paymentId: String, reason: String, properties: ReadableMap) { Aether.paymentFailed(paymentId, reason, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun approvalRequested(approvalId: String, scope: String, properties: ReadableMap) { Aether.approvalRequested(approvalId, scope, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun approvalResolved(approvalId: String, approved: Boolean, properties: ReadableMap) { Aether.approvalResolved(approvalId, approved, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun entitlementGranted(entitlementId: String, properties: ReadableMap) { Aether.entitlementGranted(entitlementId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun entitlementRevoked(entitlementId: String, properties: ReadableMap) { Aether.entitlementRevoked(entitlementId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun accessGranted(resource: String, properties: ReadableMap) { Aether.accessGranted(resource, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun accessDenied(resource: String, reason: String, properties: ReadableMap) { Aether.accessDenied(resource, reason, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentTask(taskId: String, actorId: String, properties: ReadableMap) { Aether.agentTask(taskId, actorId, properties = properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentDecision(decisionId: String, actorId: String, properties: ReadableMap) { Aether.agentDecision(decisionId, actorId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun a2hInteraction(interactionId: String, actorId: String, properties: ReadableMap) { Aether.a2hInteraction(interactionId, actorId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402Payment(paymentId: String, amount: String, currency: String, network: String, properties: ReadableMap) { Aether.x402Payment(paymentId, amount, currency, network, properties.toHashMap().mapValues { it.value }) }

    // Granular agent lifecycle
    @ReactMethod fun agentRegistered(agentId: String, properties: ReadableMap) { Aether.agentRegistered(agentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentUpdated(agentId: String, properties: ReadableMap) { Aether.agentUpdated(agentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentAuthorized(agentId: String, delegationId: String, properties: ReadableMap) { Aether.agentAuthorized(agentId, delegationId.ifEmpty { null }, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentDeauthorized(agentId: String, properties: ReadableMap) { Aether.agentDeauthorized(agentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentCapabilityGranted(agentId: String, capability: String, properties: ReadableMap) { Aether.agentCapabilityGranted(agentId, capability, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentCapabilityRevoked(agentId: String, capability: String, properties: ReadableMap) { Aether.agentCapabilityRevoked(agentId, capability, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentTaskCreated(taskId: String, actorId: String, properties: ReadableMap) { Aether.agentTaskCreated(taskId, actorId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentTaskDecomposed(taskId: String, properties: ReadableMap) { Aether.agentTaskDecomposed(taskId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentTaskStarted(taskId: String, properties: ReadableMap) { Aether.agentTaskStarted(taskId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentTaskCompleted(taskId: String, properties: ReadableMap) { Aether.agentTaskCompleted(taskId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentTaskFailed(taskId: String, reason: String, properties: ReadableMap) { Aether.agentTaskFailed(taskId, reason.ifEmpty { null }, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentToolCalled(taskId: String, tool: String, properties: ReadableMap) { Aether.agentToolCalled(taskId, tool, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentResourceRequested(resourceId: String, properties: ReadableMap) { Aether.agentResourceRequested(resourceId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentDelegatedTask(taskId: String, toAgentId: String, properties: ReadableMap) { Aether.agentDelegatedTask(taskId, toAgentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentSubagentSpawned(parentId: String, childId: String, properties: ReadableMap) { Aether.agentSubagentSpawned(parentId, childId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentPolicyEvaluated(policyId: String, outcome: String, properties: ReadableMap) { Aether.agentPolicyEvaluated(policyId, outcome, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentHandoff(fromId: String, toId: String, properties: ReadableMap) { Aether.agentHandoff(fromId, toId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentEscalatedToHuman(taskId: String, reason: String, properties: ReadableMap) { Aether.agentEscalatedToHuman(taskId, reason.ifEmpty { null }, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun agentOutcomeRecorded(taskId: String, outcome: String, properties: ReadableMap) { Aether.agentOutcomeRecorded(taskId, outcome, properties.toHashMap().mapValues { it.value }) }

    // Granular x402 lifecycle
    @ReactMethod fun x402ResourceRequested(resourceId: String, properties: ReadableMap) { Aether.x402ResourceRequested(resourceId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402PaymentRequired(resourceId: String, amount: Double, currency: String, properties: ReadableMap) { Aether.x402PaymentRequired(resourceId, amount, currency, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402QuoteReceived(quoteId: String, properties: ReadableMap) { Aether.x402QuoteReceived(quoteId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402AuthorizationRequested(paymentId: String, properties: ReadableMap) { Aether.x402AuthorizationRequested(paymentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402AuthorizationResolved(paymentId: String, authorized: Boolean, properties: ReadableMap) { Aether.x402AuthorizationResolved(paymentId, authorized, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402PaymentIntentCreated(intentId: String, properties: ReadableMap) { Aether.x402PaymentIntentCreated(intentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402PaymentSubmitted(paymentId: String, properties: ReadableMap) { Aether.x402PaymentSubmitted(paymentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402PaymentSettled(paymentId: String, properties: ReadableMap) { Aether.x402PaymentSettled(paymentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402PaymentFailed(paymentId: String, reason: String, properties: ReadableMap) { Aether.x402PaymentFailed(paymentId, reason.ifEmpty { null }, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402PaymentTimeout(paymentId: String, properties: ReadableMap) { Aether.x402PaymentTimeout(paymentId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402ReceiptVerified(receiptId: String, properties: ReadableMap) { Aether.x402ReceiptVerified(receiptId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402AccessGranted(resourceId: String, properties: ReadableMap) { Aether.x402AccessGranted(resourceId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402AccessDenied(resourceId: String, reason: String, properties: ReadableMap) { Aether.x402AccessDenied(resourceId, reason.ifEmpty { null }, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun x402RefundOrReversal(paymentId: String, properties: ReadableMap) { Aether.x402RefundOrReversal(paymentId, properties.toHashMap().mapValues { it.value }) }

    // Rewards
    @ReactMethod fun rewardActionQueued(campaignId: String, ruleId: String, properties: ReadableMap) { Aether.rewardActionQueued(campaignId, ruleId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun rewardProofGenerated(campaignId: String, proofId: String, properties: ReadableMap) { Aether.rewardProofGenerated(campaignId, proofId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun rewardDelivered(campaignId: String, rewardId: String, properties: ReadableMap) { Aether.rewardDelivered(campaignId, rewardId, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun rewardClaimSubmitted(campaignId: String, claimId: String, properties: ReadableMap) { Aether.rewardClaimSubmitted(campaignId, claimId, properties.toHashMap().mapValues { it.value }) }

    // Ecommerce additions
    @ReactMethod fun trackRemoveFromCart(productId: String, quantity: Int, properties: ReadableMap) { Aether.trackRemoveFromCart(productId, quantity, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun trackApplyCoupon(couponCode: String, properties: ReadableMap) { Aether.trackApplyCoupon(couponCode, properties.toHashMap().mapValues { it.value }) }
    @ReactMethod fun trackBeginCheckout(cartValue: Double, currency: String, properties: ReadableMap) { Aether.trackBeginCheckout(cartValue, currency, properties.toHashMap().mapValues { it.value }) }

    @ReactMethod
    fun getFingerprint(promise: Promise) {
        promise.resolve(Aether.getFingerprintId())
    }

    @ReactMethod
    fun runExperiment(id: String, variants: ReadableArray, promise: Promise) {
        // Simple deterministic assignment based on anonymousId hash
        val hash = Aether.getAnonymousId().hashCode()
        val variantList = (0 until variants.size()).map { variants.getString(it) }
        val index = Math.abs(hash) % variantList.size
        promise.resolve(variantList[index])
    }

    @ReactMethod
    fun getExperimentAssignment(id: String, promise: Promise) {
        promise.resolve(null)
    }

    @ReactMethod
    fun getConsentState(promise: Promise) {
        val granted = Aether.getConsentState().toSet()
        val state = Arguments.createMap().apply {
            putBoolean("analytics", "analytics" in granted)
            putBoolean("marketing", "marketing" in granted)
            putBoolean("web3", "web3" in granted)
            putBoolean("agent", "agent" in granted)
            putBoolean("commerce", "commerce" in granted)
        }
        promise.resolve(state)
    }

    @ReactMethod
    fun grantConsent(purposes: ReadableArray) {
        val list = (0 until purposes.size()).map { purposes.getString(it) ?: "" }
        Aether.grantConsent(list)
        emitConsentChanged()
    }

    @ReactMethod
    fun revokeConsent(purposes: ReadableArray) {
        val list = (0 until purposes.size()).map { purposes.getString(it) ?: "" }
        Aether.revokeConsent(list)
        emitConsentChanged()
    }

    private fun emitConsentChanged() {
        val granted = Aether.getConsentState().toSet()
        sendEvent("AetherConsentChanged", Arguments.createMap().apply {
            putBoolean("analytics", "analytics" in granted)
            putBoolean("marketing", "marketing" in granted)
            putBoolean("web3", "web3" in granted)
            putBoolean("agent", "agent" in granted)
            putBoolean("commerce", "commerce" in granted)
        })
    }

    @ReactMethod
    fun addListener(eventName: String) {
        // Required for NativeEventEmitter
    }

    @ReactMethod
    fun removeListeners(count: Int) {
        // Required for NativeEventEmitter
    }

    private fun sendEvent(eventName: String, params: WritableMap) {
        reactContext
            .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
            .emit(eventName, params)
    }
}
