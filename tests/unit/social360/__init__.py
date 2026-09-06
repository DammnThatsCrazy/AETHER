"""M3 Social Silver plane backend-normalization test package.

Covers the backend carriers and the six ``social_*`` Silver projectors of the
Social360 relationship-fidelity program: canonical enum alignment to the M1
``social-silver-facts.schema.json`` $defs, per-projector honesty (never fabricate
0 / friend / content hashes / canonical entity bindings), provenance stamping
(``source_scope`` / ``evidence_basis``), and dispatcher + ownership-registry
registration of the six projectors.
"""
