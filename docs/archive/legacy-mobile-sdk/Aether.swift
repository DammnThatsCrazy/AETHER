// =============================================================================
// Aether SDK — iOS (Swift)
// Core analytics, identity, session, consent, Web3 tracking
// =============================================================================

import Foundation
import UIKit

// MARK: - Configuration

public struct AetherConfig {
    public let apiKey: String
    public var environment: Environment = .production
    public var debug: Bool = false
    public var endpoint: String = "https://api.aether.network"
    public var modules: ModuleConfig = ModuleConfig()
    public var privacy: PrivacyConfig = PrivacyConfig()
    public var batchSize: Int = 10
    public var flushInterval: TimeInterval = 5.0
    
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
    public var walletTracking: Bool = false
    public var purchaseTracking: Bool = true
    public var errorTracking: Bool = true
    public var experiments: Bool = true
}

public struct PrivacyConfig {
    public var gdprMode: Bool = false
    public var anonymizeIP: Bool = true
    public var respectATT: Bool = true
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
    
    public struct LibraryInfo: Codable {
        public let name: String
        public let version: String
    }
    
    public struct DeviceInfo: Codable {
        public let type: String
        public let os: String
        public let osVersion: String
        public let model: String
        public let manufacturer: String
        public let screenWidth: Int
        public let screenHeight: Int
        public let language: String
        public let timezone: String
    }
    
    public struct CampaignInfo: Codable {
        public var source: String?
        public var medium: String?
        public var campaign: String?
    }
}

// MARK: - Identity

public struct IdentityData {
    public var userId: String?
    public var walletAddress: String?
    public var walletType: String?
    public var chainId: Int?
    public var traits: [String: AnyCodable]?
    
    public init(userId: String? = nil, walletAddress: String? = nil, traits: [String: AnyCodable]? = nil) {
        self.userId = userId
        self.walletAddress = walletAddress
        self.traits = traits
    }
}

// MARK: - Main SDK Class

public final class Aether {
    public static let shared = Aether()
    
    private var config: AetherConfig?
    private var eventQueue: [AetherEvent] = []
    private var sessionId: String = UUID().uuidString
    private var anonymousId: String = ""
    private var userId: String?
    private var traits: [String: AnyCodable] = [:]
    private var flushTimer: Timer?
    private var sessionStart: Date = Date()
    private var screenCount: Int = 0
    private var eventCount: Int = 0
    private var isInitialized = false
    
    private let serialQueue = DispatchQueue(label: "com.aether.sdk.serial")
    private let defaults = UserDefaults(suiteName: "com.aether.sdk")!
    
    private init() {}
    
    // MARK: - Public API
    
    public func initialize(config: AetherConfig) {
        guard !isInitialized else {
            log("Already initialized")
            return
        }
        
        self.config = config
        self.anonymousId = loadOrCreateAnonymousId()
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
        
        // Start semantic context collector
        SemanticContextCollector.shared.resetSession()

        // Initialize Web2 modules
        AetherEcommerce.shared.initialize(
            apiKey: config.apiKey,
            endpoint: config.endpoint
        )
        AetherFeatureFlags.shared.initialize(
            apiKey: config.apiKey,
            endpoint: config.endpoint
        )
        AetherFeedback.shared.initialize(
            apiKey: config.apiKey,
            endpoint: config.endpoint,
            userId: anonymousId
        )

        isInitialized = true
        log("Aether iOS SDK initialized (v5.0.0) — Web2 + Web3 modules enabled")

        // Start OTA data module update manager (non-blocking, background)
        AetherUpdateManager.shared.start(
            apiKey: config.apiKey,
            endpoint: config.endpoint,
            currentVersion: "5.0.0"
        )
    }
    
    public func track(_ event: String, properties: [String: AnyCodable] = [:]) {
        enqueueEvent(type: .track, properties: ["event": AnyCodable(event)].merging(properties) { _, new in new })
    }
    
    public func screenView(_ screenName: String, properties: [String: AnyCodable] = [:]) {
        screenCount += 1
        SemanticContextCollector.shared.recordScreen(screenName)
        enqueueEvent(type: .screen, properties: ["screen": AnyCodable(screenName)].merging(properties) { _, new in new })
    }
    
