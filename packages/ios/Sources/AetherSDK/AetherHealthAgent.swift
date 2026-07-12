// =============================================================================
// Aether SDK — iOS Health Agent
// Emits signed fleet heartbeats and fetches remote config manifest.
// Fire-and-forget: heartbeat failure never blocks the event pipeline.
// =============================================================================

import Foundation
import CryptoKit

// MARK: - Types

public struct SDKHeartbeatPayload: Codable {
    public let sdk_id: String
    public let sdk_version: String
    public let platform: String
    public let app_version: String
    public let queue_depth: Int
    public let retry_count: Int
    public let dropped_events: Int
    public let endpoint_latency_ms: Double
    public let ingestion_success_rate: Double
    public let schema_hash: String
    public let auth_valid: Bool
    public let consent_valid: Bool
    public let wallet_connected: Bool
    public let config_version: String
    public let rollout_cohort: String
}

public struct SDKManifest: Codable {
    public let manifest_version: String
    public let min_sdk_version: String
    public let schema_version: String
    public let rollout_percentage: Int
    public let features: [String: Bool]
    public let published_at: String
    public let signature: String
}

public typealias ManifestUpdateCallback = (SDKManifest) -> Void

// MARK: - AetherHealthAgent

public final class AetherHealthAgent {
    private let endpoint: String
    private let apiKey: String
    private let sdkId: String
    private let platform: String
    private let appVersion: String
    private let heartbeatIntervalSec: TimeInterval
    private let manifestRefreshSec: TimeInterval
    /// HMAC-SHA256 secret used to verify manifest signatures (Truth Kernel §2.9).
    /// When set, unsigned or invalid-signature manifests are rejected and the
    /// last-known-good manifest is kept (fail-closed). Source: the tenant's
    /// SDK_CONFIG_SECRET, provisioned out-of-band and never shipped in the app
    /// bundle in plaintext for production tenants.
    private let manifestVerificationKey: String?

    private var heartbeatTimer: Timer?
    private var manifestTimer: Timer?
    private var isRunning = false
    private var currentManifest: SDKManifest?
    private var configVersion: String = "0"
    private var manifestCallbacks: [ManifestUpdateCallback] = []

    // Metrics — updated by Aether SDK main class
    private(set) var droppedEvents: Int = 0
    private(set) var retryCount: Int = 0
    private var totalAttempts: Int = 0
    private var successfulAttempts: Int = 0
    private var lastLatencyMs: Double = 0

    /// Callbacks returning live state at heartbeat time.
    public var getDynamicState: (() -> (queueDepth: Int, authValid: Bool, consentValid: Bool, walletConnected: Bool))?

    private let defaults = UserDefaults(suiteName: "com.aether.sdk.health")!
    private let queue = DispatchQueue(label: "com.aether.sdk.health", qos: .background)

    public init(
        endpoint: String,
        apiKey: String,
        platform: String = "ios",
        appVersion: String = "",
        heartbeatIntervalSec: TimeInterval = 60,
        manifestRefreshSec: TimeInterval = 300,
        manifestVerificationKey: String? = nil
    ) {
        self.endpoint = endpoint
        self.apiKey = apiKey
        self.platform = platform
        self.appVersion = appVersion
        self.heartbeatIntervalSec = heartbeatIntervalSec
        self.manifestRefreshSec = manifestRefreshSec
        self.manifestVerificationKey = manifestVerificationKey
        self.sdkId = Self.loadOrCreateSdkId(defaults: defaults)
    }

    // MARK: - Public API

    public func start() {
        guard !isRunning else { return }
        isRunning = true

        // Immediate first-run (fire-and-forget)
        queue.async { [weak self] in
            self?.sendHeartbeat()
            self?.fetchManifest()
        }

        // Repeating timers on main run loop (fire-and-forget closures)
        heartbeatTimer = Timer.scheduledTimer(withTimeInterval: heartbeatIntervalSec, repeats: true) { [weak self] _ in
            self?.queue.async { self?.sendHeartbeat() }
        }
        manifestTimer = Timer.scheduledTimer(withTimeInterval: manifestRefreshSec, repeats: true) { [weak self] _ in
            self?.queue.async { self?.fetchManifest() }
        }
    }

    public func stop() {
        isRunning = false
        heartbeatTimer?.invalidate(); heartbeatTimer = nil
        manifestTimer?.invalidate(); manifestTimer = nil
    }

    public func onManifestUpdate(_ callback: @escaping ManifestUpdateCallback) {
        manifestCallbacks.append(callback)
    }

    // Called by Aether main SDK when a batch is dropped
    public func recordDroppedEvents(_ count: Int) { droppedEvents += count }

    // Called by Aether main SDK after each batch attempt
    public func recordBatchAttempt(success: Bool, latencyMs: Double) {
        totalAttempts += 1
        if success { successfulAttempts += 1 }
        lastLatencyMs = latencyMs
    }

    public func recordRetry() { retryCount += 1 }

    // MARK: - Private

