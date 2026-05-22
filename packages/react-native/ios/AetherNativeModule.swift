import Foundation
import React

@objc(AetherNative)
class AetherNativeModule: RCTEventEmitter {

    private var resolveEndpoint: String = ""

    override static func requiresMainQueueSetup() -> Bool {
        return false
    }

    override func supportedEvents() -> [String]! {
        return ["AetherIdentityChanged", "AetherConsentChanged", "AetherJourneyResumed"]
    }

    @objc
    func initialize(_ config: NSDictionary) {
        let apiKey = config["apiKey"] as? String ?? ""
        resolveEndpoint = config["endpoint"] as? String ?? "https://api.aether.network"
        var aetherConfig = AetherConfig(apiKey: apiKey)

        if let env = config["environment"] as? String {
            switch env {
            case "staging": aetherConfig.environment = .staging
            case "development": aetherConfig.environment = .development
            default: aetherConfig.environment = .production
            }
        }

        aetherConfig.debug = config["debug"] as? Bool ?? false
        aetherConfig.endpoint = resolveEndpoint

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
        let walletType = options["type"] as? String
        let chainId = options["chainId"].map { "\($0)" }
        Aether.shared.walletConnected(address: address, walletType: walletType, chainId: chainId)
        resolveWalletIdentity(address: address, walletType: walletType ?? "unknown", chainId: chainId ?? "unknown")
    }

    private func resolveWalletIdentity(address: String, walletType: String, chainId: String) {
        guard !resolveEndpoint.isEmpty,
              let url = URL(string: "\(resolveEndpoint)/sdk/identity/resolve") else { return }

        let body: [String: Any] = [
            "wallets": [["address": address, "type": walletType, "chainId": chainId]],
            "anonymousId": Aether.shared.getAnonymousId(),
            "deviceFingerprint": Aether.shared.getFingerprintId()
        ]
        guard let bodyData = try? JSONSerialization.data(withJSONObject: body) else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = bodyData
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            guard let self = self,
                  let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let resolved = json["resolved"] as? Bool, resolved,
                  let identity = json["identity"] as? [String: Any] else { return }
            self.sendEvent(withName: "AetherJourneyResumed", body: identity)
        }.resume()
    }

    @objc
    func walletDisconnect(_ address: String) {
        Aether.shared.walletDisconnected(address: address)
    }

    @objc
    func walletTransaction(_ txHash: String, options: NSDictionary) {
        let chainId = options["chainId"] as? String ?? "unknown"
        let value = options["value"] as? String
        let extra = (options as? [String: Any])?.mapValues { AnyCodable($0) }
        Aether.shared.walletTransaction(txHash: txHash, chainId: chainId, value: value, properties: extra)
    }

    @objc
    func getFingerprint(_ resolve: @escaping RCTPromiseResolveBlock, rejecter reject: RCTPromiseRejectBlock) {
        resolve(Aether.shared.getFingerprintId())
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
        let granted = Set(Aether.shared.getConsentState())
        resolve([
            "analytics": granted.contains("analytics"),
            "marketing": granted.contains("marketing"),
            "web3":      granted.contains("web3"),
            "agent":     granted.contains("agent"),
            "commerce":  granted.contains("commerce"),
        ])
    }

    @objc
    func grantConsent(_ purposes: NSArray) {
        let purposeList = purposes.compactMap { $0 as? String }
        Aether.shared.grantConsent(categories: purposeList)
        emitConsentChanged()
    }

    @objc
    func revokeConsent(_ purposes: NSArray) {
        let purposeList = purposes.compactMap { $0 as? String }
        Aether.shared.revokeConsent(categories: purposeList)
        emitConsentChanged()
    }

    private func emitConsentChanged() {
        let granted = Set(Aether.shared.getConsentState())
        sendEvent(withName: "AetherConsentChanged", body: [
            "analytics": granted.contains("analytics"),
            "marketing": granted.contains("marketing"),
            "web3":      granted.contains("web3"),
            "agent":     granted.contains("agent"),
            "commerce":  granted.contains("commerce"),
        ])
    }
}
