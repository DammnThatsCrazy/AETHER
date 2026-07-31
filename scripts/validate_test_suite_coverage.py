#!/usr/bin/env python3
"""Prove every ci-scoped test suite is actually invoked by the gate.

The historical failure mode this closes: the completion gate hardcoded two
pytest invocations while 225 backend test files sat in a tree no gate ran, and
CI separately hardcoded a ~21-file subset. Nothing noticed, because nothing
compared "suites we declare" against "suites we execute".

config/test_suites.yaml is the declaration. repo_doctor's --ci invocation set
is generated from that registry via ``ci_python_suites()`` — an importable seam
exposed for exactly this comparison — so this validator asserts the generated
set equals the registry's ci-scoped pytest set. Removing a suite from the gate
therefore requires a registry edit, and a registry edit that orphans a suite
fails here.

Non-pytest ci suites (npm workspaces, hardhat) are executed by their own
workflow jobs, not by repo_doctor; for those this validator asserts the
registry declaration itself is coherent (runner present, paths exist — already
enforced by the loader) and reports them for visibility rather than pretending
repo_doctor covers them.

Exit codes: 0 all ci suites covered; 1 any ci-scoped pytest suite missing from
repo_doctor's generated invocation set.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.test_suites import is_pytest_suite, load_suites, suites_for  # noqa: E402


def main() -> int:
    suites = load_suites(str(ROOT / "config" / "test_suites.yaml"))
    declared_ci = suites_for(suites, "ci")
    declared_pytest = {s.id for s in declared_ci if is_pytest_suite(s)}
    declared_other = {s.id for s in declared_ci if not is_pytest_suite(s)}

    # Import the gate's own generated invocation set rather than re-deriving
    # it: if repo_doctor's generation logic drifts from the registry, the
    # comparison below is exactly what must catch it.
    sys.path.insert(0, str(ROOT / "scripts"))
    import repo_doctor

    invoked = {s.id for s in repo_doctor.ci_python_suites()}

    missing = sorted(declared_pytest - invoked)
    unexpected = sorted(invoked - declared_pytest)

    print(
        f"registry: {len(suites)} suites; ci-scoped pytest: "
        f"{len(declared_pytest)}; invoked by repo_doctor --ci: {len(invoked)}"
    )
    if declared_other:
        print(
            "ci suites executed by dedicated workflow jobs (not repo_doctor): "
            + ", ".join(sorted(declared_other))
        )

    if missing:
        print("\nFAIL — declared for ci but NOT invoked by the gate:")
        for suite_id in missing:
            print(f"  - {suite_id}")
    if unexpected:
        # A suite the gate runs but the registry does not declare for ci means
        # the invocation set is no longer generated purely from the registry.
        print("\nFAIL — invoked by the gate but not declared ci in the registry:")
        for suite_id in unexpected:
            print(f"  - {suite_id}")

    if missing or unexpected:
        return 1
    print("test-suite coverage OK: gate invocation set equals the registry's ci set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
