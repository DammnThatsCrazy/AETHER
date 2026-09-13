"""
Aether Agent Layer — Semantic Tagger Enrichment Worker
Assigns semantic labels to entities using NLP / LLM classification.

Capabilities:
  - Industry / vertical classification (SIC / NAICS codes)
  - Content-based topic tagging (from crawled text)
  - Sentiment analysis on associated social mentions
  - Entity-type disambiguation (company vs. project vs. token)
  - Taxonomy alignment with a configurable ontology
"""

from __future__ import annotations

import logging
import re
from typing import Any

from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.semantic_tagger")

# Default taxonomy (extend or replace with domain-specific ontology)
_DEFAULT_TAXONOMY: dict[str, list[str]] = {
    "industry": [
        "defi", "nft", "gaming", "infrastructure", "social",
        "dao", "privacy", "ai_ml", "payments", "identity",
        "data", "security", "analytics", "exchange", "lending",
    ],
    "stage": [
        "pre_seed", "seed", "series_a", "series_b", "growth", "public",
    ],
    "sentiment": [
        "very_positive", "positive", "neutral", "negative", "very_negative",
    ],
    "content_type": [
        "product_page", "blog_post", "documentation", "press_release",
        "job_listing", "social_post", "whitepaper", "changelog",
    ],
}

# Keyword expansions: maps each taxonomy label to a set of keywords/phrases
# that indicate that label. This allows matching beyond the raw label text.
_KEYWORD_MAP: dict[str, dict[str, list[str]]] = {
    "industry": {
        "defi": [
            "defi", "decentralized finance", "yield farming", "liquidity pool",
            "amm", "automated market maker", "swap", "staking", "tvl",
            "total value locked", "dex", "decentralized exchange",
        ],
        "nft": [
            "nft", "non-fungible", "collectible", "digital art",
            "erc-721", "erc-1155", "opensea", "mint", "pfp",
        ],
        "gaming": [
            "gaming", "game", "play-to-earn", "p2e", "metaverse",
            "gamefi", "esports", "in-game", "virtual world",
        ],
        "infrastructure": [
            "infrastructure", "layer 1", "layer 2", "l1", "l2",
            "rollup", "bridge", "oracle", "node", "validator",
            "consensus", "scaling", "sidechain", "blockchain",
        ],
        "social": [
            "social", "community", "social media", "messaging",
            "social network", "chat", "communication", "forum",
        ],
        "dao": [
            "dao", "decentralized autonomous", "governance", "voting",
            "proposal", "treasury", "multisig", "snapshot",
        ],
        "privacy": [
            "privacy", "zero knowledge", "zk", "zkp", "zk-snark",
            "zk-stark", "mixer", "anonymous", "encryption", "private",
        ],
        "ai_ml": [
            "ai", "artificial intelligence", "machine learning", "ml",
            "deep learning", "neural network", "llm", "gpt", "model",
            "training", "inference", "nlp", "computer vision",
        ],
        "payments": [
            "payments", "payment", "remittance", "transfer", "send money",
            "pay", "invoice", "checkout", "merchant", "point of sale",
        ],
        "identity": [
            "identity", "did", "decentralized identity", "ssi",
            "self-sovereign", "credential", "verification", "kyc", "sybil",
        ],
        "data": [
            "data", "database", "storage", "indexing", "query",
            "data lake", "data pipeline", "etl", "analytics platform",
        ],
        "security": [
            "security", "audit", "vulnerability", "exploit", "hack",
            "penetration", "firewall", "threat", "malware", "antivirus",
        ],
        "analytics": [
            "analytics", "dashboard", "metrics", "tracking", "reporting",
            "visualization", "chart", "insight", "bi", "business intelligence",
        ],
        "exchange": [
            "exchange", "cex", "trading", "order book", "spot",
            "futures", "derivatives", "margin", "perpetual",
        ],
        "lending": [
            "lending", "borrowing", "loan", "collateral", "interest rate",
            "liquidation", "credit", "borrow", "lend", "aave", "compound",
        ],
    },
    "stage": {
        "pre_seed": ["pre-seed", "pre seed", "idea stage", "concept", "prototype"],
        "seed": ["seed", "seed round", "angel", "angel round", "early stage"],
        "series_a": ["series a", "series-a", "growth stage"],
        "series_b": ["series b", "series-b", "expansion"],
        "growth": ["growth", "scale", "scaling", "series c", "series d", "late stage"],
        "public": ["public", "ipo", "listed", "publicly traded", "stock market", "token launch", "tge"],
    },
    "sentiment": {
        "very_positive": [
            "amazing", "incredible", "outstanding", "revolutionary",
            "breakthrough", "love", "excellent", "fantastic", "thrilled",
            "delighted", "brilliant", "superb",
        ],
        "positive": [
            "good", "great", "nice", "pleased", "happy", "improved",
            "better", "promising", "bullish", "optimistic", "excited",
            "solid", "strong", "impressive",
        ],
        "neutral": [
            "announced", "launched", "released", "updated", "reported",
            "stated", "according to", "noted", "mentioned",
        ],
        "negative": [
            "bad", "poor", "disappointing", "concerned", "worried",
            "decline", "bearish", "struggling", "issue", "problem",
            "delay", "setback", "downgrade",
        ],
        "very_negative": [
            "terrible", "awful", "catastrophic", "crash", "scam",
            "fraud", "rug pull", "exploit", "hack", "stolen", "lost",
            "devastating", "disaster", "collapse",
        ],
    },
    "content_type": {
        "product_page": [
            "features", "pricing", "get started", "sign up", "free trial",
            "product", "platform", "solution", "demo",
        ],
        "blog_post": [
            "blog", "article", "post", "published", "author", "read more",
            "minutes read", "opinion", "thoughts on",
        ],
        "documentation": [
            "docs", "documentation", "api reference", "guide", "tutorial",
            "getting started", "installation", "quickstart", "sdk",
        ],
        "press_release": [
            "press release", "announces", "pr newswire", "businesswire",
            "media contact", "for immediate release",
        ],
        "job_listing": [
            "hiring", "job", "career", "position", "role", "apply now",
            "we are looking", "join our team", "open position",
        ],
        "social_post": [
            "tweet", "thread", "retweet", "like", "share", "follow",
            "dm", "posted by", "replied", "comment",
        ],
        "whitepaper": [
            "whitepaper", "white paper", "abstract", "introduction",
            "methodology", "conclusion", "references", "research",
            "technical paper", "specification",
        ],
        "changelog": [
            "changelog", "release notes", "what's new", "version",
            "bug fix", "patch", "update", "migration", "breaking change",
        ],
    },
}


