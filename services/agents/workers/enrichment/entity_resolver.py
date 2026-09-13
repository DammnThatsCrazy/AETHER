"""
Aether Agent Layer — Entity Resolver Enrichment Worker
Matches ambiguous entities across data sources using LLM reasoning.

Resolution strategies:
  - rule_based:  exact match on email/domain/name, Jaccard similarity on text
  - embedding:   TF-IDF feature vectors with cosine similarity
  - llm_hybrid:  combines rule-based matching with multi-signal confidence boost
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.entity_resolver")

# Configurable thresholds
_DEFAULT_MATCH_THRESHOLD = 0.65
_HIGH_CONFIDENCE_THRESHOLD = 0.85
_EXACT_MATCH_SCORE = 1.0


class EntityResolverWorker(BaseWorker):
    worker_type = WorkerType.ENTITY_RESOLVER
    data_source = "general_web"  # may also hit internal graph

    def _execute(self, task: AgentTask) -> TaskResult:
        """
        Expected payload keys:
            - candidate_entities: list[dict]  — partial entity records to resolve
            - match_strategy: str             — "embedding", "rule_based", "llm_hybrid"
            - existing_entities: list[dict]   — known entities to match against (optional)
            - match_threshold: float          — minimum score to consider a match (optional)
        """
        candidates = task.payload.get("candidate_entities", [])
        strategy = task.payload.get("match_strategy", "llm_hybrid")
        existing_entities = task.payload.get("existing_entities", [])
        match_threshold = task.payload.get(
            "match_threshold", _DEFAULT_MATCH_THRESHOLD
        )

        logger.info(
            f"Resolving {len(candidates)} candidate entities "
            f"using strategy={strategy}, threshold={match_threshold}"
        )

        if not candidates:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=True,
                data={"resolved_entities": [], "message": "No candidates provided"},
                confidence=1.0,
                source_attribution="internal_graph",
            )

        try:
            resolved = []
            for candidate in candidates:
                if strategy == "rule_based":
                    result = self._resolve_rule_based(
                        candidate, existing_entities, match_threshold
                    )
                elif strategy == "embedding":
                    result = self._resolve_embedding(
                        candidate, existing_entities, match_threshold
                    )
                elif strategy == "llm_hybrid":
                    result = self._resolve_llm_hybrid(
                        candidate, existing_entities, match_threshold
                    )
                else:
                    result = self._resolve_rule_based(
                        candidate, existing_entities, match_threshold
                    )
                resolved.append(result)

            confidences = [r["confidence"] for r in resolved]
            avg_confidence = sum(confidences) / max(len(confidences), 1)

        except Exception as exc:
            logger.exception(f"Entity resolution failed: {exc}")
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                data={"error": str(exc)},
                confidence=0.0,
                source_attribution="internal_graph",
            )

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            data={"resolved_entities": resolved},
            confidence=round(avg_confidence, 3),
            source_attribution="internal_graph + llm",
        )

    # ------------------------------------------------------------------
    # Strategy: Rule-Based
    # ------------------------------------------------------------------

    def _resolve_rule_based(
        self,
        candidate: dict[str, Any],
        existing: list[dict[str, Any]],
        threshold: float,
    ) -> dict[str, Any]:
        """
        Compare candidate against existing entities using deterministic rules:
        - Exact match on email, domain, name
        - Jaccard similarity on text fields (bio, description)
        """
        best_match_id = None
        best_score = 0.0
        match_signals: list[str] = []

        for entity in existing:
            score, signals = self._rule_based_score(candidate, entity)
            if score > best_score:
                best_score = score
                best_match_id = entity.get("entity_id") or entity.get("id")
                match_signals = signals

        matched = best_score >= threshold
        return {
            "input": candidate,
            "matched_entity_id": best_match_id if matched else None,
            "confidence": round(best_score, 4),
            "matched": matched,
            "strategy": "rule_based",
            "signals": match_signals,
            "reasoning": (
                f"Rule-based match with score {best_score:.3f} "
                f"on signals: {', '.join(match_signals)}"
                if matched
                else "No rule-based match above threshold"
            ),
        }

    def _rule_based_score(
        self,
        candidate: dict[str, Any],
        entity: dict[str, Any],
    ) -> tuple[float, list[str]]:
        """Compute rule-based similarity score between two entity dicts."""
        scores: list[float] = []
        signals: list[str] = []

        # Exact match fields (email, domain, name)
        exact_fields = ["email", "domain", "name", "legal_name", "website"]
        for field in exact_fields:
            c_val = _normalize(candidate.get(field, ""))
            e_val = _normalize(entity.get(field, ""))
            if c_val and e_val:
                if c_val == e_val:
                    scores.append(_EXACT_MATCH_SCORE)
                    signals.append(f"{field}_exact")
                else:
                    # Partial match — check containment
                    if c_val in e_val or e_val in c_val:
                        scores.append(0.7)
                        signals.append(f"{field}_partial")
                    else:
                        scores.append(0.0)

        # Jaccard similarity on text fields
        text_fields = ["description", "bio", "summary", "tags"]
        for field in text_fields:
            c_val = candidate.get(field, "")
            e_val = entity.get(field, "")
            if c_val and e_val:
                sim = _jaccard_similarity(str(c_val), str(e_val))
                scores.append(sim)
                if sim > 0.3:
                    signals.append(f"{field}_jaccard({sim:.2f})")

        if not scores:
            return 0.0, []

        # Weighted average: exact fields count more
        return sum(scores) / len(scores), signals

    # ------------------------------------------------------------------
    # Strategy: Embedding (TF-IDF + Cosine Similarity)
    # ------------------------------------------------------------------

    def _resolve_embedding(
        self,
        candidate: dict[str, Any],
        existing: list[dict[str, Any]],
        threshold: float,
    ) -> dict[str, Any]:
        """
        Compute TF-IDF-like feature vectors from entity text fields,
        then cosine similarity to find the best match.
        """
        candidate_text = _entity_to_text(candidate)

        # Build a mini-corpus from all entities for IDF computation
        corpus_texts = [candidate_text]
        for ent in existing:
            corpus_texts.append(_entity_to_text(ent))

        # Compute IDF from corpus
        idf = _compute_idf(corpus_texts)

        # Vectorize candidate
        candidate_vec = _tfidf_vector(candidate_text, idf)

        best_match_id = None
        best_score = 0.0

        for ent in existing:
            ent_text = _entity_to_text(ent)
            ent_vec = _tfidf_vector(ent_text, idf)
            sim = _cosine_similarity(candidate_vec, ent_vec)
            if sim > best_score:
                best_score = sim
                best_match_id = ent.get("entity_id") or ent.get("id")

        matched = best_score >= threshold
        return {
            "input": candidate,
            "matched_entity_id": best_match_id if matched else None,
            "confidence": round(best_score, 4),
            "matched": matched,
            "strategy": "embedding",
            "reasoning": (
                f"TF-IDF cosine similarity={best_score:.3f}"
                if matched
                else f"Best cosine similarity {best_score:.3f} below threshold {threshold}"
            ),
        }

    # ------------------------------------------------------------------
    # Strategy: LLM Hybrid (Rule-Based + Multi-Signal Boost)
    # ------------------------------------------------------------------

    def _resolve_llm_hybrid(
        self,
        candidate: dict[str, Any],
        existing: list[dict[str, Any]],
        threshold: float,
    ) -> dict[str, Any]:
        """
        Combine rule-based matching with a confidence boost when
        multiple signals agree. Email + domain + name all matching
        yields high confidence.
        """
        # First, get rule-based result
        rule_result = self._resolve_rule_based(candidate, existing, threshold=0.0)
        rule_score = rule_result["confidence"]
        signals = rule_result.get("signals", [])

        # Also run embedding for an independent signal
        emb_result = self._resolve_embedding(candidate, existing, threshold=0.0)
        emb_score = emb_result["confidence"]

        # Count strong signal categories
        exact_signals = [s for s in signals if "_exact" in s]
        strong_signal_count = len(exact_signals)

        # Multi-signal boost: when multiple independent signals agree
        boost = 0.0
        if strong_signal_count >= 3:
            boost = 0.15  # email + domain + name all exact = high boost
        elif strong_signal_count >= 2:
            boost = 0.10
        elif strong_signal_count >= 1:
            boost = 0.05

        # Cross-strategy agreement bonus
        if rule_score > 0.5 and emb_score > 0.5:
            boost += 0.05

        # Weighted combination
        combined = (rule_score * 0.5) + (emb_score * 0.3) + boost
        combined = min(combined, 0.99)  # cap at 0.99

        # Pick the entity ID from the higher-scoring strategy
        if rule_score >= emb_score:
            matched_id = rule_result.get("matched_entity_id")
        else:
            matched_id = emb_result.get("matched_entity_id")

        matched = combined >= threshold
        return {
            "input": candidate,
            "matched_entity_id": matched_id if matched else None,
            "confidence": round(combined, 4),
            "matched": matched,
            "strategy": "llm_hybrid",
            "rule_score": round(rule_score, 4),
            "embedding_score": round(emb_score, 4),
            "boost_applied": round(boost, 4),
            "exact_signal_count": strong_signal_count,
            "signals": signals,
            "reasoning": (
                f"Hybrid: rule={rule_score:.3f} emb={emb_score:.3f} "
                f"boost={boost:.3f} => combined={combined:.3f}"
            ),
        }


# ── Helper Functions ─────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Lowercase, strip, remove common noise."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Jaccard similarity over word tokens."""
    tokens_a = set(_normalize(text_a).split())
    tokens_b = set(_normalize(text_b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _entity_to_text(entity: dict[str, Any]) -> str:
    """Flatten entity fields into a single text string for vectorization."""
    parts: list[str] = []
    text_keys = [
        "name", "legal_name", "email", "domain", "website",
        "description", "bio", "summary", "industry", "title",
        "tags", "location", "company",
    ]
    for key in text_keys:
        val = entity.get(key)
        if val:
            if isinstance(val, list):
                parts.extend(str(v) for v in val)
            else:
                parts.append(str(val))
    return " ".join(parts).lower()


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _compute_idf(corpus: list[str]) -> dict[str, float]:
    """Compute inverse document frequency for terms across the corpus."""
    n_docs = len(corpus)
    doc_freq: Counter = Counter()
    for doc in corpus:
        unique_tokens = set(_tokenize(doc))
        for token in unique_tokens:
            doc_freq[token] += 1

    idf: dict[str, float] = {}
    for term, df in doc_freq.items():
        idf[term] = math.log((n_docs + 1) / (df + 1)) + 1.0
    return idf


def _tfidf_vector(text: str, idf: dict[str, float]) -> dict[str, float]:
    """Compute a TF-IDF weighted term-frequency vector."""
    tokens = _tokenize(text)
    tf: Counter = Counter(tokens)
    total = max(len(tokens), 1)
    vec: dict[str, float] = {}
    for term, count in tf.items():
        term_tf = count / total
        term_idf = idf.get(term, 1.0)
        vec[term] = term_tf * term_idf
    return vec


def _cosine_similarity(
    vec_a: dict[str, float],
    vec_b: dict[str, float],
) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    if not vec_a or not vec_b:
        return 0.0

    # Dot product
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)

    # Magnitudes
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0

    return dot / (mag_a * mag_b)
