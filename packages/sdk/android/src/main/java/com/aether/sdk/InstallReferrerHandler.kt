// =============================================================================
// Aether SDK — Google Play Install Referrer retrieval
//
// Connects to the Play Install Referrer service on the first eligible launch,
// parses the referrer payload through the canonical acquisition-evidence
// parser (entryMethod "android_install_referrer"), hands it to Aether for
// consent-gated emission of app_install_attributed, and persists a state
// machine so install attribution is NEVER duplicated:
//
//   not_requested → pending → retrieved | unavailable | unsupported
//                             | failed_retryable | failed_terminal
//   retrieved → consumed  (after the payload is handed to the queue)
//
// SERVICE_UNAVAILABLE / SERVICE_DISCONNECTED are retried on later launches,
// bounded to MAX_RETRYABLE_ATTEMPTS across launches. FEATURE_NOT_SUPPORTED,
// DEVELOPER_ERROR, and PERMISSION_ERROR are terminal.
// =============================================================================

package com.aether.sdk

import android.content.Context
import android.content.SharedPreferences
import com.android.installreferrer.api.InstallReferrerClient
import com.android.installreferrer.api.InstallReferrerStateListener

/**
 * Pure-JVM state transitions for install-referrer retrieval, split out from the
 * Play-services plumbing so they are unit-testable without an Android runtime.
 */
internal object InstallReferrerStateMachine {
    const val STATE_NOT_REQUESTED = "not_requested"
    const val STATE_PENDING = "pending"
    const val STATE_RETRIEVED = "retrieved"
    const val STATE_UNAVAILABLE = "unavailable"
    const val STATE_UNSUPPORTED = "unsupported"
    const val STATE_FAILED_RETRYABLE = "failed_retryable"
    const val STATE_FAILED_TERMINAL = "failed_terminal"
    const val STATE_CONSUMED = "consumed"

    const val MAX_RETRYABLE_ATTEMPTS = 3

    // Mirrors InstallReferrerClient.InstallReferrerResponse constants so the
    // decision logic stays pure JVM.
    const val RESPONSE_SERVICE_DISCONNECTED = -1
    const val RESPONSE_OK = 0
    const val RESPONSE_SERVICE_UNAVAILABLE = 1
    const val RESPONSE_FEATURE_NOT_SUPPORTED = 2
    const val RESPONSE_DEVELOPER_ERROR = 3
    const val RESPONSE_PERMISSION_ERROR = 4

    /**
     * Whether a connection attempt should be made given the persisted state.
     * `pending` means a prior attempt died mid-connection (process death); it
     * is treated like a retryable failure and stays bounded by the attempt cap.
     * All resolved states (retrieved/consumed/unavailable/unsupported/
     * failed_terminal) never reconnect — install attribution happens once.
     */
    fun shouldAttempt(state: String, attempts: Int): Boolean = when (state) {
        STATE_NOT_REQUESTED -> true
        STATE_PENDING, STATE_FAILED_RETRYABLE -> attempts < MAX_RETRYABLE_ATTEMPTS
        else -> false
    }

    /**
     * Persisted state for a non-OK setup result, applying the bounded-retry
     * rule: SERVICE_UNAVAILABLE retries until the cap and then resolves to
     * `unavailable`; SERVICE_DISCONNECTED retries until the cap and then
     * resolves to `failed_terminal`; everything else is terminal immediately.
     */
    fun resolveFailureState(responseCode: Int, attempts: Int): String = when (responseCode) {
        RESPONSE_FEATURE_NOT_SUPPORTED -> STATE_UNSUPPORTED
        RESPONSE_SERVICE_UNAVAILABLE ->
            if (attempts >= MAX_RETRYABLE_ATTEMPTS) STATE_UNAVAILABLE else STATE_FAILED_RETRYABLE
        RESPONSE_SERVICE_DISCONNECTED ->
            if (attempts >= MAX_RETRYABLE_ATTEMPTS) STATE_FAILED_TERMINAL else STATE_FAILED_RETRYABLE
        RESPONSE_DEVELOPER_ERROR, RESPONSE_PERMISSION_ERROR -> STATE_FAILED_TERMINAL
        else -> STATE_FAILED_TERMINAL
    }
}

internal class InstallReferrerHandler(
    private val context: Context,
    private val prefs: SharedPreferences,
) {
    private companion object {
        const val PREF_STATE = "aether_install_referrer_state_v1"
        const val PREF_ATTEMPTS = "aether_install_referrer_attempts_v1"
    }

    private fun currentState(): String =
        prefs.getString(PREF_STATE, InstallReferrerStateMachine.STATE_NOT_REQUESTED)
            ?: InstallReferrerStateMachine.STATE_NOT_REQUESTED

    private fun setState(state: String) {
        prefs.edit().putString(PREF_STATE, state).apply()
    }

    fun connectIfEligible() {
        val attempts = prefs.getInt(PREF_ATTEMPTS, 0)
        if (!InstallReferrerStateMachine.shouldAttempt(currentState(), attempts)) return

        prefs.edit()
            .putString(PREF_STATE, InstallReferrerStateMachine.STATE_PENDING)
            .putInt(PREF_ATTEMPTS, attempts + 1)
            .apply()

        val client = InstallReferrerClient.newBuilder(context).build()
        try {
            client.startConnection(object : InstallReferrerStateListener {
                override fun onInstallReferrerSetupFinished(responseCode: Int) {
                    val attemptsNow = prefs.getInt(PREF_ATTEMPTS, 0)
                    if (responseCode == InstallReferrerClient.InstallReferrerResponse.OK) {
                        try {
                            val details = client.installReferrer
                            // Mark retrieved before handing off: even if the
                            // process dies mid-emit, we never re-attribute.
                            setState(InstallReferrerStateMachine.STATE_RETRIEVED)
                            Aether.handleInstallReferrer(
                                referrer = details.installReferrer ?: "",
                                referrerClickTimestampSeconds = details.referrerClickTimestampSeconds,
                                installBeginTimestampSeconds = details.installBeginTimestampSeconds,
                                installVersion = details.installVersion,
                                googlePlayInstantParam = details.googlePlayInstantParam,
                            )
                            setState(InstallReferrerStateMachine.STATE_CONSUMED)
                        } catch (_: Exception) {
                            // Payload retrieval failed after an OK handshake —
                            // treat like a service drop (bounded retry).
                            setState(
                                InstallReferrerStateMachine.resolveFailureState(
                                    InstallReferrerStateMachine.RESPONSE_SERVICE_DISCONNECTED,
                                    attemptsNow,
                                )
                            )
                        }
                    } else {
                        setState(InstallReferrerStateMachine.resolveFailureState(responseCode, attemptsNow))
                    }
                    try { client.endConnection() } catch (_: Exception) { }
                }

                override fun onInstallReferrerServiceDisconnected() {
                    // Only downgrade an in-flight attempt; a completed state
                    // (retrieved/consumed) must never be overwritten.
                    if (currentState() == InstallReferrerStateMachine.STATE_PENDING) {
                        setState(
                            InstallReferrerStateMachine.resolveFailureState(
                                InstallReferrerStateMachine.RESPONSE_SERVICE_DISCONNECTED,
                                prefs.getInt(PREF_ATTEMPTS, 0),
                            )
                        )
                    }
                }
            })
        } catch (_: Exception) {
            setState(
                InstallReferrerStateMachine.resolveFailureState(
                    InstallReferrerStateMachine.RESPONSE_SERVICE_DISCONNECTED,
                    prefs.getInt(PREF_ATTEMPTS, 0),
                )
            )
            try { client.endConnection() } catch (_: Exception) { }
        }
    }
}
