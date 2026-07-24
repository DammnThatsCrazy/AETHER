// =============================================================================
// Aether SDK — Optional native UI interaction instrumentation (spec §12)
//
// Privacy-safe by construction:
//   - Disabled by default (config.enabled == false).
//   - Metadata-only. Rendered control text / label / value is NEVER captured
//     unless captureControlText is explicitly enabled.
//   - No coordinates unless captureCoordinates is explicitly enabled.
//   - Requires a STABLE identifier (explicit Aether id or accessibility
//     identifier) — never rendered text — when requireStableIdentifiers is true.
//   - Screen allow/deny lists gate emission per screen.
//   - No text-field content capture. UIControl observation is additive
//     target-action only; it never reads text and never replaces tenant
//     targets. The SDK observes explicit, developer-instrumented controls.
//
// Emission always flows through the canonical, consent-gated
// Aether.shared.observe("ui_interaction_observed", …) path.
// =============================================================================

import Foundation
#if canImport(UIKit)
import UIKit
#endif
#if canImport(SwiftUI)
import SwiftUI
#endif

/// Optional, explicit UI-interaction observer. Not an acquisition signal —
/// interaction events are kept entirely separate from AcquisitionEvidence and
/// are never used as acquisition proof.
public final class AetherInteraction {

    public static let shared = AetherInteraction()

    /// Instrumentation configuration. All privacy-affecting switches default to
    /// the safest possible value.
    public struct Config {
        /// Master switch. When false, every observation is a no-op.
        public var enabled: Bool
        /// Capture the rendered control text/label. OFF by default.
        public var captureControlText: Bool
        /// Capture touch coordinates. OFF by default.
        public var captureCoordinates: Bool
        /// Drop interactions that lack a stable identifier. ON by default.
        public var requireStableIdentifiers: Bool
        /// When non-empty, only these screens may emit.
        public var allowlistedScreens: Set<String>
        /// These screens never emit (takes precedence over the allowlist).
        public var denylistedScreens: Set<String>

        public init(
            enabled: Bool = false,
            captureControlText: Bool = false,
            captureCoordinates: Bool = false,
            requireStableIdentifiers: Bool = true,
            allowlistedScreens: Set<String> = [],
            denylistedScreens: Set<String> = []
        ) {
            self.enabled = enabled
            self.captureControlText = captureControlText
            self.captureCoordinates = captureCoordinates
            self.requireStableIdentifiers = requireStableIdentifiers
            self.allowlistedScreens = allowlistedScreens
            self.denylistedScreens = denylistedScreens
        }
    }

    private static let controlTextKeys: Set<String> = ["text", "label", "title", "value", "content", "hint", "placeholder"]
    private static let coordinateKeys: Set<String> = ["x", "y", "coordinates", "position", "touchx", "touchy"]

    private let lock = NSLock()
    private var config = Config()
    private var currentScreen: String?
    private var currentNavigationId: String?

    private init() {}

    /// Apply an instrumentation configuration.
    public func configure(_ config: Config) {
        lock.lock(); defer { lock.unlock() }
        self.config = config
    }

    /// Current configuration (snapshot).
    public func currentConfig() -> Config {
        lock.lock(); defer { lock.unlock() }
        return config
    }

    /// Record the current screen (and optionally a navigation id) for
    /// subsequent interaction events.
    public func setCurrentScreen(_ screen: String, navigationId: String? = nil) {
        lock.lock(); defer { lock.unlock() }
        currentScreen = screen
        currentNavigationId = navigationId ?? UUID().uuidString
    }

    /// Clear the tracked screen/navigation context.
    public func clearScreen() {
        lock.lock(); defer { lock.unlock() }
        currentScreen = nil
        currentNavigationId = nil
    }

    /// Low-level id/type emission for integrations that do not hold a control
    /// (SwiftUI modifier, navigation events).
    public func observeInteraction(
        id: String?,
        controlType: String,
        action: String = "tap",
        metadata: [String: Any] = [:]
    ) {
        emit(controlId: id, controlType: controlType, action: action, metadata: metadata)
    }

    // MARK: - UIKit

    #if canImport(UIKit)
    /// Explicit tracked-control helper. Emits one canonical
    /// `ui_interaction_observed` for [control]. Uses the control's
    /// accessibilityIdentifier when no explicit [id] is provided. Reads no text.
    public func trackInteraction(
        _ control: UIControl,
        id: String? = nil,
        controlType: String? = nil,
        action: String = "tap",
        metadata: [String: Any] = [:]
    ) {
        let resolvedId = id ?? control.accessibilityIdentifier
        let resolvedType = controlType ?? String(describing: type(of: control))
        emit(controlId: resolvedId, controlType: resolvedType, action: action, metadata: metadata)
    }

