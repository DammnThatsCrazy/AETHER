package com.aether.sdk

import kotlin.test.Test
import kotlin.test.assertEquals

class ConsentReceiptTest {
    @Test
    fun `canonical receipt matches backend golden vector`() {
        val receipt = Aether.buildCanonicalConsentReceipt(
            CanonicalConsentReceiptInput(
                tenantId = "tenant-1",
                subjectId = "subject-1",
                purposes = listOf("marketing", "analytics"),
                state = "granted",
                source = "sdk-test",
                policyVersion = "2026-07-18",
                grantedAt = "2026-07-18T12:00:00.000Z",
            )
        )

        assertEquals(
            "sha256:96352c9c6e59371ad054846329720b2eb1285c71bb39406ffae5b1583e1e54c0",
            receipt.integrityHash,
        )
        assertEquals("ccr_96352c9c6e59371ad054846329720b2e", receipt.receiptId)
        assertEquals(listOf("analytics", "marketing"), receipt.input.purposes)
    }
}
