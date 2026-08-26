"""Ensure secret_key in settings.yml is not a known committed value.

If the secret_key is the literal default, a known committed value from the
historical defaults, or any key present in the git history of
config/settings.yml, generate a new random key.

This script is called by the launcher batch file before starting the server.
"""
import secrets
import os
import re
import subprocess
import sys

DEFAULT_KEY = "SearXNG for Windows-mbaozi"
# Known committed keys in config/settings.yml that must be rotated on first run.
# These values were committed to the repository and are shared by all clones.
KNOWN_COMMITTED_KEYS = [
    DEFAULT_KEY,
    "ultrasecretkey",
    "your_secret_key",
    "default_secret_key",
    "654eba279ae3354410f8c36f11535af7b1d6f893482cccad86268bdd50a047c1",
    "4d7e7376e13c5de05bd915d4e270928abf72686db55a58b27ae3d5c14cf387d4",
    "c131e23ee31e69e1f16c712e6e1b3e1a7b20b976bf75f10d2a45da807201ba70",
    "7daba0202efb9448f5bcd68e7e4897d046346b1cdcf2804a72cd60039944442e",
    "9f2e5f8b6f1c4a8da1e4e9d5f0b2c7a49b1f9e2d3c4a5b6d7e8f9a0b1c2d3e4",
    "CHANGE_ME__generate_with_tools_ensure_secret_key_py__or_set_SEARXNG_SECRET",
]
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yml")
SECRET_REGEX = re.compile(
    r"""^\s*secret_key:\s*["']?(?P<value>[^"'\s#]+)["']?""",
    re.MULTILINE,
)


def get_current_secret(content):
    """Extract the current secret_key value from settings.yml text."""
    match = SECRET_REGEX.search(content)
    return match.group("value") if match else None


def get_committed_secrets_from_git():
    """Return a set of secret_key values that appear in git history for settings.yml.

    Returns an empty set if git is unavailable, the file is not tracked, or the
    command fails. Failures are non-fatal because secret rotation must also work
    in fresh checkouts without a .git directory.
    """
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    git_dir = os.path.join(repo_root, ".git")
    if not os.path.isdir(git_dir):
        return set()
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_root,
                "log",
                "-p",
                "--no-color",
                "--",
                os.path.relpath(SETTINGS_PATH, repo_root).replace(os.sep, "/"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0 or not result.stdout:
        return set()
    found = set()
    for match in re.finditer(
        r"""^[+\-]\s*secret_key:\s*["']?([^"'\s#]+)["']?""",
        result.stdout,
        re.MULTILINE,
    ):
        found.add(match.group(1))
    return found


def rotate_secret(content, current_value, reason):
    """Replace the current secret_key with a fresh random hex key."""
    new_key = secrets.token_hex(32)
    pattern = re.compile(
        r'(secret_key:\s*["\']?)' + re.escape(current_value) + r'(["\']?)'
    )
    if not pattern.search(content):
        return content, False
    rotated = pattern.sub(lambda m: f"{m.group(1)}{new_key}{m.group(2)}", content, count=1)
    print(f"[INFO] {reason}. Generated secure random key.")
    return rotated, True


def main():
    path = os.path.normpath(SETTINGS_PATH)
    if not os.path.exists(path):
        return 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
        return 0

    current = get_current_secret(content)
    if not current:
        return 0

    committed = get_committed_secrets_from_git()

    if current in KNOWN_COMMITTED_KEYS or current in committed:
        new_content, rotated = rotate_secret(
            content,
            current,
            reason="Known committed secret_key detected",
        )
    elif re.search(
        r"secret_key:\s*[\"']?(?:CHANGE_ME|ultrasecretkey|your_secret_key|placeholder)[^\"']*[\"']?",
        content,
        re.IGNORECASE,
    ):
        new_content, rotated = rotate_secret(
            content,
            current,
            reason="Placeholder secret_key detected",
        )
    else:
        return 0

    if not rotated:
        return 0
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)
    except OSError as exc:
        print(f"[ERROR] Could not write rotated secret to {path}: {exc}", file=sys.stderr)
        return 1
    print(f"[INFO] Rotated secret_key in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
