"""Cross-runtime drift guard for customer-critical settings contracts.

The browser uses runtime Zod validation while FastAPI owns the HTTP DTO.  These
assertions deliberately inspect both source surfaces so the historically
dangerous aliases cannot be reintroduced without failing the canonical suite.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend/aether/src/lib/api/endpoints.ts"
BILLING = ROOT / "Backend Architecture/aether-backend/services/billing/routes.py"
ME = ROOT / "Backend Architecture/aether-backend/services/me/routes.py"


def test_checkout_uses_plan_tier_not_provider_price_id() -> None:
    frontend = FRONTEND.read_text(encoding="utf-8")
    backend = BILLING.read_text(encoding="utf-8")

    checkout_client = frontend.split("createCheckout:", 1)[1].split("portal:", 1)[0]
    checkout_route = backend.split("class CheckoutRequest", 1)[1].split("class PortalRequest", 1)[0]
    assert "plan_tier" in checkout_client
    assert "price_id" not in checkout_client
    assert "plan_tier" in checkout_route


def test_invoice_and_api_key_dtos_have_one_canonical_shape() -> None:
    frontend = FRONTEND.read_text(encoding="utf-8")
    me = ME.read_text(encoding="utf-8")

    invoice_schema = frontend.split("const invoiceSchema", 1)[1].split("export type", 1)[0]
    for field in (
        "amount_due",
        "amount_paid",
        "amount_remaining",
        "hosted_invoice_url",
        "invoice_pdf_url",
    ):
        assert field in invoice_schema
    invoice_fields = {line.strip().split(":", 1)[0] for line in invoice_schema.splitlines() if ":" in line}
    assert "invoice_url" not in invoice_fields
    assert "amount" not in invoice_fields

    list_keys_client = frontend.split("listKeys:", 1)[1].split("createKey:", 1)[0]
    assert "api_keys" in list_keys_client
    assert " keys:" not in list_keys_client
    list_keys_route = me.split("async def list_my_api_keys", 1)[1].split(
        "async def create_my_api_key", 1
    )[0]
    assert '"api_keys"' in list_keys_route


def test_enterprise_company_enum_is_identical() -> None:
    frontend = (
        ROOT / "frontend/aether/src/pages/billing/billing-page.tsx"
    ).read_text(encoding="utf-8")
    backend = (
        ROOT / "Backend Architecture/aether-backend/services/contact/routes.py"
    ).read_text(encoding="utf-8")
    expected = {"startup", "smb", "enterprise", "government", "nonprofit"}

    company_line = next(line for line in frontend.splitlines() if "COMPANY_TYPES =" in line)
    assert all(f"'{value}'" in company_line for value in expected)
    assert all(f'"{value}"' in backend or f"'{value}'" in backend for value in expected)
