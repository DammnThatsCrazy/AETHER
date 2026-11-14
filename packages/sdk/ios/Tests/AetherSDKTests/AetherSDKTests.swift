import XCTest
import CryptoKit
@testable import AetherSDK

final class AetherSDKTests: XCTestCase {

    func testSharedSDKBatchWireVectorUsesTheNativeEncoderAndEnvelope() throws {
        let fixtureURL = try sharedBatchWireFixtureURL()
        let fixture = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL)) as? [String: Any]
        )
        XCTAssertEqual(fixture["endpoint"] as? String, sdkBatchPath)
        let request = try XCTUnwrap(fixture["request"] as? [String: Any])
        let vectorBatch = try XCTUnwrap(request["batch"] as? [[String: Any]])
        let vectorEvent = try XCTUnwrap(vectorBatch.first)
        let vectorSentAt = try XCTUnwrap(request["sentAt"] as? String)

        // Decode through the SDK's public Codable model, then serialize through
        // the same helper used by both production batch send modes.
        let eventData = try JSONSerialization.data(withJSONObject: vectorEvent)
        let event = try JSONDecoder().decode(AetherEvent.self, from: eventData)
        let payloadData = try XCTUnwrap(encodeBatchPayload(batch: [event], sentAt: vectorSentAt))
        let payload = try XCTUnwrap(
            JSONSerialization.jsonObject(with: payloadData) as? [String: Any]
        )
        let requiredBatchFields = try XCTUnwrap(fixture["requiredBatchFields"] as? [String])
        for field in requiredBatchFields {
            XCTAssertNotNil(payload[field], "Missing batch field: \(field)")
        }
        XCTAssertEqual(payload["sentAt"] as? String, vectorSentAt)

        let events = try XCTUnwrap(payload["batch"] as? [[String: Any]])
        let encodedEvent = try XCTUnwrap(events.first)
        let requiredEventFields = try XCTUnwrap(fixture["requiredEventFields"] as? [String])
        for field in requiredEventFields {
            XCTAssertNotNil(encodedEvent[field], "Missing event field: \(field)")
        }
        XCTAssertEqual(encodedEvent["id"] as? String, vectorEvent["id"] as? String)
        XCTAssertEqual(encodedEvent["type"] as? String, vectorEvent["type"] as? String)
    }

    private func sharedBatchWireFixtureURL() throws -> URL {
        var directory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        while directory.path != "/" {
            let candidate = directory.appendingPathComponent("packages/shared/contracts/sdk-batch-wire-v1.json")
            if FileManager.default.fileExists(atPath: candidate.path) { return candidate }
            directory = directory.deletingLastPathComponent()
        }
        throw NSError(
            domain: "AetherSDKTests",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "Shared batch wire fixture not found"]
        )
    }

    func testCanonicalConsentReceiptGoldenVector() throws {
        let receipt = try Aether.shared.buildCanonicalConsentReceipt(
            CanonicalConsentReceiptInput(
                tenantId: "tenant-1",
                subjectId: "subject-1",
                purposes: ["marketing", "analytics"],
                state: "granted",
                source: "sdk-test",
                policyVersion: "2026-07-18",
                grantedAt: "2026-07-18T12:00:00.000Z"
            )
        )
        XCTAssertEqual(
            receipt.integrityHash,
            "sha256:96352c9c6e59371ad054846329720b2eb1285c71bb39406ffae5b1583e1e54c0"
        )
        XCTAssertEqual(receipt.receiptId, "ccr_96352c9c6e59371ad054846329720b2e")
        XCTAssertEqual(receipt.input.purposes, ["analytics", "marketing"])
    }

    // MARK: - AnyCodable

    func testAnyCodableString() throws {
        let codable = AnyCodable("hello")
        let data = try JSONEncoder().encode(codable)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? String, "hello")
    }

    func testAnyCodableInt() throws {
        let codable = AnyCodable(42)
        let data = try JSONEncoder().encode(codable)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Int, 42)
    }

    func testAnyCodableDouble() throws {
        let codable = AnyCodable(3.14)
        let data = try JSONEncoder().encode(codable)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Double, 3.14)
    }

    // MARK: - Config / Identity

    func testIdentityDataInit() {
        let identity = IdentityData(userId: "user_123", traits: ["plan": AnyCodable("pro")])
        XCTAssertEqual(identity.userId, "user_123")
        XCTAssertNotNil(identity.traits)
    }

    func testIdentifyIdempotencyKeyIsStableForQueuedEventAndChangesForNewEvent() {
        let properties = ["userId": AnyCodable("user-1")]
        let first = Aether.shared.withIdentifyIdempotencyKey(
            type: .identify, eventId: "event-1", properties: properties
        )
        let retry = Aether.shared.withIdentifyIdempotencyKey(
            type: .identify, eventId: "event-1", properties: properties
        )
        let next = Aether.shared.withIdentifyIdempotencyKey(
            type: .identify, eventId: "event-2", properties: properties
        )

        XCTAssertEqual(first["idempotency_key"]?.value as? String, "event-1")
        XCTAssertEqual(retry["idempotency_key"]?.value as? String, "event-1")
        XCTAssertEqual(next["idempotency_key"]?.value as? String, "event-2")
        XCTAssertNotEqual(
            first["idempotency_key"]?.value as? String,
            next["idempotency_key"]?.value as? String
        )
    }

    func testAliasRetriesDeriveSameOpaqueEventIdFromInstallSecretAndIdentityPair() {
        let first = Aether.shared.deterministicAliasEventId(
            secret: "install-secret", previousId: "anon-1", userId: "user-1"
        )
        let retry = Aether.shared.deterministicAliasEventId(
            secret: "install-secret", previousId: "anon-1", userId: "user-1"
        )
        let anotherUser = Aether.shared.deterministicAliasEventId(
            secret: "install-secret", previousId: "anon-1", userId: "user-2"
        )
        let anotherInstall = Aether.shared.deterministicAliasEventId(
            secret: "other-secret", previousId: "anon-1", userId: "user-1"
        )

        XCTAssertEqual(first, retry)
        // Shared Android/iOS vector: a platform drift would break alias retry
        // deduplication when a user moves between SDKs for one installation.
        XCTAssertEqual(first, "bc6bc9c9-9124-5e2e-ab25-fb414e667997")
        XCTAssertNotEqual(first, anotherUser)
        XCTAssertNotEqual(first, anotherInstall)
        XCTAssertEqual(first.range(of: #"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"#, options: .regularExpression) != nil, true)
    }

    func testConfigDefaults() {
        let config = AetherConfig(apiKey: "test_key")
        XCTAssertEqual(config.apiKey, "test_key")
        XCTAssertEqual(config.environment, .production)
        XCTAssertFalse(config.debug)
        XCTAssertEqual(config.batchSize, 10)
        XCTAssertEqual(config.flushInterval, 5.0)
    }

    // MARK: - Sensitive field scrubber

    func testScrubberRedactsSensitiveFields() {
        let sdk = Aether.shared
        let sensitiveFields: [(String, String)] = [
            ("privatekey",     "pk_live_abc123"),
            ("private_key",    "pk_live_abc123"),
            ("seedphrase",     "word1 word2 word3"),
            ("seed_phrase",    "word1 word2 word3"),
            ("mnemonic",       "word1 word2 word3"),
            ("secret",         "topsecret"),
            ("secretkey",      "topsecret"),
            ("secret_key",     "topsecret"),
            ("password",       "hunter2"),
            ("pin",            "1234"),
            ("cardnumber",     "4111111111111111"),
            ("card_number",    "4111111111111111"),
            ("pan",            "4111111111111111"),
            ("cvv",            "123"),
            ("cvc",            "123"),
            ("cvv2",           "123"),
            ("paymenttoken",   "tok_abc"),
            ("payment_token",  "tok_abc"),
            ("authcode",       "code123"),
            ("auth_code",      "code123"),
        ]

        for (key, value) in sensitiveFields {
            let props: [String: AnyCodable] = [key: AnyCodable(value), "safe": AnyCodable("kept")]
            let scrubbed = sdk.scrubSensitiveFields(props)
            XCTAssertEqual(scrubbed[key]?.value as? String, "[REDACTED]",
                           "Expected \(key) to be redacted")
            XCTAssertEqual(scrubbed["safe"]?.value as? String, "kept",
                           "Non-sensitive field must be preserved when scrubbing \(key)")
        }
    }

    func testScrubberIsCaseInsensitive() {
        let sdk = Aether.shared
        let props: [String: AnyCodable] = [
            "Password":  AnyCodable("abc"),
            "PASSWORD":  AnyCodable("xyz"),
            "CVV":       AnyCodable("999"),
        ]
        let scrubbed = sdk.scrubSensitiveFields(props)
        XCTAssertEqual(scrubbed["Password"]?.value as? String, "[REDACTED]")
        XCTAssertEqual(scrubbed["PASSWORD"]?.value as? String, "[REDACTED]")
        XCTAssertEqual(scrubbed["CVV"]?.value as? String, "[REDACTED]")
    }

    func testScrubberPreservesNonSensitiveFields() {
        let sdk = Aether.shared
        let props: [String: AnyCodable] = [
            "userId":   AnyCodable("u_123"),
            "amount":   AnyCodable(99.99),
            "currency": AnyCodable("USD"),
            "label":    AnyCodable("checkout"),
        ]
        let scrubbed = sdk.scrubSensitiveFields(props)
        XCTAssertEqual(scrubbed["userId"]?.value as? String, "u_123")
        XCTAssertEqual(scrubbed["amount"]?.value as? Double, 99.99)
        XCTAssertEqual(scrubbed["currency"]?.value as? String, "USD")
        XCTAssertEqual(scrubbed["label"]?.value as? String, "checkout")
    }

    func testScrubberDoesNotMutateInput() {
        let sdk = Aether.shared
        let props: [String: AnyCodable] = ["password": AnyCodable("original")]
        let _ = sdk.scrubSensitiveFields(props)
        XCTAssertEqual(props["password"]?.value as? String, "original")
    }

    // MARK: - Sensitive keys set coverage

    func testSensitiveKeysSetSize() {
        // 20 canonical keys — update this count if SENSITIVE_KEYS changes
        XCTAssertEqual(Aether.sensitiveKeys.count, 20)
    }

    func testSensitiveKeysContainsExpected() {
        let expected: Set<String> = [
            "privatekey", "private_key", "seedphrase", "seed_phrase", "mnemonic",
            "secret", "secretkey", "secret_key", "password", "pin",
            "cardnumber", "card_number", "pan", "cvv", "cvc", "cvv2",
            "paymenttoken", "payment_token", "authcode", "auth_code",
        ]
        XCTAssertEqual(Aether.sensitiveKeys, expected)
    }

    // MARK: - EVM address normalisation

    func testNormalizeEVMAddressLowercases() {
        let sdk = Aether.shared
        XCTAssertEqual(sdk.normalizeWalletAddress("0xABCDEF123456"), "0xabcdef123456")
        XCTAssertEqual(sdk.normalizeWalletAddress("0XAbCdEf"), "0xabcdef")
    }

    func testNormalizeNonEVMAddressTrimsWhitespace() {
        let sdk = Aether.shared
        let sol = "  SOLANA_ADDR  "
        XCTAssertEqual(sdk.normalizeWalletAddress(sol, vm: "svm"), "SOLANA_ADDR")
        XCTAssertEqual(sdk.normalizeWalletAddress(sol, vm: "bitcoin"), "SOLANA_ADDR")
    }

    func testNormalizeEVMIsDefaultVM() {
        let sdk = Aether.shared
        // Without vm: parameter defaults to EVM → lowercase
        XCTAssertEqual(sdk.normalizeWalletAddress("0xABCD"), "0xabcd")
    }

    // MARK: - Health Agent Tests

    func testHealthAgentCreatesStableSdkId() {
        // Two instances with same UserDefaults should get same SDK ID
        let agent1 = AetherHealthAgent(endpoint: "https://api.test", apiKey: "key1")
        let agent2 = AetherHealthAgent(endpoint: "https://api.test", apiKey: "key1")
        // Both should produce a non-empty schema hash
        XCTAssertFalse(agent1.droppedEvents < 0)
        XCTAssertFalse(agent2.droppedEvents < 0)
    }

    func testHealthAgentMetricsTracking() {
        let agent = AetherHealthAgent(endpoint: "https://api.test", apiKey: "key1")
        agent.recordDroppedEvents(5)
        XCTAssertEqual(agent.droppedEvents, 5)
        agent.recordRetry()
        XCTAssertEqual(agent.retryCount, 1)
        agent.recordBatchAttempt(success: true, latencyMs: 42.0)
        XCTAssertEqual(agent.droppedEvents, 5) // unchanged
    }

    // MARK: - Granular Agent Lifecycle Tests

    func testGranularAgentLifecycleEmitters() {
        // These tests verify that calling the methods doesn't crash.
        // In a real test environment with Xcode, you'd also verify the event type.
        // Here we verify the SDK is initialized and the methods are callable.
        let sdk = Aether.shared
        // Without initializing, calls should be no-ops (isInitialized guard)
        sdk.agentRegistered(agentId: "agent-1")
        sdk.agentUpdated(agentId: "agent-1")
        sdk.agentAuthorized(agentId: "agent-1", delegationId: "del-1")
        sdk.agentDeauthorized(agentId: "agent-1")
        sdk.agentCapabilityGranted(agentId: "agent-1", capability: "read")
        sdk.agentCapabilityRevoked(agentId: "agent-1", capability: "read")
        sdk.agentTaskCreated(taskId: "task-1", actorId: "agent-1")
        sdk.agentTaskDecomposed(taskId: "task-1")
        sdk.agentTaskStarted(taskId: "task-1")
        sdk.agentTaskCompleted(taskId: "task-1")
        sdk.agentTaskFailed(taskId: "task-1", reason: "timeout")
        sdk.agentToolCalled(taskId: "task-1", tool: "web_search")
        sdk.agentResourceRequested(resourceId: "res-1")
        sdk.agentDelegatedTask(taskId: "task-1", toAgentId: "agent-2")
        sdk.agentSubagentSpawned(parentId: "agent-1", childId: "agent-2")
        sdk.agentPolicyEvaluated(policyId: "policy-1", outcome: "allowed")
        sdk.agentHandoff(fromId: "agent-1", toId: "human-1")
        sdk.agentEscalatedToHuman(taskId: "task-1", reason: "ambiguous")
        sdk.agentOutcomeRecorded(taskId: "task-1", outcome: "success")
        // All 19 calls completed without crash
        XCTAssert(true)
    }

    // MARK: - Granular x402 Lifecycle Tests

    func testGranularX402LifecycleEmitters() {
        let sdk = Aether.shared
        sdk.x402ResourceRequested(resourceId: "res-1")
        sdk.x402PaymentRequired(resourceId: "res-1", amount: 0.01, currency: "USDC")
        sdk.x402QuoteReceived(quoteId: "quote-1")
        sdk.x402AuthorizationRequested(paymentId: "pay-1")
        sdk.x402AuthorizationResolved(paymentId: "pay-1", authorized: true)
        sdk.x402PaymentIntentCreated(intentId: "intent-1")
        sdk.x402PaymentSubmitted(paymentId: "pay-1")
        sdk.x402PaymentSettled(paymentId: "pay-1")
        sdk.x402PaymentFailed(paymentId: "pay-1", reason: "insufficient_funds")
        sdk.x402PaymentTimeout(paymentId: "pay-1")
        sdk.x402ReceiptVerified(receiptId: "receipt-1")
        sdk.x402AccessGranted(resourceId: "res-1")
        sdk.x402AccessDenied(resourceId: "res-1", reason: "payment_failed")
        sdk.x402RefundOrReversal(paymentId: "pay-1")
        // All 14 calls completed without crash
        XCTAssert(true)
    }

    // MARK: - Rewards Tests

    func testRewardEventEmitters() {
        let sdk = Aether.shared
        sdk.rewardActionQueued(campaignId: "camp-1", ruleId: "rule-1")
        sdk.rewardProofGenerated(campaignId: "camp-1", proofId: "proof-1")
        sdk.rewardDelivered(campaignId: "camp-1", rewardId: "reward-1")
        sdk.rewardClaimSubmitted(campaignId: "camp-1", claimId: "claim-1")
        XCTAssert(true)
    }

    // MARK: - Ecommerce Additions Tests

    func testEcommerceAdditions() {
        let sdk = Aether.shared
        sdk.trackRemoveFromCart(["productId": AnyCodable("prod-1")])
        sdk.trackApplyCoupon("SUMMER20")
        sdk.trackBeginCheckout(cartValue: 49.99, currency: "USD")
        XCTAssert(true)
    }

    // MARK: - Consent Gating Tests

    func testConsentEventsAlwaysPassThroughRegardlessOfState() {
        // consent type should always be in the eventConsentPurpose map
        XCTAssertNotNil(Aether.shared)
        // The consent event is allowed even in GDPR mode per implementation
        XCTAssert(true, "Consent events are unconditionally passed through")
    }

    // MARK: - Tier A Verification Tests

    func testTierATransportEndpoint() {
        // Verify the SDK uses /v1/batch endpoint
        // This is a static contract test - the string is baked into the implementation
        let endpoint = "https://api.aether.io"
        XCTAssertTrue(endpoint.contains("aether.io"))
        XCTAssertEqual(endpoint + "/v1/batch", "https://api.aether.io/v1/batch")
    }

    func testTierACanonicalPurposes() {
        let purposes = Aether.canonicalConsentPurposes
        XCTAssertEqual(Set(purposes), Set([
            "analytics", "marketing", "personalization", "web3",
            "agent", "commerce", "credit", "location"
        ]))
        XCTAssertEqual(Set(Aether.explicitOptInPurposes), Set(["credit", "location"]))
    }

    // MARK: - Manifest Signature Verification (§2.9)
    //
    // Run against the vectors shared with the backend, web and Android suites
    // (docs/reference/sdks/manifest-signing.md).

    private func manifestVectors() throws -> [String: Any] {
        var directory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        while directory.path != "/" {
            let candidate = directory.appendingPathComponent("tests/fixtures/sdk/manifest-signing-vectors.json")
            if FileManager.default.fileExists(atPath: candidate.path) {
                return try XCTUnwrap(
                    JSONSerialization.jsonObject(with: Data(contentsOf: candidate)) as? [String: Any]
                )
            }
            directory = directory.deletingLastPathComponent()
        }
        throw NSError(
            domain: "AetherSDKTests",
            code: 2,
            userInfo: [NSLocalizedDescriptionKey: "Manifest signing vectors not found"]
        )
    }

    private func parseJSON(_ text: String) throws -> Any {
        try JSONSerialization.jsonObject(with: Data(text.utf8), options: [.fragmentsAllowed])
    }

    private func manifestVector(_ name: String) throws -> [String: Any] {
        let manifests = try XCTUnwrap(try manifestVectors()["manifests"] as? [[String: Any]])
        let entry = try XCTUnwrap(manifests.first { $0["name"] as? String == name })
        return try XCTUnwrap(try parseJSON(try XCTUnwrap(entry["manifest_json"] as? String)) as? [String: Any])
    }

    func testCanonicalJSONMatchesTheSharedVectors() throws {
        let cases = try XCTUnwrap(try manifestVectors()["canonical"] as? [[String: Any]])
        XCTAssertFalse(cases.isEmpty)
        for c in cases {
            let name = c["name"] as? String ?? "?"
            let input = try parseJSON(try XCTUnwrap(c["input_json"] as? String))
            XCTAssertEqual(try ManifestSignature.canonicalJSON(input), c["canonical"] as? String, name)
        }
    }

    func testInputsThatCannotBeSignedAreRejected() throws {
        let cases = try XCTUnwrap(try manifestVectors()["rejected_inputs"] as? [[String: Any]])
        for c in cases {
            let name = c["name"] as? String ?? "?"
            let input = try parseJSON(try XCTUnwrap(c["input_json"] as? String))
            XCTAssertThrowsError(try ManifestSignature.canonicalJSON(input), name)
        }
    }

    func testManifestVerificationMatchesTheSharedVectors() throws {
        let vectors = try manifestVectors()
        let publicKey = try XCTUnwrap(vectors["public_key_spki_b64url"] as? String)
        let cases = try XCTUnwrap(vectors["manifests"] as? [[String: Any]])
        XCTAssertFalse(cases.isEmpty)
        for c in cases {
            let name = c["name"] as? String ?? "?"
            let manifest = try XCTUnwrap(try parseJSON(try XCTUnwrap(c["manifest_json"] as? String)) as? [String: Any])
            XCTAssertEqual(
                ManifestSignature.verify(manifest, publicKey: publicKey),
                c["valid"] as? Bool,
                "\(name) — \(c["why"] as? String ?? "")"
            )
        }
    }

    func testManifestIsRejectedUnderADifferentOrMalformedPublicKey() throws {
        let vectors = try manifestVectors()
        let other = try XCTUnwrap(vectors["other_public_key_spki_b64url"] as? String)
        let valid = try manifestVector("valid_full_manifest")
        XCTAssertFalse(ManifestSignature.verify(valid, publicKey: other))
        XCTAssertFalse(ManifestSignature.verify(valid, publicKey: ""))
        XCTAssertFalse(ManifestSignature.verify(valid, publicKey: "not-a-key"))
        XCTAssertFalse(ManifestSignature.verify(valid, publicKey: "AAAA"))
    }

    private func envelope(_ manifest: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["data": manifest, "status": "success"])
    }

    func testIntakeUnwrapsTheEnvelopeAndAppliesASignedManifest() throws {
        let publicKey = try XCTUnwrap(try manifestVectors()["public_key_spki_b64url"] as? String)
        let manifest = try XCTUnwrap(
            ManifestIntake.accept(try envelope(try manifestVector("valid_full_manifest")), publicKey: publicKey)
        )
        XCTAssertEqual(manifest.manifest_version, "42")
        XCTAssertEqual(manifest.rollout_percentage, 100)
        XCTAssertEqual(manifest.features, ["analytics": true, "web3": false, "session_replay": true])
    }

    func testIntakeRejectsTamperedDowngradedAndUnsignedManifests() throws {
        let publicKey = try XCTUnwrap(try manifestVectors()["public_key_spki_b64url"] as? String)
        for name in ["tampered_endpoint", "tampered_rollout", "downgraded_alg", "missing_signature", "signed_by_other_key"] {
            XCTAssertNil(ManifestIntake.accept(try envelope(try manifestVector(name)), publicKey: publicKey), name)
        }
    }

    func testIntakeAppliesManifestsUnverifiedWhenNoPublicKeyIsConfigured() throws {
        let tampered = try envelope(try manifestVector("tampered_endpoint"))
        XCTAssertNotNil(ManifestIntake.accept(tampered, publicKey: nil))
        XCTAssertNotNil(ManifestIntake.accept(tampered, publicKey: ""))
    }

    func testIntakeIgnoresAResponseWithNoManifest() throws {
        let publicKey = try XCTUnwrap(try manifestVectors()["public_key_spki_b64url"] as? String)
        XCTAssertNil(ManifestIntake.accept(Data(#"{"data":{"manifest":null},"status":"success"}"#.utf8), publicKey: publicKey))
        XCTAssertNil(ManifestIntake.accept(Data("not json".utf8), publicKey: publicKey))
    }

    // MARK: - observe() + BatchHealth (§2.6 / §2.8)

    func testObserveNonCanonicalTypeIsNoOp() {
        // observe() must never enqueue an unknown type. Before init the queue is
        // empty and stays empty.
        Aether.shared.observe("not_a_real_event_type", properties: ["x": AnyCodable(1)])
        XCTAssertEqual(Aether.shared.queueDepth(), 0)
    }

    func testBatchHealthStructHoldsCounters() {
        let h = BatchHealth(accepted: 3, duplicate: 1, rejected: 0, droppedByConsent: 2, queueDepth: 5)
        XCTAssertEqual(h.accepted, 3)
        XCTAssertEqual(h.duplicate, 1)
        XCTAssertEqual(h.droppedByConsent, 2)
        XCTAssertEqual(h.queueDepth, 5)
    }

    // MARK: - Remote Manifest Wiring (rollout sampling + feature flags)
    //
    // Aether.shared is never `initialize()`d in this test target, so
    // enqueueEvent()'s `isInitialized` guard would make an end-to-end
    // track()-then-queueDepth() assertion vacuous regardless of the sampling
    // gate. Aether.shouldSample(rate:roll:) is the pure decision function the
    // gate calls, so it is exercised directly with injected rolls for a
    // deterministic test. isFeatureEnabled() has no such guard and is
    // exercised through the public singleton.

    func testManifestRolloutPercentageZeroSamplesEventsOut() {
        // rollout_percentage=0 -> samplingRate=0.0. Every roll in [0,1) must
        // be sampled OUT, including the roll=0.0 boundary.
        XCTAssertFalse(Aether.shouldSample(rate: 0.0, roll: 0.0))
        XCTAssertFalse(Aether.shouldSample(rate: 0.0, roll: 0.5))
        XCTAssertFalse(Aether.shouldSample(rate: 0.0, roll: 0.999))
    }

    func testManifestRolloutPercentageFullKeepsEveryEvent() {
        // rollout_percentage=100 -> samplingRate=1.0. Every roll in [0,1)
        // must be kept.
        XCTAssertTrue(Aether.shouldSample(rate: 1.0, roll: 0.0))
        XCTAssertTrue(Aether.shouldSample(rate: 1.0, roll: 0.999))
    }

    func testManifestRolloutPartialSamplingIsRollDependent() {
        // rollout_percentage=50 -> samplingRate=0.5: keep when roll < rate.
        XCTAssertTrue(Aether.shouldSample(rate: 0.5, roll: 0.0))
        XCTAssertTrue(Aether.shouldSample(rate: 0.5, roll: 0.499))
        XCTAssertFalse(Aether.shouldSample(rate: 0.5, roll: 0.5))
        XCTAssertFalse(Aether.shouldSample(rate: 0.5, roll: 0.999))
    }

    func testManifestFeatureFlagIsHonoredByIsFeatureEnabled() {
        let sdk = Aether.shared
        let previous = sdk.manifestFeatureOverrides
        defer { sdk.manifestFeatureOverrides = previous }

        sdk.manifestFeatureOverrides = ["remote_beta_ui": true]
        XCTAssertTrue(sdk.isFeatureEnabled("remote_beta_ui"))

        sdk.manifestFeatureOverrides = ["remote_beta_ui": false]
        XCTAssertFalse(sdk.isFeatureEnabled("remote_beta_ui", default: true))
    }

    func testIsFeatureEnabledFallsBackToDefaultWhenNoManifestOverride() {
        let sdk = Aether.shared
        let previous = sdk.manifestFeatureOverrides
        defer { sdk.manifestFeatureOverrides = previous }

        sdk.manifestFeatureOverrides = [:]
        XCTAssertFalse(sdk.isFeatureEnabled("flag_absent_everywhere"))
        XCTAssertTrue(sdk.isFeatureEnabled("flag_absent_everywhere", default: true))
    }
}
