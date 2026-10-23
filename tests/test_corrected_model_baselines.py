"""Corrected-model CI references identify the exact audited inputs and finite outputs."""
import hashlib
import json
import math
from pathlib import Path

import pytest

from bem_testproblems import get_problem

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "reference/corrected-model-cases.json"


@pytest.mark.parametrize("version", ["8.5.0", "26.2.0"])
def test_corrected_baselines_match_audited_case_definitions_and_rendered_inputs(version, tmp_path):
    cases = json.loads(FIXTURE.read_text())["cases"]
    baseline = json.loads((ROOT / f"reference/baselines/{version}-corrected-models.json").read_text())
    assert {(c["problem"], c["numerical_variant"]) for c in cases} == {
        (4, "model-corrected-v3"), (5, "model-corrected-v3"), (10, "model-corrected-v3"),
        (5, "historical-hvac"), (6, "historical-hvac"), (8, "historical-hvac"),
    }
    assert baseline["engine_version"] == version
    assert baseline["diagnostics_policy"] == "strict"
    assert baseline["case_fixture"]["sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert len(baseline["cases"]) == len(cases)
    for case, row in zip(cases, baseline["cases"], strict=True):
        assert all(row[key] == value for key, value in case.items())
        assert row["passed"] and row["severe_count"] == row["fatal_count"] == 0
        assert math.isfinite(row["objective"]) and all(map(math.isfinite, row["components"].values()))
        assert sum(row["terms"].values()) == pytest.approx(row["objective"], rel=1e-12)
        problem = get_problem(case["problem"], numerical_variant=case["numerical_variant"])
        render = problem.render_legacy if version == "8.5.0" else problem.render_modern
        suffix = ".idf" if version == "8.5.0" else ".epJSON"
        path = render(case["x"], tmp_path / (case["case_id"] + suffix))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["input_sha256"]
