"""Canonical chunk metadata contract used by embedding and storage (version 1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath


CHUNK_SCHEMA_VERSION = 1


def normalize_chunk(chunk: dict, repo_id: str) -> dict:
    """Return a validated, stable chunk record independent of parser internals."""
    path = str(chunk.get("file", "")).replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    parsed_path = PurePosixPath(path)
    if (not parsed_path.parts or parsed_path.is_absolute() or ".." in parsed_path.parts
            or (parsed_path.parts and ":" in parsed_path.parts[0])):
        raise ValueError("Chunk file path must be a safe repository-relative path")
    path = parsed_path.as_posix()
    source = chunk.get("source")
    if not path or not isinstance(source, str) or not source.strip():
        raise ValueError("A chunk requires a relative file path and non-empty source")

    chunk_type = chunk.get("type", "module")
    name = chunk.get("name") or ("<module>" if chunk_type == "module" else "<anonymous>")
    containing_class = chunk.get("containing_class")
    qualified_name = chunk.get("qualified_name") or ".".join(
        part for part in (containing_class, name) if part
    )
    if chunk_type == "module" and not chunk.get("qualified_name"):
        qualified_name = "<module>"

    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    identity = json.dumps(
        [str(repo_id), path, chunk_type, qualified_name, source_hash],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    start_line = int(chunk.get("start_line", 1))
    end_line = int(chunk.get("end_line", start_line))
    if start_line < 1 or end_line < start_line:
        raise ValueError("Chunk line range must be positive and ordered")

    return {
        "schema_version": CHUNK_SCHEMA_VERSION,
        "chunk_id": chunk_id,
        "repo_id": str(repo_id),
        "file": path,
        "type": str(chunk_type),
        "name": str(name),
        "qualified_name": str(qualified_name),
        "containing_class": containing_class,
        "start_line": start_line,
        "end_line": end_line,
        "source": source,
        "docstring": chunk.get("docstring"),
        "imports": list(chunk.get("imports") or []),
        "comments": list(chunk.get("comments") or []),
        "source_hash": source_hash,
    }
