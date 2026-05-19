#!/usr/bin/env python3
"""Aether Platform — Stripe Connection Validator

Tests the Stripe API connection, verifies all required price IDs exist
in your Stripe account, and confirms the webhook signing secret format.

Usage:
    # Full validation against live Stripe API
    export STRIPE_SECRET_KEY=sk_live_...
    export STRIPE_PRICE_P1=price_...
    export STRIPE_PRICE_P2=price_...
    export STRIPE_PRICE_P3=price_...
    export STRIPE_PRICE_P4=price_...
    export STRIPE_WEBHOOK_SECRET=whsec_...
    python scripts/validate_stripe.py

    # Or load from a .env file
    python scripts/validate_stripe.py --env .env.production

    # Check only price IDs are reachable (skip webhook format check)
    python scripts/validate_stripe.py --skip-webhook

Checks performed:
    1. SDK installed (stripe>=10)
    2. API key format (sk_live_ or sk_test_)
    3. Stripe API connection (stripe.Account.retrieve())
    4. All four plan Price IDs exist in your Stripe account
    5. Webhook secret format (whsec_ prefix and minimum length)
    6. Overage Price ID (STRIPE_OVERAGE_PRICE_ID) if configured
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


def _load_env_file(path: str) -> None:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.split(" #")[0].strip()
            if key.strip() and val:
                os.environ.setdefault(key.strip(), val)


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f"  — {detail}"
    print(msg)
    return ok


def run(skip_webhook: bool) -> bool:
    all_pass = True

    # 1. SDK installed
    try:
        import stripe  # type: ignore
        sdk_ok = True
    except ImportError:
        sdk_ok = False
    all_pass &= _check("Stripe SDK installed", sdk_ok,
                       "pip install 'stripe>=10.0.0'" if not sdk_ok else "")
    if not sdk_ok:
        return False

    # 2. API key format
    secret_key = os.getenv("STRIPE_SECRET_KEY", "")
    key_ok = bool(secret_key and (
        secret_key.startswith("sk_live_") or secret_key.startswith("sk_test_")
    ))
    is_test = secret_key.startswith("sk_test_")
    key_detail = ""
    if not secret_key:
        key_detail = "STRIPE_SECRET_KEY not set"
    elif not key_ok:
        key_detail = "must start with sk_live_ or sk_test_"
    elif is_test:
        key_detail = "WARNING: using TEST key — use sk_live_ for production"
    all_pass &= _check("API key format", key_ok, key_detail)
    if not key_ok:
        return False

    stripe.api_key = secret_key  # type: ignore[attr-defined]

    # 3. API connectivity
    try:
        account = stripe.Account.retrieve()  # type: ignore[attr-defined]
        acct_id = account.get("id", "unknown")
        conn_ok = True
        conn_detail = f"account {acct_id}"
    except Exception as e:
        conn_ok = False
        conn_detail = str(e)
    all_pass &= _check("Stripe API connection", conn_ok, conn_detail)
    if not conn_ok:
        return False

    if is_test:
        print()
        print("  WARNING: Connected to Stripe in TEST mode.")
        print("           Prices in test mode are isolated from live mode.")
        print()

    # 4. Price IDs
    price_vars = {
        "P1 (Hobbyist)": "STRIPE_PRICE_P1",
        "P2 (Professional)": "STRIPE_PRICE_P2",
        "P3 (Growth Intelligence)": "STRIPE_PRICE_P3",
        "P4 (Protocol Master)": "STRIPE_PRICE_P4",
    }
    for label, env_var in price_vars.items():
        price_id = os.getenv(env_var, "")
        if not price_id:
            all_pass &= _check(f"Price ID {label}", False, f"{env_var} not set")
            continue
        try:
            price = stripe.Price.retrieve(price_id)  # type: ignore[attr-defined]
            currency = price.get("currency", "?").upper()
            unit_amount = price.get("unit_amount")
            recurring = price.get("recurring") or {}
            interval = recurring.get("interval", "?")
            detail = f"{price_id} — {currency} {unit_amount} / {interval}"
            if price.get("active") is False:
                detail += " (INACTIVE)"
                all_pass &= _check(f"Price ID {label}", False, detail)
            else:
                _check(f"Price ID {label}", True, detail)
        except Exception as e:
            all_pass &= _check(f"Price ID {label}", False, f"{price_id} — {e}")

    # Overage price (optional)
    overage_price_id = os.getenv("STRIPE_OVERAGE_PRICE_ID", "")
    if overage_price_id:
        try:
            stripe.Price.retrieve(overage_price_id)  # type: ignore[attr-defined]
            _check("Overage Price ID", True, overage_price_id)
        except Exception as e:
            all_pass &= _check("Overage Price ID", False, f"{overage_price_id} — {e}")
    else:
        print("  [SKIP] Overage Price ID  — STRIPE_OVERAGE_PRICE_ID not set (optional)")

    # 5. Webhook secret format
    if not skip_webhook:
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        whsec_ok = bool(webhook_secret and webhook_secret.startswith("whsec_") and len(webhook_secret) >= 32)
        whsec_detail = ""
        if not webhook_secret:
            whsec_detail = "STRIPE_WEBHOOK_SECRET not set"
        elif not webhook_secret.startswith("whsec_"):
            whsec_detail = "must start with whsec_"
        elif len(webhook_secret) < 32:
            whsec_detail = f"too short ({len(webhook_secret)} chars)"
        all_pass &= _check("Webhook secret format", whsec_ok, whsec_detail)
    else:
        print("  [SKIP] Webhook secret format check  — --skip-webhook")

    return all_pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Aether's Stripe connection and configuration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--env", metavar="ENV_FILE",
        help="Load environment variables from a .env file before checking.",
    )
    parser.add_argument(
        "--skip-webhook", action="store_true",
        help="Skip webhook signing secret format check.",
    )
    args = parser.parse_args()

    if args.env:
        _load_env_file(args.env)

    print("Aether Stripe Connection Validator")
    print("=" * 40)

    ok = run(skip_webhook=args.skip_webhook)
    print()
    if ok:
        print("All checks passed. Stripe is correctly configured.")
        print()
        print("Next steps:")
        print("  - Enable billing:  STRIPE_BILLING_ENABLED=true")
        print("  - Register webhook in Stripe Dashboard pointing to:")
        print("      POST https://<your-domain>/v1/admin/billing/stripe/webhook")
        print("  - Events to subscribe: customer.subscription.* invoice.* checkout.session.*")
    else:
        print("One or more checks FAILED. Fix the issues above before enabling Stripe.")
        sys.exit(1)


if __name__ == "__main__":
    main()
