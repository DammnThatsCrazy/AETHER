#!/usr/bin/env python3
"""Print the public key that client SDKs use to verify signed SDK manifests.

The backend signs manifests with a P-256 key derived from ``SDK_CONFIG_SECRET``
(see docs/reference/sdks/manifest-signing.md). The secret never leaves the
server; paste the output of this script into the SDK config instead:

    web      Aether.init({ ..., advanced: { manifestPublicKey: "<key>" } })
    iOS      AetherConfig.manifestPublicKey = "<key>"
    Android  AetherConfig(manifestPublicKey = "<key>")

Usage:
    SDK_CONFIG_SECRET=... python scripts/sdk_manifest_public_key.py
    python scripts/sdk_manifest_public_key.py --secret-env OTHER_ENV_VAR

Rotating ``SDK_CONFIG_SECRET`` changes the key: ship the new public key in an app
update before (or together with) rotating, because clients that hold the old key
will reject manifests signed by the new one and keep their last known-good config.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from ingestion.sdk_config import manifest_signing  # noqa: E402

_DEV_SECRET = "default-dev-secret-change-in-production"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--secret-env", default="SDK_CONFIG_SECRET", help="environment variable holding the secret")
    args = parser.parse_args()

    secret = os.environ.get(args.secret_env)
    if not secret:
        print(f"error: {args.secret_env} is not set", file=sys.stderr)
        return 2
    if secret == _DEV_SECRET:
        print("warning: this is the development default secret; do not ship its key", file=sys.stderr)
    key = manifest_signing.derive_private_key(secret)
    print(manifest_signing.public_key_spki_b64url(key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
