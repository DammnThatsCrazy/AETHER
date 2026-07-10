"""Candidate-environment checks for the staging preflight gate.

Two fail-closed layers:

1. Explicit checks over the candidate env dict, mirroring the guards in
   "Backend Architecture/aether-backend/config/settings.py"
   (``Settings.__post_init__``) plus staging-hardening rules Settings cannot
   express: no wildcard/localhost CORS, no placeholder secret values, and no
   ``AETHER_ALLOW_INMEMORY_STORE`` override (shared/store.py fail-closed
   escape hatch).
2. A subprocess that constructs the real ``Settings()`` with exactly the
   candidate environment, so this gate can never drift from actual startup
   validation. A RuntimeError raised by ``Settings.__post_init__`` becomes
   the failure detail.

The candidate environment is either the current process environment or a
KEY=VALUE file passed via ``--env-file`` (comments and blank lines ignored).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from .preflight_results import CheckResult, failed, passed

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "Backend Architecture" / "aether-backend"

# Exact env var names from config/settings.py.
ALLOWED_ENVIRONMENTS = ("staging", "production")        # Environment enum values
CORS_ENV_VAR = "CORS_ORIGINS"                           # APIConfig.cors_origins
INMEMORY_OVERRIDE_VAR = "AETHER_ALLOW_INMEMORY_STORE"   # shared/store.py override

# Secrets Settings.__post_init__ requires to be non-default in non-local envs.
REQUIRED_SECRET_VARS = (
    "JWT_SECRET",              # AuthConfig.jwt_secret
    "SDK_CONFIG_SECRET",       # SDK config signing secret (Settings.__post_init__)
    "WATERMARK_SECRET_KEY",    # ModelExtractionDefenseConfig.watermark_secret_key
    "CANARY_SECRET_SEED",      # ModelExtractionDefenseConfig.canary_secret_seed
    "EXTRACTION_CANARY_SEED",  # ExtractionMeshConfig.canary_secret_seed
)

# A var counts as secret-like when its name contains one of these markers.
SECRET_NAME_MARKERS = ("SECRET", "PASSWORD", "TOKEN", "KEY", "SEED")

# Case-insensitive substrings that mark a secret value as a placeholder.
PLACEHOLDER_SUBSTRINGS = (
    "changeme",
    "change-me",
    "dev-secret",
    "local-secret",
    "test-secret",
    "example",
    "placeholder",
)

FALSY_VALUES = ("", "0", "false", "no", "off")

SETTINGS_PROBE = "from config.settings import Settings; Settings()"

# Minimal host vars the probe subprocess needs to start the interpreter.
_SUBPROCESS_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")

SettingsRunner = Callable[[dict], "tuple[bool, str]"]


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a KEY=VALUE env file.

    Blank lines and ``#`` comments are ignored; ``export `` prefixes are
    tolerated; one layer of matching single/double quotes is stripped from
    values. Lines without ``=`` are ignored.
    """
    env: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def load_candidate_env(env_file: str | Path | None = None) -> dict[str, str]:
    """Candidate env = the process environment, or --env-file contents."""
    if env_file is None:
        return dict(os.environ)
    return parse_env_file(env_file)


