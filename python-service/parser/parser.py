import ast
from pathlib import Path


def parse_file(file_path):

    code = Path(file_path).read_text(encoding="utf-8")

    tree = ast.parse(code)

    imports = []

    for node in tree.body:

        if isinstance(node, ast.Import):

            for item in node.names:
                imports.append(item.name)

        elif isinstance(node, ast.ImportFrom):

            module = node.module or ""

            for item in node.names:
                imports.append(f"{module}.{item.name}")

    chunks = []

    def visit(node, class_stack=None):

        if class_stack is None:
            class_stack = []

        if isinstance(node, ast.ClassDef):

            source = ast.get_source_segment(code, node)

            chunk = {
                "file": str(file_path),
                "type": "class",
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "containing_class": ".".join(class_stack) if class_stack else None,
                "docstring": ast.get_docstring(node),
                "imports": imports,
                "source": source
            }

            chunks.append(chunk)

            class_stack = class_stack + [node.name]

        elif isinstance(node, ast.FunctionDef):

            source = ast.get_source_segment(code, node)

            chunk = {
                "file": str(file_path),
                "type": "function",
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "containing_class": ".".join(class_stack) if class_stack else None,
                "docstring": ast.get_docstring(node),
                "imports": imports,
                "source": source
            }

            chunks.append(chunk)

        for child in ast.iter_child_nodes(node):
            visit(child, class_stack)

    visit(tree)

    return chunks