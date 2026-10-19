from parser.tree_sitter_chunker import chunk_file


def test_module_statements_and_symbol_chunks_share_relative_metadata(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        """import os
from pathlib import Path
CONFIG = os.getenv('APP_MODE') # module comment

class Service:
    def run(self):
        # method-local comment
        return CONFIG

def helper():
    return 1

AFTER = 2
""",
        encoding="utf-8",
    )

    chunks = chunk_file(source, repo_root=tmp_path)
    modules = [chunk for chunk in chunks if chunk["type"] == "module"]
    service = next(chunk for chunk in chunks if chunk["name"] == "Service")
    method = next(chunk for chunk in chunks if chunk["name"] == "run")

    assert [chunk["source"] for chunk in modules] == [
        "CONFIG = os.getenv('APP_MODE')", "AFTER = 2"
    ]
    assert [chunk["start_line"] for chunk in modules] == [3, 13]
    assert modules[0]["comments"] == ["# module comment"]
    assert all("def run" not in chunk["source"] for chunk in modules)
    assert all("class Service" not in chunk["source"] for chunk in modules)
    assert all("method-local comment" not in " ".join(chunk["comments"])
               for chunk in modules)
    assert all(chunk["file"] == "sample.py" for chunk in modules)
    assert service["containing_class"] is None
    assert method["containing_class"] == "Service"
    # Class and method chunks intentionally overlap for class-level context.
    assert service["start_line"] <= method["start_line"] <= service["end_line"]


def test_declaration_only_file_does_not_get_empty_module_chunk(tmp_path):
    source = tmp_path / "symbols.py"
    source.write_text("def f():\n    return 1\n", encoding="utf-8")
    chunks = chunk_file(source, repo_root=tmp_path)
    assert len(chunks) == 1
    assert chunks[0]["type"] == "function"


def test_import_only_file_has_no_module_execution_chunk(tmp_path):
    source = tmp_path / "imports.py"
    source.write_text("from pathlib import Path\n", encoding="utf-8")
    assert chunk_file(source, repo_root=tmp_path) == []


def test_nested_identical_helpers_get_distinct_qualified_names_and_ids(tmp_path):
    from chunk_schema import normalize_chunk

    source = tmp_path / "nested.py"
    source.write_text(
        """def first():
    def helper():
        return 1
    return helper()

def second():
    def helper():
        return 1
    return helper()
""",
        encoding="utf-8",
    )

    chunks = chunk_file(source, repo_root=tmp_path)
    helpers = [chunk for chunk in chunks if chunk["name"] == "helper"]
    normalized = [normalize_chunk(chunk, "repo") for chunk in helpers]

    assert [chunk["qualified_name"] for chunk in helpers] == [
        "first.helper", "second.helper"
    ]
    assert len({chunk["chunk_id"] for chunk in normalized}) == 2


def test_decorated_function_keeps_decorator_source_and_range_once(tmp_path):
    source = tmp_path / "decorated_function.py"
    source.write_text(
        """def decorate(function):
    return function

@decorate
def run():
    return True
""",
        encoding="utf-8",
    )

    chunks = chunk_file(source, repo_root=tmp_path)
    functions = [chunk for chunk in chunks if chunk["name"] == "run"]

    assert len(functions) == 1
    assert functions[0]["source"] == "@decorate\ndef run():\n    return True"
    assert (functions[0]["start_line"], functions[0]["end_line"]) == (4, 6)
    assert functions[0]["qualified_name"] == "run"


def test_decorated_class_keeps_decorator_source_range_and_method_scope(tmp_path):
    source = tmp_path / "decorated_class.py"
    source.write_text(
        """def decorate(cls):
    return cls

@decorate
class Service:
    def run(self):
        return True
""",
        encoding="utf-8",
    )

    chunks = chunk_file(source, repo_root=tmp_path)
    classes = [chunk for chunk in chunks if chunk["name"] == "Service"]
    methods = [chunk for chunk in chunks if chunk["name"] == "run"]

    assert len(classes) == 1
    assert classes[0]["source"] == (
        "@decorate\nclass Service:\n    def run(self):\n        return True"
    )
    assert (classes[0]["start_line"], classes[0]["end_line"]) == (4, 7)
    assert classes[0]["qualified_name"] == "Service"
    assert len(methods) == 1
    assert methods[0]["qualified_name"] == "Service.run"
    assert methods[0]["containing_class"] == "Service"


def test_module_comments_stay_with_their_statement_boundary(tmp_path):
    source = tmp_path / "comment_boundaries.py"
    source.write_text(
        """# before first statement
FIRST = 1  # first statement comment

class Service:
    # declaration-internal comment
    def run(self):
        return True
# between declaration and second statement
SECOND = 2  # second statement comment
# after second statement
""",
        encoding="utf-8",
    )

    chunks = chunk_file(source, repo_root=tmp_path)
    modules = [chunk for chunk in chunks if chunk["type"] == "module"]

    assert [chunk["source"] for chunk in modules] == ["FIRST = 1", "SECOND = 2"]
    assert modules[0]["comments"] == ["# first statement comment"]
    assert modules[1]["comments"] == ["# second statement comment"]
    assert all(
        "declaration-internal" not in " ".join(chunk["comments"])
        and "between declaration" not in " ".join(chunk["comments"])
        and "before first" not in " ".join(chunk["comments"])
        and "after second" not in " ".join(chunk["comments"])
        for chunk in modules
    )