def _extract_error(stderr: str, returncode: int) -> str:
    lines = [ln.strip() for ln in stderr.strip().splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "Error" in ln or "Exception" in ln:
            return ln
    if lines:
        return lines[-1]
    return f"Settings() subprocess exited {returncode} with no stderr"


def run_settings_subprocess(
    env: dict,
    *,
    backend_dir: Path = BACKEND_DIR,
    timeout: float = 120.0,
) -> tuple[bool, str]:
    """Construct the real Settings() in a subprocess under the candidate env.

    Returns (ok, detail). On failure the detail carries the RuntimeError
    raised by Settings.__post_init__ (the repo's fail-closed startup guards).
    """
    sub_env = {k: os.environ[k] for k in _SUBPROCESS_PASSTHROUGH if k in os.environ}
    sub_env.update({str(k): str(v) for k, v in env.items()})
    try:
        proc = subprocess.run(
            [sys.executable, "-c", SETTINGS_PROBE],
            cwd=str(backend_dir),
            env=sub_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"Settings() subprocess timed out after {timeout:.0f}s"
    except OSError as exc:
        return False, f"Settings() subprocess could not start: {exc}"
    if proc.returncode == 0:
        return True, "Settings() constructed successfully under the candidate environment"
    return False, _extract_error(proc.stderr, proc.returncode)


def run_env_checks(
    env: dict,
    *,
    prefix: str = "env",
    settings_runner: Optional[SettingsRunner] = None,
) -> list[CheckResult]:
    """Run all environment checks against a candidate env dict.

    Check order and names are deterministic. ``settings_runner`` exists so
    tests can replace the Settings() subprocess with a hermetic stub.
    """
    results: list[CheckResult] = []

    # 1. AETHER_ENV must target a hosted environment.
    aether_env = env.get("AETHER_ENV", "")
    name = f"{prefix}:aether-env"
    if aether_env in ALLOWED_ENVIRONMENTS:
        results.append(passed(name, f"AETHER_ENV={aether_env}"))
    else:
        results.append(failed(
            name,
            f"AETHER_ENV={aether_env!r} — must be one of: {', '.join(ALLOWED_ENVIRONMENTS)}",
            "set AETHER_ENV=staging (or production) in the deploy environment",
        ))

    # 2. In-memory durable-store override must stay off.
    name = f"{prefix}:inmemory-store-disabled"
    override = env.get(INMEMORY_OVERRIDE_VAR, "")
    if override.strip().lower() in FALSY_VALUES:
        results.append(passed(name, f"{INMEMORY_OVERRIDE_VAR} is unset/falsy"))
    else:
        results.append(failed(
            name,
            f"{INMEMORY_OVERRIDE_VAR}={override!r} — the in-memory durable-store "
            "fallback must stay disabled outside local mode",
            f"unset {INMEMORY_OVERRIDE_VAR}; hosted environments must use Redis "
            "(shared/store.py fails closed by design)",
        ))

    # 3. CORS origins must be explicit — no wildcard, no localhost.
    name = f"{prefix}:cors-origins"
    origins = [o.strip() for o in env.get(CORS_ENV_VAR, "").split(",") if o.strip()]
    if not origins:
        results.append(failed(
            name,
            f"{CORS_ENV_VAR} is not set — config/settings.py falls back to a "
            "default that includes http://localhost:3000",
            f"set {CORS_ENV_VAR} to the explicit staging origins "
            "(comma-separated, no wildcard, no localhost)",
        ))
    else:
        bad = sorted(
            o for o in origins
            if "*" in o or "localhost" in o.lower() or "127.0.0.1" in o
        )
        if bad:
            results.append(failed(
                name,
                f"{CORS_ENV_VAR} contains wildcard/localhost origins: {', '.join(bad)}",
                f"remove wildcard and localhost entries from {CORS_ENV_VAR}",
            ))
        else:
            results.append(passed(
                name, f"{len(origins)} explicit origin(s); no wildcard/localhost"
            ))

    # 4. DATABASE_URL present (Settings.__post_init__ requires it non-local).
    name = f"{prefix}:database-url"
    if env.get("DATABASE_URL", "").strip():
        results.append(passed(name, "DATABASE_URL is set"))
    else:
        results.append(failed(
            name,
            "DATABASE_URL is not set — required in non-local environments",
            "set DATABASE_URL (e.g. postgresql://aether:pass@db:5432/aether)",
        ))

    # 5. Redis configuration present (shared/store.py: REDIS_URL or REDIS_HOST).
    name = f"{prefix}:redis-config"
    if env.get("REDIS_URL", "").strip():
        results.append(passed(name, "REDIS_URL is set"))
    elif env.get("REDIS_HOST", "").strip():
        results.append(passed(name, f"REDIS_HOST={env['REDIS_HOST'].strip()}"))
    else:
        results.append(failed(
            name,
            "neither REDIS_URL nor REDIS_HOST is set — the shared durable store "
            "fails closed without Redis outside local mode",
            "set REDIS_URL or REDIS_HOST/REDIS_PORT for the staging Redis",
        ))

    # 6. JWT / signing secrets present.
    name = f"{prefix}:signing-secrets"
    missing = [v for v in REQUIRED_SECRET_VARS if not env.get(v, "").strip()]
    if aether_env == "production" and not env.get("BYOK_ENCRYPTION_KEY", "").strip():
        missing.append("BYOK_ENCRYPTION_KEY")
    if missing:
        results.append(failed(
            name,
            f"missing required secret(s): {', '.join(missing)}",
            "python scripts/generate_secrets.py and set the missing vars",
        ))
    else:
        results.append(passed(
            name, f"all {len(REQUIRED_SECRET_VARS)} required signing secrets are set"
        ))

    # 7. No placeholder values in secret-like vars.
    name = f"{prefix}:no-placeholder-secrets"
    findings: list[str] = []
    for key in sorted(env):
        upper = key.upper()
        if not any(marker in upper for marker in SECRET_NAME_MARKERS):
            continue
        value = str(env[key]).lower()
        if not value:
            continue
        hits = sorted(s for s in PLACEHOLDER_SUBSTRINGS if s in value)
        if hits:
            findings.append(f"{key} contains {', '.join(repr(h) for h in hits)}")
    if findings:
        results.append(failed(
            name,
            "placeholder value(s) in secret-like vars: " + "; ".join(findings),
            "replace placeholder secrets with real generated values "
            "(python scripts/generate_secrets.py)",
        ))
    else:
        results.append(passed(name, "no placeholder substrings in secret-like vars"))

    # 8. The real Settings() constructor accepts the candidate environment.
    name = f"{prefix}:settings-construct"
    runner = settings_runner if settings_runner is not None else run_settings_subprocess
    ok, detail = runner(env)
    if ok:
        results.append(passed(name, detail))
    else:
        results.append(failed(
            name,
            detail,
            "fix the candidate environment until config.settings.Settings() "
            "constructs (see Settings.__post_init__ guards in "
            '"Backend Architecture/aether-backend/config/settings.py")',
        ))

    return results
