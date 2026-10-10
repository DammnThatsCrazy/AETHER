package com.aether.sdk

import org.junit.Assert.*
import org.junit.Test

/**
 * Pure-JVM tests for the canonical acquisition-evidence parser, URL
 * sanitization, and the install-referrer state machine. No Android runtime
 * required (org.json is provided as a real test dependency).
 */
class AetherAttributionTest {

    private val observedAt = "2026-07-23T12:00:00.000Z"

    // -------------------------------------------------------------------------
    // Canonical evidence parser
    // -------------------------------------------------------------------------

    @Test
    fun parser_capturesUtmClickIdsAndAetherTokens() {
        val evidence = parseAcquisitionEvidenceFromUrl(
            "https://shop.example.com/products/widget" +
                "?utm_source=twitter&utm_medium=social&utm_campaign=summer&utm_content=profile_bio" +
                "&utm_term=widgets&utm_id=cmp-42&gclid=abc123&aether_ref=tok_opaque&aether_cid=uuid-1",
            entryMethod = "android_app_link",
            observedAtIso = observedAt,
        )!!
        assertEquals("twitter", evidence.getString("utmSource"))
        assertEquals("social", evidence.getString("utmMedium"))
        assertEquals("summer", evidence.getString("utmCampaign"))
        assertEquals("profile_bio", evidence.getString("utmContent"))
        assertEquals("widgets", evidence.getString("utmTerm"))
        assertEquals("cmp-42", evidence.getString("utmId"))
        assertEquals("abc123", evidence.getJSONObject("clickIds").getString("gclid"))
        assertEquals("tok_opaque", evidence.getString("referralToken"))
        assertEquals("uuid-1", evidence.getString("canonicalCampaignId"))
        assertEquals("android_app_link", evidence.getString("entryMethod"))
        assertEquals(ACQUISITION_EVIDENCE_SCHEMA_VERSION, evidence.getInt("schemaVersion"))
        assertEquals(observedAt, evidence.getString("evidenceObservedAt"))
    }

    @Test
    fun parser_hostIsDestinationDomainNeverReferrer() {
        val evidence = parseAcquisitionEvidenceFromUrl(
            "https://shop.example.com/landing?utm_source=x",
            entryMethod = "android_app_link",
            observedAtIso = observedAt,
        )!!
        assertEquals("shop.example.com", evidence.getString("destinationDomain"))
        // The link host must NEVER be reported as a referrer.
        assertFalse(evidence.has("referrerDomain"))
        assertFalse(evidence.has("referrer"))
    }

    @Test
    fun parser_hashesDestinationPathTruncated24Hex() {
        val evidence = parseAcquisitionEvidenceFromUrl(
            "https://shop.example.com/private/account-area?utm_source=x",
            entryMethod = "android_app_link",
            observedAtIso = observedAt,
        )!!
        val hash = evidence.getString("destinationPathHash")
        assertEquals(24, hash.length)
        assertTrue(hash.matches(Regex("^[0-9a-f]{24}$")))
        // Deterministic and equal to the standalone helper.
        assertEquals(hashDestinationPath("/private/account-area"), hash)
        // Raw path is not present anywhere in the evidence.
        assertFalse(evidence.toString().contains("account-area"))
    }

    @Test
    fun parser_mapsClickIdAliasesForSharedContractParity() {
        val evidence = parseAcquisitionEvidenceFromUrl(
            "https://a.example.com/?li_fat_id=li1&rdt_cid=rd1&fbclid=fb1",
            entryMethod = "android_app_link",
            observedAtIso = observedAt,
        )!!
        val clickIds = evidence.getJSONObject("clickIds")
        assertEquals("li1", clickIds.getString("liEFatId"))
        assertEquals("rd1", clickIds.getString("rdtCid"))
        assertEquals("fb1", clickIds.getString("fbclid"))
    }

    @Test
    fun parser_decodesPercentEncodedValues() {
        val evidence = parseAcquisitionEvidenceFromUrl(
            "https://a.example.com/?utm_campaign=spring%20sale",
            entryMethod = "android_app_link",
            observedAtIso = observedAt,
        )!!
        assertEquals("spring sale", evidence.getString("utmCampaign"))
    }

    @Test
    fun parser_handlesCustomSchemeAndUnparseableUrls() {
        val custom = parseAcquisitionEvidenceFromUrl(
            "myapp://open/details?utm_source=push",
            entryMethod = "manual_sdk_evidence",
            observedAtIso = observedAt,
        )
        assertNotNull(custom)
        assertEquals("manual_sdk_evidence", custom!!.getString("entryMethod"))
        assertEquals("push", custom.getString("utmSource"))

        val broken = parseAcquisitionEvidenceFromUrl(
            "https://a b c^^not a url",
            entryMethod = "android_app_link",
            observedAtIso = observedAt,
        )
        assertNull(broken)
    }

    // -------------------------------------------------------------------------
    // URL sanitization (transmitted URLs)
    // -------------------------------------------------------------------------

    @Test
    fun sanitize_stripsAetherTokensClickIdsAndFragment() {
        val sanitized = sanitizeAttributionUrl(
            "https://shop.example.com/landing?utm_source=tw&aether_ref=tok&gclid=g1&fbclid=f1&utm_medium=social#frag"
        )
        assertEquals("https://shop.example.com/landing?utm_source=tw&utm_medium=social", sanitized)
        assertFalse(sanitized.contains("aether_ref"))
        assertFalse(sanitized.contains("gclid"))
        assertFalse(sanitized.contains("#"))
    }

