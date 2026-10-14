
from pathlib import Path
from parser.tree_sitter_chunker import chunk_file

sample = Path("test_tree_sitter_sample.py")


sample.write_text(
    '''import math
from pathlib import Path

class Calculator:
    """A simple calculator."""

    def add(self, a, b):
        """Add two numbers."""
        return a + b

def multiply(a, b):
    return a * b

def subtract(a, b):
    # Subtract b from a
    return a - b
''',
    encoding="utf-8",
)


chunks = chunk_file(sample)

for chunk in chunks:
    print("-" * 40)
    print("Type:", chunk["type"])
    print("Name:", chunk["name"])
    print("Lines:", chunk["start_line"], "-", chunk["end_line"])
    print("Containing class:", chunk["containing_class"])
    print("Docstring:", chunk["docstring"])
    print("Imports:", chunk["imports"])
    print("Comments:", chunk["comments"])
    print("Source:")
    print(chunk["source"])

# Verify the integrated chunk metadata
class_chunk = next(c for c in chunks if c["name"] == "Calculator")
add_chunk = next(c for c in chunks if c["name"] == "add")
subtract_chunk = next(c for c in chunks if c["name"] == "subtract")

assert class_chunk["docstring"] == "A simple calculator."
assert add_chunk["docstring"] == "Add two numbers."
assert subtract_chunk["comments"] == ["# Subtract b from a"]

assert class_chunk["imports"] == ["math", "pathlib.Path"]
assert add_chunk["containing_class"] == "Calculator"
assert subtract_chunk["containing_class"] is None

print("All Tree-sitter metadata checks passed!")
