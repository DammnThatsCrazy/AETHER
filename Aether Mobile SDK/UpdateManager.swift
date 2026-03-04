// =============================================================================
// AETHER SDK — iOS OTA Update Manager (v5.0.0)
// Fetches remote manifest, syncs OTA data modules (chain registry, protocols,
// wallet labels, wallet classification) without requiring SDK reinstall.
// Runs entirely on background queues — never blocks the main thread.
// =============================================================================

import Foundation
import CommonCrypto

// MARK: - Manifest Types

/// Describes a single remotely-hosted data module.
public struct AetherDataModuleDescriptor: Decodable {
    public let version: String
    public let url: String
    public let hash: String
    public let size: Int
    public let updatedAt: String
}

/// The SDK manifest returned by the CDN.
public struct AetherSDKManifest: Decodable {
    public let latestVersion: String
    public let minimumVersion: String
    public let updateUrgency: String          // "none" | "recommended" | "critical"
    public let featureFlags: [String: Bool]
    public let dataModules: DataModules
    public let checkIntervalMs: Int
    public let generatedAt: String

    public struct DataModules: Decodable {
        public let chainRegistry: AetherDataModuleDescriptor?
        public let protocolRegistry: AetherDataModuleDescriptor?
        public let walletLabels: AetherDataModuleDescriptor?
        public let walletClassification: AetherDataModuleDescriptor?
    }
}

// MARK: - Notifications

public extension NSNotification.Name {
    /// Posted when a critical SDK update is available. The `userInfo` dictionary
    /// contains `"version"` (String) and `"urgency"` (String).
    static let AetherUpdateAvailable = NSNotification.Name("AetherUpdateAvailable")
}

// MARK: - AetherUpdateManager

/// Singleton manager responsible for fetching remote data-module updates over
/// the air. It verifies SHA-256 integrity, caches in UserDefaults, and
/// schedules periodic re-checks. All work runs on a utility-QoS serial queue.
public final class AetherUpdateManager {

    // -------------------------------------------------------------------------
    // MARK: Singleton
    // -------------------------------------------------------------------------

    public static let shared = AetherUpdateManager()
    private init() {}

    // -------------------------------------------------------------------------
    // MARK: Constants
    // -------------------------------------------------------------------------

    public static let version = "5.0.0"
    private let suiteName = "com.aether.sdk.data"
    private let manifestCacheKey = "_aether_manifest"
    private let modulePrefix = "_aether_dm_"

    // -------------------------------------------------------------------------
    // MARK: Internal State
    // -------------------------------------------------------------------------

    private var apiKey: String?
    private var endpoint: String?
    private var currentVersion: String?
    private var isRunning = false
    private var destroyed = false

    private lazy var defaults: UserDefaults = {
        UserDefaults(suiteName: suiteName) ?? .standard
    }()

    /// Dedicated serial queue — all work happens here.
    private let queue = DispatchQueue(
        label: "com.aether.sdk.update",
        qos: .utility
    )

    /// In-flight URLSession tasks that we may need to cancel.
    private var activeTasks: [URLSessionDataTask] = []

    /// Work item for the next scheduled check so we can cancel on destroy.
    private var nextCheckWork: DispatchWorkItem?

    // -------------------------------------------------------------------------
    // MARK: Public API
    // -------------------------------------------------------------------------

    /// Start background update checks.
    ///
    /// - Parameters:
    ///   - apiKey:          Your Aether SDK API key (sent as Bearer token).
    ///   - endpoint:        Base URL for the Aether API (e.g. `https://api.aether.network`).
    ///   - currentVersion:  The current version string of the SDK bundle.
    public func start(apiKey: String, endpoint: String, currentVersion: String) {
        queue.async { [weak self] in
            guard let self = self, !self.destroyed else { return }
            guard !self.isRunning else {
                self.log("UpdateManager already running")
                return
            }

            self.apiKey = apiKey
            self.endpoint = endpoint
            self.currentVersion = currentVersion
            self.isRunning = true

            self.log("Starting UpdateManager v\(AetherUpdateManager.version)")

            // Fire initial check (fire-and-forget).
            self.performUpdateCheck()
        }
    }

    /// Read a previously cached data module from UserDefaults, decoded as `T`.
    ///
    /// - Parameter key: The module key (e.g. `"chainRegistry"`).
    /// - Returns: The decoded value, or `nil` if nothing is cached or decoding fails.
    public func getDataModule<T: Decodable>(_ key: String) -> T? {
        guard let raw = defaults.data(forKey: modulePrefix + key) else { return nil }
        // The cached blob is a JSON wrapper: { "version": "...", "data": <T> }
        // We extract just the "data" portion.
        do {
            guard let wrapper = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
                  let inner = wrapper["data"] else {
                return nil
            }
            let innerData = try JSONSerialization.data(withJSONObject: inner)
            return try JSONDecoder().decode(T.self, from: innerData)
        } catch {
            log("Failed to decode cached module '\(key)': \(error.localizedDescription)")
            return nil
        }
    }

