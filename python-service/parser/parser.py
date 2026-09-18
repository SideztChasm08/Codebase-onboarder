import ast
from pathlib import Path


def parse_file(file_path):
    code = Path(file_path).read_text(encoding="utf-8")

    tree = ast.parse(code)

    chunks = []

    for node in ast.walk(tree):

        # Function
        if isinstance(node, ast.FunctionDef):

            source = ast.get_source_segment(code, node)

            chunk = {
                "file": str(file_path),
                "type": "function",
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "source": source
            }

            chunks.append(chunk)

        # Class
        if isinstance(node, ast.ClassDef):

            source = ast.get_source_segment(code, node)

            chunk = {
                "file": str(file_path),
                "type": "class",
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "source": source
            }

            chunks.append(chunk)

    return chunks