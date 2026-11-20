package com.aether.sdk

import android.content.SharedPreferences
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private class MemoryPrefs : SharedPreferences {
    val map = mutableMapOf<String, Any?>()

    override fun getAll(): MutableMap<String, *> = map
    override fun getString(key: String?, defValue: String?) = (map[key] as? String) ?: defValue
    override fun getStringSet(key: String?, defValues: MutableSet<String>?) = defValues
    override fun getInt(key: String?, defValue: Int) = defValue
    override fun getLong(key: String?, defValue: Long) = defValue
    override fun getFloat(key: String?, defValue: Float) = defValue
    override fun getBoolean(key: String?, defValue: Boolean) = defValue
    override fun contains(key: String?) = map.containsKey(key)
    override fun registerOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener?) {}
    override fun unregisterOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener?) {}
    override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
        override fun putString(key: String?, value: String?) = apply { map[key!!] = value }
        override fun putStringSet(key: String?, values: MutableSet<String>?) = this
        override fun putInt(key: String?, value: Int) = this
        override fun putLong(key: String?, value: Long) = this
        override fun putFloat(key: String?, value: Float) = this
        override fun putBoolean(key: String?, value: Boolean) = this
        override fun remove(key: String?) = apply { map.remove(key) }
        override fun clear() = apply { map.clear() }
        override fun commit() = true
        override fun apply() {}
    }
}

class DeviceIntegrityManagerTest {

    private val now = 1_000_000L

    private fun manager(
        prefs: MemoryPrefs = MemoryPrefs(),
        post: suspend (String, JSONObject) -> JSONObject? = { _, _ -> null },
        token: suspend (String) -> String? = { null },
    ) = DeviceIntegrityManager(prefs, post, token, "com.example.app", now = { now })

    @Test
    fun storedTokenIsBoundToInstallAndExpiry() {
        val m = manager()
        assertNull(m.currentToken("anon-1"))
        m.store(JSONObject().put("integrityToken", "tok").put("expiresAt", now + 7 * 86_400), "anon-1")
        assertEquals("tok", m.currentToken("anon-1"))
        assertNull(m.currentToken("anon-2"))
        assertFalse(m.needsRefresh("anon-1"))
        assertTrue(m.needsRefresh("anon-2"))
    }

    @Test
    fun refreshIsDueInsideTheMarginAndClearRemovesToken() {
        val m = manager()
        m.store(JSONObject().put("integrityToken", "tok").put("expiresAt", now + 3_600), "a")
        assertTrue(m.needsRefresh("a"))
        assertEquals("tok", m.currentToken("a"))
        m.clear()
        assertNull(m.currentToken("a"))
    }

    @Test
    fun fullFlowRequestsChallengeUsesItAsNonceAndStoresToken() = runTest {
        val calls = mutableListOf<Pair<String, JSONObject>>()
        var nonceSeen: String? = null
        val m = manager(
            post = { path, body ->
                calls += path to body
                if (path.endsWith("/challenge")) JSONObject().put("challenge", "ch-123")
                else JSONObject().put("verdict", "verified").put("integrityToken", "itok").put("expiresAt", now + 86_400)
            },
            token = { nonce -> nonceSeen = nonce; "play-token" },
        )
        m.refreshIfNeeded("anon-1")
        assertEquals("ch-123", nonceSeen)
        assertEquals(listOf("/sdk/device-integrity/challenge", "/sdk/device-integrity/verify"), calls.map { it.first })
        val verify = calls[1].second
        assertEquals("play-token", verify.getString("integrityToken"))
        assertEquals("ch-123", verify.getString("challenge"))
        assertEquals("com.example.app", verify.getString("packageName"))
        assertEquals("itok", m.currentToken("anon-1"))
    }

    @Test
    fun failuresStoreNothingAndNeverThrow() = runTest {
        val m = manager(
            post = { path, _ -> if (path.endsWith("/challenge")) JSONObject().put("challenge", "c") else null },
            token = { throw IllegalStateException("play services missing") },
        )
        m.refreshIfNeeded("anon-1")
        assertNull(m.currentToken("anon-1"))
    }
}
