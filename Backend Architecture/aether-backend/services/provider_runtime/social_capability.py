"""Social-capability honesty gate for UPR social plugins (M2-A).

Turns the M1 UPR social capability vocabulary
(``packages/shared/contracts/social-provider-capability-vocabulary.json``) into a
*runtime-enforced canonical surface*. :func:`social_capability_violations` is
wired into :func:`services.provider_runtime.validation.capability_violations`
(§32), so it runs on every registry.register — but ONLY for a plugin whose
``ProviderIdentity.product == "social"`` (identities like
``reddit.social.account_read``). Commerce and other non-social plugins
(``product != "social"``) are completely unaffected: the gate returns an empty
violation list for them without reading their adapters.

For a social plugin the gate enforces, from the generated vocabulary:

* **(a) capability membership** — the identity ``capability`` segment must be a
  member of the vocabulary ``capabilities`` list (e.g. ``relationship_read`` is
  canonical; ``bestie_read`` is not).
* **(b) grammar well-formedness** — the identity must parse as the canonical
  ``family.product.capability`` grammar with exactly three well-formed segments
  and product ``social``.
* **(c) violation reporting, never a silent raise** — a plugin whose surfaces
  raise while this gate reads them yields violations (the base §32 path reports
  the same accessor failures); this function never raises for a broken plugin.
* **(d) lifecycle honesty** — a social plugin whose manifest readiness claims
  ``partner_live`` (the vocabulary lifecycle state whose token value matches
  ``CredentialReadiness.PARTNER_LIVE``) must attach external evidence: a
  ``certification_report`` artifact (a passed
  :class:`~shared.integration_contracts.certification.CertificationReport` from
  the UPR certification harness whose readiness is ``PARTNER_LIVE``). Claiming
  ``partner_live`` without that evidence is a violation ("``code_complete`` is
  never promoted to ``partner_live`` without external evidence"). Lower /
  blocked states (``credential_waiting``, ``sandbox_validated``, ...) are NEVER
  flagged — the vocabulary is explicit that remaining ``code_complete`` /
  externally blocked without live credentials is an honest status, not a defect.

The readiness and certification enums are reused verbatim — no new enums are
invented here.

Naming-drift reconciliation (documented, NOT a rename — the M1 JSON values are
untouched): the vocabulary's ``acquisitionClasses`` uses ``olympus_managed``
while ``sourceScope`` elsewhere uses ``olympus_corpus``. These are two distinct
concept spaces that merely look similar. ``olympus_corpus`` names the *source
scope of a social fact* (a record observed from the Olympus corpus), whereas
``olympus_managed`` names *how a provider capability was acquired* (a UPR
capability operated by Olympus). They are not aliases of one another and must
not be renamed to match.
"""

from __future__ import annotations

from typing import Optional

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.certification import CertificationReport
from shared.integration_contracts.identity import (
    IdentityError,
    ProviderIdentity,
    parse_identity,
)
from shared.social_provider.generated_social_provider_capability_vocabulary import (
    SOCIAL_PROVIDER_CAPABILITIES,
    SOCIAL_PROVIDER_CAPABILITY_GRAMMAR,
    SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_CONTRACT_VERSION,
)

#: The vocabulary's canonical product segment (identities are
#: ``<family>.social.<capability>``).
SOCIAL_PRODUCT = "social"

_PARTNER_LIVE_VALUE = CredentialReadiness.PARTNER_LIVE.value  # "partner_live"

#: Attribute name a partner-live social plugin uses to attach the external
#: certification evidence artifact the vocabulary requires.
_PARTNER_LIVE_EVIDENCE_ATTR = "certification_report"


def _product_of(plugin: object) -> Optional[str]:
    """Return the plugin's identity ``product`` segment, or ``None`` when the
    identity cannot be read (the base §32 path already reports that failure)."""
    try:
        identity = plugin.identity()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a raising accessor is handled by the base gate
        return None
    product = getattr(identity, "product", None)
    return str(product) if product is not None else None


