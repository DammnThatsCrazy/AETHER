import Foundation

/// Automation evidence for actor classification (`context.device.automation`).
///
/// Presence-only booleans. Accessibility state (VoiceOver, Switch Control, …)
/// is deliberately NOT read, so assistive-technology users are never flagged.
///
/// Limits: XCUITest / Appium (WebDriverAgent) drive the app from a separate
/// runner process and cannot be detected reliably from inside the app; this
/// detects XCTest hosting the app process and the Simulator only.
///
/// See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
enum AutomationSignals {

    /// Computed once per process: neither value changes while the app runs.
    static let current: EventContext.AutomationInfo = .init(
        testHarness: isTestHarness(environment: ProcessInfo.processInfo.environment),
        emulator: isSimulator
    )

    static var isSimulator: Bool {
        #if targetEnvironment(simulator)
        return true
        #else
        return false
        #endif
    }

    /// XCTest hosts this process: its configuration is in the environment or
    /// its classes are loaded.
    static func isTestHarness(
        environment: [String: String],
        classLoaded: (String) -> Bool = { NSClassFromString($0) != nil }
    ) -> Bool {
        let markers = ["XCTestConfigurationFilePath", "XCTestSessionIdentifier", "XCTestBundlePath"]
        if markers.contains(where: { environment[$0] != nil }) { return true }
        return classLoaded("XCTestCase")
    }
}
