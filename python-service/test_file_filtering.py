
from pathlib import Path
from tempfile import TemporaryDirectory

from repository_ingestion import discover_source_files

with TemporaryDirectory() as temp:
    root = Path(temp)

    (root / "main.py").write_text("def hello(): pass")
    (root / "notes.txt").write_text("not Python")

    ignored = root / "__pycache__"
    ignored.mkdir()
    (ignored / "cached.py").write_text("def ignored(): pass")

    files = discover_source_files(root)

    assert files == [Path("main.py")], files

print("File filtering tests passed!")
