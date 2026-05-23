// =============================================================================
// Aether SDK — iOS (Swift)
// Core analytics, identity, session, consent, Web3 tracking
// =============================================================================

import Foundation
import UIKit
import CryptoKit
import MetricKit
import Network
import AppTrackingTransparency
import AdSupport

// MARK: - Configuration

public struct AetherConfig {
    public let apiKey: String
    public var environment: Environment = .production
    public var debug: Bool = false
    public var endpoint: String = "https://api.aether.io"
    public var modules: ModuleConfig = ModuleConfig()
    public var privacy: PrivacyConfig = PrivacyConfig()
    public var batchSize: Int = 10
    public var flushInterval: TimeInterval = 5.0
    public var autoResumeJourney: Bool = true
    public var onJourneyResumed: ((_ resolvedAnonymousId: String, _ resolvedUserId: String?) -> Void)? = nil

    public init(apiKey: String) {
        self.apiKey = apiKey
    }

    public enum Environment: String, Codable {
        case production, staging, development
    }
}

public struct ModuleConfig {
    public var screenTracking: Bool = true
    public var deepLinkAttribution: Bool = true
    public var pushNotificationTracking: Bool = true
    public var walletTracking: Bool = true
    public var purchaseTracking: Bool = true
    public var errorTracking: Bool = true
    public var experiments: Bool = false

    public init() {}
}

public struct PrivacyConfig {
    public var gdprMode: Bool = false
    public var anonymizeIP: Bool = true
    public var respectATT: Bool = true

    public init() {}
}

// MARK: - Event Types

public enum AetherEventType: String, Codable {
    case track, screen, identify, conversion, wallet, transaction, error, consent
}

public struct AetherEvent: Codable {
    public let id: String
    public let type: AetherEventType
    public let timestamp: String
    public let sessionId: String
    public let anonymousId: String
    public var userId: String?
    public var properties: [String: AnyCodable]
    public var context: EventContext
}

public struct EventContext: Codable {
    public let library: LibraryInfo
    public var device: DeviceInfo?
    public var campaign: CampaignInfo?
    public var fingerprint: FingerprintInfo?
    public var network: String?
    public var thermalState: String?
    public var consent: [String: Bool]?

    public struct LibraryInfo: Codable {
        public let name: String
        public let version: String
    }

    public struct DeviceInfo: Codable {
        public let osName: String
        public let osVersion: String
        public let locale: String
        public let timezone: String
    }

    public struct CampaignInfo: Codable {
        public var source: String?
        public var medium: String?
        public var campaign: String?
        public var content: String?
        public var term: String?
        public var clickIds: [String: String] = [:]
        public var referrerDomain: String?
    }

    public struct FingerprintInfo: Codable {
        public let id: String
    }
}

// MARK: - Identity

public struct WalletEntry {
    public var address: String
    public var vm: String       // evm | svm | bitcoin | movevm | near | tvm | cosmos
    public var walletType: String
    public var chainId: String

    public init(address: String, vm: String = "evm", walletType: String = "unknown", chainId: String = "unknown") {
        self.address = address; self.vm = vm
        self.walletType = walletType; self.chainId = chainId
    }
}

public struct IdentityData {
    public var userId: String?
    public var email: String?
    public var walletAddress: String?
    public var walletType: String?
    public var chainId: Int?
    public var traits: [String: AnyCodable]?
    public var wallets: [WalletEntry]

    public init(userId: String? = nil, email: String? = nil, walletAddress: String? = nil,
                traits: [String: AnyCodable]? = nil, wallets: [WalletEntry] = []) {
        self.userId = userId; self.email = email
        self.walletAddress = walletAddress
        self.traits = traits; self.wallets = wallets
    }
}

// MARK: - Device Fingerprint

struct DeviceFingerprint {
    static func generate() -> String {
        let signals = [
            UIDevice.current.identifierForVendor?.uuidString ?? "",
            UIDevice.current.model,
            UIDevice.current.systemVersion,
            String(describing: UIScreen.main.bounds.width),
            String(describing: UIScreen.main.bounds.height),
            String(describing: UIScreen.main.scale),
            Locale.current.identifier,
            TimeZone.current.identifier,
            String(ProcessInfo.processInfo.processorCount),
            String(ProcessInfo.processInfo.physicalMemory),
        ]
        return sha256(signals.joined(separator: "|"))
    }

