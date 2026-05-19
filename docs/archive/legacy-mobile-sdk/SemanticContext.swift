// =============================================================================
// Aether SDK — iOS Tiered Semantic Context
// Enriches every event with layered context based on consent + configuration.
// Tier 1: Essential (always) → Tier 2: Functional → Tier 3: Rich
// =============================================================================

import Foundation
import UIKit

// MARK: - Types

public enum ContextTier: Int, Codable, Comparable {
    case essential = 1
    case functional = 2
    case rich = 3

    public static func < (lhs: ContextTier, rhs: ContextTier) -> Bool {
        lhs.rawValue < rhs.rawValue
    }
}

public struct Tier1Context: Codable {
    public let eventId: String
    public let timestamp: String
    public let sdkVersion: String
    public let platform: String
    public let device: Tier1Device

    public struct Tier1Device: Codable {
        public let type: String
        public let os: String
        public let language: String
        public let online: Bool
    }
}

public struct Tier2Context: Codable {
    public let journeyStage: String
    public let screenPath: [String]
    public let sessionDuration: Double
    public let appState: String
    public let screenDepth: Int
    public let eventSequenceIndex: Int
    public let entryPoint: String
}

public struct Tier3Context: Codable {
    public let inferredIntent: InferredIntent?
    public let sentimentSignals: SentimentSignals
    public let errorLog: ErrorLog

    public struct InferredIntent: Codable {
        public let action: String
        public let confidence: Double
        public let journeyPhase: String
    }

    public struct SentimentSignals: Codable {
        public let frustration: Double
        public let engagement: Double
        public let urgency: Double
        public let confusion: Double
    }

    public struct ErrorLog: Codable {
        public let errorCount: Int
        public let lastError: ErrorEntry?
        public let errorRate: Double

        public struct ErrorEntry: Codable {
            public let message: String
            public let type: String
            public let timestamp: String
        }
    }
}

public struct SemanticContextEnvelope: Codable {
    public let tier: Int
    public let t1: Tier1Context
    public let t2: Tier2Context?
    public let t3: Tier3Context?
}

// MARK: - Collector

public final class SemanticContextCollector {
    public static let shared = SemanticContextCollector()

    private let sdkVersion = "5.0.0"
    private let serialQueue = DispatchQueue(label: "com.aether.sdk.context")

    // Tier 2 state
    private var screenPath: [String] = []
    private var eventSequence: Int = 0
    private var sessionStartDate: Date = Date()
    private var entryPoint: String = ""
    private var screenDepth: Int = 0
    private var appState: String = "active"

    // Tier 3 state
    private var errorBuffer: [(message: String, type: String, timestamp: String)] = []
    private var backtrackCount: Int = 0
    private var sessionInteractionCount: Int = 0
    private var lastIntent: Tier3Context.InferredIntent? = nil

    // Consent
    private var analyticsConsent: Bool = false
    private var marketingConsent: Bool = false

    private init() {
        setupLifecycleObservers()
    }

    // MARK: - Public API

    public func collect() -> SemanticContextEnvelope {
        return serialQueue.sync {
            eventSequence += 1
            let tier = resolveTier()

            let t1 = collectTier1()
            let t2: Tier2Context? = tier >= .functional ? collectTier2() : nil
            let t3: Tier3Context? = tier >= .rich ? collectTier3() : nil

            return SemanticContextEnvelope(tier: tier.rawValue, t1: t1, t2: t2, t3: t3)
        }
    }

