"""Credentialless provider certification + readiness-truth framework.

Public surface:

Readiness truth (``readiness``):
    CredentialReadiness, IMPLEMENTATION_STATUS_TO_READINESS, to_readiness,
    readiness_rank, ReadinessDimensions

Descriptor (``descriptor``):
    AdapterCertificationDescriptor

Checks (``checks``):
    CertificationCheckResult, CertifiableAdapter, ALL_CHECKS, run_certification

Registry (``registry``):
    iter_first_release_descriptors, build_capability_matrix

The framework certifies provider adapters WITHOUT network access or real
credentials by asserting on each adapter's honest descriptor (plus optional
offline hooks), and it resolves the first-release provider scope's CURRENT
readiness directly from source so readiness claims stay truthful.
"""

from __future__ import annotations

from shared.certification.checks import (
    ALL_CHECKS,
    CertifiableAdapter,
    CertificationCheckResult,
    run_certification,
)
from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import (
    IMPLEMENTATION_STATUS_TO_READINESS,
    CredentialReadiness,
    ReadinessDimensions,
    readiness_rank,
    to_readiness,
)
from shared.certification.registry import (
    build_capability_matrix,
    iter_first_release_descriptors,
)

__all__ = [
    # readiness
    "CredentialReadiness",
    "IMPLEMENTATION_STATUS_TO_READINESS",
    "to_readiness",
    "readiness_rank",
    "ReadinessDimensions",
    # descriptor
    "AdapterCertificationDescriptor",
    # checks
    "CertificationCheckResult",
    "CertifiableAdapter",
    "ALL_CHECKS",
    "run_certification",
    # registry
    "iter_first_release_descriptors",
    "build_capability_matrix",
]
