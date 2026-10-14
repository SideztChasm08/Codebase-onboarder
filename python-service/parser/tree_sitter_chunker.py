
import ast
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser


PY_LANGUAGE = Language(tspython.language())


def get_node_name(node):
    name_node = node.child_by_field_name("name")

    if name_node is None:
        return None

    return name_node.text.decode("utf-8")


def extract_python_metadata(source):
    """Extract imports and docstrings using Python's AST."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], {}

    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                imports.append(item.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""

            for item in node.names:
                imports.append(f"{module}.{item.name}")

    docstrings = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            key = (
                "class" if isinstance(node, ast.ClassDef) else "function",
                node.name,
                node.lineno,
            )

            docstrings[key] = ast.get_docstring(node)

    return imports, docstrings

def extract_comments(node):
    """Collect comments inside a syntax node."""
    comments = []

    def visit(current):
        if current.type == "comment":
            comments.append(current.text.decode("utf-8"))
            return

        for child in current.children:
            visit(child)

    visit(node)
    return comments


def chunk_file(file_path, repo_root=None):
    file_path = Path(file_path).resolve()
    source = file_path.read_text(encoding="utf-8")
    source_bytes = source.encode("utf-8")

    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source_bytes)

    imports, docstrings = extract_python_metadata(source)
    if repo_root is not None:
       repo_root = Path(repo_root).resolve()
       stored_path = file_path.relative_to(repo_root).as_posix()
    else:
         stored_path = file_path.as_posix()
    chunks = []

    def visit(node, class_stack=None):
        if class_stack is None:
            class_stack = []

        if node.type in ("class_definition", "function_definition"):
            name = get_node_name(node)

            if name is not None:
                chunk_type = (
                    "class"
                    if node.type == "class_definition"
                    else "function"
                )

                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                key = (chunk_type, name, start_line)

                chunks.append({
                    "file": stored_path,
                    "type": chunk_type,
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "containing_class": (
                        ".".join(class_stack) if class_stack else None
                    ),
                    "docstring": docstrings.get(key),
                    "imports": imports,
                    "comments": extract_comments(node),
                    "source": node.text.decode("utf-8"),
                })

                if chunk_type == "class":
                    class_stack = class_stack + [name]

        for child in node.children:
            visit(child, class_stack)

    visit(tree.root_node)
    return chunks
