import XCTest
@testable import AetherSDK

final class AetherSDKTests: XCTestCase {
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
}