    /// Remove all cached data and stop scheduled checks.
    public func destroy() {
        queue.async { [weak self] in
            guard let self = self else { return }
            self.destroyed = true
            self.isRunning = false

            // Cancel pending work.
            self.nextCheckWork?.cancel()
            self.nextCheckWork = nil

            // Cancel in-flight network tasks.
            for task in self.activeTasks {
                task.cancel()
            }
            self.activeTasks.removeAll()

            self.log("UpdateManager destroyed")
        }
    }

    /// Clear all cached modules and manifest from UserDefaults.
    public func clearCache() {
        let keys = defaults.dictionaryRepresentation().keys.filter {
            $0.hasPrefix(modulePrefix) || $0 == manifestCacheKey
        }
        for key in keys {
            defaults.removeObject(forKey: key)
        }
        log("Cache cleared")
    }

    // -------------------------------------------------------------------------
    // MARK: Update Check Flow
    // -------------------------------------------------------------------------

    private func performUpdateCheck() {
        guard !destroyed else { return }

        fetchManifest { [weak self] result in
            guard let self = self, !self.destroyed else { return }

            switch result {
            case .success(let manifest):
                // Notify if a critical SDK update is available.
                if manifest.updateUrgency == "critical",
                   manifest.latestVersion != self.currentVersion {
                    DispatchQueue.main.async {
                        NotificationCenter.default.post(
                            name: .AetherUpdateAvailable,
                            object: nil,
                            userInfo: [
                                "version": manifest.latestVersion,
                                "urgency": manifest.updateUrgency
                            ]
                        )
                    }
                }

                // Sync individual data modules.
                self.syncDataModules(manifest: manifest) {
                    // Schedule next check.
                    let interval = self.resolveCheckInterval(manifest: manifest)
                    self.scheduleNextCheck(afterMs: interval)
                    self.log("Update check complete. Next in \(interval / 1000)s")
                }

            case .failure(let error):
                self.log("Manifest fetch failed: \(error.localizedDescription)")
                // Retry in 5 minutes.
                self.scheduleNextCheck(afterMs: 300_000)
            }
        }
    }

    // -------------------------------------------------------------------------
    // MARK: Manifest Fetch
    // -------------------------------------------------------------------------

