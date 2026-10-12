"""
repo_manager.py  (Ticket 201)

Clone a repository, or update it if it was already cloned, then list its
Python files. Lives in python-service/.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Where cloned repos are stored: one sub-folder per repo_id.
# Defaults to your WSL home folder (fast, and not synced by OneDrive).
# Override with the REPOS_ROOT environment variable.
REPOS_ROOT = Path(
    os.environ.get("REPOS_ROOT", Path.home() / ".codebase-assistant" / "repos")
)

MAX_ATTEMPTS = 5              # total tries per git operation
BASE_BACKOFF_SECONDS = 2      # waits 2s, 4s, 8s, 16s between the 5 attempts
GIT_TIMEOUT_SECONDS = 300     # hard limit for a single git command

# Folders that never contain the project's own code.
SKIP_DIRS = {
    ".git", "venv", ".venv", "env", "node_modules", "__pycache__",
    "site-packages", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
}
MAX_FILE_BYTES = 1_000_000    # skip huge files (usually generated code)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RepoError(Exception):
    """Base class: anything that went wrong while fetching a repo."""


class TransientGitError(RepoError):
    """Might work if we try again (network blip, HTTP 5xx, 408, 429, timeout)."""


class PermanentGitError(RepoError):
    """Retrying will not help (repo not found, no access, git missing)."""


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_repo_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Only https:// repository URLs are supported.")


def validate_repo_id(repo_id: str) -> None:
    # Prevents path tricks like "../../something" from escaping REPOS_ROOT.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", repo_id):
        raise ValueError("repo_id may only contain letters, digits, '_' and '-'.")


# ---------------------------------------------------------------------------
# Running git and classifying failures
# ---------------------------------------------------------------------------

_TRANSIENT_MARKERS = (
    "could not resolve host", "timed out", "connection reset",
    "failed to connect", "rpc failed", "early eof",
    "remote end hung up", "temporary failure", "unexpected disconnect",
)
_PERMANENT_MARKERS = (
    "repository not found", "authentication failed", "could not read username",
    "terminal prompts disabled", "permission denied", "access denied",
    "does not appear to be a git repository",
)


def _classify_failure(stderr: str) -> RepoError:
    """Turn git's error text into a transient or permanent error."""
    message = stderr.strip()[-500:] or "git failed with no error output"
    text = message.lower()

    # git prints HTTP failures like: "The requested URL returned error: 503"
    match = re.search(r"returned error: (\d{3})", text)
    if match:
        status = int(match.group(1))
        if status >= 500 or status in (408, 429):
            return TransientGitError(f"HTTP {status}: {message}")
        return PermanentGitError(f"HTTP {status}: {message}")

    if any(marker in text for marker in _PERMANENT_MARKERS):
        return PermanentGitError(message)
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return TransientGitError(message)

    # Unknown failure: fail fast and show the message so we can learn from it.
    return PermanentGitError(message)


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",         # never wait for a password prompt
        "GIT_HTTP_LOW_SPEED_LIMIT": "1000",  # abort if slower than 1 KB/s...
        "GIT_HTTP_LOW_SPEED_TIME": "60",     # ...for 60 seconds
    }
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise TransientGitError(
            f"git timed out after {GIT_TIMEOUT_SECONDS}s"
        ) from exc
    except FileNotFoundError as exc:
        raise PermanentGitError("git is not installed or not on PATH") from exc

    if result.returncode != 0:
        raise _classify_failure(result.stderr)
    return result.stdout


def _with_retries(action, label: str):
    """Run action(); retry transient failures with exponential backoff."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return action()
        except TransientGitError as exc:
            if attempt == MAX_ATTEMPTS:
                raise RepoError(
                    f"{label} failed after {MAX_ATTEMPTS} attempts: {exc}"
                ) from exc
            time.sleep(BASE_BACKOFF_SECONDS * 2 ** (attempt - 1))
    # PermanentGitError is not caught above, so it propagates immediately.


# ---------------------------------------------------------------------------
# Clone / update
# ---------------------------------------------------------------------------

def _clone(url: str, repo_path: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path)  # leftover from a previous failed attempt
    try:
        # "--" stops git from treating the URL as an option.
        _run_git(["clone", "--depth", "1", "--", url, str(repo_path)])
    except RepoError:
        shutil.rmtree(repo_path, ignore_errors=True)  # don't keep half a clone
        raise


def _update(repo_path: Path) -> None:
    _run_git(["fetch", "--depth", "1", "origin", "HEAD"], cwd=repo_path)
    _run_git(["reset", "--hard", "FETCH_HEAD"], cwd=repo_path)


def clone_or_update(url: str, repo_id: str) -> Path:
    """Make sure the repo is on disk and up to date. Returns its local path."""
    validate_repo_url(url)
    validate_repo_id(repo_id)

    repo_path = REPOS_ROOT / repo_id

    if (repo_path / ".git").exists():
        _with_retries(lambda: _update(repo_path), "update")
    else:
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        _with_retries(lambda: _clone(url, repo_path), "clone")

    return repo_path


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def list_python_files(repo_path: Path) -> list[Path]:
    python_files = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        # Editing dirnames in place tells os.walk not to descend into them.
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            file_path = Path(dirpath) / name
            if file_path.stat().st_size > MAX_FILE_BYTES:
                continue
            python_files.append(file_path)
    return sorted(python_files)


# ---------------------------------------------------------------------------
# Manual test: python repo_manager.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    path = clone_or_update("https://github.com/pallets/flask", "flask-demo")
    files = list_python_files(path)
    print(f"{len(files)} Python files found under {path}")
    for f in files[:5]:
        print("  ", f.relative_to(path))
