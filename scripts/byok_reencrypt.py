#!/usr/bin/env python3
"""
BYOK Encryption Key Rotation — Re-encrypt all provider_api_keys rows.

Safely rotates the BYOK_ENCRYPTION_KEY without downtime by re-encrypting
every stored tenant API key from the old Fernet key to the new one.

ROTATION PROCEDURE (zero downtime):
  Step 1  Generate new key:
            python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

  Step 2  Deploy with both keys set:
            BYOK_ENCRYPTION_KEY=<new-key>
            BYOK_ENCRYPTION_KEY_PREVIOUS=<old-key>
          The vault will decrypt with either key, so live traffic is unaffected.

  Step 3  Run this script:
            python scripts/byok_reencrypt.py \\
              --old-key <old-key> --new-key <new-key> \\
              --db-url postgresql://user:pass@host/db

  Step 4  Verify (dry-run should report 0 rows needing rotation):
            python scripts/byok_reencrypt.py \\
              --old-key <old-key> --new-key <new-key> \\
              --db-url postgresql://user:pass@host/db --dry-run

  Step 5  Remove BYOK_ENCRYPTION_KEY_PREVIOUS and redeploy.

SAFETY PROPERTIES:
  - Each row is updated in its own transaction; a failure leaves prior rows
    already re-encrypted and does not corrupt them.
  - The script is idempotent: rows already encrypted with the new key are
    detected and skipped automatically.
  - --dry-run never writes to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

try:
    import asyncpg
except ImportError:
    print("ERROR: asyncpg not installed. Run: pip install asyncpg", file=sys.stderr)
    sys.exit(1)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    print("ERROR: cryptography not installed. Run: pip install cryptography>=42.0", file=sys.stderr)
    sys.exit(1)


def _build_fernet(key: str, label: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except Exception as e:
        print(f"ERROR: Invalid {label}: {e}", file=sys.stderr)
        sys.exit(1)


async def reencrypt(
    db_url: str,
    old_key: str,
    new_key: str,
    batch_size: int,
    dry_run: bool,
    verbose: bool,
) -> int:
    """Re-encrypt all provider_api_keys rows. Returns count of rows updated."""
    old_fernet = _build_fernet(old_key, "--old-key")
    new_fernet = _build_fernet(new_key, "--new-key")

    conn: asyncpg.Connection = await asyncpg.connect(db_url)
    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM provider_api_keys")
        print(f"provider_api_keys: {total} total rows")

        offset = 0
        updated = 0
        skipped = 0
        errors = 0

        while True:
            rows = await conn.fetch(
                "SELECT id, tenant_id, provider_name, encrypted_key "
                "FROM provider_api_keys ORDER BY created_at, id "
                "LIMIT $1 OFFSET $2",
                batch_size,
                offset,
            )
            if not rows:
                break

            for row in rows:
                row_id = row["id"]
                tenant = row["tenant_id"]
                provider = row["provider_name"]
                ciphertext: str = row["encrypted_key"]

                # Attempt to decrypt with new key first — already rotated, skip.
                try:
                    new_fernet.decrypt(ciphertext.encode())
                    if verbose:
                        print(f"  SKIP  {tenant}/{provider} — already encrypted with new key")
                    skipped += 1
                    continue
                except InvalidToken:
                    pass

                # Decrypt with old key.
                try:
                    plaintext = old_fernet.decrypt(ciphertext.encode()).decode()
                except InvalidToken:
                    print(
                        f"  ERROR {tenant}/{provider} (id={row_id}) — "
                        "cannot decrypt with either key; manual intervention required",
                        file=sys.stderr,
                    )
                    errors += 1
                    continue

                new_ciphertext = new_fernet.encrypt(plaintext.encode()).decode()

                if dry_run:
                    if verbose:
                        print(f"  DRY   {tenant}/{provider} — would re-encrypt")
                    updated += 1
                    continue

                try:
                    async with conn.transaction():
                        await conn.execute(
                            "UPDATE provider_api_keys SET encrypted_key=$1, updated_at=NOW() WHERE id=$2",
                            new_ciphertext,
                            row_id,
                        )
                    if verbose:
                        print(f"  OK    {tenant}/{provider}")
                    updated += 1
                except Exception as exc:
                    print(f"  ERROR {tenant}/{provider} — DB update failed: {exc}", file=sys.stderr)
                    errors += 1

            offset += batch_size

        label = "would update" if dry_run else "updated"
        print(
            f"\nDone: {label} {updated}, skipped {skipped} (already rotated), {errors} errors"
        )
        if errors:
            print(
                "Some rows could not be re-encrypted. Check logs above. "
                "Do NOT remove BYOK_ENCRYPTION_KEY_PREVIOUS until all errors are resolved.",
                file=sys.stderr,
            )
        return errors

    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-encrypt BYOK provider_api_keys rows during key rotation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--old-key", required=True, help="Current (old) Fernet encryption key")
    parser.add_argument("--new-key", required=True, help="New Fernet encryption key to rotate to")
    parser.add_argument(
        "--db-url",
        default="",
        help="PostgreSQL DSN (default: reads TSDB_URL or constructs from TSDB_* env vars)",
    )
    parser.add_argument("--batch-size", type=int, default=100, help="Rows per batch (default: 100)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print one line per row")
    args = parser.parse_args()

    if not args.db_url:
        import os
        args.db_url = os.getenv("TSDB_URL", "")
        if not args.db_url:
            host = os.getenv("TSDB_HOST", "localhost")
            port = os.getenv("TSDB_PORT", "5432")
            db = os.getenv("TSDB_DATABASE", "aether")
            user = os.getenv("TSDB_USER", "aether")
            pw = os.getenv("TSDB_PASSWORD", "")
            args.db_url = f"postgresql://{user}:{pw}@{host}:{port}/{db}"

    if args.dry_run:
        print("DRY RUN — no changes will be written to the database\n")

    errors = asyncio.run(
        reencrypt(
            db_url=args.db_url,
            old_key=args.old_key,
            new_key=args.new_key,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
