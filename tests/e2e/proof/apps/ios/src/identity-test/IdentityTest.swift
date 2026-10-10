//
//  FPS — iOS SDK Identity Late Binding Test
//
import AetherIOS

class IdentityTest {
    static func run() {
        let sdk = AetherSDK(apiKey: "ak_test_key")
        
        // 1. Heartbeat
        sdk.heartbeat { result in
            print("heartbeat: \(result ? "OK" : "FAIL")")
        }
        
        // 2. Anonymous event
        sdk.track(event: "page_view", properties: ["url": "/"])
        
        // 3. Identify
        sdk.identify(userId: "user_123", traits: ["email": "test@example.com"])
        
        // 4. Alias
        sdk.alias(previousId: "old_anon", userId: "user_123")
        
        // 5. Reset
        sdk.reset()
        
        // 6. Consent
        sdk.setConsent(state: ["identity": true])
    }
}
