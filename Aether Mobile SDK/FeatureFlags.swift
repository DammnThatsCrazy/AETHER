// =============================================================================
// Aether SDK — FEATURE FLAGS MODULE (iOS)
// Client-side feature flag evaluation with remote configuration
// =============================================================================

import Foundation

// MARK: - Types

public struct AetherFeatureFlag: Codable {
    public let key: String
    public let enabled: Bool
    public var value: AnyCodable?
    public var variant: String?
    public let source: FlagSource

    public enum FlagSource: String, Codable {
        case remote
        case local
        case `default`
        case override_
    }

    public init(
        key: String,
        enabled: Bool,
        value: AnyCodable? = nil,
        variant: String? = nil,
        source: FlagSource = .default
    ) {
        self.key = key
        self.enabled = enabled
        self.value = value
        self.variant = variant
        self.source = source
    }
}

public struct AetherFlagConfig {
    public let endpoint: String
    public let apiKey: String
    public var refreshIntervalSec: TimeInterval
    public var defaults: [String: AetherFeatureFlag]
    public var overrides: [String: Any]

    public init(
        endpoint: String,
        apiKey: String,
        refreshIntervalSec: TimeInterval = 300,
        defaults: [String: AetherFeatureFlag] = [:],
        overrides: [String: Any] = [:]
    ) {
        self.endpoint = endpoint
        self.apiKey = apiKey
        self.refreshIntervalSec = refreshIntervalSec
        self.defaults = defaults
        self.overrides = overrides
    }
}

// MARK: - AetherFeatureFlags

public final class AetherFeatureFlags {
    public static let shared = AetherFeatureFlags()

    private let serialQueue = DispatchQueue(label: "com.aether.sdk.featureflags")
    private let defaults = UserDefaults(suiteName: "com.aether.sdk")!
    private let cacheKey = "aether_feature_flags"

    private var config: AetherFlagConfig?
    private var flags: [String: AetherFeatureFlag] = [:]
    private var overrides: [String: Any] = [:]
    private var defaultFlags: [String: AetherFeatureFlag] = [:]
    private var refreshTimer: DispatchSourceTimer?
    private var isConfigured = false

    private init() {}

    // MARK: - Configuration

