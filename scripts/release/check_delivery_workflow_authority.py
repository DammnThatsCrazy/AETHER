#!/usr/bin/env python3
"""Validate the enforced one-owner map for GitHub delivery workflows."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/delivery_workflow_authority.yaml"
REQUIRED_AUTHORITIES = {
    "verification", "candidate", "environment", "infrastructure",
    "promotion", "regression", "ephemeral_cleanup",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a mapping")
    return value


def _workflow_triggers(workflow: dict[str, Any]) -> set[str]:
    value = workflow.get("on", workflow.get(True))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, dict):
        return {str(item) for item in value}
    return set()


_HEREDOC = re.compile(
    r"<<-?\s*(?:(?P<quote>['\"])(?P<quoted>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P=quote)|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))"
)
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_CONTROL_TOKENS = frozenset(
    {"!", "if", "then", "elif", "else", "fi", "do", "done", "while", "until", "for", "in", "case", "esac", "{", "}", "(", ")"}
)
_SEPARATOR_TOKENS = frozenset({";", "&&", "||", "|", "&"})


def _run_commands(run: str) -> list[list[str]]:
    """Extract command-token segments from one executable shell body.

    This is intentionally a small shell-aware filter, not a shell evaluator.
    It removes comments, heredoc payloads, assignments, and log/no-op commands
    before the authority matcher sees tokens.  A malformed line is ignored so
    the validator fails closed rather than treating arbitrary text as proof.
    """

    commands: list[list[str]] = []
    current: list[str] = []
    heredoc: str | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        tokens = list(current)
        current = []
        while tokens and tokens[0] in _CONTROL_TOKENS:
            tokens.pop(0)
        while tokens and _ASSIGNMENT.match(tokens[0]):
            tokens.pop(0)
        if not tokens or tokens[0] in {"echo", "printf", ":"}:
            return
        commands.append(tokens)

    for raw_line in run.splitlines():
        line = raw_line.rstrip()
        if heredoc is not None:
            if line.strip() == heredoc:
                heredoc = None
            continue
        match = _HEREDOC.search(line)
        continued = line.endswith("\\") and not line.endswith("\\\\")
        if continued:
            line = line[:-1]
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
        except ValueError:
            current = []
            continue
        for token in tokens:
            if token in _SEPARATOR_TOKENS:
                flush()
            else:
                current.append(token.rstrip("\\"))
        if not continued:
            flush()
        if match:
            heredoc = match.group("quoted") or match.group("plain")
    flush()
    return commands


def _workflow_run_commands(workflow: dict[str, Any]) -> list[list[str]]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []
    commands: list[list[str]] = []
    for job in jobs.values():
        if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
            continue
        for step in job["steps"]:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                commands.extend(_run_commands(step["run"]))
    return commands


def _executable_run_text(workflow: dict[str, Any]) -> str:
    """Return normalized shell commands from executable ``run`` steps.

    Authority commands must be present in code that a runner can execute.  A
    comment, step name, or documentation block is not evidence that a command
    is wired into the workflow.  Only ``jobs.*.steps[*].run`` bodies are
    considered; YAML action ``uses`` steps are excluded because this registry's
    required commands are shell command contracts.
    """

    return "\n".join(" ".join(command) for command in _workflow_run_commands(workflow))


def _token_matches(actual: str, expected: str) -> bool:
    actual = actual.strip("'\"")
    return actual == expected or actual.endswith("/" + expected) or Path(actual).name == expected


def _has_required_command(workflow: dict[str, Any], required: str) -> bool:
    try:
        expected = shlex.split(required, comments=True, posix=True)
    except ValueError:
        return False
    if not expected:
        return False
    for command in _workflow_run_commands(workflow):
        width = len(expected)
        for index in range(len(command) - width + 1):
            if all(_token_matches(command[index + offset], token) for offset, token in enumerate(expected)):
                return True
    return False


def validate(config_path: Path = CONFIG, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        config = _load(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"cannot load workflow authority registry: {exc}"]
    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if config.get("operator_surface") != "github_actions":
        errors.append("operator_surface must be github_actions")
    if config.get("kyber_mutation_controls") is not False:
        errors.append("kyber_mutation_controls must be false")
    if config.get("status") != "enforced":
        errors.append("status must be enforced")
    authorities = config.get("authorities")
    if not isinstance(authorities, list) or not authorities:
        return errors + ["authorities must be a non-empty list"]
    seen: set[str] = set()
    for item in authorities:
        if not isinstance(item, dict):
            errors.append("each authority must be a mapping")
            continue
        authority_id = item.get("id")
        owner = item.get("owner")
        workflows = item.get("workflows")
        required_commands = item.get("required_commands", [])
        if not isinstance(authority_id, str) or not authority_id.strip():
            errors.append("each authority requires a non-empty id")
            continue
        if authority_id in seen:
            errors.append(f"duplicate authority: {authority_id}")
        seen.add(authority_id)
        if not isinstance(owner, str) or not owner.strip():
            errors.append(f"authority {authority_id} requires an owner")
        if not isinstance(workflows, list) or not workflows:
            errors.append(f"authority {authority_id} requires workflows")
            continue
        parsed_workflows: list[dict[str, Any]] = []
        for raw_path in workflows:
            if not isinstance(raw_path, str) or not raw_path.startswith(".github/workflows/"):
                errors.append(f"authority {authority_id} has non-GitHub workflow path: {raw_path!r}")
                continue
            path = root / raw_path
            if not path.is_file():
                errors.append(f"authority {authority_id} workflow is missing: {raw_path}")
                continue
            try:
                workflow = _load(path)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                errors.append(f"{raw_path}: cannot parse workflow: {exc}")
                continue
            if not _workflow_triggers(workflow):
                errors.append(f"{raw_path}: workflow must declare a trigger")
            parsed_workflows.append(workflow)
        if not isinstance(required_commands, list) or any(not isinstance(command, str) or not command.strip() for command in required_commands):
            errors.append(f"authority {authority_id} required_commands must be a list of non-empty strings")
        else:
            for command in required_commands:
                if not any(_has_required_command(workflow, command) for workflow in parsed_workflows):
                    errors.append(f"authority {authority_id} is not wired to required command {command!r}")
    missing = sorted(REQUIRED_AUTHORITIES - seen)
    extra = sorted(seen - REQUIRED_AUTHORITIES)
    if missing:
        errors.append("missing required authorities: " + ", ".join(missing))
    if extra:
        errors.append("unknown authorities: " + ", ".join(extra))
    return errors


def main() -> int:
    errors = validate()
    print(json.dumps({"schema_version": 1, "status": "FAILED" if errors else "PASS", "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
