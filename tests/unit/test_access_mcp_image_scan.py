from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "infra/aws/terraform/scripts/verify_access_mcp_image_scan.sh"
DIGEST = "sha256:" + "a" * 64


FAKE_AWS = r'''#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "ecr describe-images" ]]; then
  printf '%s\n' "$FAKE_AWS_DIGEST"
  exit 0
fi
if [[ "$1 $2" != "ecr describe-image-scan-findings" ]]; then
  printf 'unexpected AWS command\n' >&2
  exit 90
fi
counter_file="$FAKE_AWS_STATE_DIR/scan-count"
count=0
if [[ -f "$counter_file" ]]; then
  count="$(cat "$counter_file")"
fi
count=$((count + 1))
printf '%s\n' "$count" > "$counter_file"
case "$FAKE_AWS_MODE" in
  pending_then_clean)
    if (( count == 1 )); then printf 'IN_PROGRESS\t0\t0\n'; else printf 'COMPLETE\t0\t0\n'; fi
    ;;
  not_found_then_clean)
    if (( count == 1 )); then printf 'An error occurred (ScanNotFoundException)\n' >&2; exit 254; else printf 'COMPLETE\t0\t0\n'; fi
    ;;
  high)
    printf 'COMPLETE\t1\t0\n'
    ;;
  critical)
    printf 'COMPLETE\t0\t1\n'
    ;;
  failed)
    printf 'FAILED\t0\t0\n'
    ;;
  timeout)
    printf 'IN_PROGRESS\t0\t0\n'
    ;;
  malformed)
    printf 'COMPLETE\tunknown\t0\n'
    ;;
esac
'''


class AccessMcpImageScanVerifierTests(unittest.TestCase):
    def run_verifier(self, mode: str, *, timeout: int = 4) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="access-mcp-scan-test-") as temp_dir:
            temp_path = Path(temp_dir)
            fake_aws_path = temp_path / "aws"
            fake_aws_path.write_text(FAKE_AWS, encoding="utf-8")
            fake_aws_path.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{temp_dir}{os.pathsep}{env.get('PATH', '')}",
                    "AWS_REGION": "us-east-1",
                    "ACCESS_MCP_SCAN_TIMEOUT_SECONDS": str(timeout),
                    "ACCESS_MCP_SCAN_POLL_SECONDS": "1",
                    "FAKE_AWS_MODE": mode,
                    "FAKE_AWS_STATE_DIR": temp_dir,
                    "FAKE_AWS_DIGEST": DIGEST,
                }
            )
            result = subprocess.run(
                ["bash", str(VERIFIER), DIGEST],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.scan_calls = 0
            counter_file = temp_path / "scan-count"
            if counter_file.exists():
                self.scan_calls = int(counter_file.read_text(encoding="utf-8"))
            return result

    def test_waits_for_scan_completion_and_accepts_clean_digest(self) -> None:
        result = self.run_verifier("pending_then_clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, DIGEST + "\n")
        self.assertEqual(self.scan_calls, 2)

    def test_retries_scan_not_found_then_accepts_clean_digest(self) -> None:
        result = self.run_verifier("not_found_then_clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, DIGEST + "\n")
        self.assertEqual(self.scan_calls, 2)

    def test_rejects_high_or_critical_findings(self) -> None:
        for mode in ("high", "critical"):
            with self.subTest(mode=mode):
                result = self.run_verifier(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("scan rejected", result.stderr)

    def test_rejects_terminal_failure_and_malformed_counts(self) -> None:
        for mode in ("failed", "malformed"):
            with self.subTest(mode=mode):
                result = self.run_verifier(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_times_out_while_scan_remains_in_progress(self) -> None:
        result = self.run_verifier("timeout", timeout=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out waiting", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
