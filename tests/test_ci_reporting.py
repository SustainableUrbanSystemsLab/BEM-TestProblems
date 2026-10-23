"""Negative validation tests must not publish failures into the host CI report."""

import os
import subprocess
import sys
from pathlib import Path


def test_negative_tests_preserve_the_real_github_summary(tmp_path):
    summary = tmp_path / "job-summary.md"
    summary.write_text("Existing job report\n", encoding="utf-8")
    environment = dict(os.environ, GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(summary))
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/test_replication_failure_validation.py"
         "::test_nonfinite_refined_output_cannot_be_accepted",
         "tests/test_validate_cases.py"
         "::test_unexpected_strict_failure_has_no_penalty_and_does_not_match_a_success_baseline",
         f"--basetemp={tmp_path / 'child-tests'}"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=60,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert summary.read_text(encoding="utf-8") == "Existing job report\n"
