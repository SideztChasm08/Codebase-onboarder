
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

    # Keep each executable module-level statement separate. Slicing from the
    # first through last statement could accidentally include declarations in
    # between them.
    module_statements = [
        child for child in tree.root_node.named_children
        if child.type not in {
            "comment", "import_statement", "import_from_statement",
            "future_import_statement",
            "function_definition", "class_definition", "decorated_definition",
        }
    ]
    for statement in module_statements:
        start_line = statement.start_point[0] + 1
        end_line = statement.end_point[0] + 1
        statement_comments = extract_comments(statement)
        statement_comments.extend([
            child.text.decode("utf-8")
            for child in tree.root_node.named_children
            if child.type == "comment"
            and start_line <= child.start_point[0] + 1 <= end_line
        ])
        chunks.append({
            "file": stored_path,
            "type": "module",
            "name": "<module>",
            "qualified_name": f"<module>.statement@{statement.start_byte}",
            "start_line": start_line,
            "end_line": end_line,
            "containing_class": None,
            "docstring": None,
            "imports": imports,
            "comments": list(dict.fromkeys(statement_comments)),
            "source": source_bytes[statement.start_byte:statement.end_byte].decode("utf-8"),
        })

    def visit(node, lexical_scope=None, class_stack=None, source_node=None):
        lexical_scope = lexical_scope or []
        class_stack = class_stack or []
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type in ("function_definition", "class_definition"):
                    visit(child, lexical_scope, class_stack, node)
                else:
                    visit(child, lexical_scope, class_stack)
            return

        if node.type in ("class_definition", "function_definition"):
            name = get_node_name(node)

            if name is not None:
                chunk_type = (
                    "class"
                    if node.type == "class_definition"
                    else "function"
                )

                span_node = source_node or node
                start_line = span_node.start_point[0] + 1
                end_line = span_node.end_point[0] + 1
                qualified_name = ".".join([*lexical_scope, name])

                key = (chunk_type, name, node.start_point[0] + 1)

                chunks.append({
                    "file": stored_path,
                    "type": chunk_type,
                    "name": name,
                    "qualified_name": qualified_name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "containing_class": (
                        ".".join(class_stack) if class_stack else None
                    ),
                    "docstring": docstrings.get(key),
                    "imports": imports,
                    "comments": extract_comments(span_node),
                    "source": span_node.text.decode("utf-8"),
                })

                lexical_scope = [*lexical_scope, name]
                if chunk_type == "class":
                    class_stack = [*class_stack, name]

        for child in node.children:
            visit(child, lexical_scope, class_stack)

    visit(tree.root_node, [], [])
    return chunks
