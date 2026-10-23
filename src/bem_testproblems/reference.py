"""Locate opt-in original reference assets without downloading during evaluation."""

import hashlib
import json
import os
from importlib.resources import files
from pathlib import Path

_FETCH_INSTRUCTION = (
    "Run the repository's tools/fetch_reference.py with your project Python, "
    "or set BEM_REFERENCE_DIR to an already fetched .reference-cache/beobenchmark directory."
)


def reference_root() -> Path:
    """Return the configured cache, checkout cache, or installed user's cwd cache."""
    configured = os.environ.get("BEM_REFERENCE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "src" / "bem_testproblems" / "reference.py").is_file():
        return checkout / ".reference-cache" / "beobenchmark"
    return Path.cwd().resolve() / ".reference-cache" / "beobenchmark"


def legacy_template_path(filename: str) -> Path:
    """Return one original IDF only after checking its package-pinned checksum.

    The trusted manifest is part of this package, never read from the cache.
    Original files are optional reference inputs, not normal modern-run assets.
    """
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("A known original template filename is required")
    manifest = json.loads(
        files("bem_testproblems").joinpath("data", "reference-assets.json").read_bytes()
    )
    cache_path = f"models/{filename}"
    records = [record for record in manifest["files"] if record["cache_path"] == cache_path]
    if len(records) != 1:
        raise ValueError(f"Unknown original reference template {filename!r}")
    path = reference_root() / "models" / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Original reference template is not cached: {path}. {_FETCH_INSTRUCTION}"
        )
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != records[0]["sha256"]:
        raise ValueError(
            f"Original reference template checksum mismatch: {path}. {_FETCH_INSTRUCTION}"
        )
    return path
