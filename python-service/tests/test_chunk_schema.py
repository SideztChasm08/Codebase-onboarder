import pytest

from chunk_schema import CHUNK_SCHEMA_VERSION, normalize_chunk


def sample(**updates):
    chunk = {
        "file": "./src/auth.py",
        "type": "function",
        "name": "login",
        "containing_class": "Auth",
        "start_line": 10,
        "end_line": 15,
        "source": "def login():\n    return True",
        "docstring": "Authenticate",
        "imports": ["hashlib"],
        "comments": ["# example"],
    }
    chunk.update(updates)
    return chunk


def test_normalize_is_deterministic_and_preserves_metadata():
    first = normalize_chunk(sample(), "repo-a")
    second = normalize_chunk(sample(), "repo-a")
    assert first == second
    assert first["schema_version"] == CHUNK_SCHEMA_VERSION
    assert first["file"] == "src/auth.py"
    assert first["qualified_name"] == "Auth.login"
    assert first["imports"] == ["hashlib"]
    assert first["comments"] == ["# example"]
    assert len(first["chunk_id"]) == 64


def test_identity_changes_for_repository_path_or_content():
    base = normalize_chunk(sample(), "repo-a")["chunk_id"]
    assert normalize_chunk(sample(), "repo-b")["chunk_id"] != base
    assert normalize_chunk(sample(file="src/other.py"), "repo-a")["chunk_id"] != base
    assert normalize_chunk(sample(source="def login(): return False"), "repo-a")["chunk_id"] != base


def test_module_metadata_defaults_are_explicit():
    module = normalize_chunk(
        {"file": "src/config.py", "type": "module", "source": "DEBUG = True"}, "r"
    )
    assert module["qualified_name"] == "<module>"
    assert module["name"] == "<module>"
    assert module["start_line"] == module["end_line"] == 1


@pytest.mark.parametrize("data", [
    {"file": "x.py", "source": ""},
    {"file": "", "source": "pass"},
    {"file": "x.py", "source": "pass", "start_line": 0},
])
def test_invalid_chunks_are_rejected(data):
    with pytest.raises(ValueError):
        normalize_chunk(data, "repo")