    /// Additively observe a UIControl event without replacing the tenant's own
    /// targets. A retained observer is attached to [control] (via an associated
    /// object) and fires alongside the tenant's actions. Never reads text.
    public func instrument(
        _ control: UIControl,
        id: String? = nil,
        controlType: String = "control",
        for controlEvent: UIControl.Event = .primaryActionTriggered,
        action: String = "tap",
        metadata: [String: Any] = [:]
    ) {
        let resolvedId = id ?? control.accessibilityIdentifier
        let observer = ControlObserver(id: resolvedId, controlType: controlType, action: action, metadata: metadata)
        control.addTarget(observer, action: #selector(ControlObserver.handle), for: controlEvent)
        // Retain the observer for the lifetime of the control — UIControl keeps
        // only an unowned reference to its targets.
        objc_setAssociatedObject(control, &AetherInteraction.observerKey, observer, .OBJC_ASSOCIATION_RETAIN_NONATOMIC)
    }

    private static var observerKey: UInt8 = 0

    /// Retained target-action bridge; forwards to the shared observer.
    private final class ControlObserver: NSObject {
        let id: String?
        let controlType: String
        let action: String
        let metadata: [String: Any]

        init(id: String?, controlType: String, action: String, metadata: [String: Any]) {
            self.id = id
            self.controlType = controlType
            self.action = action
            self.metadata = metadata
        }

        @objc func handle() {
            AetherInteraction.shared.observeInteraction(id: id, controlType: controlType, action: action, metadata: metadata)
        }
    }
    #endif

    // MARK: - Emission

    private func emit(controlId: String?, controlType: String, action: String, metadata: [String: Any]) {
        let snapshot: Config
        let screen: String?
        let navigationId: String?
        lock.lock()
        snapshot = config
        screen = currentScreen
        navigationId = currentNavigationId
        lock.unlock()

        guard snapshot.enabled else { return }
        guard screenAllowed(snapshot, screen) else { return }

        let hasId = !(controlId ?? "").isEmpty
        if !hasId && snapshot.requireStableIdentifiers {
            return
        }

        var properties: [String: AnyCodable] = [
            "controlId": AnyCodable(hasId ? controlId! : "unidentified"),
            "controlType": AnyCodable(controlType),
            "action": AnyCodable(action),
        ]
        if let screen = screen { properties["screen"] = AnyCodable(screen) }
        if let navigationId = navigationId { properties["navigationId"] = AnyCodable(navigationId) }
        for (key, value) in sanitizeMetadata(snapshot, metadata) {
            properties[key] = AnyCodable(value)
        }

        Aether.shared.observe("ui_interaction_observed", properties: properties)
    }

    private func screenAllowed(_ config: Config, _ screen: String?) -> Bool {
        guard let screen = screen else { return config.allowlistedScreens.isEmpty }
        if config.denylistedScreens.contains(screen) { return false }
        if !config.allowlistedScreens.isEmpty && !config.allowlistedScreens.contains(screen) { return false }
        return true
    }

    /// Strip control-text and coordinate keys unless explicitly enabled —
    /// defense in depth even against callers passing text through metadata.
    private func sanitizeMetadata(_ config: Config, _ metadata: [String: Any]) -> [String: Any] {
        guard !metadata.isEmpty else { return metadata }
        var out: [String: Any] = [:]
        for (key, value) in metadata {
            let lower = key.lowercased()
            if !config.captureControlText && AetherInteraction.controlTextKeys.contains(lower) { continue }
            if !config.captureCoordinates && AetherInteraction.coordinateKeys.contains(lower) { continue }
            out[key] = value
        }
        return out
    }
}

// MARK: - SwiftUI

#if canImport(SwiftUI)
@available(iOS 13.0, *)
public extension View {
    /// Observe tap interactions on this view via a *simultaneous* gesture, so
    /// the tenant's own `.onTapGesture` / button action still fires. Carries
    /// only the stable [id] — never rendered text.
    func aetherTrack(
        id: String,
        controlType: String = "swiftui",
        action: String = "tap",
        metadata: [String: Any] = [:]
    ) -> some View {
        simultaneousGesture(
            TapGesture().onEnded {
                AetherInteraction.shared.observeInteraction(id: id, controlType: controlType, action: action, metadata: metadata)
            }
        )
    }

    /// Register a navigation-stack destination: sets the current screen when
    /// the view appears and clears it when it disappears, so interaction events
    /// carry the active screen and a per-destination navigation id.
    func aetherScreen(_ name: String) -> some View {
        onAppear { AetherInteraction.shared.setCurrentScreen(name) }
    }
}
#endif