    @Test
    fun sanitize_dropsQueryEntirelyWhenOnlyStrippedParams() {
        assertEquals(
            "https://shop.example.com/x",
            sanitizeAttributionUrl("https://shop.example.com/x?aether_ref=tok&gclid=g1")
        )
    }

    @Test
    fun sanitize_worksTextuallyOnUnparseableUrls() {
        val sanitized = sanitizeAttributionUrl("not a valid url?aether_ref=tok&keep=1#f")
        assertEquals("not a valid url?keep=1", sanitized)
    }

    // -------------------------------------------------------------------------
    // Install referrer parsing
    // -------------------------------------------------------------------------

    @Test
    fun installReferrer_parsesQueryStylePayloadThroughSameParser() {
        val evidence = parseInstallReferrerEvidence(
            "utm_source=google-play&utm_medium=cpc&utm_campaign=launch&gclid=g42",
            observedAt,
        )
        assertEquals("google-play", evidence.getString("utmSource"))
        assertEquals("cpc", evidence.getString("utmMedium"))
        assertEquals("launch", evidence.getString("utmCampaign"))
        assertEquals("g42", evidence.getJSONObject("clickIds").getString("gclid"))
        assertEquals("android_install_referrer", evidence.getString("entryMethod"))
        assertEquals(ACQUISITION_EVIDENCE_SCHEMA_VERSION, evidence.getInt("schemaVersion"))
        assertFalse(evidence.has("destinationDomain"))
        assertFalse(evidence.has("referrerDomain"))
    }

    @Test
    fun installReferrer_nonQueryPayloadYieldsEntryMethodOnly() {
        val evidence = parseInstallReferrerEvidence("organic", observedAt)
        assertEquals("android_install_referrer", evidence.getString("entryMethod"))
        assertFalse(evidence.has("utmSource"))
        assertFalse(evidence.has("clickIds"))
    }

    // -------------------------------------------------------------------------
    // Path hashing
    // -------------------------------------------------------------------------

    @Test
    fun hashDestinationPath_nullForEmptyAndStableOtherwise() {
        assertNull(hashDestinationPath(null))
        assertNull(hashDestinationPath(""))
        val a = hashDestinationPath("/checkout")
        val b = hashDestinationPath("/checkout")
        assertEquals(a, b)
        assertEquals(24, a!!.length)
        assertNotEquals(a, hashDestinationPath("/other"))
    }

    // -------------------------------------------------------------------------
    // Install-referrer state machine
    // -------------------------------------------------------------------------

    @Test
    fun stateMachine_attemptEligibility() {
        val sm = InstallReferrerStateMachine
        assertTrue(sm.shouldAttempt(sm.STATE_NOT_REQUESTED, 0))
        assertTrue(sm.shouldAttempt(sm.STATE_FAILED_RETRYABLE, 1))
        assertTrue(sm.shouldAttempt(sm.STATE_PENDING, 2))
        assertFalse(sm.shouldAttempt(sm.STATE_FAILED_RETRYABLE, sm.MAX_RETRYABLE_ATTEMPTS))
        assertFalse(sm.shouldAttempt(sm.STATE_RETRIEVED, 0))
        assertFalse(sm.shouldAttempt(sm.STATE_CONSUMED, 0))
        assertFalse(sm.shouldAttempt(sm.STATE_UNAVAILABLE, 0))
        assertFalse(sm.shouldAttempt(sm.STATE_UNSUPPORTED, 0))
        assertFalse(sm.shouldAttempt(sm.STATE_FAILED_TERMINAL, 0))
    }

    @Test
    fun stateMachine_failureResolution() {
        val sm = InstallReferrerStateMachine
        // SERVICE_UNAVAILABLE: retryable until the cap, then resolved unavailable.
        assertEquals(sm.STATE_FAILED_RETRYABLE, sm.resolveFailureState(sm.RESPONSE_SERVICE_UNAVAILABLE, 1))
        assertEquals(sm.STATE_UNAVAILABLE, sm.resolveFailureState(sm.RESPONSE_SERVICE_UNAVAILABLE, sm.MAX_RETRYABLE_ATTEMPTS))
        // SERVICE_DISCONNECTED: retryable until the cap, then terminal.
        assertEquals(sm.STATE_FAILED_RETRYABLE, sm.resolveFailureState(sm.RESPONSE_SERVICE_DISCONNECTED, 2))
        assertEquals(sm.STATE_FAILED_TERMINAL, sm.resolveFailureState(sm.RESPONSE_SERVICE_DISCONNECTED, sm.MAX_RETRYABLE_ATTEMPTS))
        // FEATURE_NOT_SUPPORTED is terminal immediately.
        assertEquals(sm.STATE_UNSUPPORTED, sm.resolveFailureState(sm.RESPONSE_FEATURE_NOT_SUPPORTED, 0))
        // Developer / permission errors are terminal immediately.
        assertEquals(sm.STATE_FAILED_TERMINAL, sm.resolveFailureState(sm.RESPONSE_DEVELOPER_ERROR, 0))
        assertEquals(sm.STATE_FAILED_TERMINAL, sm.resolveFailureState(sm.RESPONSE_PERMISSION_ERROR, 0))
        // Unknown response codes are terminal (never retried blindly).
        assertEquals(sm.STATE_FAILED_TERMINAL, sm.resolveFailureState(99, 0))
    }
}
