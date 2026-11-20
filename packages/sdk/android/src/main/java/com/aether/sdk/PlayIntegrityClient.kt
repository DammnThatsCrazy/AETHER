package com.aether.sdk

import android.content.Context
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * Calls into the Play Integrity library. Only loaded after
 * [DeviceIntegrityManager.playIntegrityAvailable] returned true, so the
 * compileOnly classes are never touched in apps without the library.
 */
internal object PlayIntegrityClient {
    suspend fun requestToken(context: Context, nonce: String, cloudProjectNumber: Long?): String? =
        suspendCancellableCoroutine { cont ->
            try {
                val manager = com.google.android.play.core.integrity.IntegrityManagerFactory.create(context)
                val builder = com.google.android.play.core.integrity.IntegrityTokenRequest.builder().setNonce(nonce)
                if (cloudProjectNumber != null) builder.setCloudProjectNumber(cloudProjectNumber)
                manager.requestIntegrityToken(builder.build())
                    .addOnSuccessListener { response -> if (cont.isActive) cont.resume(response.token()) }
                    .addOnFailureListener { if (cont.isActive) cont.resume(null) }
            } catch (_: Throwable) {
                if (cont.isActive) cont.resume(null)
            }
        }
}
