#!/usr/bin/env python3
"""Run pytest files in isolated processes with bounded parallelism."""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_file(path: Path) -> tuple[Path, int, str]:
    env = os.environ.copy()
    backend = str(ROOT / "Backend Architecture" / "aether-backend")
    env["PYTHONPATH"] = backend + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(path), "-q", "-n", "0", "--tb=short"],
        cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return path, proc.returncode, proc.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1))
    args = parser.parse_args()
    files = sorted({
        path
        for root in args.paths
        for path in root.rglob("test_*.py")
        if "__pycache__" not in path.parts
    })
    if not files:
        print(f"no test files found below {', '.join(map(str, args.paths))}", file=sys.stderr)
        return 2
    failures = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_file, path): path for path in files}
        for future in concurrent.futures.as_completed(futures):
            path, code, output = future.result()
            completed += 1
            print("." if code == 0 else "F", end="", flush=True)
            if code:
                failures.append((path, output))
            if completed % 72 == 0:
                print(f" {completed}/{len(files)}")
    print(f" {completed}/{len(files)}")
    for path, output in failures:
        print(f"\n{'=' * 72}\nFAILED FILE: {path}\n{'=' * 72}\n{output}")
    print(f"isolated pytest files: {len(files) - len(failures)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
