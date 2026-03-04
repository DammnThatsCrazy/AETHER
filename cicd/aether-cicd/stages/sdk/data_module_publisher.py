"""
Aether CI/CD -- SDK Data Module Publisher
Extracts TypeScript data registries into standalone JSON files and uploads
them independently of a full SDK release.

Data modules are the fast-moving reference data that the SDK consumes via
over-the-air (OTA) updates:

  - chain-registry     -- unified cross-VM chain information
  - protocol-registry  -- DeFi protocol contract addresses
  - wallet-labels      -- known wallet address labels (CEX, whale, etc.)
  - wallet-classification -- classification rules (RDNS sets, wallet types)

Workflow:
  1. Read pre-generated JSON from packages/web/src/web3/data-modules/ (or
     extract from TypeScript sources as a fallback).
  2. Stamp each module with a date-based version (e.g. "2026.03.04").
  3. Calculate SHA-256 integrity hashes.
  4. Upload versioned + latest copies to S3.
  5. Regenerate SDK manifests so all platforms pick up the new data.

All heavy lifting is done through the shared runner -- no direct subprocess
calls in this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.pipeline_config import SDK_RELEASE_TARGETS
from shared.runner import run_cmd, log

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

STAGE = "SDK-DATA"

# Mapping of module key -> (TypeScript source path relative to web_src_dir,
#                           output directory name on CDN)
_MODULE_SOURCES: Dict[str, Dict[str, str]] = {
    "chain-registry": {
        "ts_path": "web3/chains/chain-registry.ts",
        "cdn_dir": "chain-registry",
    },
    "protocol-registry": {
        "ts_path": "web3/defi/protocol-registry.ts",
        "cdn_dir": "protocol-registry",
    },
    "wallet-labels": {
        "ts_path": "web3/wallet/wallet-labels.ts",
        "cdn_dir": "wallet-labels",
    },
    "wallet-classification": {
        "ts_path": "web3/wallet/wallet-classifier.ts",
        "cdn_dir": "wallet-classification",
    },
}

DEFAULT_CDN_BASE = "https://cdn.aether.network"


# --------------------------------------------------------------------------- #
# Hashing helpers
# --------------------------------------------------------------------------- #

def _sha256_bytes(data: bytes) -> str:
    """Return hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    """Return hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Date-based versioning
# --------------------------------------------------------------------------- #

def _date_version() -> str:
    """
    Generate a date-stamped version string.
    Format: YYYY.MM.DD (e.g. "2026.03.04").
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y.%m.%d")


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

