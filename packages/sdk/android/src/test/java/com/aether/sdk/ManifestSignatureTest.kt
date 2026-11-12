package com.aether.sdk

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/**
 * Truth Kernel §2.9 — manifest signature verification, against the vectors shared
 * with the backend, web and iOS suites (docs/reference/sdks/manifest-signing.md).
 */
class ManifestSignatureTest {

    private val vectors: JSONObject = run {
        val relative = "tests/fixtures/sdk/manifest-signing-vectors.json"
        // Gradle runs unit tests with the module directory as the working directory.
        val file = generateSequence(File(".").absoluteFile) { it.parentFile }
            .map { File(it, relative) }
            .firstOrNull { it.isFile }
            ?: error("cannot find $relative from ${File(".").absolutePath}")
        JSONObject(file.readText(Charsets.UTF_8))
    }

    private val publicKey: String = vectors.getString("public_key_spki_b64url")
    private val otherPublicKey: String = vectors.getString("other_public_key_spki_b64url")

    private fun each(name: String, block: (JSONObject) -> Unit) {
        val arr: JSONArray = vectors.getJSONArray(name)
        for (i in 0 until arr.length()) block(arr.getJSONObject(i))
    }

    private fun parse(text: String): Any = org.json.JSONTokener(text).nextValue()

    @Test
    fun `canonical JSON matches the shared vectors`() {
        each("canonical") { c ->
            assertEquals(c.getString("name"), c.getString("canonical"), ManifestSignature.canonicalJson(parse(c.getString("input_json"))))
        }
    }

    @Test
    fun `inputs that cannot be signed are rejected`() {
        each("rejected_inputs") { r ->
            try {
                ManifestSignature.canonicalJson(parse(r.getString("input_json")))
                fail("expected rejection: ${r.getString("name")}")
            } catch (_: ManifestCanonicalizationException) {
                // expected
            }
        }
    }

    @Test
    fun `verification matches the shared manifest vectors`() {
        each("manifests") { m ->
            val manifest = JSONObject(m.getString("manifest_json"))
            assertEquals(
                "${m.getString("name")} — ${m.getString("why")}",
                m.getBoolean("valid"),
                ManifestSignature.verify(manifest, publicKey),
            )
        }
    }

    private fun vector(name: String): JSONObject {
        val arr = vectors.getJSONArray("manifests")
        for (i in 0 until arr.length()) {
            val m = arr.getJSONObject(i)
            if (m.getString("name") == name) return JSONObject(m.getString("manifest_json"))
        }
        error("no vector $name")
    }

    @Test
    fun `valid manifest is rejected under a different public key`() {
        assertFalse(ManifestSignature.verify(vector("valid_full_manifest"), otherPublicKey))
    }

    @Test
    fun `malformed public keys fail closed`() {
        val m = vector("valid_full_manifest")
        assertFalse(ManifestSignature.verify(m, ""))
        assertFalse(ManifestSignature.verify(m, "not-a-key"))
        assertFalse(ManifestSignature.verify(m, "AAAA"))
    }

    // -- intake: envelope unwrapping + signature gate ------------------------

    private fun envelope(manifest: JSONObject): String =
        JSONObject().put("data", manifest).put("status", "success").toString()

    @Test
    fun `intake unwraps the APIResponse envelope and applies a signed manifest`() {
        val manifest = ManifestIntake.accept(envelope(vector("valid_full_manifest")), publicKey)
        assertNotNull(manifest)
        assertEquals("42", manifest!!.manifest_version)
        assertEquals(100, manifest.rollout_percentage)
        assertEquals(mapOf("analytics" to true, "web3" to false, "session_replay" to true), manifest.features)
    }

    @Test
    fun `intake rejects tampered, downgraded and unsigned manifests`() {
        for (name in listOf("tampered_endpoint", "tampered_rollout", "downgraded_alg", "missing_signature", "signed_by_other_key")) {
            assertNull(name, ManifestIntake.accept(envelope(vector(name)), publicKey))
        }
    }

    @Test
    fun `intake applies manifests unverified when no public key is configured`() {
        assertNotNull(ManifestIntake.accept(envelope(vector("tampered_endpoint")), null))
        assertNotNull(ManifestIntake.accept(envelope(vector("tampered_endpoint")), ""))
    }

    @Test
    fun `intake ignores a response with no manifest`() {
        assertNull(ManifestIntake.accept("""{"data":{"manifest":null},"status":"success"}""", publicKey))
        assertNull(ManifestIntake.accept("not json", publicKey))
        assertTrue(ManifestIntake.accept(vector("valid_full_manifest").toString(), publicKey) != null) // un-enveloped body also accepted
    }
}