    public func recordScreen(_ name: String) {
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            if self.screenPath.count >= 2 && self.screenPath[self.screenPath.count - 2] == name {
                self.backtrackCount += 1
            }
            self.screenPath.append(name)
            if self.screenPath.count > 50 { self.screenPath = Array(self.screenPath.suffix(50)) }
            self.screenDepth += 1
        }
    }

    public func recordError(message: String, type: String) {
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            self.errorBuffer.append((message: message, type: type, timestamp: ISO8601DateFormatter().string(from: Date())))
            if self.errorBuffer.count > 100 { self.errorBuffer.removeFirst() }
        }
    }

    public func recordInteraction() {
        serialQueue.async { [weak self] in
            self?.sessionInteractionCount += 1
        }
    }

    public func updateConsent(analytics: Bool, marketing: Bool) {
        serialQueue.async { [weak self] in
            self?.analyticsConsent = analytics
            self?.marketingConsent = marketing
        }
    }

    public func resetSession() {
        serialQueue.async { [weak self] in
            self?.screenPath = []
            self?.eventSequence = 0
            self?.sessionStartDate = Date()
            self?.screenDepth = 0
            self?.backtrackCount = 0
            self?.sessionInteractionCount = 0
            self?.errorBuffer = []
        }
    }

    // MARK: - Tier Collectors

    private func collectTier1() -> Tier1Context {
        let device = UIDevice.current
        return Tier1Context(
            eventId: UUID().uuidString,
            timestamp: ISO8601DateFormatter().string(from: Date()),
            sdkVersion: sdkVersion,
            platform: "ios",
            device: .init(
                type: device.userInterfaceIdiom == .pad ? "tablet" : "mobile",
                os: "iOS \(device.systemVersion)",
                language: Locale.current.language.languageCode?.identifier ?? "en",
                online: true // Reachability would be injected in production
            )
        )
    }

    private func collectTier2() -> Tier2Context {
        let elapsed = Date().timeIntervalSince(sessionStartDate)
        return Tier2Context(
            journeyStage: inferJourneyStage(elapsed: elapsed),
            screenPath: Array(screenPath.suffix(20)),
            sessionDuration: elapsed * 1000,
            appState: appState,
            screenDepth: screenDepth,
            eventSequenceIndex: eventSequence,
            entryPoint: entryPoint.isEmpty ? (screenPath.first ?? "unknown") : entryPoint
        )
    }

    private func collectTier3() -> Tier3Context {
        let windowSeconds: Double = 300
        let recentErrors = errorBuffer.filter {
            guard let ts = ISO8601DateFormatter().date(from: $0.timestamp) else { return false }
            return Date().timeIntervalSince(ts) < windowSeconds
        }
        let errorRate = Double(recentErrors.count) / (windowSeconds / 60.0)

        let elapsed = Date().timeIntervalSince(sessionStartDate)
        let engagement = min(1.0, (Double(screenDepth) / 10.0) * 0.4 + min(elapsed / 120.0, 1.0) * 0.6)
        let frustration = min(1.0, Double(recentErrors.count) * 0.2 / 5.0)
        let confusion = min(1.0, Double(backtrackCount) * 0.4 / 3.0)
        let urgency = min(1.0, eventSequence > 0 ? (Double(screenDepth) / Double(eventSequence)) * 2.0 : 0)

        let lastErr: Tier3Context.ErrorLog.ErrorEntry? = errorBuffer.last.map {
            .init(message: $0.message, type: $0.type, timestamp: $0.timestamp)
        }

        return Tier3Context(
            inferredIntent: lastIntent,
            sentimentSignals: .init(
                frustration: (frustration * 1000).rounded() / 1000,
                engagement: (engagement * 1000).rounded() / 1000,
                urgency: (urgency * 1000).rounded() / 1000,
                confusion: (confusion * 1000).rounded() / 1000
            ),
            errorLog: .init(
                errorCount: errorBuffer.count,
                lastError: lastErr,
                errorRate: (errorRate * 100).rounded() / 100
            )
        )
    }

    // MARK: - Helpers

    private func resolveTier() -> ContextTier {
        if analyticsConsent && marketingConsent { return .rich }
        if analyticsConsent { return .functional }
        return .essential
    }

    private func inferJourneyStage(elapsed: TimeInterval) -> String {
        if elapsed < 10 && screenDepth <= 1 { return "new" }
        if screenDepth > 5 || elapsed > 180 { return "engaged" }
        return "returning"
    }

    private func setupLifecycleObservers() {
        NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            self?.serialQueue.async { self?.appState = "active" }
        }
        NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.serialQueue.async { self?.appState = "background" }
        }
        NotificationCenter.default.addObserver(forName: UIApplication.willResignActiveNotification, object: nil, queue: .main) { [weak self] _ in
            self?.serialQueue.async { self?.appState = "inactive" }
        }
    }
}
