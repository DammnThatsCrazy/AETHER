import CryptoKit
import Foundation
#if canImport(DeviceCheck)
import DeviceCheck
#endif

/// Apple App Attest for agent-detection device-integrity evidence.
///
/// Opt in with `AetherConfig.deviceIntegrity = true` (the app needs the App
/// Attest capability / `com.apple.developer.devicecheck.appattest-environment`
/// entitlement). The SDK asks Aether for a single-use challenge, attests a fresh
/// App Attest key against `SHA256(challenge)`, and receives a short-lived
/// integrity token that rides on every event as `context.device.integrity`.
///
/// Attestation proves a genuine app on a genuine Apple device. It is evidence
/// against spoofed / scripted clients, never proof that a human is acting.
/// See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
final class DeviceIntegrityManager {

    struct StoredToken: Codable, Equatable {
        let token: String
        let expiresAt: Int
        let anonymousId: String
    }

    /// Sends a JSON POST to an Aether path; completes with the decoded JSON body or nil.
    typealias Post = (_ path: String, _ body: [String: Any], _ completion: @escaping ([String: Any]?) -> Void) -> Void

    static let defaultsKey = "com.aether.deviceIntegrity.token"
    /// Refresh this long before the token expires.
    static let refreshMarginSeconds = 6 * 3600

    private let defaults: UserDefaults
    private let post: Post
    private let now: () -> Date
    private var inFlight = false
    private let lock = NSLock()

    init(defaults: UserDefaults = .standard, post: @escaping Post, now: @escaping () -> Date = Date.init) {
        self.defaults = defaults
        self.post = post
        self.now = now
    }

    /// The token for this install, or nil when absent, expired or bound to another install id.
    func currentToken(for anonymousId: String) -> String? {
        guard let stored = load(), stored.anonymousId == anonymousId,
              stored.expiresAt > Int(now().timeIntervalSince1970) else { return nil }
        return stored.token
    }

    func needsRefresh(for anonymousId: String) -> Bool {
        guard let stored = load(), stored.anonymousId == anonymousId else { return true }
        return stored.expiresAt - Self.refreshMarginSeconds <= Int(now().timeIntervalSince1970)
    }

    func clear() {
        defaults.removeObject(forKey: Self.defaultsKey)
    }

    /// Attest (once per token lifetime) when App Attest is available. Never throws.
    func refreshIfNeeded(anonymousId: String) {
        guard needsRefresh(for: anonymousId) else { return }
        lock.lock()
        if inFlight { lock.unlock(); return }
        inFlight = true
        lock.unlock()
        attest(anonymousId: anonymousId) { [weak self] in
            self?.lock.lock()
            self?.inFlight = false
            self?.lock.unlock()
        }
    }

    // MARK: - Flow

    private func attest(anonymousId: String, done: @escaping () -> Void) {
        #if canImport(DeviceCheck)
        guard #available(iOS 14.0, macOS 11.0, tvOS 15.0, *), DCAppAttestService.shared.isSupported else {
            done(); return
        }
        post("/sdk/device-integrity/challenge", ["platform": "ios", "anonymousId": anonymousId]) { [weak self] json in
            guard let self, let challenge = json?["challenge"] as? String else { done(); return }
            let service = DCAppAttestService.shared
            // A fresh key per attestation: App Attest keys are attested once.
            service.generateKey { keyId, error in
                guard let keyId, error == nil else { done(); return }
                let clientDataHash = Data(SHA256.hash(data: Data(challenge.utf8)))
                service.attestKey(keyId, clientDataHash: clientDataHash) { attestation, error in
                    guard let attestation, error == nil else { done(); return }
                    let body: [String: Any] = [
                        "platform": "ios",
                        "anonymousId": anonymousId,
                        "challenge": challenge,
                        "keyId": keyId,
                        "attestationObject": attestation.base64EncodedString(),
                    ]
                    self.post("/sdk/device-integrity/verify", body) { result in
                        self.store(result, anonymousId: anonymousId)
                        done()
                    }
                }
            }
        }
        #else
        done()
        #endif
    }

    /// Persist a verify response (`integrityToken`, `expiresAt`). Exposed for tests.
    func store(_ result: [String: Any]?, anonymousId: String) {
        guard let token = result?["integrityToken"] as? String,
              let expires = (result?["expiresAt"] as? NSNumber)?.intValue else { return }
        let stored = StoredToken(token: token, expiresAt: expires, anonymousId: anonymousId)
        if let data = try? JSONEncoder().encode(stored) {
            defaults.set(data, forKey: Self.defaultsKey)
        }
    }

    private func load() -> StoredToken? {
        guard let data = defaults.data(forKey: Self.defaultsKey) else { return nil }
        return try? JSONDecoder().decode(StoredToken.self, from: data)
    }
}
