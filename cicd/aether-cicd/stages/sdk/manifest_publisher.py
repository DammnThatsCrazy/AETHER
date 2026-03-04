"""
Aether CI/CD -- SDK Manifest Publisher
Generates per-platform SDK manifest JSON files and uploads them to CDN.

Each platform (web, ios, android, react-native) gets its own manifest at:
  s3://cdn.aether.network/sdk/manifests/{platform}/latest.json

The manifest tells each SDK client:
  - What the latest version is and the minimum supported version
  - Where to download SDK bundles and data modules
  - SHA-256 hashes for integrity verification
  - Feature flags for remote configuration
  - How often to check for updates

After upload the corresponding CloudFront paths are invalidated so
edge caches serve fresh manifests immediately.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.pipeline_config import SDK_RELEASE_TARGETS
from shared.runner import run_cmd, log

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

STAGE = "SDK-MANIFEST"

PLATFORMS = ["web", "ios", "android", "react-native"]

DEFAULT_CDN_BASE = "https://cdn.aether.network"

# Data modules that every manifest references
DATA_MODULE_NAMES = [
    "chainRegistry",
    "protocolRegistry",
    "walletLabels",
    "walletClassification",
]

# Map manifest module key -> filename on CDN
_MODULE_FILE_MAP: Dict[str, str] = {
    "chainRegistry": "chain-registry",
    "protocolRegistry": "protocol-registry",
    "walletLabels": "wallet-labels",
    "walletClassification": "wallet-classification",
}

# Default check interval per platform (ms)
_CHECK_INTERVAL: Dict[str, int] = {
    "web": 3_600_000,          # 1 hour
    "ios": 14_400_000,         # 4 hours
    "android": 14_400_000,     # 4 hours
    "react-native": 7_200_000, # 2 hours
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _sha256_file(path: str) -> str:
    """Return hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_size(path: str) -> int:
    """Return file size in bytes."""
    return os.path.getsize(path)


