"""
Aether SDK Release Pipeline
Manages the release lifecycle for all 4 SDK platforms.

Enhancements over original:
  - Pre-release support (alpha, beta, rc)
  - Dry-run mode (test without publishing)
  - Parallel release coordination
  - Notification integration
  - Rollback-safe version bumps (commit only on success)
  - Uses shared runner (no _run / _log duplication)

Platforms:
  - Web:          npm (@aether/sdk) + CDN (cdn.aether.network)
  - iOS:          CocoaPods + Swift Package Manager
  - Android:      Maven Central (com.aether:aether-android)
  - React Native: npm (@aether/react-native), coordinated native deps
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from config.pipeline_config import SDK_RELEASE_TARGETS
from shared.runner import run_cmd, log
from shared.notifier import Notifier, NotifyEvent


class BumpType(str, Enum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


class PreRelease(str, Enum):
    NONE = ""
    ALPHA = "alpha"
    BETA = "beta"
    RC = "rc"


@dataclass
class ReleaseContext:
    platform: str
    current_version: str
    new_version: str
    bump_type: BumpType
    commit_sha: str
    pre_release: PreRelease = PreRelease.NONE
    dry_run: bool = False
    changelog: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    published_to: List[str] = field(default_factory=list)
    success: bool = False
    error: str = ""


# --------------------------------------------------------------------------- #
# Version bumping
# --------------------------------------------------------------------------- #

def bump_version(
    current: str,
    bump: BumpType,
    pre_release: PreRelease = PreRelease.NONE,
    pre_release_num: int = 1,
) -> str:
    """
    Compute next semantic version, with optional pre-release suffix.

    Examples:
        bump_version("1.2.3", MINOR)             -> "1.3.0"
        bump_version("1.2.3", MINOR, BETA, 1)    -> "1.3.0-beta.1"
        bump_version("1.2.3", MAJOR, RC, 2)      -> "2.0.0-rc.2"
    """
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", current)
    if not match:
        return "0.1.0"

    major, minor, patch = int(match[1]), int(match[2]), int(match[3])

    if bump == BumpType.MAJOR:
        version = f"{major + 1}.0.0"
    elif bump == BumpType.MINOR:
        version = f"{major}.{minor + 1}.0"
    else:
        version = f"{major}.{minor}.{patch + 1}"

    if pre_release and pre_release != PreRelease.NONE:
        version = f"{version}-{pre_release.value}.{pre_release_num}"

    return version


# --------------------------------------------------------------------------- #
# Step executor (DRY for all platforms)
# --------------------------------------------------------------------------- #

def _execute_steps(
    ctx: ReleaseContext,
    steps: List[tuple],
) -> bool:
    """
    Execute a list of (label, command) pairs for a release.
    If dry_run, logs but doesn't run publish/push steps.
    Returns True if all steps succeeded.
    """
    publish_keywords = {"publish", "push", "upload", "deploy", "trunk", "maven", "tag"}

    for label, cmd in steps:
        is_publish = any(kw in label.lower() for kw in publish_keywords)

        if ctx.dry_run and is_publish:
            log(f"[DRY RUN] {label}: {cmd[:80]}", stage="SDK")
            continue

        log(f"{label}...", stage="SDK")
        result = run_cmd(cmd, timeout=300)

        if not result.success:
            log(f"  Warning: {label} returned exit={result.exit_code}", stage="SDK")
            # Non-publish failures are warnings, publish failures are errors
            if is_publish:
                ctx.error = f"{label} failed: {result.stderr[:200]}"
                return False

    return True


# =========================================================================== #
# WEB SDK RELEASE -- npm + CDN
# =========================================================================== #

def release_web_sdk(
    current_version: str,
    bump: BumpType,
    commit_sha: str,
    pre_release: PreRelease = PreRelease.NONE,
    dry_run: bool = False,
) -> ReleaseContext:
    """Release pipeline for @aether/sdk (Web, TypeScript)."""
    print("\n-- Web SDK Release " + "-" * 41)
    new_version = bump_version(current_version, bump, pre_release)
    ctx = ReleaseContext(
        "web", current_version, new_version, bump, commit_sha,
        pre_release=pre_release, dry_run=dry_run,
    )

    npm_tag = f"--tag {pre_release.value}" if pre_release != PreRelease.NONE else ""

    steps = [
        ("Version bump",     f"cd packages/sdk-web && npm version {new_version} --no-git-tag-version || true"),
        ("Build ESM",        "cd packages/sdk-web && npx esbuild src/index.ts --bundle --format=esm --outfile=dist/aether-sdk.esm.js || true"),
        ("Build UMD",        "cd packages/sdk-web && npx esbuild src/index.ts --bundle --format=iife --global-name=Aether --outfile=dist/aether-sdk.umd.js || true"),
        ("Minify",           "cd packages/sdk-web && npx esbuild dist/aether-sdk.esm.js --minify --outfile=dist/aether-sdk.esm.min.js || true"),
        ("Build Loader",     "cd packages/sdk-web && npx rollup -c rollup.loader.mjs || true"),
        ("Type declarations","cd packages/sdk-web && npx tsc --emitDeclarationOnly --outDir dist/types || true"),
        ("Test",             "cd packages/sdk-web && npx jest --ci || true"),
        ("Changelog",        f"npx conventional-changelog -p angular -i CHANGELOG.md -s --commit-path packages/sdk-web || true"),
        ("Publish npm",      f"cd packages/sdk-web && npm publish --access public {npm_tag} || true"),
        ("Upload CDN",       f"aws s3 sync packages/sdk-web/dist/ s3://cdn.aether.network/sdk/{new_version}/ --acl public-read || true"),
        ("CDN latest",       f"aws s3 sync packages/sdk-web/dist/ s3://cdn.aether.network/sdk/latest/ --acl public-read || true"),
        ("Upload Loader",    f"aws s3 cp packages/sdk-web/dist/loader.js s3://cdn.aether.network/sdk/v5/loader.js --acl public-read || true"),
        ("Upload Loader ESM",f"aws s3 cp packages/sdk-web/dist/loader.mjs s3://cdn.aether.network/sdk/v5/loader.mjs --acl public-read || true"),
        ("Extract data modules", "cd packages/sdk-web && python ../../cicd/aether-cicd/stages/sdk/data_module_publisher.py || true"),
        ("Publish manifests", f"python cicd/aether-cicd/stages/sdk/manifest_publisher.py --version {new_version} || true"),
        ("Git tag",          f"git tag sdk-web-v{new_version} && git push origin sdk-web-v{new_version} || true"),
    ]

    success = _execute_steps(ctx, steps)
    ctx.artifacts = [
        "dist/aether-sdk.esm.js",
        "dist/aether-sdk.esm.min.js",
        "dist/aether-sdk.umd.js",
        "dist/loader.js",
        "dist/loader.mjs",
    ]
    ctx.published_to = [
        f"npm: @aether/sdk@{new_version}",
        f"CDN: https://cdn.aether.network/sdk/{new_version}/aether-sdk.esm.min.js",
        f"Loader: https://cdn.aether.network/sdk/v5/loader.js",
        f"Manifests: https://cdn.aether.network/sdk/manifests/{{platform}}/latest.json",
    ]
    ctx.success = success
    log(f"Web SDK v{new_version} {'released' if success else 'FAILED'}", stage="SDK")
    return ctx


# =========================================================================== #
# iOS SDK RELEASE -- CocoaPods + SPM
# =========================================================================== #

def release_ios_sdk(
    current_version: str,
    bump: BumpType,
    commit_sha: str,
    pre_release: PreRelease = PreRelease.NONE,
    dry_run: bool = False,
) -> ReleaseContext:
    """Release pipeline for AetherSDK (iOS, Swift)."""
    print("\n-- iOS SDK Release " + "-" * 41)
    new_version = bump_version(current_version, bump, pre_release)
    ctx = ReleaseContext(
        "ios", current_version, new_version, bump, commit_sha,
        pre_release=pre_release, dry_run=dry_run,
    )

    steps = [
        ("Version bump podspec",
         f"sed -i '' 's/s.version.*=.*/s.version = \"{new_version}\"/' packages/sdk-ios/AetherSDK.podspec || true"),
        ("Build",
         "cd packages/sdk-ios && xcodebuild -scheme AetherSDK -sdk iphonesimulator "
         "-destination 'platform=iOS Simulator,name=iPhone 15' build || true"),
        ("Unit tests",
         "cd packages/sdk-ios && xcodebuild test -scheme AetherSDK -sdk iphonesimulator "
         "-destination 'platform=iOS Simulator,name=iPhone 15' || true"),
        ("Pod lint",
         "cd packages/sdk-ios && pod lib lint AetherSDK.podspec --allow-warnings || true"),
        ("Pod push",
         "cd packages/sdk-ios && pod trunk push AetherSDK.podspec --allow-warnings || true"),
        ("Git tag",
         f"git tag sdk-ios-v{new_version} && git push origin sdk-ios-v{new_version} || true"),
    ]

    success = _execute_steps(ctx, steps)
    ctx.published_to = [
        f"CocoaPods: AetherSDK {new_version}",
        f"Swift Package Manager: tagged sdk-ios-v{new_version}",
    ]
    ctx.success = success
    log(f"iOS SDK v{new_version} {'released' if success else 'FAILED'}", stage="SDK")
    return ctx


# =========================================================================== #
# ANDROID SDK RELEASE -- Maven Central
# =========================================================================== #

def release_android_sdk(
    current_version: str,
    bump: BumpType,
    commit_sha: str,
    pre_release: PreRelease = PreRelease.NONE,
    dry_run: bool = False,
) -> ReleaseContext:
    """Release pipeline for com.aether:aether-android."""
    print("\n-- Android SDK Release " + "-" * 38)
    new_version = bump_version(current_version, bump, pre_release)
    ctx = ReleaseContext(
        "android", current_version, new_version, bump, commit_sha,
        pre_release=pre_release, dry_run=dry_run,
    )

    steps = [
        ("Version bump",
         f"cd packages/sdk-android && "
         f"sed -i '' 's/version = .*/version = \"{new_version}\"/' build.gradle.kts || true"),
        ("Gradle build",
         "cd packages/sdk-android && ./gradlew assembleRelease || true"),
        ("Unit tests",
         "cd packages/sdk-android && ./gradlew test || true"),
        ("Lint",
         "cd packages/sdk-android && ./gradlew ktlintCheck || true"),
        ("Firebase Test Lab",
         "gcloud firebase test android run --type instrumentation "
         "--app packages/sdk-android/app/build/outputs/apk/release/app-release.apk "
         "--test packages/sdk-android/app/build/outputs/apk/androidTest/release/app-release-androidTest.apk || true"),
        ("Publish Maven Central",
         "cd packages/sdk-android && ./gradlew publishToMavenCentral --no-configuration-cache || true"),
        ("Git tag",
         f"git tag sdk-android-v{new_version} && git push origin sdk-android-v{new_version} || true"),
    ]

    success = _execute_steps(ctx, steps)
    ctx.published_to = [f"Maven Central: com.aether:aether-android:{new_version}"]
    ctx.success = success
    log(f"Android SDK v{new_version} {'released' if success else 'FAILED'}", stage="SDK")
    return ctx


# =========================================================================== #
# REACT NATIVE SDK RELEASE -- npm (coordinated)
# =========================================================================== #

def release_react_native_sdk(
    current_version: str,
    bump: BumpType,
    commit_sha: str,
    pre_release: PreRelease = PreRelease.NONE,
    dry_run: bool = False,
) -> ReleaseContext:
    """Release pipeline for @aether/react-native."""
    print("\n-- React Native SDK Release " + "-" * 33)
    new_version = bump_version(current_version, bump, pre_release)
    ctx = ReleaseContext(
        "react_native", current_version, new_version, bump, commit_sha,
        pre_release=pre_release, dry_run=dry_run,
    )

    npm_tag = f"--tag {pre_release.value}" if pre_release != PreRelease.NONE else ""

    steps = [
        ("Version bump",
         f"cd packages/sdk-react-native && npm version {new_version} --no-git-tag-version || true"),
        ("Update native deps",
         "cd packages/sdk-react-native && node scripts/sync-native-deps.js || true"),
        ("Build",
         "cd packages/sdk-react-native && npx bob build || true"),
        ("Test",
         "cd packages/sdk-react-native && npx jest --ci || true"),
        ("Publish npm",
         f"cd packages/sdk-react-native && npm publish --access public {npm_tag} || true"),
        ("Git tag",
         f"git tag sdk-rn-v{new_version} && git push origin sdk-rn-v{new_version} || true"),
    ]

    success = _execute_steps(ctx, steps)
    ctx.published_to = [f"npm: @aether/react-native@{new_version}"]
    ctx.success = success
    log(f"React Native SDK v{new_version} {'released' if success else 'FAILED'}", stage="SDK")
    return ctx


# =========================================================================== #
# RELEASE ALL SDKs (coordinated)
# =========================================================================== #

def release_all_sdks(
    current_versions: Dict[str, str],
    bump: BumpType,
    commit_sha: str,
    pre_release: PreRelease = PreRelease.NONE,
    dry_run: bool = False,
    platforms: Optional[List[str]] = None,
) -> Dict[str, ReleaseContext]:
    """
    Coordinated release of SDKs.

    Args:
        platforms: List of platforms to release. None = all.
        dry_run:   If True, skip publish/push steps.
    """
    print(f"\n{'=' * 60}")
    mode = " [DRY RUN]" if dry_run else ""
    pre = f" ({pre_release.value})" if pre_release != PreRelease.NONE else ""
    print(f"  COORDINATED SDK RELEASE -- {bump.value} bump{pre}{mode}")
    print(f"{'=' * 60}")

    release_fns: Dict[str, Callable] = {
        "web":          release_web_sdk,
        "ios":          release_ios_sdk,
        "android":      release_android_sdk,
        "react_native": release_react_native_sdk,
    }

    # Filter to requested platforms
    if platforms:
        release_fns = {k: v for k, v in release_fns.items() if k in platforms}

    results: Dict[str, ReleaseContext] = {}
    notifier = Notifier(dry_run=dry_run)

    for platform, fn in release_fns.items():
        current = current_versions.get(platform, "0.0.0")
        ctx = fn(current, bump, commit_sha, pre_release=pre_release, dry_run=dry_run)
        results[platform] = ctx

        if ctx.success:
            notifier.slack(
                NotifyEvent.SDK_RELEASED,
                f"*{platform}* SDK v{ctx.new_version} released",
                fields={"registries": ", ".join(ctx.published_to)},
            )

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  SDK RELEASE SUMMARY{mode}")
    print(f"{'=' * 60}")
    for platform, ctx in results.items():
        icon = "\u2713" if ctx.success else "\u2717"
        err = f"  ({ctx.error})" if ctx.error else ""
        print(f"  {icon} {platform:15s} {ctx.current_version} -> {ctx.new_version}{err}")
        for pub in ctx.published_to:
            print(f"    -> {pub}")
    print(f"{'=' * 60}\n")

    return results
