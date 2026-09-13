"""Population360 intelligence-projection provider + human demographic lens.

Sibling of ``services/temporal360``: the ``population360`` context_360
projection (WHO / WHAT SET) and its governed human demographic lens. No
``Demographic360`` backend exists — demographics are a lens over canonical
profile facts (see ``demographics.py``).
"""

from services.population360.demographics import (
    DemographicLens,
    DemographicLensResult,
    HumanProfileFact,
    ProfileFactsReader,
    ProfileFactsUnavailable,
    SmallCellSuppression,
    SuppressedDistribution,
    UnavailableProfileFactsReader,
)

__all__ = [
    "DemographicLens",
    "DemographicLensResult",
    "HumanProfileFact",
    "ProfileFactsReader",
    "ProfileFactsUnavailable",
    "SmallCellSuppression",
    "SuppressedDistribution",
    "UnavailableProfileFactsReader",
]
