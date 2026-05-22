#!/usr/bin/env bash
# Bumps the SDK version across all packages in one pass.
# Usage: ./scripts/bump-sdk-version.sh 8.9.0
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>  (e.g. $0 8.9.0)" >&2
  exit 1
fi

# Basic semver check
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
  echo "Error: '$VERSION' is not a valid semver string" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Bumping SDK version to $VERSION..."

# ── npm packages ────────────────────────────────────────────────────────────
for PKG in packages/shared packages/react-native; do
  npm pkg set version="$VERSION" --prefix "$ROOT/$PKG"
  echo "  ✓ $PKG/package.json"
done

# Update @aether/shared peer dep in react-native to the new version
npm pkg set "dependencies.@aether/shared=^${VERSION}" \
  --prefix "$ROOT/packages/react-native"
echo "  ✓ packages/react-native @aether/shared dep → ^${VERSION}"

# ── Android ─────────────────────────────────────────────────────────────────
GRADLE_PROPS="$ROOT/packages/android/gradle.properties"
sed -i "s/^sdkVersion=.*/sdkVersion=${VERSION}/" "$GRADLE_PROPS"
echo "  ✓ packages/android/gradle.properties"

# ── iOS podspec (standalone) ─────────────────────────────────────────────────
IOS_PODSPEC="$ROOT/packages/ios/AetherSDK.podspec"
sed -i "s/s\.version\s*=\s*\"[^\"]*\"/s.version         = \"${VERSION}\"/" "$IOS_PODSPEC"
echo "  ✓ packages/ios/AetherSDK.podspec"

# ── React Native podspec ─────────────────────────────────────────────────────
RN_PODSPEC="$ROOT/packages/react-native/aether-react-native.podspec"
sed -i "s/s\.version\s*=\s*\"[^\"]*\"/s.version          = \"${VERSION}\"/" "$RN_PODSPEC"
echo "  ✓ packages/react-native/aether-react-native.podspec"

echo ""
echo "Done. All packages set to $VERSION."
echo "Review changes with: git diff packages/"