    static func sha256(_ input: String) -> String {
        let data = Data(input.utf8)
        let hash = SHA256.hash(data: data)
        return hash.compactMap { String(format: "%02x", $0) }.joined()
    }
}

// MARK: - Main SDK Class

public final class Aether: NSObject {
    public static let shared = Aether()

    private var config: AetherConfig?
    private var eventQueue: [AetherEvent] = []
    private var sessionId: String = UUID().uuidString
    private var anonymousId: String = ""
    private var userId: String?
    private var walletAddress: String?
    private var email: String?
    private var traits: [String: AnyCodable] = [:]
    private var flushTimer: Timer?
    private var sessionStart: Date = Date()
    private var appStartDate: Date = Date()
    private var screenCount: Int = 0
    private var eventCount: Int = 0
    private var isInitialized = false
    private var serverConfig: [String: Any] = [:]
    private var consentState: [String] = []
    private var fingerprintId: String = ""
    private var campaignInfo: EventContext.CampaignInfo?
    private let networkMonitor = NWPathMonitor()
    private var currentNetworkType: String = "unknown"

    private static let clickIdParams: Set<String> = [
        "gclid", "msclkid", "fbclid", "ttclid", "twclid",
        "li_fat_id", "rdt_cid", "scid", "dclid", "epik",
        "irclickid", "aff_id"
    ]

    private let serialQueue = DispatchQueue(label: "com.aether.sdk.serial")
    private let defaults = UserDefaults(suiteName: "com.aether.sdk")!
    private static let maxQueueSize = 500
    private static let sessionTimeoutSeconds: TimeInterval = 30 * 60
    private var lastActivityDate: Date?

    private override init() {
        super.init()
        startNetworkMonitor()
    }

    // MARK: - Public API

    public func initialize(config: AetherConfig) {
        guard !isInitialized else {
            log("Already initialized")
            return
        }

        self.config = config
        self.anonymousId = loadOrCreateAnonymousId()
        self.walletAddress = defaults.string(forKey: "walletAddress")
        self.consentState = defaults.stringArray(forKey: "consentState") ?? []
        self.userId = defaults.string(forKey: "userId")
        self.sessionId = UUID().uuidString
        self.sessionStart = Date()

        // Setup flush timer
        flushTimer = Timer.scheduledTimer(withTimeInterval: config.flushInterval, repeats: true) { [weak self] _ in
            self?.flush()
        }

        // Setup lifecycle observers
        setupLifecycleObservers()

        // Auto screen tracking via swizzling
        if config.modules.screenTracking {
            UIViewController.swizzleViewDidAppear()
        }

        self.fingerprintId = DeviceFingerprint.generate()

        // Request App Tracking Transparency authorization if required (iOS 14.5+)
        if config.privacy.respectATT {
            requestTrackingAuthorization()
        }

        isInitialized = true
        log("Aether iOS SDK initialized (v7.0.0)")

        fetchConfig()
        emitSessionStart()

        // MetricKit: subscribe for diagnostic/performance payloads (iOS 13+)
        MXMetricManager.shared.add(self)

        if config.autoResumeJourney {
            resolveIdentity(walletAddress: walletAddress, userId: nil, email: nil)
        }
    }

    public func track(_ event: String, properties: [String: AnyCodable] = [:]) {
        enqueueEvent(type: .track, properties: ["event": AnyCodable(event)].merging(properties) { _, new in new })
    }

    public func screenView(_ screenName: String, properties: [String: AnyCodable] = [:]) {
        screenCount += 1
        enqueueEvent(type: .screen, properties: ["screen": AnyCodable(screenName)].merging(properties) { _, new in new })
    }

    public func conversion(_ event: String, value: Double? = nil, properties: [String: AnyCodable] = [:]) {
        var props = properties
        props["event"] = AnyCodable(event)
        if let value = value { props["value"] = AnyCodable(value) }
        enqueueEvent(type: .conversion, properties: props)
    }

