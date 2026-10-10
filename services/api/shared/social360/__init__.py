"""Social360 bounded-domain carriers (backend).

Backend Python home for the canonical Social360 vocabulary that M1 declared as
JSON contracts under ``packages/shared/contracts/``. M1 did not generate Python
twins for the Social Silver fact contracts; the carriers in this package are the
hand-authored backend mirrors of those canonical JSON enum members.

``canonical`` mirrors the ``sourceScope`` / ``evidenceBasis`` $defs of
``packages/shared/contracts/social-silver-facts.schema.json``. These two
vocabularies are DISTINCT from the product-intelligence
``interaction-vocabulary.json`` evidenceBasis — do not reuse that set here.
"""

from __future__ import annotations

from .canonical import (
    EVIDENCE_BASIS,
    EVIDENCE_BASIS_BY_ACQUISITION_MODE,
    FACT_KIND_BY_EVENT_TYPE,
    SOCIAL_SILVER_CONTRACT_VERSION,
    SOURCE_SCOPES,
    SOURCE_SCOPE_BY_ACQUISITION_MODE,
    fact_kind_for,
)

__all__ = [
    "EVIDENCE_BASIS",
    "EVIDENCE_BASIS_BY_ACQUISITION_MODE",
    "FACT_KIND_BY_EVENT_TYPE",
    "SOCIAL_SILVER_CONTRACT_VERSION",
    "SOURCE_SCOPES",
    "SOURCE_SCOPE_BY_ACQUISITION_MODE",
    "fact_kind_for",
]
