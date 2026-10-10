"""Cross-platform contracts for native late identity binding and alias retries."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_native_late_binding_emits_the_same_canonical_journey_event() -> None:
    android = _source("packages/sdk/android/src/main/java/com/aether/sdk/Aether.kt")
    ios = _source("packages/sdk/ios/Sources/AetherSDK/Aether.swift")

    assert 'enqueueEvent("journey_resumed"' in android
    assert "enqueueEvent(type: .journey_resumed" in ios
    assert '"event": "journey_resumed"' not in ios


def test_react_native_bridges_native_late_binding_to_the_public_hook_event() -> None:
    android = _source(
        "packages/sdk/react-native/android/src/main/java/com/aether/reactnative/AetherNativeModule.kt"
    )
    ios = _source("packages/sdk/react-native/ios/AetherNativeModule.swift")
    js = _source("packages/sdk/react-native/src/bridge.ts")

    assert "onJourneyResumed = { anonymousId, userId ->" in android
    assert 'sendEvent("AetherJourneyResumed"' in android
    assert "aetherConfig.onJourneyResumed =" in ios
    assert 'sendEvent(withName: "AetherJourneyResumed"' in ios
    assert "addListener('AetherJourneyResumed'" in js


def test_android_and_ios_alias_id_generators_share_a_golden_vector() -> None:
    android_test = _source("packages/sdk/android/src/test/java/com/aether/sdk/AetherTest.kt")
    ios_test = _source("packages/sdk/ios/Tests/AetherSDKTests/AetherSDKTests.swift")
    vector = "bc6bc9c9-9124-5e2e-ab25-fb414e667997"

    assert vector in android_test
    assert vector in ios_test