    public func hydrateIdentity(_ data: IdentityData) {
        let priorUserId = self.userId
        let priorEmail = self.email
        if let userId = data.userId { self.userId = userId }
        if let em = data.email { self.email = em }
        if let traits = data.traits { self.traits.merge(traits) { _, new in new } }
        if let addr = data.walletAddress {
            walletAddress = addr
            defaults.set(addr, forKey: "walletAddress")
        }
        // Multi-wallet: connect each as a proper wallet event
        for w in data.wallets {
            walletConnected(address: w.address, walletType: w.walletType, chainId: w.chainId)
        }

        enqueueEvent(type: .identify, properties: [
            "userId":       AnyCodable(userId ?? ""),
            "traits":       AnyCodable(traits),
            "walletAddress": AnyCodable(data.walletAddress ?? ""),
            "walletsCount": AnyCodable(data.wallets.count),
            "wallets": AnyCodable(data.wallets.map { ["address": $0.address, "vm": $0.vm, "walletType": $0.walletType] }),
        ])

        defaults.set(userId, forKey: "userId")

        // Cross-device: fire resolve when userId or email just became known
        if config?.autoResumeJourney == true {
            let uidChanged = self.userId != nil && self.userId != priorUserId
            let emailChanged = self.email != nil && self.email != priorEmail
            if uidChanged || emailChanged {
                resolveIdentity(walletAddress: walletAddress, userId: self.userId, email: self.email)
            }
        }
    }

    public func getAnonymousId() -> String { anonymousId }
    public func getUserId() -> String? { userId }
    public func getFingerprintId() -> String { fingerprintId }

    public func reset() {
        flush()
        userId = nil
        walletAddress = nil
        traits = [:]
        consentState = []
        anonymousId = UUID().uuidString
        sessionId = UUID().uuidString
        defaults.removeObject(forKey: "userId")
        defaults.removeObject(forKey: "walletAddress")
        defaults.removeObject(forKey: "consentState")
        defaults.set(anonymousId, forKey: "anonymousId")
        log("SDK reset")
    }

    public func flush() {
        serialQueue.async { [weak self] in
            self?.sendBatch()
        }
    }

    // MARK: - Deep Link Attribution

    public func handleDeepLink(_ url: URL) {
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        var attribution: [String: AnyCodable] = ["url": AnyCodable(url.absoluteString)]
        var clickIds: [String: String] = [:]

        for item in components?.queryItems ?? [] {
            if item.name.hasPrefix("utm_") {
                attribution[item.name] = AnyCodable(item.value ?? "")
            }
            if Self.clickIdParams.contains(item.name), let val = item.value {
                clickIds[item.name] = val
                attribution[item.name] = AnyCodable(val)
            }
        }

        // Store campaign info for inclusion in event context
        self.campaignInfo = EventContext.CampaignInfo(
            source: attribution["utm_source"]?.value as? String,
            medium: attribution["utm_medium"]?.value as? String,
            campaign: attribution["utm_campaign"]?.value as? String,
            content: attribution["utm_content"]?.value as? String,
            term: attribution["utm_term"]?.value as? String,
            clickIds: clickIds,
            referrerDomain: components?.host
        )

        track("deep_link_opened", properties: attribution)
    }

    // MARK: - Push Notification

    public func trackPushOpened(userInfo: [AnyHashable: Any]) {
        var props: [String: AnyCodable] = [:]
        if let campaignId = userInfo["campaign_id"] as? String {
            props["campaignId"] = AnyCodable(campaignId)
        }
        track("push_notification_opened", properties: props)
    }

    // MARK: - Wallet Tracking

    public func walletConnected(address: String, walletType: String? = nil, chainId: String? = nil) {
        walletAddress = address
        defaults.set(address, forKey: "walletAddress")
        enqueueEvent(type: .wallet, properties: [
            "action": AnyCodable("connect"),
            "address": AnyCodable(address),
            "walletType": AnyCodable(walletType ?? "unknown"),
            "chainId": AnyCodable(chainId ?? "unknown")
        ])
        if config?.autoResumeJourney == true {
            resolveIdentity(walletAddress: address, userId: userId, email: email)
        }
    }

    public func walletDisconnected(address: String) {
        enqueueEvent(type: .wallet, properties: [
            "action": AnyCodable("disconnect"),
            "address": AnyCodable(address)
        ])
    }

    public func walletTransaction(txHash: String, chainId: String, value: String? = nil, properties: [String: AnyCodable]? = nil) {
        var props: [String: AnyCodable] = [
            "action": AnyCodable("transaction"),
            "txHash": AnyCodable(txHash),
            "chainId": AnyCodable(chainId)
        ]
        if let value = value { props["value"] = AnyCodable(value) }
        if let extra = properties { props.merge(extra) { _, new in new } }
        enqueueEvent(type: .transaction, properties: props)
    }

