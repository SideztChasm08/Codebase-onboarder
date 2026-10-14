
from pathlib import Path
from urllib.parse import urlparse

from git import Repo


SUPPORTED_EXTENSIONS = {".py"}

IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
}


def validate_repository_url(repo_url):
    """Allow HTTPS repository URLs for the initial MVP."""
    parsed = urlparse(repo_url)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(
            "Please provide a valid HTTPS repository URL."
        )

    return repo_url


def clone_repository(repo_url, destination, branch=None):
    """Clone a repository into a new local directory."""
    repo_url = validate_repository_url(repo_url)
    destination = Path(destination).resolve()

    if destination.exists():
        raise FileExistsError(
            f"Destination already exists: {destination}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        clone_options = {"depth": 1}

        if branch:
            clone_options["branch"] = branch
            clone_options["single_branch"] = True

        Repo.clone_from(
            repo_url,
            str(destination),
            **clone_options
        )

    except Exception:
        # Remove an incomplete clone before reporting failure.
        if destination.exists():
            import shutil
            shutil.rmtree(destination)

        raise

    return destination


def discover_source_files(repo_path):
    """Find supported source files while skipping generated folders."""
    repo_path = Path(repo_path).resolve()

    if not repo_path.is_dir():
        raise NotADirectoryError(
            f"Repository directory not found: {repo_path}"
        )

    source_files = []

    for file_path in repo_path.rglob("*"):
        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(repo_path)

        # Skip files inside ignored directories.
        if any(
            part in IGNORED_DIRECTORIES
            for part in relative_path.parts[:-1]
        ):
            continue

        # Include only supported source files.
        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            source_files.append(relative_path)

    return sorted(source_files)
