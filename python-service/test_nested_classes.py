from pathlib import Path
from parser.tree_sitter_chunker import chunk_file

sample = Path("nested_sample.py")
chunks = chunk_file(sample)

for chunk in chunks:
    print(
        chunk["type"],
        chunk["name"],
        "| Containing class:",
        chunk["containing_class"]
    )