    // MARK: - Consent Management
    //
    // Canonical purposes (see packages/shared/consent.ts):
    //   "analytics", "marketing", "web3", "agent", "commerce"
    // Callers SHOULD only pass these strings. Backend validator ignores others.

    public static let canonicalConsentPurposes: [String] =
        ["analytics", "marketing", "web3", "agent", "commerce"]

    public func grantConsent(categories: [String]) {
        consentState = Array(Set(consentState + categories))
        defaults.set(consentState, forKey: "consentState")
        enqueueEvent(type: .consent, properties: [
            "action": AnyCodable("grant"),
            "categories": AnyCodable(categories)
        ])
    }

    public func revokeConsent(categories: [String]) {
        consentState = consentState.filter { !categories.contains($0) }
        defaults.set(consentState, forKey: "consentState")
        enqueueEvent(type: .consent, properties: [
            "action": AnyCodable("revoke"),
            "categories": AnyCodable(categories)
        ])
    }

    public func getConsentState() -> [String] { return consentState }

    // MARK: - Ecommerce

    public func trackProductView(_ product: [String: AnyCodable]) {
        enqueueEvent(type: .track, properties: [
            "event": AnyCodable("product_viewed"),
            "product": AnyCodable(product)
        ])
    }

    public func trackAddToCart(_ item: [String: AnyCodable]) {
        enqueueEvent(type: .track, properties: [
            "event": AnyCodable("product_added"),
            "item": AnyCodable(item)
        ])
    }

    public func trackPurchase(orderId: String, total: Double, currency: String = "USD", items: [[String: AnyCodable]]? = nil) {
        var props: [String: AnyCodable] = [
            "event": AnyCodable("order_completed"),
            "orderId": AnyCodable(orderId),
            "total": AnyCodable(total),
            "currency": AnyCodable(currency)
        ]
        if let items = items { props["items"] = AnyCodable(items) }
        enqueueEvent(type: .conversion, properties: props)
    }

    // MARK: - Feature Flags (from server config)

    public func isFeatureEnabled(_ key: String, default defaultValue: Bool = false) -> Bool {
        guard let flags = serverConfig["featureFlags"] as? [String: Any],
              let value = flags[key] as? Bool else { return defaultValue }
        return value
    }

    public func getFeatureValue(_ key: String, default defaultValue: Any? = nil) -> Any? {
        guard let flags = serverConfig["featureFlags"] as? [String: Any] else { return defaultValue }
        return flags[key] ?? defaultValue
    }

    // MARK: - Private

    private func enqueueEvent(type: AetherEventType, properties: [String: AnyCodable]) {
        guard isInitialized else { return }

        let event = AetherEvent(
            id: UUID().uuidString,
            type: type,
            timestamp: ISO8601DateFormatter().string(from: Date()),
            sessionId: sessionId,
            anonymousId: anonymousId,
            userId: userId,
            properties: properties,
            context: buildContext()
        )

        serialQueue.async { [weak self] in
            guard let self = self else { return }
            // Enforce max queue size
            while self.eventQueue.count >= Aether.maxQueueSize { self.eventQueue.removeFirst() }
            self.eventQueue.append(event)
            self.eventCount += 1
            if let batchSize = self.config?.batchSize, self.eventQueue.count >= batchSize {
                self.sendBatch()
            }
        }
    }

    private func sendBatch() {
        guard !eventQueue.isEmpty, let config = config else { return }

        let batch = Array(eventQueue.prefix(config.batchSize))
        eventQueue.removeFirst(min(batch.count, eventQueue.count))

        sendBatchWithRetry(batch: batch, config: config, retryCount: 0)
    }

