"""The Aether app's SSO callback request body matches the API's model.

The app sent ``{ jwt }`` while ``POST /v1/auth/sso/callback`` requires
``token``, so every Auth0 sign-in on staging was rejected with 422
"Field required: token". Nothing tested either side of the call.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "services/backend/services/auth/routes.py"
ENDPOINTS = ROOT / "frontend/aether/src/lib/api/endpoints.ts"


def _model_fields(name: str) -> tuple[set[str], set[str]]:
    """(all fields, required fields) of a pydantic model in routes.py."""
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    model = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    fields: set[str] = set()
    required: set[str] = set()
    for stmt in model.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields.add(stmt.target.id)
            value = stmt.value
            is_required = value is None or (
                isinstance(value, ast.Call)
                and getattr(value.func, "id", "") == "Field"
                and value.args
                and isinstance(value.args[0], ast.Constant)
                and value.args[0].value is Ellipsis
            )
            if is_required:
                required.add(stmt.target.id)
    return fields, required


def _sent_body_keys() -> set[str]:
    text = ENDPOINTS.read_text(encoding="utf-8")
    call = re.search(r"post\('/v1/auth/sso/callback',\s*[^,]+,\s*\{([^}]*)\}", text)
    assert call, "ssoCallback request not found in endpoints.ts"
    keys = set()
    for part in call.group(1).split(","):
        part = part.strip()
        if part:
            keys.add(part.split(":")[0].strip())
    return keys


def test_app_sends_every_required_field_and_nothing_unknown():
    fields, required = _model_fields("SSOCallbackRequest")
    sent = _sent_body_keys()
    assert required <= sent, f"missing required fields: {required - sent}"
    assert sent <= fields, f"fields the API does not accept: {sent - fields}"
