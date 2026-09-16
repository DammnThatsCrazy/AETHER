#!/usr/bin/env bash
# Bumps the SDK version across all packages and runtime metadata in one pass.
# Usage: ./scripts/bump-sdk-version.sh 8.9.0
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>  (e.g. 8.9.0)" >&2
  exit 1
fi
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
  echo "Error: '$VERSION' is not a valid semver string" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Bumping SDK version to $VERSION..."

for PKG in . packages/shared packages/web packages/react-native; do
  npm pkg set version="$VERSION" --prefix "$ROOT/$PKG"
  echo "  ✓ $PKG/package.json"
done
npm pkg set "dependencies.@aether/shared=^${VERSION}" --prefix "$ROOT/packages/react-native"
npm pkg set "dependencies.@aether/shared=^${VERSION}" --prefix "$ROOT/packages/web"

sed -i "s/^sdkVersion=.*/sdkVersion=${VERSION}/" "$ROOT/packages/android/gradle.properties"
sed -i "s/s\.version\s*=\s*\"[^\"]*\"/s.version         = \"${VERSION}\"/" "$ROOT/packages/ios/AetherSDK.podspec"
sed -i "s/s\.version\s*=\s*\"[^\"]*\"/s.version          = \"${VERSION}\"/" "$ROOT/packages/react-native/aether-react-native.podspec"

perl -0pi -e "s/SDK_VERSION = '[^']+'/SDK_VERSION = '$VERSION'/g" \
  "$ROOT/packages/shared/sdk-version.ts" \
  "$ROOT/packages/web/src/index.ts" \
  "$ROOT/packages/web/src/core/event-queue.ts" \
  "$ROOT/packages/web/src/health/sdk-health-agent.ts" \
  "$ROOT/packages/react-native/src/modules/HealthAgent.ts"
perl -0pi -e "s/version: '[^']+'/version: '$VERSION'/g" "$ROOT/packages/react-native/src/context/SemanticContext.ts"
perl -0pi -e "s/VERSION = \"[^\"]+\"/VERSION = \"$VERSION\"/g" "$ROOT/packages/android/src/main/java/com/aether/sdk/Aether.kt"
perl -0pi -e "s/v[0-9]+\.[0-9]+\.[0-9]+\)/v$VERSION\)/g; s/version: \"[^\"]+\"/version: \"$VERSION\"/g" "$ROOT/packages/ios/Sources/AetherSDK/Aether.swift"

# The loader carries its own copy of the version (it is bundled separately from
# the SDK), and the backend carries the mirror the install verifier reads back.
# Both are pinned by validate_sdk_release_alignment.py below, so a bump that
# skipped them would fail closed rather than ship a mislabelled install — but
# the release could not complete unattended, which is why they are listed here.
perl -0pi -e "s/LOADER_VERSION = '[^']+'/LOADER_VERSION = '$VERSION'/g" \
  "$ROOT/packages/web/src/loader/bootstrap.ts"
perl -0pi -e "s/CANONICAL_SDK_VERSION = \"[^\"]+\"/CANONICAL_SDK_VERSION = \"$VERSION\"/g" \
  "$ROOT/services/backend/services/sdk_distribution/versions.py"

python "$ROOT/scripts/validate_sdk_release_alignment.py"
echo "Done. SDK release metadata set to $VERSION."