    private func sendBatchWithRetry(batch: [AetherEvent], config: AetherConfig, retryCount: Int) {
        let maxRetries = 3
        guard let url = URL(string: "\(config.endpoint)/v1/batch") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("ios", forHTTPHeaderField: "X-Aether-SDK")
        request.timeoutInterval = 10.0

        let encodedBatch = batch.map { try? JSONEncoder().encode($0) }
            .compactMap { $0 }
            .map { try? JSONSerialization.jsonObject(with: $0) }
            .compactMap { $0 }
        let payload: [String: Any] = ["batch": encodedBatch, "sentAt": ISO8601DateFormatter().string(from: Date())]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            guard let self = self else { return }
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0

            if let error = error {
                self.log("Batch send failed: \(error.localizedDescription)")
                if retryCount < maxRetries {
                    let delay = min(pow(2.0, Double(retryCount)), 30.0)
                    DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                } else {
                    self.serialQueue.async { self.eventQueue.insert(contentsOf: batch, at: 0) }
                }
            } else if statusCode == 429 {
                let retryAfter = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Retry-After")
                    .flatMap { Double($0) } ?? 5.0
                if retryCount < maxRetries {
                    DispatchQueue.global().asyncAfter(deadline: .now() + retryAfter) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                }
            } else if statusCode >= 500 {
                if retryCount < maxRetries {
                    let delay = min(pow(2.0, Double(retryCount)), 30.0)
                    DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                } else {
                    self.log("Batch dropped after \(maxRetries) retries (server error \(statusCode))")
                }
            } else if statusCode >= 400 {
                self.log("Batch rejected (client error \(statusCode)) — not retrying")
            }
        }.resume()
    }

    private func fetchConfig() {
        guard let url = URL(string: "\(config?.endpoint ?? "")/v1/config?apiKey=\(config?.apiKey ?? "")") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            self?.serialQueue.async {
                self?.serverConfig = json
                if self?.config?.debug == true { self?.log("Config loaded") }
            }
        }.resume()
    }

    private func buildContext() -> EventContext {
        let granted = Set(consentState)
        return EventContext(
            library: .init(name: "aether-ios", version: "7.0.0"),
            device: .init(
                osName: "iOS",
                osVersion: UIDevice.current.systemVersion,
                locale: Locale.current.identifier,
                timezone: TimeZone.current.identifier
            ),
            campaign: self.campaignInfo,
            fingerprint: .init(id: self.fingerprintId),
            network: currentNetworkType,
            thermalState: thermalStateString(),
            consent: [
                "analytics": granted.contains("analytics"),
                "marketing": granted.contains("marketing"),
                "web3": granted.contains("web3"),
                "agent": granted.contains("agent"),
                "commerce": granted.contains("commerce"),
            ]
        )
    }

    private func emitSessionStart() {
        let startupMs = Int(Date().timeIntervalSince(appStartDate) * 1000)
        let memoryUsedMB = memoryUsageMB()
        enqueueEvent(type: .track, properties: [
            "event":          AnyCodable("session_start"),
            "startupTimeMs":  AnyCodable(startupMs),
            "memoryUsedMB":   AnyCodable(memoryUsedMB),
            "thermalState":   AnyCodable(thermalStateString()),
            "networkType":    AnyCodable(currentNetworkType),
            "osVersion":      AnyCodable(UIDevice.current.systemVersion),
            "device":         AnyCodable(UIDevice.current.model),
        ])
    }

    private func memoryUsageMB() -> Int {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size) / 4
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return 0 }
        return Int(info.resident_size / 1048576)
    }

    private func thermalStateString() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal:  return "nominal"
        case .fair:     return "fair"
        case .serious:  return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }

    private func requestTrackingAuthorization() {
        if #available(iOS 14.5, *) {
            // Must be called after the first UIApplicationDidBecomeActive
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                ATTrackingManager.requestTrackingAuthorization { [weak self] status in
                    let statusStr: String
                    switch status {
                    case .authorized:          statusStr = "authorized"
                    case .denied:              statusStr = "denied"
                    case .restricted:          statusStr = "restricted"
                    case .notDetermined:       statusStr = "not_determined"
                    @unknown default:          statusStr = "unknown"
                    }
                    self?.enqueueEvent(type: .track, properties: [
                        "event": AnyCodable("att_authorization"),
                        "status": AnyCodable(statusStr),
                        "idfa": AnyCodable(status == .authorized ? ASIdentifierManager.shared().advertisingIdentifier.uuidString : ""),
                    ])
                }
            }
        }
    }

    private func startNetworkMonitor() {
        networkMonitor.pathUpdateHandler = { [weak self] path in
            if path.usesInterfaceType(.wifi) { self?.currentNetworkType = "wifi" }
            else if path.usesInterfaceType(.cellular) { self?.currentNetworkType = "cellular" }
            else if path.usesInterfaceType(.wiredEthernet) { self?.currentNetworkType = "ethernet" }
            else if path.status == .satisfied { self?.currentNetworkType = "other" }
            else { self?.currentNetworkType = "none" }
        }
        networkMonitor.start(queue: DispatchQueue(label: "com.aether.sdk.network"))
    }

    private func loadOrCreateAnonymousId() -> String {
        if let stored = defaults.string(forKey: "anonymousId") {
            return stored
        }
        let id = UUID().uuidString
        defaults.set(id, forKey: "anonymousId")
        return id
    }

    private func setupLifecycleObservers() {
        NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.flush()
        }
        NotificationCenter.default.addObserver(forName: UIApplication.willTerminateNotification, object: nil, queue: .main) { [weak self] _ in
            self?.flush()
        }
        NotificationCenter.default.addObserver(forName: UIApplication.willEnterForegroundNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self = self else { return }
            let now = Date()
            let elapsed = self.lastActivityDate.map { now.timeIntervalSince($0) } ?? (Aether.sessionTimeoutSeconds + 1)
            if elapsed > Aether.sessionTimeoutSeconds {
                self.sessionId = UUID().uuidString
                self.sessionStart = now
            }
            self.lastActivityDate = now
            self.track("app_foreground")
        }
        NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.lastActivityDate = Date()
        }
    }

    private func sha256(_ string: String) -> String {
        let data = Data(string.lowercased().utf8)
        let hash = SHA256.hash(data: data)
        return hash.compactMap { String(format: "%02x", $0) }.joined()
    }

    private func resolveIdentity(walletAddress addr: String?, userId uid: String?, email: String?) {
        guard let cfg = config,
              let url = URL(string: "\(cfg.endpoint)/sdk/identity/resolve") else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(cfg.apiKey, forHTTPHeaderField: "x-api-key")
        request.timeoutInterval = 5.0

        var wallets: [[String: String]] = []
        if let address = addr, !address.isEmpty {
            wallets = [["address": address, "vm": "evm"]]
        }
        var body: [String: Any] = [
            "wallets": wallets,
            "anonymous_id": anonymousId,
            "device_fingerprint": fingerprintId,
            "platform": "ios",
        ]
        if let uid = uid { body["user_id"] = uid }
        if let em = email, !em.isEmpty { body["email_hash"] = sha256(em.trimmingCharacters(in: .whitespaces)) }
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            guard let self = self,
                  let data = data,
                  let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let resolved = json["resolved"] as? Bool, resolved,
                  let identity = json["identity"] as? [String: Any] else { return }

            let resolvedAnonymousId = identity["anonymous_id"] as? String ?? ""
            let resolvedUserId = identity["user_id"] as? String

            guard !resolvedAnonymousId.isEmpty, resolvedAnonymousId != self.anonymousId else { return }

            self.serialQueue.async {
                if let uid = resolvedUserId {
                    self.userId = uid
                    self.defaults.set(uid, forKey: "userId")
                }
                self.enqueueEvent(type: .track, properties: [
                    "event": AnyCodable("journey_resumed"),
                    "resolvedAnonymousId": AnyCodable(resolvedAnonymousId),
                    "resolvedUserId": AnyCodable(resolvedUserId ?? "")
                ])
                self.log("Journey resumed from prior device")
                cfg.onJourneyResumed?(resolvedAnonymousId, resolvedUserId)
            }
        }.resume()
    }

    private func log(_ message: String) {
        guard config?.debug == true else { return }
        print("[Aether SDK] \(message)")
    }
}

