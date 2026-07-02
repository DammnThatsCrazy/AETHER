from pathlib import Path


def test_semantic_sentiment_release_gate_assets_exist():
    for path in [
        "Backend Architecture/aether-backend/services/semantic_intelligence/routes.py",
        "Backend Architecture/aether-backend/services/semantic_intelligence/models.py",
        "scripts/semantic_sentiment/check_release_gate.py",
        "docs/semantic-sentiment/SEMANTIC-SENTIMENT-INTELLIGENCE.md",
    ]:
        assert Path(path).exists()