    private func sendHeartbeat() {
        guard let url = URL(string: "\(endpoint)/v1/diagnostics/sdk/heartbeat") else { return }
        let state = getDynamicState?() ?? (queueDepth: 0, authValid: true, consentValid: true, walletConnected: false)
        let rate = totalAttempts > 0 ? Double(successfulAttempts) / Double(totalAttempts) : 1.0

        let payload = SDKHeartbeatPayload(
            sdk_id: sdkId,
            sdk_version: "8.12.0",
            platform: platform,
            app_version: appVersion,
            queue_depth: state.queueDepth,
            retry_count: retryCount,
            dropped_events: droppedEvents,
            endpoint_latency_ms: lastLatencyMs,
            ingestion_success_rate: rate,
            schema_hash: schemaHash(),
            auth_valid: state.authValid,
            consent_valid: state.consentValid,
            wallet_connected: state.walletConnected,
            config_version: configVersion,
            rollout_cohort: "default"
        )

        guard let body = try? JSONEncoder().encode(payload) else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("ios", forHTTPHeaderField: "X-Aether-SDK")
        request.httpBody = body
        request.timeoutInterval = 5.0

        URLSession.shared.dataTask(with: request) { _, _, _ in /* fire-and-forget */ }.resume()
    }

    private func fetchManifest() {
        guard let url = URL(string: "\(endpoint)/v1/config/sdk/manifest") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 5.0

        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            guard let self = self,
                  let data = data,
                  let manifest = try? JSONDecoder().decode(SDKManifest.self, from: data) else { return }

            // Signature gate (Truth Kernel §2.9): when a verification key is
            // configured, reject unsigned/invalid manifests and keep the last
            // known-good config (fail-closed). Without a key, apply as before.
            if let key = self.manifestVerificationKey, !key.isEmpty {
                guard self.verifyManifestSignature(manifest, key: key) else {
                    self.log("Manifest signature verification failed — keeping last-known-good config")
                    return
                }
            }

            let previousVersion = self.configVersion
            self.configVersion = manifest.manifest_version
            self.currentManifest = manifest

            if manifest.manifest_version != previousVersion {
                let callbacks = self.manifestCallbacks
                DispatchQueue.main.async {
                    callbacks.forEach { $0(manifest) }
                }
            }
        }.resume()
    }

    /// Return the currently cached (verified, if a key is configured) manifest.
    public func getManifest() -> SDKManifest? { currentManifest }

    // MARK: - Manifest Signature Verification (§2.9)

    /// Verify a manifest's HMAC-SHA256 signature over its canonical serialization
    /// using `key` (hex-encoded signature, constant-time comparison). Returns
    /// false for an empty signature or empty key so callers fail closed.
    public func verifyManifestSignature(_ manifest: SDKManifest, key: String) -> Bool {
        guard !manifest.signature.isEmpty, !key.isEmpty else { return false }
        let canonical = Self.canonicalManifestString(manifest)
        let mac = HMAC<SHA256>.authenticationCode(
            for: Data(canonical.utf8),
            using: SymmetricKey(data: Data(key.utf8))
        )
        let expected = mac.map { String(format: "%02x", $0) }.joined()
        return Self.constantTimeEquals(expected, manifest.signature.lowercased())
    }

    /// Deterministic canonical serialization of the signed manifest fields
    /// (signature excluded). Top-level fields and feature keys are sorted so the
    /// SDK and the backend signer produce byte-identical input.
    static func canonicalManifestString(_ m: SDKManifest) -> String {
        let features = m.features.keys.sorted()
            .map { "\($0)=\(m.features[$0]! ? "true" : "false")" }
            .joined(separator: ",")
        let fields: [(String, String)] = [
            ("features", features),
            ("manifest_version", m.manifest_version),
            ("min_sdk_version", m.min_sdk_version),
            ("published_at", m.published_at),
            ("rollout_percentage", String(m.rollout_percentage)),
            ("schema_version", m.schema_version),
        ]
        return fields.sorted { $0.0 < $1.0 }
            .map { "\($0.0)=\($0.1)" }
            .joined(separator: "|")
    }

    /// Length-checked, constant-time string comparison (avoids early-exit timing
    /// leaks when comparing signatures).
    static func constantTimeEquals(_ a: String, _ b: String) -> Bool {
        let ab = Array(a.utf8), bb = Array(b.utf8)
        guard ab.count == bb.count else { return false }
        var diff: UInt8 = 0
        for i in 0..<ab.count { diff |= ab[i] ^ bb[i] }
        return diff == 0
    }

    private func log(_ message: String) {
        #if DEBUG
        print("[Aether Health] \(message)")
        #endif
    }

    private func schemaHash() -> String {
        let types = AetherEventType.allCases.map { $0.rawValue }.sorted().joined(separator: ",")
        let data = Data(types.utf8)
        let hash = SHA256.hash(data: data)
        return hash.compactMap { String(format: "%02x", $0) }.joined()
    }

    private static func loadOrCreateSdkId(defaults: UserDefaults) -> String {
        if let stored = defaults.string(forKey: "sdkId") { return stored }
        let id = UUID().uuidString
        defaults.set(id, forKey: "sdkId")
        return id
    }
}
