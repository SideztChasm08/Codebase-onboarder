
from pathlib import Path
from uuid import uuid4

from repository_ingestion import (
    clone_repository,
    discover_source_files,
)
from parser.tree_sitter_chunker import chunk_file


REPO_URL = (
    "https://github.com/SideztChasm08/Codebase-onboarder.git"
)

destination = Path(f"cloned_dev_test_{uuid4().hex[:8]}")

# Step 1: Clone the selected branch.
cloned_path = clone_repository(
    REPO_URL,
    destination,
    branch="dev",
)

# Step 2: Discover supported source files.
source_files = discover_source_files(cloned_path)

print("Repository cloned to:", cloned_path)
print("Python files found:", len(source_files))

# Step 3: Parse each file and collect its chunks.
all_chunks = []

for relative_path in source_files:
    full_path = cloned_path / relative_path
    chunks = chunk_file(full_path, repo_root=cloned_path)
    all_chunks.extend(chunks)

    print(f"\nFile: {relative_path}")
    print(f"Chunks found: {len(chunks)}")

# Step 4: Display a summary.
print("\nTotal chunks:", len(all_chunks))

for chunk in all_chunks:
    print(
        chunk["type"],
        chunk["name"],
        "| File:",
        chunk["file"],
        "| Lines:",
        chunk["start_line"],
        "-",
        chunk["end_line"],
    )

print("\nEnd-to-end ingestion test completed!")
