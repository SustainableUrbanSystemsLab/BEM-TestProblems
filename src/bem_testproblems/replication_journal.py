# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Durable append-only traces for long searches; terminal JSON stays self-contained."""

import json
import os
import uuid
from pathlib import Path


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate trace journal key")
        result[key] = value
    return result


def _journal_path(checkpoint, relative):
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Invalid relative trace journal path")
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise ValueError("Trace journal must remain inside the checkpoint directory")
    base = Path(checkpoint).parent.resolve()
    target = base
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("Trace journal paths must not contain symbolic links")
    if not target.resolve().is_relative_to(base):
        raise ValueError("Trace journal escapes the checkpoint directory")
    return target


def read_checkpoint(path, record=None):
    """Materialize exactly the committed journal prefix, ignoring uncommitted tails.

    A killed worker can leave extra complete lines or a partial trailing line
    after the last atomic checkpoint. Those bytes remain private evidence and
    are not observations belonging to the committed checkpoint.
    """
    record = json.loads(Path(path).read_text()) if record is None else record
    if "trace_storage" not in record:
        return record
    storage = record["trace_storage"]
    count = record.get("evaluation_count")
    if (not isinstance(storage, dict) or set(storage) != {"format", "path", "events"}
            or storage["format"] != "jsonl-v1" or type(storage["events"]) is not int
            or type(count) is not int or count < 0 or storage["events"] < count
            or record.get("trace") != [] or record.get("status") not in {"running", "interrupted"}):
        raise ValueError("Invalid compact trace checkpoint")
    trace = []
    with _journal_path(path, storage["path"]).open("rb") as stream:
        for _ in range(storage["events"]):
            line = stream.readline()
            if not line.endswith(b"\n"):
                raise ValueError("Trace journal is missing a committed complete event")
            try:
                item = json.loads(line, object_pairs_hook=_unique_pairs)
                json.dumps(item, allow_nan=False)
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid committed trace journal event") from error
            if not isinstance(item, dict):
                raise ValueError("Invalid committed trace journal event")
            if "update_evaluation" in item:
                if (set(item) != {"update_evaluation", "cleanup_warning"} or not trace
                        or type(item["update_evaluation"]) is not int
                        or item["update_evaluation"] != len(trace)
                        or not isinstance(item["cleanup_warning"], str)
                        or "cleanup_warning" in trace[-1]):
                    raise ValueError("Invalid trace cleanup update")
                trace[-1]["cleanup_warning"] = item["cleanup_warning"]
            elif (type(item.get("evaluation")) is int and item["evaluation"] == len(trace) + 1
                  and item.get("status") in {"success", "failed"}):
                trace.append(item)
            else:
                raise ValueError("Trace evaluations are missing or out of order")
    if len(trace) != count:
        raise ValueError("Trace evaluation count differs from the checkpoint")
    return {key: value for key, value in {**record, "trace": trace}.items() if key != "trace_storage"}


class TraceJournal:
    """Write each observation once before atomically publishing its small checkpoint."""

    def __init__(self, checkpoint, attempt):
        checkpoint = Path(checkpoint)
        self.relative = f"traces/{checkpoint.stem}-attempt{attempt:03}-{uuid.uuid4().hex}.jsonl"
        self.path = _journal_path(checkpoint, self.relative)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("x", encoding="utf-8"):
            pass
        self.events = self.evaluations = 0

    def _append(self, item):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, separators=(",", ":"), allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.events += 1

    def cleanup_warning(self, evaluation, message):
        self._append({"update_evaluation": evaluation, "cleanup_warning": message})

    def snapshot(self, record):
        for item in record["trace"][self.evaluations:]:
            self._append(item)
            self.evaluations += 1
        return {**record, "trace": [], "trace_storage": {
            "format": "jsonl-v1", "path": self.relative, "events": self.events}}
