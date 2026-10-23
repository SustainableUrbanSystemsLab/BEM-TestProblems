"""A high aggregate percentage must not hide an entirely untested file."""

import json

import pytest

from tools.check_coverage import main, untested_files


def report(covered):
    return {"files": {"module.py": {"summary": {"num_statements": 4, "covered_lines": covered}},
                      "empty.py": {"summary": {"num_statements": 0, "covered_lines": 0}}}}


@pytest.mark.parametrize("covered,expected", [(0, ["module.py"]), (1, []), (4, [])])
def test_every_nonempty_file_needs_execution(covered, expected):
    assert untested_files(report(covered)) == expected


def test_an_empty_report_cannot_pass():
    with pytest.raises(ValueError, match="no Python files"):
        untested_files({"files": {}})


@pytest.mark.parametrize("covered,exit_code", [(0, 1), (4, 0)])
def test_ci_command_returns_failure_for_an_unexercised_file(tmp_path, covered, exit_code, capsys):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report(covered)))
    assert main([str(path)]) == exit_code
    message = capsys.readouterr().out
    assert ("Unexercised Python files: module.py" if exit_code else "Every Python file") in message
