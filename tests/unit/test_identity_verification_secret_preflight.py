from __future__ import annotations

import json
import subprocess

from scripts.release import check_identity_verification_secrets as preflight


def _runner_for(metadata_by_name: dict[str, dict]):
    seen: list[list[str]] = []

    def runner(command, **kwargs):
        seen.append(command)
        name = command[4].removeprefix("aether/")
        metadata = metadata_by_name.get(name)
        if metadata is None:
            return subprocess.CompletedProcess(command, 1, "", "not found")
        return subprocess.CompletedProcess(command, 0, json.dumps(metadata), "")

    return runner, seen


def test_identity_verification_preflight_checks_only_metadata():
    runner, seen = _runner_for({
        name: {"VersionIdsToStages": {"version": ["AWSCURRENT"]}}
        for name in preflight.SECRET_NAMES
    })

    assert preflight.secret_errors(runner=runner) == []
    assert len(seen) == 2
    assert all(command[2] == "describe-secret" for command in seen)
    assert all("get-secret-value" not in command for command in seen)


def test_identity_verification_preflight_rejects_missing_or_deleted_versions():
    runner, _ = _runner_for({
        preflight.SECRET_NAMES[0]: {"DeletedDate": "pending"},
        preflight.SECRET_NAMES[1]: {"VersionIdsToStages": {"old": ["AWSPREVIOUS"]}},
    })

    errors = preflight.secret_errors(runner=runner)

    assert len(errors) == 2
    assert all("usable AWSCURRENT" in error for error in errors)