    private func fetchManifest(completion: @escaping (Result<AetherSDKManifest, Error>) -> Void) {
        guard let endpoint = endpoint else {
            completion(.failure(UpdateError.notConfigured))
            return
        }

        let urlString = "\(endpoint)/sdk/manifests/ios/latest.json"
        guard let url = URL(string: urlString) else {
            completion(.failure(UpdateError.invalidURL(urlString)))
            return
        }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("ios", forHTTPHeaderField: "X-Aether-SDK")
        request.setValue(currentVersion ?? "unknown", forHTTPHeaderField: "X-Aether-Version")
        if let apiKey = apiKey {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }

        let task = URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            self?.queue.async {
                if let error = error {
                    completion(.failure(error))
                    return
                }
                guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
                    let code = (response as? HTTPURLResponse)?.statusCode ?? -1
                    completion(.failure(UpdateError.httpError(code)))
                    return
                }
                guard let data = data else {
                    completion(.failure(UpdateError.emptyResponse))
                    return
                }

                do {
                    let manifest = try JSONDecoder().decode(AetherSDKManifest.self, from: data)
                    // Cache the raw manifest.
                    self?.defaults.set(data, forKey: self?.manifestCacheKey ?? "")
                    completion(.success(manifest))
                } catch {
                    completion(.failure(error))
                }
            }
        }

        activeTasks.append(task)
        task.resume()
    }

    // -------------------------------------------------------------------------
    // MARK: Data Module Sync
    // -------------------------------------------------------------------------

    private func syncDataModules(manifest: AetherSDKManifest, completion: @escaping () -> Void) {
        let modules: [(String, AetherDataModuleDescriptor?)] = [
            ("chainRegistry",        manifest.dataModules.chainRegistry),
            ("protocolRegistry",     manifest.dataModules.protocolRegistry),
            ("walletLabels",         manifest.dataModules.walletLabels),
            ("walletClassification", manifest.dataModules.walletClassification),
        ]

        let group = DispatchGroup()

        for (name, descriptor) in modules {
            guard let descriptor = descriptor else { continue }

            // Check cache version — skip if identical.
            if let cached = getCachedModuleVersion(name), cached == descriptor.version {
                log("Module '\(name)' v\(cached) up to date")
                continue
            }

            group.enter()
            downloadAndCacheModule(name: name, descriptor: descriptor) {
                group.leave()
            }
        }

        group.notify(queue: queue) {
            completion()
        }
    }

    private func downloadAndCacheModule(
        name: String,
        descriptor: AetherDataModuleDescriptor,
        completion: @escaping () -> Void
    ) {
        guard let url = URL(string: descriptor.url) else {
            log("Invalid URL for module '\(name)': \(descriptor.url)")
            completion()
            return
        }

        log("Downloading module '\(name)' v\(descriptor.version)")

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let apiKey = apiKey {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }

        let task = URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            self?.queue.async {
                defer { completion() }
                guard let self = self, !self.destroyed else { return }

                if let error = error {
                    self.log("Download failed for '\(name)': \(error.localizedDescription)")
                    return
                }
                guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
                    let code = (response as? HTTPURLResponse)?.statusCode ?? -1
                    self.log("HTTP \(code) downloading module '\(name)'")
                    return
                }
                guard let data = data else {
                    self.log("Empty response for module '\(name)'")
                    return
                }

                // Verify SHA-256 hash.
                if !descriptor.hash.isEmpty {
                    let computedHash = self.sha256Hex(data: data)
                    if computedHash != descriptor.hash {
                        self.log("Hash mismatch for '\(name)': expected \(descriptor.hash), got \(computedHash)")
                        return // Reject update, keep previous version.
                    }
                }

                // Parse JSON to ensure validity.
                guard let jsonObject = try? JSONSerialization.jsonObject(with: data) else {
                    self.log("Invalid JSON for module '\(name)'")
                    return
                }

                // Build cache wrapper.
                let wrapper: [String: Any] = [
                    "version": descriptor.version,
                    "data": jsonObject,
                    "hash": descriptor.hash,
                    "updatedAt": descriptor.updatedAt
                ]
                guard let cacheData = try? JSONSerialization.data(withJSONObject: wrapper) else {
                    self.log("Failed to serialize cache wrapper for '\(name)'")
                    return
                }

                self.defaults.set(cacheData, forKey: self.modulePrefix + name)
                self.log("Cached module '\(name)' v\(descriptor.version)")
            }
        }

        activeTasks.append(task)
        task.resume()
    }

    // -------------------------------------------------------------------------
    // MARK: Cache Helpers
    // -------------------------------------------------------------------------

    private func getCachedModuleVersion(_ name: String) -> String? {
        guard let raw = defaults.data(forKey: modulePrefix + name) else { return nil }
        guard let wrapper = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else { return nil }
        return wrapper["version"] as? String
    }

    // -------------------------------------------------------------------------
    // MARK: Scheduling
    // -------------------------------------------------------------------------

    private func scheduleNextCheck(afterMs: Int) {
        nextCheckWork?.cancel()

        let work = DispatchWorkItem { [weak self] in
            self?.performUpdateCheck()
        }
        nextCheckWork = work

        queue.asyncAfter(
            deadline: .now() + .milliseconds(afterMs),
            execute: work
        )
    }

    private func resolveCheckInterval(manifest: AetherSDKManifest) -> Int {
        let ms = manifest.checkIntervalMs
        // Clamp: minimum 60s, maximum 24h.
        return max(60_000, min(ms, 86_400_000))
    }

    // -------------------------------------------------------------------------
    // MARK: SHA-256
    // -------------------------------------------------------------------------

    private func sha256Hex(data: Data) -> String {
        var hash = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
        data.withUnsafeBytes { buffer in
            _ = CC_SHA256(buffer.baseAddress, CC_LONG(data.count), &hash)
        }
        return hash.map { String(format: "%02x", $0) }.joined()
    }

    // -------------------------------------------------------------------------
    // MARK: Logging
    // -------------------------------------------------------------------------

    private func log(_ message: String) {
        #if DEBUG
        print("[Aether UpdateManager] \(message)")
        #endif
    }

    // -------------------------------------------------------------------------
    // MARK: Error Types
    // -------------------------------------------------------------------------

    private enum UpdateError: LocalizedError {
        case notConfigured
        case invalidURL(String)
        case httpError(Int)
        case emptyResponse

        var errorDescription: String? {
            switch self {
            case .notConfigured:       return "UpdateManager not configured — call start() first"
            case .invalidURL(let url): return "Invalid URL: \(url)"
            case .httpError(let code): return "HTTP error \(code)"
            case .emptyResponse:       return "Empty response body"
            }
        }
    }
}
