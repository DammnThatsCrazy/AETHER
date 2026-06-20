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
    func startJourney(_ nameOrType: String, properties: NSDictionary) {
        Aether.shared.startJourney(nameOrType, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:])
    }

    @objc
    func pauseJourney(_ reason: String, properties: NSDictionary) {
        Aether.shared.pauseJourney(reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:])
    }

    @objc
    func resumeJourney(_ reason: String, properties: NSDictionary) {
        Aether.shared.resumeJourney(reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:])
    }

    @objc
    func continueJourney(_ stepIdOrName: String, properties: NSDictionary) {
        Aether.shared.continueJourney(stepIdOrName, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:])
    }

    @objc
    func completeJourney(_ reason: String, properties: NSDictionary) {
        Aether.shared.completeJourney(reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:])
    }

    @objc
    func abandonJourney(_ reason: String, properties: NSDictionary) {
        Aether.shared.abandonJourney(reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:])
    }

    @objc
    func checkpointJourney(_ stepIdOrName: String, properties: NSDictionary) {
        Aether.shared.checkpointJourney(stepIdOrName, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:])
    }

    @objc
    func getCurrentJourney(_ resolve: @escaping RCTPromiseResolveBlock, rejecter reject: RCTPromiseRejectBlock) {
        resolve(Aether.shared.getCurrentJourney() ?? NSNull())
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
    func contractAction(_ contract: String, action: String, options: NSDictionary) {
        let vm = options["vm"] as? String ?? "evm"
        let props = (options as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]
        Aether.shared.contractAction(contract: contract, action: action, vm: vm, properties: props)
    }

    @objc func paymentInitiated(_ paymentId: String, amount: Double, currency: String, properties: NSDictionary) { Aether.shared.paymentInitiated(paymentId: paymentId, amount: amount, currency: currency, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func paymentCompleted(_ paymentId: String, amount: Double, currency: String, properties: NSDictionary) { Aether.shared.paymentCompleted(paymentId: paymentId, amount: amount, currency: currency, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func paymentFailed(_ paymentId: String, reason: String, properties: NSDictionary) { Aether.shared.paymentFailed(paymentId: paymentId, reason: reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func approvalRequested(_ approvalId: String, scope: String, properties: NSDictionary) { Aether.shared.approvalRequested(approvalId: approvalId, scope: scope, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func approvalResolved(_ approvalId: String, approved: Bool, properties: NSDictionary) { Aether.shared.approvalResolved(approvalId: approvalId, approved: approved, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func entitlementGranted(_ entitlementId: String, properties: NSDictionary) { Aether.shared.entitlementGranted(entitlementId: entitlementId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func entitlementRevoked(_ entitlementId: String, properties: NSDictionary) { Aether.shared.entitlementRevoked(entitlementId: entitlementId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func accessGranted(_ resource: String, properties: NSDictionary) { Aether.shared.accessGranted(resource: resource, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func accessDenied(_ resource: String, reason: String, properties: NSDictionary) { Aether.shared.accessDenied(resource: resource, reason: reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentTask(_ taskId: String, actorId: String, properties: NSDictionary) { Aether.shared.agentTask(taskId: taskId, actorId: actorId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentDecision(_ decisionId: String, actorId: String, properties: NSDictionary) { Aether.shared.agentDecision(decisionId: decisionId, actorId: actorId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func a2hInteraction(_ interactionId: String, actorId: String, properties: NSDictionary) { Aether.shared.a2hInteraction(interactionId: interactionId, actorId: actorId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402Payment(_ paymentId: String, amount: String, currency: String, network: String, properties: NSDictionary) { Aether.shared.x402Payment(paymentId: paymentId, amount: amount, currency: currency, network: network, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }

    // MARK: - Granular Agent Lifecycle
    @objc func agentRegistered(_ agentId: String, properties: NSDictionary) { Aether.shared.agentRegistered(agentId: agentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentUpdated(_ agentId: String, properties: NSDictionary) { Aether.shared.agentUpdated(agentId: agentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentAuthorized(_ agentId: String, delegationId: String, properties: NSDictionary) { Aether.shared.agentAuthorized(agentId: agentId, delegationId: delegationId.isEmpty ? nil : delegationId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentDeauthorized(_ agentId: String, properties: NSDictionary) { Aether.shared.agentDeauthorized(agentId: agentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentCapabilityGranted(_ agentId: String, capability: String, properties: NSDictionary) { Aether.shared.agentCapabilityGranted(agentId: agentId, capability: capability, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentCapabilityRevoked(_ agentId: String, capability: String, properties: NSDictionary) { Aether.shared.agentCapabilityRevoked(agentId: agentId, capability: capability, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentTaskCreated(_ taskId: String, actorId: String, properties: NSDictionary) { Aether.shared.agentTaskCreated(taskId: taskId, actorId: actorId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentTaskDecomposed(_ taskId: String, properties: NSDictionary) { Aether.shared.agentTaskDecomposed(taskId: taskId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentTaskStarted(_ taskId: String, properties: NSDictionary) { Aether.shared.agentTaskStarted(taskId: taskId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentTaskCompleted(_ taskId: String, properties: NSDictionary) { Aether.shared.agentTaskCompleted(taskId: taskId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentTaskFailed(_ taskId: String, reason: String, properties: NSDictionary) { Aether.shared.agentTaskFailed(taskId: taskId, reason: reason.isEmpty ? nil : reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentToolCalled(_ taskId: String, tool: String, properties: NSDictionary) { Aether.shared.agentToolCalled(taskId: taskId, tool: tool, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentResourceRequested(_ resourceId: String, properties: NSDictionary) { Aether.shared.agentResourceRequested(resourceId: resourceId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentDelegatedTask(_ taskId: String, toAgentId: String, properties: NSDictionary) { Aether.shared.agentDelegatedTask(taskId: taskId, toAgentId: toAgentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentSubagentSpawned(_ parentId: String, childId: String, properties: NSDictionary) { Aether.shared.agentSubagentSpawned(parentId: parentId, childId: childId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentPolicyEvaluated(_ policyId: String, outcome: String, properties: NSDictionary) { Aether.shared.agentPolicyEvaluated(policyId: policyId, outcome: outcome, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentHandoff(_ fromId: String, toId: String, properties: NSDictionary) { Aether.shared.agentHandoff(fromId: fromId, toId: toId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentEscalatedToHuman(_ taskId: String, reason: String, properties: NSDictionary) { Aether.shared.agentEscalatedToHuman(taskId: taskId, reason: reason.isEmpty ? nil : reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func agentOutcomeRecorded(_ taskId: String, outcome: String, properties: NSDictionary) { Aether.shared.agentOutcomeRecorded(taskId: taskId, outcome: outcome, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }

    // MARK: - Granular x402 Lifecycle
    @objc func x402ResourceRequested(_ resourceId: String, properties: NSDictionary) { Aether.shared.x402ResourceRequested(resourceId: resourceId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402PaymentRequired(_ resourceId: String, amount: Double, currency: String, properties: NSDictionary) { Aether.shared.x402PaymentRequired(resourceId: resourceId, amount: amount, currency: currency, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402QuoteReceived(_ quoteId: String, properties: NSDictionary) { Aether.shared.x402QuoteReceived(quoteId: quoteId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402AuthorizationRequested(_ paymentId: String, properties: NSDictionary) { Aether.shared.x402AuthorizationRequested(paymentId: paymentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402AuthorizationResolved(_ paymentId: String, authorized: Bool, properties: NSDictionary) { Aether.shared.x402AuthorizationResolved(paymentId: paymentId, authorized: authorized, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402PaymentIntentCreated(_ intentId: String, properties: NSDictionary) { Aether.shared.x402PaymentIntentCreated(intentId: intentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402PaymentSubmitted(_ paymentId: String, properties: NSDictionary) { Aether.shared.x402PaymentSubmitted(paymentId: paymentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402PaymentSettled(_ paymentId: String, properties: NSDictionary) { Aether.shared.x402PaymentSettled(paymentId: paymentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402PaymentFailed(_ paymentId: String, reason: String, properties: NSDictionary) { Aether.shared.x402PaymentFailed(paymentId: paymentId, reason: reason.isEmpty ? nil : reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402PaymentTimeout(_ paymentId: String, properties: NSDictionary) { Aether.shared.x402PaymentTimeout(paymentId: paymentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402ReceiptVerified(_ receiptId: String, properties: NSDictionary) { Aether.shared.x402ReceiptVerified(receiptId: receiptId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402AccessGranted(_ resourceId: String, properties: NSDictionary) { Aether.shared.x402AccessGranted(resourceId: resourceId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402AccessDenied(_ resourceId: String, reason: String, properties: NSDictionary) { Aether.shared.x402AccessDenied(resourceId: resourceId, reason: reason.isEmpty ? nil : reason, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func x402RefundOrReversal(_ paymentId: String, properties: NSDictionary) { Aether.shared.x402RefundOrReversal(paymentId: paymentId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }

    // MARK: - Rewards
    @objc func rewardActionQueued(_ campaignId: String, ruleId: String, properties: NSDictionary) { Aether.shared.rewardActionQueued(campaignId: campaignId, ruleId: ruleId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func rewardProofGenerated(_ campaignId: String, proofId: String, properties: NSDictionary) { Aether.shared.rewardProofGenerated(campaignId: campaignId, proofId: proofId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func rewardDelivered(_ campaignId: String, rewardId: String, properties: NSDictionary) { Aether.shared.rewardDelivered(campaignId: campaignId, rewardId: rewardId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func rewardClaimSubmitted(_ campaignId: String, claimId: String, properties: NSDictionary) { Aether.shared.rewardClaimSubmitted(campaignId: campaignId, claimId: claimId, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }

    // MARK: - Ecommerce additions
    @objc func trackRemoveFromCart(_ productId: String, quantity: Int, properties: NSDictionary) { Aether.shared.trackRemoveFromCart(productId: productId, quantity: quantity, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func trackApplyCoupon(_ couponCode: String, properties: NSDictionary) { Aether.shared.trackApplyCoupon(couponCode: couponCode, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }
    @objc func trackBeginCheckout(_ cartValue: Double, currency: String, properties: NSDictionary) { Aether.shared.trackBeginCheckout(cartValue: cartValue, currency: currency, properties: (properties as? [String: Any])?.mapValues { AnyCodable($0) } ?? [:]) }

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
