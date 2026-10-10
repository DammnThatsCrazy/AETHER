"""Demo-seed error types shared across the demo-seed modules.

``SeedPolicyError`` gates on environment configuration (production/staging
refusals, DATABASE_URL binding); ``SeedSafetyError`` guards data-integrity
invariants (ownership mismatches, overwrite refusal, the M8-C1 process-local
DurableStore guard). Both are imported by ``policy`` and ``service`` and
re-exported from ``service`` for back-compat with existing imports.
"""


class SeedPolicyError(RuntimeError):
    pass


class SeedSafetyError(RuntimeError):
    pass
