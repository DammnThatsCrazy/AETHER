from services.noesis.capability_registry import CAPABILITY_REGISTRY


def test_semantic_noesis_capabilities_registered():
    intents = {cap.intent for cap in CAPABILITY_REGISTRY}
    assert {"sentiment_explain", "narrative_analysis", "semantic_profile_explain"} <= intents
