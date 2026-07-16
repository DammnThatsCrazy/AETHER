"""Release workflows must validate pull requests without mutating them."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_native_sdk_validation_runs_on_pull_requests():
    workflow = _workflow("sdk-release-validation.yml")
    assert "github.event_name == 'push'" not in workflow
    assert "gradle assembleRelease publishToMavenLocal" in workflow
    assert "xcodebuild test" in workflow
    assert "xcrun simctl list devices available -j" in workflow
    assert "steps.simulator.outputs.udid" in workflow
    assert "name=iPhone 16" not in workflow
    assert "pod spec lint packages/ios/AetherSDK.podspec" in workflow


def test_shared_sdk_parity_changes_trigger_all_sdk_jobs():
    workflow = _workflow("sdk-release-validation.yml")
    assert workflow.count("packages/shared/sdk-parity.json") == 2
    assert workflow.count("scripts/release/sdk_conformance.py") == 2


def test_hardening_gate_is_read_only_and_never_rewrites_pr_history():
    workflow = _workflow("hardening-release-gate.yml")
    assert "contents: read" in workflow
    for forbidden in (
        "docs_drift.py --update",
        "git push",
        "git commit",
        "git reset --soft",
        "force-with-lease",
    ):
        assert forbidden not in workflow
    assert "run: make ci-check" in workflow
    assert "run: make release-gate" in workflow
