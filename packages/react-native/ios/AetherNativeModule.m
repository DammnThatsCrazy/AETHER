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