def _collect_data_module_info(
    data_modules_dir: str,
    cdn_base: str,
) -> Dict[str, Dict[str, Any]]:
    """
    Scan the data-modules output directory and collect version, hash, and
    size metadata for each module.

    Expects files named like:
      data_modules_dir/{module}/latest.json

    Returns a dict keyed by manifest module name (camelCase).
    """
    modules: Dict[str, Dict[str, Any]] = {}
    dm_path = Path(data_modules_dir)

    for module_key, file_stem in _MODULE_FILE_MAP.items():
        latest_file = dm_path / file_stem / "latest.json"
        if not latest_file.exists():
            log(f"Data module file not found: {latest_file}", stage=STAGE)
            # Provide a placeholder so the manifest is still valid
            modules[module_key] = {
                "version": "0.0.0",
                "url": f"{cdn_base}/sdk/data/{file_stem}/latest.json",
                "hash": "",
                "size": 0,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            continue

        file_str = str(latest_file)
        sha = _sha256_file(file_str)
        size = _file_size(file_str)

        # Try to read the embedded version from the JSON itself
        try:
            with open(latest_file, "r") as f:
                data = json.load(f)
            version = data.get("_version", data.get("version", "unknown"))
            updated_at = data.get("_generatedAt", datetime.now(timezone.utc).isoformat())
        except (json.JSONDecodeError, OSError):
            version = "unknown"
            updated_at = datetime.now(timezone.utc).isoformat()

        modules[module_key] = {
            "version": str(version),
            "url": f"{cdn_base}/sdk/data/{file_stem}/latest.json",
            "hash": f"sha256:{sha}",
            "size": size,
            "updatedAt": updated_at,
        }

    return modules


# --------------------------------------------------------------------------- #
# Manifest generation
# --------------------------------------------------------------------------- #

def generate_manifest(
    platform: str,
    sdk_version: str,
    data_modules_info: Dict[str, Dict[str, Any]],
    cdn_base: str = DEFAULT_CDN_BASE,
) -> dict:
    """
    Generate a manifest dict for a single platform.

    Args:
        platform:           One of web, ios, android, react-native.
        sdk_version:        The current SDK release version (semver string).
        data_modules_info:  Dict of data-module metadata from _collect_data_module_info.
        cdn_base:           CDN base URL (no trailing slash).

    Returns:
        A dict ready to be serialised as JSON and uploaded.
    """
    now = datetime.now(timezone.utc).isoformat()

    manifest: Dict[str, Any] = {
        "latestVersion": sdk_version,
        "minimumVersion": _derive_minimum_version(sdk_version),
        "updateUrgency": "normal",
        "featureFlags": _default_feature_flags(platform),
        "dataModules": {},
        "checkIntervalMs": _CHECK_INTERVAL.get(platform, 3_600_000),
        "generatedAt": now,
    }

    # Web platform gets SDK bundle download URLs
    if platform == "web":
        manifest["downloads"] = {
            "sdkBundleUrl": f"{cdn_base}/sdk/{sdk_version}/aether-sdk.esm.min.js",
            "sdkBundleHash": "",  # populated during release from actual artifact
            "sdkBundleSize": 0,
        }
        # Try to resolve actual bundle hash if the file exists locally
        local_bundle = f"packages/sdk-web/dist/aether-sdk.esm.min.js"
        if os.path.isfile(local_bundle):
            manifest["downloads"]["sdkBundleHash"] = f"sha256:{_sha256_file(local_bundle)}"
            manifest["downloads"]["sdkBundleSize"] = _file_size(local_bundle)

    # Data modules -- identical across platforms
    for module_key in DATA_MODULE_NAMES:
        if module_key in data_modules_info:
            manifest["dataModules"][module_key] = data_modules_info[module_key]
        else:
            # Provide an empty stub so clients don't crash
            manifest["dataModules"][module_key] = {
                "version": "0.0.0",
                "url": "",
                "hash": "",
                "size": 0,
                "updatedAt": now,
            }

    return manifest


def _derive_minimum_version(latest: str) -> str:
    """
    Derive minimum supported version from the latest version.
    Policy: minimum = latest major with minor 0, patch 0.
    e.g. 5.2.3 -> 5.0.0
    """
    parts = latest.split(".")
    if len(parts) >= 1:
        try:
            major = int(parts[0].lstrip("v"))
            return f"{major}.0.0"
        except ValueError:
            pass
    return "1.0.0"


def _default_feature_flags(platform: str) -> Dict[str, bool]:
    """Return default feature flags per platform."""
    base_flags = {
        "otaDataUpdates": True,
        "remoteConfig": True,
        "telemetry": True,
    }
    if platform == "web":
        base_flags["serviceWorkerCache"] = True
    return base_flags


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #

def publish_manifests(
    sdk_version: str,
    cdn_base: str = DEFAULT_CDN_BASE,
    data_modules_dir: str = "data-modules",
    dry_run: bool = False,
) -> Dict[str, dict]:
    """
    Generate and publish manifest files for all platforms.

    Workflow:
      1. Collect data-module metadata from the local data-modules/ directory.
      2. Generate a manifest JSON for each platform.
      3. Upload each manifest to S3.
      4. Invalidate CloudFront cache for the manifest paths.

    Args:
        sdk_version:      Current SDK version string.
        cdn_base:         CDN base URL.
        data_modules_dir: Path to the directory containing extracted data modules.
        dry_run:          If True, generate manifests but skip upload and invalidation.

    Returns:
        Dict mapping platform name to the generated manifest dict.
    """
    log(f"Publishing manifests for SDK v{sdk_version}", stage=STAGE)

    # Step 1 -- Collect data module info
    data_info = _collect_data_module_info(data_modules_dir, cdn_base)
    log(f"Collected metadata for {len(data_info)} data modules", stage=STAGE)

    results: Dict[str, dict] = {}
    s3_paths: List[str] = []
    cf_paths: List[str] = []

    for platform in PLATFORMS:
        # Step 2 -- Generate manifest
        manifest = generate_manifest(platform, sdk_version, data_info, cdn_base)
        results[platform] = manifest

        # Write manifest to a local temp file
        local_path = f"/tmp/aether-manifest-{platform}.json"
        with open(local_path, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=False)

        log(f"Generated manifest for {platform} ({os.path.getsize(local_path)} bytes)", stage=STAGE)

        # Step 3 -- Upload to S3
        s3_key = f"sdk/manifests/{platform}/latest.json"
        s3_uri = f"s3://cdn.aether.network/{s3_key}"
        s3_paths.append(s3_uri)
        cf_paths.append(f"/{s3_key}")

        if dry_run:
            log(f"[DRY RUN] Would upload {local_path} -> {s3_uri}", stage=STAGE)
        else:
            upload_result = run_cmd(
                f"aws s3 cp {local_path} {s3_uri} "
                f"--content-type application/json "
                f"--cache-control 'public, max-age=60'",
                timeout=60,
            )
            if upload_result.success:
                log(f"Uploaded manifest: {s3_uri}", stage=STAGE)
            else:
                log(f"FAILED to upload {s3_uri}: {upload_result.stderr[:200]}", stage=STAGE)

    # Step 4 -- Invalidate CloudFront
    if not dry_run and cf_paths:
        _invalidate_cloudfront(cf_paths)
    elif dry_run:
        log(f"[DRY RUN] Would invalidate CloudFront paths: {cf_paths}", stage=STAGE)

    log(f"Manifest publishing complete for {len(results)} platforms", stage=STAGE)
    return results


def _invalidate_cloudfront(paths: List[str]) -> bool:
    """
    Create a CloudFront invalidation for the given paths.

    Reads CLOUDFRONT_DISTRIBUTION_ID from the environment.
    """
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
        log(f"CloudFront invalidation created for {len(paths)} paths", stage=STAGE)
    else:
        log(f"CloudFront invalidation failed: {result.stderr[:200]}", stage=STAGE)
    return result.success