def extract_data_modules(web_src_dir: str) -> Dict[str, Dict[str, Any]]:
    """
    Extract data modules from the pre-generated data-modules directory, or
    fall back to reading from TypeScript source files.

    The build system is expected to produce JSON files under a ``data-modules/``
    directory adjacent to the web source.  If those files exist, they are used
    directly.  Otherwise this function reads the TypeScript files and extracts
    the exportable data structures into JSON.

    Args:
        web_src_dir:  Path to ``packages/web/src`` (the root of the web
                      package source tree).

    Returns:
        Dict keyed by module name (e.g. "chain-registry") with:
          - "data":  The extracted JSON-serialisable data dict.
          - "source": Path to the source file used.
          - "size":  Size of the serialised JSON in bytes.
          - "hash":  SHA-256 hex digest of the serialised JSON.
    """
    log(f"Extracting data modules from {web_src_dir}", stage=STAGE)

    src_path = Path(web_src_dir)
    data_modules_dir = src_path.parent / "data-modules"

    results: Dict[str, Dict[str, Any]] = {}

    for module_name, meta in _MODULE_SOURCES.items():
        # Prefer pre-generated JSON
        pre_gen = data_modules_dir / module_name / "data.json"
        ts_source = src_path / meta["ts_path"]

        if pre_gen.exists():
            log(f"Using pre-generated data for {module_name}: {pre_gen}", stage=STAGE)
            try:
                with open(pre_gen, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                log(f"Failed to read pre-generated {pre_gen}: {exc}", stage=STAGE)
                data = _extract_from_typescript(str(ts_source), module_name)
            source = str(pre_gen)
        elif ts_source.exists():
            log(f"Pre-generated data not found, extracting from TS: {ts_source}", stage=STAGE)
            data = _extract_from_typescript(str(ts_source), module_name)
            source = str(ts_source)
        else:
            log(f"WARNING: No source found for {module_name}", stage=STAGE)
            data = {}
            source = ""

        # Serialise for hashing and sizing
        serialised = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")

        results[module_name] = {
            "data": data,
            "source": source,
            "size": len(serialised),
            "hash": f"sha256:{_sha256_bytes(serialised)}",
        }

        entry_count = len(data) if isinstance(data, dict) else 0
        log(
            f"Extracted {module_name}: {entry_count} entries, "
            f"{len(serialised)} bytes",
            stage=STAGE,
        )

    return results


def _extract_from_typescript(ts_path: str, module_name: str) -> dict:
    """
    Best-effort extraction of data from a TypeScript source file.

    This is a fallback for when the build system has not produced
    pre-generated JSON.  It reads the TS file and attempts to parse
    exported const object literals into Python dicts.

    For production use the pre-generated JSON path is strongly preferred.
    """
    try:
        with open(ts_path, "r") as f:
            content = f.read()
    except OSError as exc:
        log(f"Cannot read {ts_path}: {exc}", stage=STAGE)
        return {}

    # Strategy: find the first large exported Record/object and extract
    # a summary rather than trying to fully parse TS.
    data: Dict[str, Any] = {
        "_module": module_name,
        "_source": ts_path,
        "_extractedAt": datetime.now(timezone.utc).isoformat(),
        "_note": "Extracted from TypeScript source (fallback mode)",
    }

    # Count exported entries by looking for top-level object keys
    # Pattern: 'key': { or "key": {
    key_pattern = re.compile(r"^\s+['\"]([^'\"]+)['\"]\s*:\s*\{", re.MULTILINE)
    keys = key_pattern.findall(content)
    data["_entryCount"] = len(keys)

    if module_name == "chain-registry":
        # Extract chain IDs and names
        chain_pattern = re.compile(
            r"chainId:\s*['\"]([^'\"]+)['\"].*?name:\s*['\"]([^'\"]+)['\"]",
            re.DOTALL,
        )
        chains = chain_pattern.findall(content)
        data["chains"] = {cid: name for cid, name in chains}

    elif module_name == "protocol-registry":
        # Extract protocol names and categories
        proto_pattern = re.compile(
            r"['\"](\w+)['\"]\s*:\s*\{\s*name:\s*['\"]([^'\"]+)['\"]"
            r".*?category:\s*['\"]([^'\"]+)['\"]",
            re.DOTALL,
        )
        protos = proto_pattern.findall(content)
        data["protocols"] = {
            pid: {"name": name, "category": cat}
            for pid, name, cat in protos
        }

    elif module_name == "wallet-labels":
        # Extract address -> label name mappings
        label_pattern = re.compile(
            r"['\"]?(0x[a-fA-F0-9]{40})['\"]?\s*:\s*\{[^}]*name:\s*['\"]([^'\"]+)['\"]",
        )
        labels = label_pattern.findall(content)
        data["labels"] = {addr.lower(): name for addr, name in labels}

    elif module_name == "wallet-classification":
        # Extract known RDNS sets
        rdns_pattern = re.compile(r"['\"]([a-z]+\.[a-z.]+)['\"]")
        rdns_entries = rdns_pattern.findall(content)
        data["knownRdns"] = sorted(set(rdns_entries))

    return data


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #

def publish_data_modules(
    web_src_dir: str,
    cdn_base: str = DEFAULT_CDN_BASE,
    version: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Extract, version-stamp, hash, upload, and regenerate manifests for all
    data modules.

    Args:
        web_src_dir:  Path to ``packages/web/src``.
        cdn_base:     CDN base URL.
        version:      Override version string.  Defaults to date-stamp
                      (e.g. "2026.03.04").
        dry_run:      If True, extract and hash but skip S3 upload and
                      CloudFront invalidation.

    Returns:
        Dict keyed by module name with upload results and metadata.
    """
    version = version or _date_version()
    log(f"Publishing data modules, version={version}, dry_run={dry_run}", stage=STAGE)

    # Step 1 -- Extract
    modules = extract_data_modules(web_src_dir)

    results: Dict[str, Dict[str, Any]] = {}
    cf_paths: List[str] = []
    output_dir = Path("/tmp/aether-data-modules")
    output_dir.mkdir(parents=True, exist_ok=True)

    for module_name, module_info in modules.items():
        cdn_dir = _MODULE_SOURCES[module_name]["cdn_dir"]
        data = module_info["data"]

        # Step 2 -- Stamp with version metadata
        stamped_data = {
            **data,
            "_version": version,
            "_generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        serialised = json.dumps(stamped_data, indent=2, sort_keys=True)
        serialised_bytes = serialised.encode("utf-8")
        sha = _sha256_bytes(serialised_bytes)
        size = len(serialised_bytes)

        # Write local files
        module_out = output_dir / cdn_dir
        module_out.mkdir(parents=True, exist_ok=True)

        versioned_path = module_out / f"{version}.json"
        latest_path = module_out / "latest.json"

        for p in (versioned_path, latest_path):
            with open(p, "w") as f:
                f.write(serialised)

        log(
            f"{module_name}: version={version}, "
            f"hash=sha256:{sha[:16]}..., size={size} bytes",
            stage=STAGE,
        )

        # Step 3 -- Upload to S3
        s3_base = f"s3://cdn.aether.network/sdk/data/{cdn_dir}"
        s3_versioned = f"{s3_base}/{version}.json"
        s3_latest = f"{s3_base}/latest.json"

        upload_ok = True
        if dry_run:
            log(f"[DRY RUN] Would upload {versioned_path} -> {s3_versioned}", stage=STAGE)
            log(f"[DRY RUN] Would upload {latest_path} -> {s3_latest}", stage=STAGE)
        else:
            for local, remote in [
                (str(versioned_path), s3_versioned),
                (str(latest_path), s3_latest),
            ]:
                result = run_cmd(
                    f"aws s3 cp {local} {remote} "
                    f"--content-type application/json "
                    f"--cache-control 'public, max-age=300'",
                    timeout=60,
                )
                if result.success:
                    log(f"Uploaded: {remote}", stage=STAGE)
                else:
                    log(f"FAILED upload {remote}: {result.stderr[:200]}", stage=STAGE)
                    upload_ok = False

        cf_paths.append(f"/sdk/data/{cdn_dir}/{version}.json")
        cf_paths.append(f"/sdk/data/{cdn_dir}/latest.json")

        results[module_name] = {
            "version": version,
            "hash": f"sha256:{sha}",
            "size": size,
            "s3_versioned": s3_versioned,
            "s3_latest": s3_latest,
            "upload_success": upload_ok,
            "local_path": str(versioned_path),
        }

    # Step 4 -- Invalidate CloudFront
    if not dry_run and cf_paths:
        _invalidate_cloudfront_data(cf_paths)
    elif dry_run:
        log(f"[DRY RUN] Would invalidate {len(cf_paths)} CloudFront paths", stage=STAGE)

    # Step 5 -- Regenerate manifests so they reference the new data versions
    log("Regenerating SDK manifests with updated data module references", stage=STAGE)
    _regenerate_manifests(str(output_dir), cdn_base, dry_run)

    log(f"Data module publishing complete: {len(results)} modules, version={version}", stage=STAGE)
    return results


def _invalidate_cloudfront_data(paths: List[str]) -> bool:
    """Create a CloudFront invalidation for data module paths."""
    dist_id = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "")
    if not dist_id:
        log("CLOUDFRONT_DISTRIBUTION_ID not set, skipping invalidation", stage=STAGE)
        return False

    paths_arg = " ".join(paths)
    result = run_cmd(
        f"aws cloudfront create-invalidation "
        f"--distribution-id {dist_id} "
        f"--paths {paths_arg}",
        timeout=30,
    )
    if result.success:
        log(f"CloudFront invalidation created for {len(paths)} data paths", stage=STAGE)
    else:
        log(f"CloudFront invalidation failed: {result.stderr[:200]}", stage=STAGE)
    return result.success


def _regenerate_manifests(
    data_modules_dir: str,
    cdn_base: str,
    dry_run: bool,
) -> None:
    """
    Regenerate SDK manifests after data modules are published.

    Imports manifest_publisher lazily to avoid circular imports.
    """
    try:
        from stages.sdk.manifest_publisher import publish_manifests

        # Read SDK version from package.json or fallback
        sdk_version = _read_sdk_version()
        publish_manifests(
            sdk_version=sdk_version,
            cdn_base=cdn_base,
            data_modules_dir=data_modules_dir,
            dry_run=dry_run,
        )
    except Exception as exc:
        log(f"Manifest regeneration failed: {exc}", stage=STAGE)
        # Non-fatal: data modules are already published, manifests can be
        # regenerated separately.


def _read_sdk_version() -> str:
    """
    Read the current SDK version from packages/sdk-web/package.json.
    Falls back to "0.0.0" if unavailable.
    """
    pkg_path = "packages/sdk-web/package.json"
    try:
        with open(pkg_path, "r") as f:
            pkg = json.load(f)
        return pkg.get("version", "0.0.0")
    except (OSError, json.JSONDecodeError):
        log(f"Could not read SDK version from {pkg_path}, using 0.0.0", stage=STAGE)
        return "0.0.0"