    public func conversion(_ event: String, value: Double? = nil, properties: [String: AnyCodable] = [:]) {
        var props = properties
        props["event"] = AnyCodable(event)
        if let value = value { props["value"] = AnyCodable(value) }
        enqueueEvent(type: .conversion, properties: props)
    }
    
    public func hydrateIdentity(_ data: IdentityData) {
        if let userId = data.userId { self.userId = userId }
        if let traits = data.traits { self.traits.merge(traits) { _, new in new } }
        
        enqueueEvent(type: .identify, properties: [
            "userId": AnyCodable(userId ?? ""),
            "traits": AnyCodable(traits),
            "walletAddress": AnyCodable(data.walletAddress ?? "")
        ])
        
        // Persist
        defaults.set(userId, forKey: "userId")
    }
    
    public func getAnonymousId() -> String { anonymousId }
    public func getUserId() -> String? { userId }
    
    public func reset() {
        flush()
        userId = nil
        traits = [:]
        anonymousId = UUID().uuidString
        sessionId = UUID().uuidString
        defaults.removeObject(forKey: "userId")
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
        
        for item in components?.queryItems ?? [] {
            if item.name.hasPrefix("utm_") || item.name == "gclid" || item.name == "fbclid" {
                attribution[item.name] = AnyCodable(item.value ?? "")
            }
        }
        
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
    
    // MARK: - Private
    
    private func enqueueEvent(type: AetherEventType, properties: [String: AnyCodable]) {
        guard isInitialized else { return }
        
        var enrichedProperties = properties
        // Inject tiered semantic context into every event
        if let semanticData = try? JSONEncoder().encode(SemanticContextCollector.shared.collect()),
           let semanticDict = try? JSONSerialization.jsonObject(with: semanticData) as? [String: Any] {
            enrichedProperties["_semantic"] = AnyCodable(semanticDict)
        }

        let event = AetherEvent(
            id: UUID().uuidString,
            type: type,
            timestamp: ISO8601DateFormatter().string(from: Date()),
            sessionId: sessionId,
            anonymousId: anonymousId,
            userId: userId,
            properties: enrichedProperties,
            context: buildContext()
        )
        
        serialQueue.async { [weak self] in
            self?.eventQueue.append(event)
            if let batchSize = self?.config?.batchSize, (self?.eventQueue.count ?? 0) >= batchSize {
                self?.sendBatch()
            }
        }
        
        eventCount += 1
    }
    
    private func sendBatch() {
        guard !eventQueue.isEmpty, let config = config else { return }
        
        let batch = Array(eventQueue.prefix(config.batchSize))
        eventQueue.removeFirst(min(batch.count, eventQueue.count))
        
        guard let url = URL(string: "\(config.endpoint)/v1/batch") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("ios", forHTTPHeaderField: "X-Aether-SDK")
        
        let payload: [String: Any] = [
            "batch": batch.map { try? JSONEncoder().encode($0) }.compactMap { $0 }.map { try? JSONSerialization.jsonObject(with: $0) }.compactMap { $0 },
            "sentAt": ISO8601DateFormatter().string(from: Date())
        ]
        
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        
        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            if let error = error {
                self?.log("Batch send failed: \(error.localizedDescription)")
                // Re-enqueue failed events
                self?.serialQueue.async {
                    self?.eventQueue.insert(contentsOf: batch, at: 0)
                }
            } else if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode >= 400 {
                self?.log("Batch send HTTP error: \(httpResponse.statusCode)")
            }
        }.resume()
    }
    
    private func buildContext() -> EventContext {
        let device = UIDevice.current
        let screen = UIScreen.main
        
        return EventContext(
            library: .init(name: "AetherSDK-iOS", version: "5.0.0"),
            device: .init(
                type: device.userInterfaceIdiom == .pad ? "tablet" : "mobile",
                os: "iOS",
                osVersion: device.systemVersion,
                model: device.model,
                manufacturer: "Apple",
                screenWidth: Int(screen.bounds.width * screen.scale),
                screenHeight: Int(screen.bounds.height * screen.scale),
                language: Locale.current.language.languageCode?.identifier ?? "en",
                timezone: TimeZone.current.identifier
            )
        )
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
            self?.sessionId = UUID().uuidString
            self?.sessionStart = Date()
            self?.track("app_foreground")
        }
    }
    
    private func log(_ message: String) {
        guard config?.debug == true else { return }
        print("[Aether SDK] \(message)")
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