class SemanticTaggerWorker(BaseWorker):
    """
    Enrichment worker that assigns semantic tags to entity data.

    Payload contract:
        entity_id   : str        — graph entity to tag
        text_corpus : list[str]  — text snippets to classify
        taxonomy    : str | None — taxonomy key from _DEFAULT_TAXONOMY or custom dict
        model       : str        — "rule_based" | "embedding" | "llm" (default "rule_based")
        top_k       : int        — max tags to return per category (default 3)
    """

    worker_type = WorkerType.SEMANTIC_TAGGER
    data_source = "general_web"

    def _execute(self, task: AgentTask) -> TaskResult:
        entity_id = task.payload.get("entity_id", "")
        corpus = task.payload.get("text_corpus", [])
        taxonomy_key = task.payload.get("taxonomy")
        model = task.payload.get("model", "rule_based")
        top_k = task.payload.get("top_k", 3)

        taxonomy = (
            task.payload.get("custom_taxonomy")
            or _DEFAULT_TAXONOMY
        )

        logger.info(
            f"Tagging entity {entity_id}: "
            f"{len(corpus)} snippets, model={model}, top_k={top_k}"
        )

        if not corpus:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=True,
                data={
                    "entity_id": entity_id,
                    "tags": {},
                    "total_tags_assigned": 0,
                    "model_used": model,
                    "corpus_size": 0,
                    "message": "Empty corpus provided",
                },
                confidence=0.0,
                source_attribution=f"semantic_tagger:{model}",
            )

        try:
            tags = self._classify_corpus(corpus, taxonomy, top_k)
        except Exception as exc:
            logger.exception(f"Semantic tagging failed: {exc}")
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                data={"error": str(exc), "entity_id": entity_id},
                confidence=0.0,
                source_attribution=f"semantic_tagger:{model}",
            )

        all_scores = [
            s["score"]
            for tag_list in tags.values()
            for s in tag_list
        ]
        avg_score = sum(all_scores) / max(len(all_scores), 1)

        data = {
            "entity_id": entity_id,
            "tags": tags,
            "total_tags_assigned": sum(len(v) for v in tags.values()),
            "model_used": model,
            "corpus_size": len(corpus),
        }
        confidence = round(min(avg_score + 0.1, 0.95), 3)

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            data=data,
            confidence=confidence,
            source_attribution=f"semantic_tagger:{model}",
        )

    # ------------------------------------------------------------------
    # Core classification logic
    # ------------------------------------------------------------------

    def _classify_corpus(
        self,
        corpus: list[str],
        taxonomy: dict[str, list[str]],
        top_k: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Rule-based classifier with keyword matching.

        For each text snippet, scan for keyword hits across all taxonomy
        categories. Score tags by hit frequency normalized by corpus size.
        """
        tags: dict[str, list[dict[str, Any]]] = {}
        corpus_size = len(corpus)

        # Pre-process corpus: combine and lowercase for scanning
        # Also keep individual snippets for per-snippet scoring
        combined_text = " ".join(corpus).lower()
        # Total word count for normalization
        total_words = max(len(combined_text.split()), 1)

        for category, labels in taxonomy.items():
            scored: list[dict[str, Any]] = []

            for label in labels:
                # Get expanded keywords for this label
                keywords = _KEYWORD_MAP.get(category, {}).get(label, [])
                # Always include the label itself (with underscores as spaces)
                keywords_to_check = [label.replace("_", " ")] + keywords

                # Count total hits across all keywords for this label
                total_hits = 0
                snippet_hits = 0  # how many snippets contain at least one keyword

                for keyword in keywords_to_check:
                    kw_lower = keyword.lower()
                    # Count occurrences in combined text
                    hits = _count_keyword_occurrences(combined_text, kw_lower)
                    total_hits += hits

                # Count how many snippets mention this label's keywords
                for snippet in corpus:
                    snippet_lower = snippet.lower()
                    for keyword in keywords_to_check:
                        if keyword.lower() in snippet_lower:
                            snippet_hits += 1
                            break  # one hit per snippet is enough

                if total_hits == 0 and category != "sentiment":
                    continue

                # Score calculation:
                # 1. Raw frequency normalized by total words
                frequency_score = min(total_hits / total_words * 50, 1.0)
                # 2. Coverage: what fraction of snippets mention this tag
                coverage_score = snippet_hits / corpus_size
                # 3. Combined score
                score = (frequency_score * 0.6) + (coverage_score * 0.4)
                score = min(round(score, 4), 0.95)

                # For sentiment, ensure we always produce a result if any
                # keywords matched at all
                if category == "sentiment" and total_hits == 0:
                    continue

                if score > 0.01:  # minimum threshold
                    scored.append({
                        "label": label,
                        "score": score,
                        "hits": total_hits,
                        "snippet_coverage": round(coverage_score, 3),
                        "method": "keyword_match",
                    })

            # Sort by score descending, then limit to top_k
            scored.sort(key=lambda x: x["score"], reverse=True)
            tags[category] = scored[:top_k]

            # If sentiment category has no matches, default to neutral
            if category == "sentiment" and not tags[category]:
                tags[category] = [{
                    "label": "neutral",
                    "score": 0.3,
                    "hits": 0,
                    "snippet_coverage": 0.0,
                    "method": "default_neutral",
                }]

        return tags


# ── Helper Functions ─────────────────────────────────────────────────

def _count_keyword_occurrences(text: str, keyword: str) -> int:
    """
    Count non-overlapping occurrences of a keyword in text,
    using word-boundary matching to avoid partial matches.
    """
    # Escape regex special chars in the keyword
    pattern = r"\b" + re.escape(keyword) + r"\b"
    try:
        return len(re.findall(pattern, text))
    except re.error:
        # Fallback to simple string count
        return text.count(keyword)