    /// Initialize the feature flags module with a configuration.
    /// Loads cache, applies defaults/overrides, and starts background refresh.
    public func configure(_ config: AetherFlagConfig) {
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            self.config = config
            self.defaultFlags = config.defaults
            self.overrides = config.overrides
            self.isConfigured = true

            // Load cached flags from disk
            self.loadCache()

            // Start background refresh timer
            self.startRefreshTimer(intervalSec: config.refreshIntervalSec)

            // Fire initial fetch
            self.fetchFlags()
        }
    }

    // MARK: - Public API

    /// Simple boolean check for a flag key.
    /// Priority: overrides > remote > defaults
    public func isEnabled(_ key: String) -> Bool {
        let flag = resolveFlag(key)
        Aether.shared.track("feature_flag_evaluated", properties: [
            "flag_key": AnyCodable(key),
            "enabled": AnyCodable(flag.enabled),
            "source": AnyCodable(flag.source.rawValue)
        ])
        return flag.enabled
    }

    /// Get the full flag object with metadata.
    public func getFlag(_ key: String) -> AetherFeatureFlag {
        let flag = resolveFlag(key)
        Aether.shared.track("feature_flag_evaluated", properties: [
            "flag_key": AnyCodable(key),
            "enabled": AnyCodable(flag.enabled),
            "source": AnyCodable(flag.source.rawValue),
            "variant": AnyCodable(flag.variant ?? "")
        ])
        return flag
    }

    /// Get a typed value from a flag, falling back to the provided default.
    public func getValue<T>(_ key: String, default defaultValue: T) -> T {
        let flag = resolveFlag(key)
        if let anyValue = flag.value?.value as? T {
            return anyValue
        }
        return defaultValue
    }

    /// Set a local override for a flag (useful for dev/testing).
    public func setOverride(_ key: String, value: Any) {
        serialQueue.async { [weak self] in
            self?.overrides[key] = value
        }
    }

    /// Clear a local override for a flag.
    public func clearOverride(_ key: String) {
        serialQueue.async { [weak self] in
            self?.overrides.removeValue(forKey: key)
        }
    }

    /// Clear all local overrides.
    public func clearAllOverrides() {
        serialQueue.async { [weak self] in
            self?.overrides.removeAll()
        }
    }

    /// Force a remote fetch of flags.
    public func refresh() {
        serialQueue.async { [weak self] in
            self?.fetchFlags()
        }
    }

    /// Stop the background refresh timer and clean up.
    public func destroy() {
        serialQueue.async { [weak self] in
            self?.refreshTimer?.cancel()
            self?.refreshTimer = nil
            self?.isConfigured = false
        }
    }

    // MARK: - Flag Resolution

    /// Priority: overrides > remote > defaults
    private func resolveFlag(_ key: String) -> AetherFeatureFlag {
        return serialQueue.sync {
            // 1. Check overrides
            if let overrideValue = overrides[key] {
                let enabled: Bool
                if let boolValue = overrideValue as? Bool {
                    enabled = boolValue
                } else {
                    enabled = true
                }
                return AetherFeatureFlag(
                    key: key,
                    enabled: enabled,
                    value: AnyCodable(overrideValue),
                    source: .override_
                )
            }

            // 2. Check remote flags
            if let remoteFlag = flags[key] {
                return remoteFlag
            }

            // 3. Check defaults
            if let defaultFlag = defaultFlags[key] {
                return defaultFlag
            }

            // 4. Unknown flag — disabled by default
            return AetherFeatureFlag(key: key, enabled: false, source: .default)
        }
    }

    // MARK: - Remote Fetch

    private func fetchFlags() {
        guard let config = config else { return }

        let urlString = "\(config.endpoint)/sdk/flags"
        guard let url = URL(string: urlString) else { return }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("ios", forHTTPHeaderField: "X-Aether-SDK")

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self else { return }
            self.serialQueue.async {
                guard let data = data, error == nil,
                      let httpResponse = response as? HTTPURLResponse,
                      httpResponse.statusCode == 200 else {
                    return
                }

                self.parseAndCacheFlags(data)
            }
        }.resume()
    }

    private func parseAndCacheFlags(_ data: Data) {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let flagsArray = json["flags"] as? [[String: Any]] else { return }

        for flagDict in flagsArray {
            guard let key = flagDict["key"] as? String else { continue }
            let enabled = flagDict["enabled"] as? Bool ?? false
            let variant = flagDict["variant"] as? String
            let value = flagDict["value"]

            let flag = AetherFeatureFlag(
                key: key,
                enabled: enabled,
                value: value != nil ? AnyCodable(value!) : nil,
                variant: variant,
                source: .remote
            )
            flags[key] = flag
        }

        // Persist to cache
        defaults.set(data, forKey: cacheKey)
    }

    // MARK: - Cache

    private func loadCache() {
        guard let data = defaults.data(forKey: cacheKey) else { return }
        parseAndCacheFlags(data)
        // Re-tag cached flags as local (from cache, not live remote)
        for (key, flag) in flags {
            flags[key] = AetherFeatureFlag(
                key: flag.key,
                enabled: flag.enabled,
                value: flag.value,
                variant: flag.variant,
                source: .local
            )
        }
    }

    // MARK: - Background Refresh

    private func startRefreshTimer(intervalSec: TimeInterval) {
        refreshTimer?.cancel()

        let timer = DispatchSource.makeTimerSource(queue: serialQueue)
        timer.schedule(
            deadline: .now() + intervalSec,
            repeating: intervalSec,
            leeway: .seconds(5)
        )
        timer.setEventHandler { [weak self] in
            self?.fetchFlags()
        }
        timer.resume()
        refreshTimer = timer
    }
}