// MARK: - MetricKit Delegate

extension Aether: MXMetricManagerSubscriber {
    public func didReceive(_ payloads: [MXMetricPayload]) {
        for payload in payloads {
            var props: [String: AnyCodable] = [
                "event":        AnyCodable("metrickit_payload"),
                "appVersion":   AnyCodable(payload.metaData?.applicationBuildNumber ?? ""),
                "periodStart":  AnyCodable(ISO8601DateFormatter().string(from: payload.timeStampBegin)),
                "periodEnd":    AnyCodable(ISO8601DateFormatter().string(from: payload.timeStampEnd)),
            ]

            if let launch = payload.applicationLaunchMetrics {
                props["resumeTimeP50Ms"]   = AnyCodable(launch.applicationResumeTime.histogram.buckets.first?.averageValue.converted(to: .milliseconds).value ?? 0)
                props["coldLaunchTimeP50Ms"] = AnyCodable(launch.timeToFirstDrawKey.histogram.buckets.first?.averageValue.converted(to: .milliseconds).value ?? 0)
            }
            if let hang = payload.applicationResponsivenessMetrics {
                props["hangRatePerHour"] = AnyCodable(hang.hangRate.averageValue.value)
            }
            if let cpu = payload.cpuMetrics {
                props["cpuTimePerSecond"] = AnyCodable(cpu.cumulativeCPUTime.converted(to: .seconds).value)
            }
            if let mem = payload.memoryMetrics {
                props["peakMemoryMB"] = AnyCodable(mem.peakMemoryUsage.converted(to: .megabytes).value)
            }
            if let network = payload.networkTransferMetrics {
                props["wifiUploadMB"]   = AnyCodable(network.cumulativeWifiUpload.converted(to: .megabytes).value)
                props["wifiDownloadMB"] = AnyCodable(network.cumulativeWifiDownload.converted(to: .megabytes).value)
                props["cellUploadMB"]   = AnyCodable(network.cumulativeCellularUpload.converted(to: .megabytes).value)
                props["cellDownloadMB"] = AnyCodable(network.cumulativeCellularDownload.converted(to: .megabytes).value)
            }
            if let disk = payload.diskIOMetrics {
                props["diskWritesMB"] = AnyCodable(disk.cumulativeLogicalWrites.converted(to: .megabytes).value)
            }

            enqueueEvent(type: .track, properties: props)
        }
    }

