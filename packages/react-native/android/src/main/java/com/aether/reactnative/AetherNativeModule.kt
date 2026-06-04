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
