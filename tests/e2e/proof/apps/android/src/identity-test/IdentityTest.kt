//
//  FPS — Android SDK Identity Late Binding Test
//
import com.aether.sdk.AetherSDK

fun main() {
    val sdk = AetherSDK(apiKey = "ak_test_key")
    
    // 1. Heartbeat
    sdk.heartbeat { result ->
        println("heartbeat: ${if (result) "OK" else "FAIL"}")
    }
    
    // 2. Anonymous event
    sdk.track("page_view", mapOf("url" to "/"))
    
    // 3. Identify
    sdk.identify("user_123", mapOf("email" to "test@example.com"))
    
    // 4. Alias
    sdk.alias("old_anon", "user_123")
    
    // 5. Reset
    sdk.reset()
    
    // 6. Consent
    sdk.setConsent(mapOf("identity" to true))
}