    public func didReceive(_ payloads: [MXDiagnosticPayload]) {
        for payload in payloads {
            var props: [String: AnyCodable] = [
                "event":      AnyCodable("metrickit_diagnostic"),
                "appVersion": AnyCodable(payload.metaData?.applicationBuildNumber ?? ""),
            ]
            if let crashes = payload.crashDiagnostics, !crashes.isEmpty {
                props["crashCount"] = AnyCodable(crashes.count)
                props["crashType"]  = AnyCodable(crashes.first?.exceptionType ?? "unknown")
            }
            if let hangs = payload.hangDiagnostics, !hangs.isEmpty {
                props["hangCount"]          = AnyCodable(hangs.count)
                props["hangDurationMs"]     = AnyCodable(hangs.first?.hangDuration.converted(to: .milliseconds).value ?? 0)
            }
            enqueueEvent(type: .track, properties: props)
        }
    }
}

// MARK: - UIViewController Swizzling for Auto Screen Tracking

extension UIViewController {
    static var hasSwizzled = false

    static func swizzleViewDidAppear() {
        guard !hasSwizzled else { return }
        hasSwizzled = true

        let originalSelector = #selector(UIViewController.viewDidAppear(_:))
        let swizzledSelector = #selector(UIViewController.aether_viewDidAppear(_:))

        guard let originalMethod = class_getInstanceMethod(UIViewController.self, originalSelector),
              let swizzledMethod = class_getInstanceMethod(UIViewController.self, swizzledSelector) else { return }

        method_exchangeImplementations(originalMethod, swizzledMethod)
    }

    @objc func aether_viewDidAppear(_ animated: Bool) {
        aether_viewDidAppear(animated) // Calls original

        let screenName = String(describing: type(of: self))
        let ignoredPrefixes = ["UI", "_", "NS"]
        if !ignoredPrefixes.contains(where: { screenName.hasPrefix($0) }) {
            Aether.shared.screenView(screenName)
        }
    }
}

// MARK: - AnyCodable Helper

public struct AnyCodable: Codable {
    public let value: Any

    public init(_ value: Any) { self.value = value }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let v = try? container.decode(String.self) { value = v }
        else if let v = try? container.decode(Int.self) { value = v }
        else if let v = try? container.decode(Double.self) { value = v }
        else if let v = try? container.decode(Bool.self) { value = v }
        else if let v = try? container.decode([String: AnyCodable].self) { value = v }
        else if let v = try? container.decode([AnyCodable].self) { value = v }
        else { value = "" }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case let v as String: try container.encode(v)
        case let v as Int: try container.encode(v)
        case let v as Double: try container.encode(v)
        case let v as Bool: try container.encode(v)
        case let v as [String: AnyCodable]: try container.encode(v)
        case let v as [AnyCodable]: try container.encode(v)
        default: try container.encode(String(describing: value))
        }
    }
}
