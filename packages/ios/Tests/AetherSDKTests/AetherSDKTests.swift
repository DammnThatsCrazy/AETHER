import XCTest
@testable import AetherSDK

final class AetherSDKTests: XCTestCase {

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
}
