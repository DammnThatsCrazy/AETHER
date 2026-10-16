#!/usr/bin/env python3
"""CI V2 change classifier and suite selector.

Maps the PR merge-base diff to registered suites using config/ci/ownership.yaml
and config/test_suites.yaml. Fails closed: an unmatched path, a rule naming an
unknown suite, or any error selects every PR-lane suite (broad-safe) or exits
non-zero; it never silently selects nothing for executable changes.

    python scripts/ci_select.py --base origin/development            # diff mode
    python scripts/ci_select.py --files a.py b.md                    # explicit files
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "config" / "ci" / "ownership.yaml"
REGISTRY = ROOT / "config" / "test_suites.yaml"
DOCS_SUITE = "docs"


def _glob(pattern: str, path: str) -> bool:
    # `**` crosses directories, `*` does not cross them in fnmatch's regex
    # translation here: normalise by translating `**/` and `/**` ourselves.
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    if pattern.startswith("**/"):
        return fnmatch.fnmatch(path, pattern[3:]) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern[3:])
    return fnmatch.fnmatch(path, pattern)


def _any(patterns, path: str) -> bool:
    return any(_glob(p, path) for p in patterns)


def changed_paths(base: str, head: str = "HEAD") -> list[str]:
    """Merge-base diff with rename detection; renames contribute old and new path."""
    out = subprocess.run(
        ["git", "diff", "--name-status", "-M", f"{base}...{head}"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    paths: list[str] = []
    for line in out.splitlines():
        cols = line.split("\t")
        paths.extend(cols[1:])  # R100\told\tnew -> both; D/M/A -> the one path
    return sorted(set(paths))


def load():
    rules = yaml.safe_load(RULES.read_text())
    suites = {s["id"]: s for s in yaml.safe_load(REGISTRY.read_text())["suites"]}
    return rules, suites


def _validate(rules: dict, suites: dict) -> None:
    named = set(rules.get("critical", []))
    for e in rules.get("extra", []):
        named.update(e["suites"])
    for c in rules.get("checks", []):
        if not (c.get("id") and c.get("include") and c.get("run")):
            raise ValueError(f"ownership.yaml check needs id, include and run: {c}")
    unknown = sorted(named - set(suites))
    if unknown or DOCS_SUITE not in suites:
        raise ValueError(f"ownership.yaml names unknown suites: {unknown or [DOCS_SUITE]}")


def select(paths: list[str], rules: dict, suites: dict) -> dict:
    _validate(rules, suites)
    pr = sorted(i for i, s in suites.items() if s["lane"] == "pr")
    selected: dict[str, set[str]] = {}
    reasons: list[str] = []
    mode = "targeted"

    def add(ids, why):
        for i in ids:
            selected.setdefault(i, set()).add(why)

    if not paths:
        return _result("empty", paths, {}, ["no changed files"], suites, {}, rules)

    non_text = [p for p in paths if not _any(rules["text_only"], p)]
    for p in paths:
        if _any(rules["text_only"], p):
            add([DOCS_SUITE], f"text-only: {p}")
    for p in non_text:
        if _any(rules["fanout"], p):
            mode = "broad-safe"
            reasons.append(f"fan-out path: {p}")
            continue
        hit = False
        for sid, s in suites.items():
            if s["lane"] != "pr":
                continue
            if any(p == sp or p.startswith(sp.rstrip("/") + "/") for sp in s["paths"]):
                add([sid], f"registry path: {p}")
                hit = True
        for e in rules.get("extra", []):
            if _any(e["include"], p):
                add(e["suites"], f"rule: {p}")
                hit = True
        if not hit:
            mode = "broad-safe"
            reasons.append(f"unclassified path: {p}")
    checks: dict[str, str] = {}
    for c in rules.get("checks", []):
        if mode == "broad-safe":
            checks[c["id"]] = "broad-safe fallback"
        else:
            hit = next((p for p in non_text if _any(c["include"], p)), None)
            if hit:
                checks[c["id"]] = f"path: {hit}"
    if mode == "broad-safe":
        add(pr, "broad-safe fallback")
    if non_text:
        add(rules.get("critical", []), "critical invariant")
    elif mode == "targeted":
        mode = "docs-only"
    return _result(mode, paths, selected, reasons, suites, checks, rules)


def _result(mode, paths, selected, reasons, suites, checks=None, rules=None) -> dict:
    by_id = {c["id"]: c for c in (rules or {}).get("checks", [])}
    return {
        "checks": [
            {"id": i, "why": why, "setup": by_id[i].get("setup", []), "run": by_id[i]["run"],
             "env": by_id[i].get("env", {}), "node": by_id[i].get("node", True),
             "python_extra": by_id[i].get("python_extra")}
            for i, why in sorted((checks or {}).items())
        ],
        "schema_version": 1,
        "mode": mode,
        "changed_files": paths,
        "suites": {k: sorted(v) for k, v in sorted(selected.items())},
        "reasons": reasons,
    }


SHARD_TARGET_SECONDS = 300  # registry `expected_runtime_seconds` budget per worker


def _shard(ids: list[str], suites: dict, target: int) -> list[list[str]]:
    """Balance suites into the fewest bins under `target` expected seconds (LPT)."""
    cost = {i: int(suites[i].get("expected_runtime_seconds") or 0) for i in ids}
    k = max(1, -(-sum(cost.values()) // target))
    bins: list[list[str]] = [[] for _ in range(k)]
    load = [0] * k
    for i in sorted(ids, key=lambda x: (-cost[x], x)):
        j = load.index(min(load))
        bins[j].append(i)
        load[j] += cost[i]
    return [sorted(b) for b in bins if b]


def workers(result: dict, suites: dict, target: int = SHARD_TARGET_SECONDS) -> list[dict]:
    """Group selected suites by (dependency_profile, runtime_class), sharded for parallelism.

    suite_worker.py requires every suite in a worker to share its profile and
    runtime class, so shards never mix them.
    """
    sys.path.insert(0, str(ROOT))
    from scripts.lib.test_suites import load_dependency_profiles  # noqa: E402

    profiles = load_dependency_profiles(ROOT)
    groups: dict[tuple, list[str]] = {}
    for sid in result["suites"]:
        s = suites[sid]
        groups.setdefault((s["dependency_profile"], s["runtime_class"]), []).append(sid)
    out = []
    for (profile, rc), ids in sorted(groups.items()):
        p = profiles[profile]
        shards = _shard(ids, suites, target)
        for n, shard in enumerate(shards, 1):
            out.append({
                "id": f"{profile}-{rc}" + (f"-{n}" if len(shards) > 1 else ""),
                "suite_ids": shard, "dependency_profile": profile, "runtime_class": rc,
                "node_required": bool(p.get("node")),
                "python_extra": p.get("python_extra") if profile != "ci-control" else None,
            })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--output")
    ap.add_argument("--github-output", action="store_true")
    args = ap.parse_args(argv)
    try:
        rules, suites = load()
        paths = sorted(set(args.files)) if args.files is not None else changed_paths(args.base or "HEAD^", args.head)
        result = select(paths, rules, suites)
        result["workers"] = workers(result, suites)
    except Exception as exc:  # selector failure must fail the verdict, never pass silently
        print(f"ci_select: FAILED: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    else:
        sys.stdout.write(text)
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"mode={result['mode']}\n")
            fh.write(f"workers={json.dumps(result['workers'], separators=(',', ':'))}\n")
            fh.write(f"has_workers={'true' if result['workers'] else 'false'}\n")
            fh.write(f"checks={json.dumps(result['checks'], separators=(',', ':'))}\n")
            fh.write(f"has_checks={'true' if result['checks'] else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
