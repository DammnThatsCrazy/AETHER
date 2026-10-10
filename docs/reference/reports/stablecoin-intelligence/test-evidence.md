# Stablecoin Intelligence Test Evidence

Status: local validation for PR4 service primitives.

Planned evidence commands:

- `python -m pytest tests/unit/test_stablecoin_intelligence_pr4_operations.py -q`
- `python -m pytest tests/unit/test_stablecoin_intelligence_foundation.py tests/unit/test_stablecoin_intelligence_pr2_pipeline.py tests/unit/test_stablecoin_intelligence_pr4_operations.py -q`
- `make repo-doctor-fix`
- `make ci-check`

Release blockers remain for integration, E2E, staging provider, load, chaos, backup, restore, and security validation.
