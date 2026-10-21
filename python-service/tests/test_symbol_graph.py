import json

from symbol_graph import (build_symbol_graph, load_symbol_graph,
                          save_symbol_graph)


def test_definitions_scopes_calls_import_aliases_and_determinism(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "targets.py").write_text(
        "def target():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "entry.py").write_text(
        """from pkg.targets import target as alias
import pkg.targets as targets
import pkg.targets

def root():
    alias()
    targets.target()
    pkg.targets.target()
    external_library_call()

def recurse():
    recurse()

class Service:
    def run(self):
        self.run()

def first():
    def helper():
        return 1
    return helper()

def second():
    def helper():
        return 2
    return helper()
""",
        encoding="utf-8",
    )

    graph = build_symbol_graph(tmp_path, "repo", "rev-1")
    repeated = build_symbol_graph(tmp_path, "repo", "rev-1")

    assert graph.to_dict() == repeated.to_dict()
    target = graph.find_definitions("pkg.targets.target")
    assert len(target) == 1
    assert target[0]["file"] == "pkg/targets.py"
    assert (target[0]["start_line"], target[0]["end_line"]) == (1, 2)
    assert len(graph.find_references("pkg.targets.target")) == 3
    assert len(graph.find_callers("pkg.targets.target")) == 1
    assert len(graph.find_references("pkg.entry.recurse")) == 1
    assert len(graph.find_references("pkg.entry.Service.run")) == 1
    helpers = [s for s in graph.symbols if s["name"] == "helper"]
    assert {s["qualified_name"] for s in helpers} == {
        "pkg.entry.first.helper", "pkg.entry.second.helper"
    }
    assert len({s["symbol_id"] for s in helpers}) == 2
    assert len(graph.find_references("pkg.entry.first.helper")) == 1
    assert len(graph.find_references("pkg.entry.second.helper")) == 1
    assert any(c["expression"] == "external_library_call()".removesuffix("()")
               for c in graph.unresolved_calls)


def test_syntax_errors_are_reported_without_losing_other_files(tmp_path):
    (tmp_path / "good.py").write_text("def okay(): pass\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def nope(:\n", encoding="utf-8")
    graph = build_symbol_graph(tmp_path, "repo", "rev")
    assert [symbol["name"] for symbol in graph.symbols] == ["okay"]
    assert graph.syntax_errors == [{
        "file": "broken.py", "line": 1,
        "message": "invalid syntax",
    }]


def test_decorated_definition_uses_decorator_start_and_full_range(tmp_path):
    (tmp_path / "decorated.py").write_text(
        """def register(function):
    return function

@register
def handler():
    return True
""",
        encoding="utf-8",
    )
    graph = build_symbol_graph(tmp_path, "repo", "rev")
    handler = graph.find_definitions("decorated.handler")[0]
    assert (handler["start_line"], handler["end_line"]) == (4, 6)
    assert handler["decorators"] == ["register"]


def test_graph_snapshots_are_isolated_by_repository_and_revision(tmp_path):
    (tmp_path / "mod.py").write_text("def item(): pass\n", encoding="utf-8")
    graph = build_symbol_graph(tmp_path, "repo-a", "rev-a")
    later_graph = build_symbol_graph(tmp_path, "repo-a", "rev-b")
    assert [s["symbol_id"] for s in graph.symbols] == [
        s["symbol_id"] for s in later_graph.symbols
    ]
    saved = tmp_path / "graph.json"
    save_symbol_graph(graph, saved)
    assert load_symbol_graph(saved, "repo-a", "rev-a").repo_id == "repo-a"
    for repo_id, revision, message in [
        ("repo-b", "rev-a", "repository"),
        ("repo-a", "rev-b", "revision"),
    ]:
        try:
            load_symbol_graph(saved, repo_id, revision)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("mismatched graph identity was accepted")
    assert json.loads(saved.read_text(encoding="utf-8"))["schema_version"] == 1
