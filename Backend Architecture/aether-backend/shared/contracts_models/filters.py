"""Canonical boolean filter language (Python).

TS twin: the ``FilterOperator`` / ``FilterExpression`` / ``FilterGroup``
section of ``packages/shared/graph-contract.ts`` (parity-tested by
``tests/unit/test_graph_contract_parity.py`` and the exploration parity
suite). Moved here from ``services/operational_intelligence/models.py`` so
shared planes (exploration, comparison) can compose the filter language
without a services-layer dependency; the old location re-exports these
names unchanged.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base model for API contracts that must tolerate additive fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class FilterOperator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    BETWEEN = "between"
    RELATIVE_TIME = "relative_time"
    THRESHOLD = "threshold"

    @classmethod
    def valid_values(cls) -> frozenset[str]:
        return frozenset(m.value for m in cls)


class FilterExpression(ContractModel):
    field: str
    op: FilterOperator
    value: Optional[Any] = None


class FilterGroup(ContractModel):
    logic: Literal["AND", "OR", "NOT"]
    expressions: list[Union[FilterExpression, "FilterGroup"]]


FilterGroup.model_rebuild()

__all__ = ["ContractModel", "FilterOperator", "FilterExpression", "FilterGroup"]
