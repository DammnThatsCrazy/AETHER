#import <React/RCTBridgeModule.h>
#import <React/RCTEventEmitter.h>

@interface RCT_EXTERN_MODULE(AetherNative, RCTEventEmitter)

RCT_EXTERN_METHOD(initialize:(NSDictionary *)config)
RCT_EXTERN_METHOD(track:(NSString *)event properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(screenView:(NSString *)screenName properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(conversion:(NSString *)event value:(double)value properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(hydrateIdentity:(NSDictionary *)data)
RCT_EXTERN_METHOD(getIdentity:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(reset)
RCT_EXTERN_METHOD(flush)
RCT_EXTERN_METHOD(handleDeepLink:(NSString *)url)
RCT_EXTERN_METHOD(trackPushOpened:(NSDictionary *)data)
RCT_EXTERN_METHOD(walletConnect:(NSString *)address options:(NSDictionary *)options)
RCT_EXTERN_METHOD(walletDisconnect)
RCT_EXTERN_METHOD(walletTransaction:(NSString *)txHash options:(NSDictionary *)options)
RCT_EXTERN_METHOD(contractAction:(NSString *)contract action:(NSString *)action options:(NSDictionary *)options)
RCT_EXTERN_METHOD(paymentInitiated:(NSString *)paymentId amount:(double)amount currency:(NSString *)currency properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(paymentCompleted:(NSString *)paymentId amount:(double)amount currency:(NSString *)currency properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(paymentFailed:(NSString *)paymentId reason:(NSString *)reason properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(approvalRequested:(NSString *)approvalId scope:(NSString *)scope properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(approvalResolved:(NSString *)approvalId approved:(BOOL)approved properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(entitlementGranted:(NSString *)entitlementId properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(entitlementRevoked:(NSString *)entitlementId properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(accessGranted:(NSString *)resource properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(accessDenied:(NSString *)resource reason:(NSString *)reason properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(agentTask:(NSString *)taskId actorId:(NSString *)actorId properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(agentDecision:(NSString *)decisionId actorId:(NSString *)actorId properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(a2hInteraction:(NSString *)interactionId actorId:(NSString *)actorId properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(x402Payment:(NSString *)paymentId amount:(NSString *)amount currency:(NSString *)currency network:(NSString *)network properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(runExperiment:(NSString *)id variants:(NSArray *)variants resolve:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(getExperimentAssignment:(NSString *)id resolve:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(getConsentState:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(grantConsent:(NSArray *)purposes)
RCT_EXTERN_METHOD(revokeConsent:(NSArray *)purposes)

// Journey lifecycle APIs — without these externs the Swift implementations are
// not registered with the bridge, so AetherNative.startJourney(...) and the
// other journey methods are undefined (silent no-ops) on iOS.
RCT_EXTERN_METHOD(startJourney:(NSString *)nameOrType properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(pauseJourney:(NSString *)reason properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(resumeJourney:(NSString *)reason properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(continueJourney:(NSString *)stepIdOrName properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(completeJourney:(NSString *)reason properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(abandonJourney:(NSString *)reason properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(checkpointJourney:(NSString *)stepIdOrName properties:(NSDictionary *)properties)
RCT_EXTERN_METHOD(getCurrentJourney:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)

@end
