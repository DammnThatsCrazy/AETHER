import Foundation
import React

@objc(AetherNative)
class AetherNativeModule: RCTEventEmitter {

    override static func requiresMainQueueSetup() -> Bool {
        return false
    }

    override func supportedEvents() -> [String]! {
        return ["AetherIdentityChanged"]
    }

    @objc
    func initialize(_ config: NSDictionary) {
        let apiKey = config["apiKey"] as? String ?? ""
        var aetherConfig = AetherConfig(apiKey: apiKey)

        if let env = config["environment"] as? String {
            switch env {
            case "staging": aetherConfig.environment = .staging
            case "development": aetherConfig.environment = .development
            default: aetherConfig.environment = .production
            }
        }

        aetherConfig.debug = config["debug"] as? Bool ?? false
        aetherConfig.endpoint = config["endpoint"] as? String ?? "https://api.aether.network"

        if let modules = config["modules"] as? NSDictionary {
            aetherConfig.modules.screenTracking = modules["screenTracking"] as? Bool ?? true
            aetherConfig.modules.deepLinkAttribution = modules["deepLinkAttribution"] as? Bool ?? true
            aetherConfig.modules.pushNotificationTracking = modules["pushTracking"] as? Bool ?? true
            aetherConfig.modules.walletTracking = modules["walletTracking"] as? Bool ?? false
            aetherConfig.modules.experiments = modules["experiments"] as? Bool ?? true
        }

        if let privacy = config["privacy"] as? NSDictionary {
            aetherConfig.privacy.gdprMode = privacy["gdprMode"] as? Bool ?? false
            aetherConfig.privacy.anonymizeIP = privacy["anonymizeIP"] as? Bool ?? true
        }

        Aether.shared.initialize(config: aetherConfig)
    }

    @objc
    func track(_ event: String, properties: NSDictionary) {
        let props = (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]
        Aether.shared.track(event, properties: props)
    }

    @objc
    func screenView(_ screenName: String, properties: NSDictionary) {
        let props = (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]
        Aether.shared.screenView(screenName, properties: props)
    }

    @objc
    func conversion(_ event: String, value: Double, properties: NSDictionary) {
        let props = (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]
        Aether.shared.conversion(event, value: value, properties: props)
    }

    @objc
    func hydrateIdentity(_ data: NSDictionary) {
        let traits = (data["traits"] as? [String: Any])?.mapValues { AnyCodable($0) }
        let identityData = IdentityData(
            userId: data["userId"] as? String,
            walletAddress: data["walletAddress"] as? String,
            traits: traits
        )
        Aether.shared.hydrateIdentity(identityData)

        sendEvent(withName: "AetherIdentityChanged", body: [
            "anonymousId": Aether.shared.getAnonymousId(),
            "userId": Aether.shared.getUserId() as Any
        ])
    }

    @objc
    func getIdentity(_ resolve: @escaping RCTPromiseResolveBlock, rejecter reject: RCTPromiseRejectBlock) {
        resolve([
            "anonymousId": Aether.shared.getAnonymousId(),
            "userId": Aether.shared.getUserId() as Any,
            "traits": [:] as [String: Any]
        ])
    }

    @objc
    func reset() {
        Aether.shared.reset()
    }

    @objc
    func flush() {
        Aether.shared.flush()
    }

    @objc
    func handleDeepLink(_ url: String) {
        if let deepLinkURL = URL(string: url) {
            Aether.shared.handleDeepLink(deepLinkURL)
        }
    }

    @objc
    func trackPushOpened(_ data: NSDictionary) {
        Aether.shared.trackPushOpened(userInfo: data as! [AnyHashable: Any])
    }

    @objc
    func walletConnect(_ address: String, options: NSDictionary) {
        let identityData = IdentityData(
            walletAddress: address,
            traits: nil
        )
        Aether.shared.hydrateIdentity(identityData)
    }

    @objc
    func walletDisconnect() {
        Aether.shared.track("wallet_disconnected")
    }

    @objc
    func walletTransaction(_ txHash: String, options: NSDictionary) {
        let props = (options as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]
        var allProps = props
        allProps["txHash"] = AnyCodable(txHash)
        Aether.shared.track("wallet_transaction", properties: allProps)
    }

    @objc
    func runExperiment(_ id: String, variants: NSArray, resolve: @escaping RCTPromiseResolveBlock, rejecter reject: RCTPromiseRejectBlock) {
        let variantList = variants.compactMap { $0 as? String }
        let hash = abs(Aether.shared.getAnonymousId().hashValue)
        let index = hash % variantList.count
        resolve(variantList[index])
    }

    @objc
    func getExperimentAssignment(_ id: String, resolve: @escaping RCTPromiseResolveBlock, rejecter reject: RCTPromiseRejectBlock) {
        resolve(nil)
    }

    @objc
    func getConsentState(_ resolve: @escaping RCTPromiseResolveBlock, rejecter reject: RCTPromiseRejectBlock) {
        resolve([
            "analytics": true,
            "marketing": false,
            "web3": false
        ])
    }

    @objc
    func grantConsent(_ purposes: NSArray) {
        let purposeList = purposes.compactMap { $0 as? String }
        Aether.shared.track("consent_granted", properties: ["purposes": AnyCodable(purposeList)])
    }

    @objc
    func revokeConsent(_ purposes: NSArray) {
        let purposeList = purposes.compactMap { $0 as? String }
        Aether.shared.track("consent_revoked", properties: ["purposes": AnyCodable(purposeList)])
    }
}
