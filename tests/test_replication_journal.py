# SPDX-License-Identifier: MIT
"""Journal durability, committed prefixes, and private path confinement."""

import copy
import json

import pytest

from bem_testproblems.replication_journal import TraceJournal, read_checkpoint


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "runs/search.json"
    writer = TraceJournal(path, 1)
    record = {"status": "running", "evaluation_count": 2, "trace": [
        {"evaluation": 1, "status": "success", "f": 4.0},
        {"evaluation": 2, "status": "failed", "f": None}]}
    compact = writer.snapshot(record)
    path.write_text(json.dumps(compact))
    return path, writer, record, compact


@pytest.mark.parametrize("tail", ["", '{"evaluation":3', '{"evaluation":3}\n'])
def test_reader_recovers_exact_committed_prefix_and_ignores_only_uncommitted_tail(checkpoint, tail):
    path, writer, record, _ = checkpoint
    with writer.path.open("a") as stream:
        stream.write(tail)
    assert read_checkpoint(path) == record
    assert tail in writer.path.read_text()


def test_partial_utf8_bytes_after_committed_prefix_do_not_change_recovered_evidence(checkpoint):
    path, writer, record, _ = checkpoint
    with writer.path.open("ab") as stream:
        stream.write(b'{"message":"\xe2')
    assert read_checkpoint(path) == record


@pytest.mark.parametrize("content", [
    '{"evaluation":1,"status":"success","f":4}\n{"evaluation":2',
    '{"evaluation":1,"status":"success","f":4}\n',
    '{"evaluation":2,"status":"success","f":4}\n{}\n',
    '{"evaluation":1,"status":"success","f":NaN}\n{}\n',
    '{"evaluation":1,"status":"success","f":1e999}\n{}\n',
    '[]\n{}\n',
    '{"evaluation":1,"evaluation":1,"status":"success","f":4}\n{}\n',
])
def test_reader_rejects_incomplete_or_invalid_committed_events(checkpoint, content):
    path, writer, _, _ = checkpoint
    writer.path.write_text(content)
    with pytest.raises(ValueError):
        read_checkpoint(path)


@pytest.mark.parametrize("edit", [
    lambda record: record.update(evaluation_count=3),
    lambda record: record.update(evaluation_count=True),
    lambda record: record.update(status="completed"),
    lambda record: record.update(trace=[{}]),
    lambda record: record["trace_storage"].update(events=True),
    lambda record: record["trace_storage"].update(events=1),
    lambda record: record["trace_storage"].update(events=3),
])
def test_reader_fails_closed_on_checkpoint_count_or_storage_mismatch(checkpoint, edit):
    path, _, _, compact = checkpoint
    invalid = copy.deepcopy(compact)
    edit(invalid)
    path.write_text(json.dumps(invalid))
    with pytest.raises(ValueError):
        read_checkpoint(path)


@pytest.mark.parametrize("relative", ["../escape.jsonl", "/tmp/escape.jsonl", "..\\escape.jsonl"])
def test_journal_cannot_escape_checkpoint_directory(checkpoint, relative):
    path, _, _, compact = checkpoint
    compact["trace_storage"]["path"] = relative
    with pytest.raises(ValueError, match="journal"):
        read_checkpoint(path, compact)


def test_journal_rejects_symbolic_links_even_to_an_inside_target(checkpoint):
    path, writer, _, compact = checkpoint
    link = path.parent / "linked.jsonl"
    try:
        link.symlink_to(writer.path)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symbolic links is not permitted on this system")
    compact["trace_storage"]["path"] = link.name
    with pytest.raises(ValueError, match="symbolic links"):
        read_checkpoint(path, compact)


def test_cleanup_updates_do_not_duplicate_function_evaluations(checkpoint):
    path, writer, record, _ = checkpoint
    writer.cleanup_warning(2, "diagnostics retained because cleanup failed")
    compact = writer.snapshot(record)
    recovered = read_checkpoint(path, compact)
    assert recovered["evaluation_count"] == len(recovered["trace"]) == 2
    assert recovered["trace"][-1]["cleanup_warning"] == "diagnostics retained because cleanup failed"
    assert compact["trace_storage"]["events"] == 3


def test_full_terminal_checkpoint_remains_self_contained_without_a_journal(tmp_path):
    path = tmp_path / "terminal.json"
    record = {"status": "completed", "evaluation_count": 1,
              "trace": [{"evaluation": 1, "status": "success", "f": 1.0}]}
    path.write_text(json.dumps(record))
    assert read_checkpoint(path) == record


def test_checkpoint_provenance_identifies_committed_journal_content_but_not_crash_tail(checkpoint):
    from tools import continue_replication

    path, writer, _, _ = checkpoint
    original = continue_replication._read(path)[1]
    with writer.path.open("a") as stream:
        stream.write('{"evaluation":3')
    assert continue_replication._read(path)[1] == original
    writer.path.write_text(writer.path.read_text().replace('"f":4.0', '"f":5.0'))
    assert continue_replication._read(path)[1] != original
