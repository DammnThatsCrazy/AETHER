"""Assert the ADR-008 Model Runtime config is documented in .env.example (D8/D9).

The model runtime (services/model_runtime) reads the MODEL_RUNTIME_* variables
documented below. Every variable the module reads must appear here, the
production-required ones must carry the [REQUIRED IN PRODUCTION] marker, and the
section must NEVER contain real credentials — only empty/neutral placeholders.
"""

from __future__ import annotations

from pathlib import Path

# The backend example may live either at
#   Backend Architecture/aether-backend/.env.example
# or, when that file is absent, at the repo root .env.example. Resolve from this
# test file's own location and use whichever exists.
_BACKEND_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
_ROOT_ENV_EXAMPLE = Path(__file__).resolve().parents[4] / ".env.example"

_SECTION_HEADER = "# === Model Runtime — Multi-Model Intelligence Harness (ADR-008) ==="

# Exactly the variables read by services/model_runtime/config.py.
_DOCUMENTED_VARS: tuple[str, ...] = (
    "MODEL_RUNTIME_ENABLED",
    "MODEL_RUNTIME_DEFAULT_PROVIDER",
    "MODEL_RUNTIME_ESTIMATED_REQUEST_TOKENS",
    "MODEL_RUNTIME_MAX_PROVIDERS",
    "MODEL_RUNTIME_CREDENTIAL_BACKEND",
    "MODEL_RUNTIME_CREDENTIAL_AWS_REGION",
    "MODEL_RUNTIME_CREDENTIAL_AWS_PREFIX",
    "MODEL_RUNTIME_CREDENTIAL_CACHE_TTL_SECONDS",
    "MODEL_RUNTIME_OBSERVABILITY_ENABLED",
    "MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD",
    "MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S",
    "MODEL_RUNTIME_ADAPTERS_DIR",
)

# Documented defaults. A documented line is either `NAME=` (empty placeholder) or
# `NAME=<this documented default>`; a value other than the documented default
# would be a real secret left in the example file.
_DOCUMENTED_DEFAULTS: dict[str, str] = {
    "MODEL_RUNTIME_ENABLED": "false",
    "MODEL_RUNTIME_DEFAULT_PROVIDER": "deterministic",
    "MODEL_RUNTIME_ESTIMATED_REQUEST_TOKENS": "800",
    "MODEL_RUNTIME_MAX_PROVIDERS": "16",
    "MODEL_RUNTIME_CREDENTIAL_BACKEND": "in_memory",
    "MODEL_RUNTIME_CREDENTIAL_AWS_REGION": "",
    "MODEL_RUNTIME_CREDENTIAL_AWS_PREFIX": "aether/credentials",
    "MODEL_RUNTIME_CREDENTIAL_CACHE_TTL_SECONDS": "60",
    "MODEL_RUNTIME_OBSERVABILITY_ENABLED": "false",
    "MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD": "5",
    "MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S": "60",
    "MODEL_RUNTIME_ADAPTERS_DIR": "services/model_runtime/adapters",
}

_REQUIRED_MARKED_VARS: tuple[str, ...] = (
    "MODEL_RUNTIME_CREDENTIAL_BACKEND",
    "MODEL_RUNTIME_CREDENTIAL_AWS_REGION",
)

# Secret-shaped markers that must never appear anywhere in the model-runtime
# section, even in comments (sk- and AKIA are provider-key / AWS-key prefixes).
_SECRET_SHAPED_MARKERS: tuple[str, ...] = (
    "sk-",
    "AKIA",
    "-----BEGIN",
    "aws_secret_access_key",
    "secret_key",
)


def _env_example() -> Path:
    if _BACKEND_ENV_EXAMPLE.exists():
        return _BACKEND_ENV_EXAMPLE
    return _ROOT_ENV_EXAMPLE


def _model_runtime_section(text: str) -> list[str]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == _SECTION_HEADER:
            return lines[i + 1 :]
    raise AssertionError(f"model runtime section header not found: {_SECTION_HEADER!r}")


def test_env_example_is_reachable():
    assert _env_example().is_file(), f"no .env.example found at {_env_example()}"


def test_all_documented_vars_present():
    text = _env_example().read_text(encoding="utf-8")
    for name in _DOCUMENTED_VARS:
        assert f"{name}=" in text, f"missing documented variable: {name}"


def test_required_in_production_markers_present():
    text = _env_example().read_text(encoding="utf-8")
    for name in _REQUIRED_MARKED_VARS:
        line = next(
            (ln for ln in text.splitlines() if ln.startswith(f"{name}=")),
            "",
        )
        assert line, f"no definition line for required variable: {name}"
        assert (
            "[REQUIRED IN PRODUCTION]" in line
        ), f"{name} must carry the [REQUIRED IN PRODUCTION] marker"


def test_no_secret_shaped_values_in_model_runtime_section():
    text = _env_example().read_text(encoding="utf-8")
    section = _model_runtime_section(text)

    for marker in _SECRET_SHAPED_MARKERS:
        assert not any(marker in line for line in section), (
            f"secret-shaped marker {marker!r} found in model-runtime section"
        )

    # Every variable line must be NAME= or NAME=<documented default>; any other
    # non-empty value would be a real secret placed in the example file.
    # Values never contain '#', so strip the aligned trailing comment first.
    for line in section:
        if not line.startswith("MODEL_RUNTIME_"):
            continue
        name, rest = line.split("=", 1)
        if " # " in rest:
            rest = rest.split("#", 1)[0]
        value = rest.strip()
        assert name in _DOCUMENTED_DEFAULTS, f"undocumented variable line: {line}"
        documented = _DOCUMENTED_DEFAULTS[name]
        assert value == documented, (
            f"{name} has value {value!r}; expected documented default {documented!r}"
        )
