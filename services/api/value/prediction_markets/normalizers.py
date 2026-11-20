"""Market-level prediction-market normalizers.

The canonical implementations moved into the derivatives plane
(``value.derivatives.event_contracts``) when event contracts became
derivatives instruments. This module re-exports them so the existing
``/v1/prediction-markets`` observation routes keep one normalization path.
"""
from __future__ import annotations

from value.derivatives.event_contracts import (
    normalize_kalshi_market,
    normalize_polymarket_market,
)

__all__ = ["normalize_kalshi_market", "normalize_polymarket_market"]
