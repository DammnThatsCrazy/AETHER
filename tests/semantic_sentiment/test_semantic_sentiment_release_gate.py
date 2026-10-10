from pathlib import Path


def test_semantic_sentiment_release_gate_assets_exist():
    for path in [
        "services/api/intelligence/semantic_intelligence/routes.py",
        "services/api/intelligence/semantic_intelligence/models.py",
        "services/api/alembic/versions/20260702_semantic_sentiment.py",
        "packages/shared/semantic-sentiment.ts",
        "scripts/semantic_sentiment/check_release_gate.py",
        "docs/product/semantic-sentiment/SEMANTIC-SENTIMENT-INTELLIGENCE.md",
    ]:
        assert Path(path).exists()


def test_no_local_pytest_asyncio_shadow_module():
    assert not Path("pytest_asyncio.py").exists()