def _partner_live_evidence(plugin: object) -> Optional[CertificationReport]:
    """The plugin's attached external certification artifact, if any.

    ``certification_report`` may be the :class:`CertificationReport` itself or a
    zero-arg callable returning one. Anything else (``None``, a non-report) is
    treated as "no evidence" — never a silent pass.
    """
    raw = getattr(plugin, _PARTNER_LIVE_EVIDENCE_ATTR, None)
    if callable(raw):
        try:
            raw = raw()
        except Exception:  # noqa: BLE001 - a raising accessor means no evidence
            return None
    return raw if isinstance(raw, CertificationReport) else None


def social_capability_violations(plugin: object) -> list[str]:
    """Collect every M2-A social-capability violation (empty list = honest).

    Non-social plugins (``product != "social"``) always yield ``[]`` — commerce
    plugins are completely unaffected. For a social plugin this validates (a)
    capability membership, (b) grammar well-formedness and (d) partner_live
    lifecycle honesty against the generated vocabulary, reporting violations as
    strings and never raising.
    """
    violations: list[str] = []

    product = _product_of(plugin)
    if product is None:
        # Cannot read identity → the base §32 identity cross-check already
        # reports the raising accessor. Not provably social: stay out of scope.
        return violations
    if product != SOCIAL_PRODUCT:
        return violations

    try:
        identity: ProviderIdentity = plugin.identity()  # type: ignore[attr-defined]
        key = identity.key
    except Exception as exc:  # noqa: BLE001 - report, never raise
        violations.append(f"social capability check could not read identity: {exc!r}")
        return violations

    # (b) Grammar well-formedness: identity.key parses to exactly the canonical
    # family.product.capability grammar with a social product segment.
    try:
        parsed = parse_identity(key)
    except IdentityError as exc:
        violations.append(
            f"social provider identity {key!r} is not well-formed "
            f"({SOCIAL_PROVIDER_CAPABILITY_GRAMMAR}): {exc}"
        )
        return violations
    if str(parsed.product) != SOCIAL_PRODUCT:
        violations.append(
            f"social provider identity {key!r} product segment "
            f"{parsed.product!r} is not {SOCIAL_PRODUCT!r}"
        )

    # (a) Capability membership: the capability segment must be canonical.
    capability = str(identity.capability)
    if capability not in SOCIAL_PROVIDER_CAPABILITIES:
        violations.append(
            f"social provider capability {capability!r} is outside the canonical "
            f"vocabulary {sorted(SOCIAL_PROVIDER_CAPABILITIES)} "
            f"(v{SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_CONTRACT_VERSION})"
        )

    # (d) Lifecycle honesty: partner_live requires external certification
    # evidence (the manifest is read defensively — a raising manifest() was
    # already reported by the base §32 path, but never raise here either).
    manifest = None
    try:
        manifest = plugin.manifest()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        violations.append(f"social lifecycle check could not read manifest(): {exc!r}")
        return violations

    readiness = getattr(manifest, "readiness", None)
    state = getattr(readiness, "state", None)
    raw_state = getattr(state, "value", state)
    if raw_state == _PARTNER_LIVE_VALUE:
        report = _partner_live_evidence(plugin)
        if report is None:
            violations.append(
                "social provider claims lifecycle partner_live without external "
                "evidence: a passed certification_report (CertificationReport with "
                "readiness.state=PARTNER_LIVE) is required — code_complete is never "
                "promoted to partner_live without external evidence"
            )
        elif not report.passed or str(getattr(report.readiness.state, "value", report.readiness.state)) != _PARTNER_LIVE_VALUE:
            violations.append(
                "social provider claims lifecycle partner_live but its attached "
                "certification_report does not evidence partner_live (passed=all "
                "checks with readiness.state=PARTNER_LIVE)"
            )

    return violations


def assert_social_capability_honest(plugin: object) -> None:
    """Raise when a social plugin violates the M2-A capability vocabulary.

    Delegates violation aggregation to :func:`social_capability_violations`.
    Used by the runtime only when the plugin is social-scoped.
    """
    violations = social_capability_violations(plugin)
    if not violations:
        return None
    from shared.integration_contracts.plugin import PluginValidationError

    raise PluginValidationError(violations)


__all__ = [
    "SOCIAL_PRODUCT",
    "assert_social_capability_honest",
    "social_capability_violations",
]
