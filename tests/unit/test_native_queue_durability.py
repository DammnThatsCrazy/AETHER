"""Machine-checkable native queue durability contract.

Native toolchains are not available in the core Python CI image, so these
contract checks complement the Swift/Kotlin unit suites and prevent silent
regression of the persistence/requeue invariants.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IOS = ROOT / "packages/ios/Sources/AetherSDK/Aether.swift"
ANDROID = ROOT / "packages/android/src/main/java/com/aether/sdk/Aether.kt"


def test_ios_queue_is_versioned_atomic_bounded_and_corruption_aware():
    source = IOS.read_text()
    for token in (
        "PersistedQueueEnvelope",
        "version: 1",
        "options: .atomic",
        "Aether.maxQueueSize",
        "Quarantined corrupt durable queue",
        "requeueBatch(batch)",
        "Batch retained after",
    ):
        assert token in source


def test_android_queue_is_versioned_atomic_bounded_and_corruption_aware():
    source = ANDROID.read_text()
    for token in (
        "QUEUE_FORMAT_VERSION",
        'file.name + ".tmp"',
        "MAX_QUEUE_SIZE",
        "Quarantined corrupt durable queue",
        "requeueBatch(batch)",
        "Batch retained after",
    ):
        assert token in source


def test_transient_failures_do_not_claim_the_batch_was_dropped():
    ios = IOS.read_text()
    android = ANDROID.read_text()
    assert "Batch dropped after \\(maxRetries) retries (server error" not in ios
    assert "Batch dropped after $maxRetries retries (server error" not in android
