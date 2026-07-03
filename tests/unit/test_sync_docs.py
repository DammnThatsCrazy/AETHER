from __future__ import annotations

from scripts import sync_docs


def test_semantic_sentiment_nested_docs_are_indexed() -> None:
    groups = sync_docs.authored_docs()

    assert "semantic-sentiment/SEMANTIC-SENTIMENT-INTELLIGENCE.md" in groups["Product Domains"]
    assert "runbooks/semantic-sentiment/semantic-sentiment-operations.md" in groups["Runbooks"]
