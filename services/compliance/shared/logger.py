"""
Aether Compliance — Shared Logger
Single logging utility used by all modules. Eliminates duplicated _log() functions.

Tags: DPD (Data Protection), DSR, CST (Consent), BRC (Breach), SOC2, GAP, AUD (Audit),
      IAM (Access Review), POL (Policy), CMP (Compliance Tests), ROPA, DLN (Data Lineage)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from functools import partial


def log(msg: str, tag: str = "CMP") -> None:
    """Print a tagged log message."""
    print(f"  [{tag}] {msg}")


@contextmanager
def timed(label: str, tag: str = "CMP"):
    """Context manager that logs elapsed time."""
    start = time.time()
    log(f"{label}...", tag)
    yield
    elapsed = time.time() - start
    log(f"{label} done ({elapsed:.2f}s)", tag)


# Convenience partials — one per module
dpd_log = partial(log, tag="DPD")   # Data Protection by Design
dsr_log = partial(log, tag="DSR")   # Data Subject Rights
cst_log = partial(log, tag="CST")   # Consent Management
brc_log = partial(log, tag="BRC")   # Breach Notification
soc2_log = partial(log, tag="SOC2") # SOC 2 Trust Criteria
gap_log = partial(log, tag="GAP")   # Gap Analysis
aud_log = partial(log, tag="AUD")   # Audit Engine
iam_log = partial(log, tag="IAM")   # Access Review
pol_log = partial(log, tag="POL")   # Policy Generator
ropa_log = partial(log, tag="ROPA") # Record of Processing Activities
dln_log = partial(log, tag="DLN")   # Data Lineage
