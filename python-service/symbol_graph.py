"""Deterministic, best-effort Python symbol and call graph construction."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from repository_ingestion import discover_source_files


def _stable_id(*parts: str) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def module_name(relative_path: str) -> str:
    path = Path(relative_path).with_suffix("")
    parts = list(path.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "<module>"


@dataclass
class SymbolGraph:
    repo_id: str
    revision: str
    symbols: list[dict]
    call_sites: list[dict]
    unresolved_calls: list[dict]
    syntax_errors: list[dict]

    def find_definitions(self, name: str) -> list[dict]:
        """Find matching symbols by simple name or fully qualified name."""
        return [s for s in self.symbols
                if s["name"] == name or s["qualified_name"] == name]

    def find_references(self, name: str) -> list[dict]:
        targets = {s["symbol_id"] for s in self.find_definitions(name)}
        return [call for call in self.call_sites if call["target_symbol_id"] in targets]

    def find_callers(self, name: str) -> list[dict]:
        callers = {call["caller_symbol_id"] for call in self.find_references(name)
                   if call["caller_symbol_id"]}
        return [s for s in self.symbols if s["symbol_id"] in callers]

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "repo_id": self.repo_id,
            "revision": self.revision,
            "symbols": self.symbols,
            "call_sites": self.call_sites,
            "unresolved_calls": self.unresolved_calls,
            "syntax_errors": self.syntax_errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SymbolGraph":
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported symbol graph schema version")
        return cls(data["repo_id"], data["revision"], data["symbols"],
                   data["call_sites"], data["unresolved_calls"],
                   data.get("syntax_errors", []))


class _FileAnalysis:
    def _collect_imports(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    local = item.asname or item.name.split(".")[0]
                    imported_module = item.name if item.asname else local
                    self.imports[local] = (imported_module, None)
            elif isinstance(node, ast.ImportFrom):
                base = self._resolve_import_module(node.module or "", node.level)
                for item in node.names:
                    if item.name != "*":
                        self.imports[item.asname or item.name] = (base, item.name)

    def _resolve_import_module(self, name: str, level: int) -> str:
        if not level:
            return name
        package = self.module.split(".")[:-1]
        if self.path.endswith("/__init__.py") or self.path == "__init__.py":
            package = self.module.split(".")
        keep = max(0, len(package) - level + 1)
        prefix = package[:keep]
        return ".".join([*prefix, name] if name else prefix)

    def _collect_definitions(self, node: ast.AST, scope: list[dict]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = ("class" if isinstance(child, ast.ClassDef) else
                        "method" if scope and scope[-1]["kind"] == "class" else
                        "nested_function" if scope and scope[-1]["kind"] != "module" else
                        "function")
                qname = ".".join([self.module, *(s["name"] for s in scope
                                                    if s["kind"] != "module"), child.name])
                decorators = child.decorator_list
                start = min([child.lineno, *(d.lineno for d in decorators)])
                end = child.end_lineno or child.lineno
                identity_source = "\n".join(self._source_lines[start - 1:end])
                symbol = {
                    "symbol_id": _stable_id(self.repo_id, self.path,
                                            qname, kind, str(start), identity_source),
                    "repo_id": self.repo_id,
                    "revision": self.revision,
                    "file": self.path,
                    "module": self.module,
                    "name": child.name,
                    "qualified_name": qname,
                    "kind": kind,
                    "start_line": start,
                    "end_line": end,
                    "decorators": [ast.get_source_segment("\n".join(self._source_lines), d)
                                   for d in decorators],
                }
                self.definitions.append(symbol)
                self.nodes[id(child)] = symbol
                nested_scope = [*scope, {"name": child.name, "kind": kind}]
                self._collect_definitions(child, nested_scope)
            else:
                self._collect_definitions(child, scope)

    def _collect_calls(self, node: ast.AST, functions: list[dict], class_name: str | None):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Decorators, defaults, and annotations execute in the enclosing scope.
            outer_nodes = [*node.decorator_list, node.args]
            if node.returns:
                outer_nodes.append(node.returns)
            for outer_node in outer_nodes:
                self._collect_calls(outer_node, functions, class_name)
            symbol = self.nodes.get(id(node))
            functions = [*functions, symbol] if symbol else functions
            for statement in node.body:
                self._collect_calls(statement, functions, class_name)
            return
        elif isinstance(node, ast.ClassDef):
            for outer_node in [*node.decorator_list, *node.bases, *node.keywords]:
                self._collect_calls(outer_node, functions, class_name)
            symbol = self.nodes.get(id(node))
            class_name = symbol["qualified_name"] if symbol else class_name
            for statement in node.body:
                self._collect_calls(statement, functions, class_name)
            return
        if isinstance(node, ast.Call):
            self.calls.append((node, functions[-1] if functions else None, class_name))
        for child in ast.iter_child_nodes(node):
            self._collect_calls(child, functions, class_name)

    @property
    def _source_lines(self):
        return self.source.splitlines()

    @classmethod
    def parse(cls, relative_path: str, source: str, repo_id: str, revision: str):
        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as exc:
            return None, {"file": relative_path, "line": exc.lineno,
                          "message": exc.msg}
        instance = cls.__new__(cls)
        instance.repo_id = str(repo_id)
        instance.revision = str(revision)
        instance.source = source
        instance.path = relative_path
        instance.module = module_name(relative_path)
        instance.tree = tree
        instance.imports = {}
        instance.definitions = []
        instance.nodes = {}
        instance.calls = []
        instance._collect_imports()
        instance._collect_definitions(tree, [{"name": instance.module, "kind": "module"}])
        instance._collect_calls(tree, [], None)
        return instance, None


def build_symbol_graph(repo_path, repo_id: str, revision: str) -> SymbolGraph:
    """Parse supported Python files into a deterministic repository snapshot."""
    if not repo_id or not revision:
        raise ValueError("repo_id and revision are required")
    root = Path(repo_path).resolve()
    analyses = []
    errors = []
    for relative in discover_source_files(root):
        rel = Path(relative).as_posix()
        analysis, error = _FileAnalysis.parse(
            rel, (root / relative).read_text(encoding="utf-8"), str(repo_id), str(revision)
        )
        if error:
            errors.append(error)
        else:
            analyses.append(analysis)

    symbols = [symbol for analysis in analyses for symbol in analysis.definitions]
    by_module_name: dict[tuple[str, str], list[dict]] = {}
    for symbol in symbols:
        by_module_name.setdefault((symbol["module"], symbol["name"]), []).append(symbol)
    by_qname = {}
    for symbol in symbols:
        by_qname.setdefault(symbol["qualified_name"], []).append(symbol)

    call_sites = []
    unresolved = []
    for analysis in analyses:
        for node, caller, class_name in analysis.calls:
            expression = ast.unparse(node.func)
            target = _resolve_call(node.func, analysis, by_module_name, by_qname,
                                   class_name, caller)
            site = {
                "call_id": _stable_id(str(repo_id), analysis.path,
                                      str(node.lineno), str(node.col_offset), expression,
                                      caller["symbol_id"] if caller else ""),
                "repo_id": str(repo_id), "revision": str(revision),
                "file": analysis.path, "line": node.lineno, "column": node.col_offset,
                "expression": expression,
                "caller_symbol_id": caller["symbol_id"] if caller else None,
                "caller_qualified_name": caller["qualified_name"] if caller else None,
            }
            if target:
                site["target_symbol_id"] = target["symbol_id"]
                site["target_qualified_name"] = target["qualified_name"]
                call_sites.append(site)
            else:
                site["resolution"] = "unresolved"
                unresolved.append(site)
    symbols.sort(key=lambda item: (item["file"], item["start_line"], item["qualified_name"]))
    call_sites.sort(key=lambda item: (item["file"], item["line"], item["column"], item["expression"]))
    unresolved.sort(key=lambda item: (item["file"], item["line"], item["column"]))
    errors.sort(key=lambda item: item["file"])
    return SymbolGraph(str(repo_id), str(revision), symbols, call_sites, unresolved, errors)


def _resolve_call(func: ast.AST, analysis: _FileAnalysis,
                  by_module_name: dict, by_qname: dict, class_name: str | None,
                  caller: dict | None):
    candidates = []
    if isinstance(func, ast.Name):
        imported = analysis.imports.get(func.id)
        if imported:
            module, imported_name = imported
            if imported_name:
                candidates = by_module_name.get((module, imported_name), [])
        else:
            if caller:
                scope = caller["qualified_name"]
                while scope:
                    candidates = by_qname.get(f"{scope}.{func.id}", [])
                    if candidates:
                        break
                    if "." not in scope:
                        break
                    scope = scope.rsplit(".", 1)[0]
            if not candidates:
                candidates = by_module_name.get((analysis.module, func.id), [])
    elif isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id in {"self", "cls"} and class_name:
            candidates = by_qname.get(f"{class_name}.{func.attr}", [])
        elif isinstance(func.value, (ast.Name, ast.Attribute)):
            prefix = _resolve_import_prefix(ast.unparse(func.value), analysis.imports)
            if prefix:
                candidates = by_qname.get(f"{prefix}.{func.attr}", [])
                if not candidates:
                    candidates = by_module_name.get((prefix, func.attr), [])
            elif isinstance(func.value, ast.Name):
                candidates = by_qname.get(
                    f"{analysis.module}.{func.value.id}.{func.attr}", []
                )
    return candidates[0] if len(candidates) == 1 else None


def _resolve_import_prefix(expression: str, imports: dict[str, tuple[str, str | None]]):
    parts = expression.split(".")
    binding = imports.get(parts[0])
    if not binding:
        return None
    module, imported_name = binding
    prefix = ".".join(filter(None, (module, imported_name)))
    return ".".join([prefix, *parts[1:]])


def save_symbol_graph(graph: SymbolGraph, path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")


def load_symbol_graph(path, repo_id: str | None = None,
                      revision: str | None = None) -> SymbolGraph:
    graph = SymbolGraph.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    if repo_id is not None and graph.repo_id != repo_id:
        raise ValueError("Symbol graph repository does not match requested repo_id")
    if revision is not None and graph.revision != revision:
        raise ValueError("Symbol graph revision does not match requested revision")
    return graph
