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
            endpoint = config.getString("endpoint") ?: "https://api.aether.network",
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
        Aether.hydrateIdentity(IdentityData(
            walletAddress = address,
            walletType = options.getString("type"),
            chainId = if (options.hasKey("chainId")) options.getInt("chainId") else null
        ))
    }

    @ReactMethod
    fun walletDisconnect() {
        Aether.track("wallet_disconnected")
    }

    @ReactMethod
    fun walletTransaction(txHash: String, options: ReadableMap) {
        Aether.track("wallet_transaction", mapOf(
            "txHash" to txHash
        ) + options.toHashMap().mapValues { it.value })
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
        val state = Arguments.createMap().apply {
            putBoolean("analytics", true)
            putBoolean("marketing", false)
            putBoolean("web3", false)
        }
        promise.resolve(state)
    }

    @ReactMethod
    fun grantConsent(purposes: ReadableArray) {
        Aether.track("consent_granted", mapOf(
            "purposes" to (0 until purposes.size()).map { purposes.getString(it) }
        ))
    }

    @ReactMethod
    fun revokeConsent(purposes: ReadableArray) {
        Aether.track("consent_revoked", mapOf(
            "purposes" to (0 until purposes.size()).map { purposes.getString(it) }
        ))
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
