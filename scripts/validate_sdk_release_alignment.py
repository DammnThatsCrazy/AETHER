#!/usr/bin/env python3
"""Validate SDK release alignment across package metadata, native constants, endpoints, and canonical event emission."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / 'package.json').read_text())['version']
ERRORS: list[str] = []

def fail(msg: str) -> None:
    ERRORS.append(msg)

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')

# Version drift
package_paths = ['package.json','packages/shared/package.json','packages/web/package.json','packages/react-native/package.json']
for rel in package_paths:
    version = json.loads(text(rel))['version']
    if version != VERSION:
        fail(f'{rel} version {version} != root {VERSION}')

rn_dep = json.loads(text('packages/react-native/package.json'))['dependencies']['@aether/shared']
web_dep = json.loads(text('packages/web/package.json'))['dependencies']['@aether/shared']
for rel, dep in [('packages/react-native/package.json', rn_dep), ('packages/web/package.json', web_dep)]:
    if dep != f'^{VERSION}': fail(f'{rel} @aether/shared dependency {dep} != ^{VERSION}')

version_patterns = {
    'packages/shared/sdk-version.ts': [f"SDK_VERSION = '{VERSION}'"],
    'packages/android/gradle.properties': [f'sdkVersion={VERSION}'],
    'packages/android/src/main/java/com/aether/sdk/Aether.kt': [f'VERSION = "{VERSION}"'],
    'packages/ios/AetherSDK.podspec': [f's.version      = "{VERSION}"', f's.version         = "{VERSION}"'],
    'packages/ios/Sources/AetherSDK/Aether.swift': [f'v{VERSION}', f'version: "{VERSION}"'],
    'packages/react-native/aether-react-native.podspec': [f's.version          = "{VERSION}"', f's.version      = "{VERSION}"', f's.version         = "{VERSION}"', "s.version      = package['version']"],
    'packages/react-native/src/modules/HealthAgent.ts': [f"SDK_VERSION = '{VERSION}'"],
    'packages/react-native/src/context/SemanticContext.ts': [f"version: '{VERSION}'"],
    'packages/web/src/index.ts': [f"SDK_VERSION = '{VERSION}'"],
    'packages/web/src/core/event-queue.ts': [f"SDK_VERSION = '{VERSION}'"],
    'packages/web/src/health/sdk-health-agent.ts': [f"SDK_VERSION = '{VERSION}'"],
}
for rel, needles in version_patterns.items():
    body = text(rel)
    if not any(n in body for n in needles):
        fail(f'{rel} missing synchronized SDK version {VERSION}')

# Endpoint drift
sdk_files = [
    'packages/web/src/core/event-queue.ts',
    'packages/android/src/main/java/com/aether/sdk/Aether.kt',
    'packages/ios/Sources/AetherSDK/Aether.swift',
    'docs/source-of-truth/INGESTION_CONTRACT.md',
    'docs/SDK-API-CONTRACTS.md',
]
for rel in sdk_files:
    body = text(rel)
    if '/v1/batch' not in body:
        fail(f'{rel} does not reference canonical /v1/batch endpoint')
    if rel.startswith('packages/') and re.search(r'/v1/ingest/events(?:/batch)?', body):
        fail(f'{rel} contains competing SDK ingestion endpoint /v1/ingest/events')
    if rel.startswith('docs/SDK') and re.search(r'SDKs (?:batch|POST|send)[^\n]+/v1/ingest/events', body):
        fail(f'{rel} presents /v1/ingest/events as an SDK ingestion target')

# Canonical event registry and consent map sync (by name)
events_ts = text('packages/shared/events.ts')
registry = set(re.findall(r"\| '([^']+)'", events_ts.split('export type EventFamily')[0]))
if not registry:
    fail('could not parse shared EventType registry')
for rel in ['packages/web/src/core/event-queue.ts','packages/android/src/main/java/com/aether/sdk/Aether.kt','packages/ios/Sources/AetherSDK/Aether.swift']:
    body = text(rel)
    for name in registry:
        if name not in body:
            fail(f'{rel} missing canonical event/consent entry {name}')

# Prevent raw non-canonical enqueue calls from SDK source.
for rel in [
    'packages/web/src/index.ts',
    'packages/web/src/core/event-queue.ts',
    'packages/android/src/main/java/com/aether/sdk/Aether.kt',
    'packages/ios/Sources/AetherSDK/Aether.swift',
]:
    body = text(rel)
    for m in re.finditer(r"enqueueEvent\(\s*(?:type\s*=\s*)?[\"']([a-z0-9_]+)[\"']", body):
        ev = m.group(1)
        if ev not in registry:
            fail(f'{rel} emits non-canonical raw event type {ev}; use track with properties.event')

# Publish workflow must include every target and artifact checks.
workflow = text('.github/workflows/publish-sdk.yml')
for required in ['packages/shared','packages/web','packages/react-native','pod spec lint packages/ios/AetherSDK.podspec','pod spec lint packages/react-native/aether-react-native.podspec','assembleRelease','publishToMavenLocal','npm pack --workspace=packages/web']:
    if required not in workflow:
        fail(f'publish workflow missing {required}')

if ERRORS:
    print('SDK release alignment validation failed:')
    for err in ERRORS:
        print(f'  - {err}')
    sys.exit(1)
print(f'SDK release alignment validation passed for {VERSION}: versions, endpoints, canonical events, consent maps, and publish workflow are synchronized.')
