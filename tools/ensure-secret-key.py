"""Provide a stable per-install Flask secret_key without touching tracked files.

Why this script exists
----------------------
The previous design rotated ``config/settings.yml`` in place every time the
placeholder or a known-committed value was detected, which meant the freshly
generated key landed in a git-tracked file. Every rotation produced a commit
diff with a real secret in it.

The fix is to keep the key out of tracked paths entirely:

* ``config/settings.yml`` is gitignored. The launcher seeds it from
  ``config/settings.yml.example`` on first run, and the user customises it
  freely. The ``secret_key:`` line in that file is a placeholder that SearXNG
  overrides via the ``SEARXNG_SECRET`` environment variable at runtime.
* ``config/secret.key`` is also gitignored. It is the only place a real key
  is persisted, and is regenerated on demand (delete the file to rotate).

This script is called by the launcher (``SearXNG for Windows.bat``) before
the server starts. It:

1. Seeds ``config/settings.yml`` from ``config/settings.yml.example`` if the
   local copy is missing.
2. Reads ``config/secret.key``. If it is present and non-empty, the key is
   reused (this preserves Flask session cookies across restarts).
3. Otherwise, generates a fresh 32-byte random hex key, writes it to
   ``config/secret.key`` with restrictive permissions, and prints
   ``set SEARXNG_SECRET=<key>`` so the batch launcher can capture it via
   ``for /f``.

The launcher always exports ``SEARXNG_SECRET`` from whatever key this script
emits, which means the ``secret_key`` value in ``config/settings.yml`` is
never used at runtime.
"""
from __future__ import annotations

import os
import secrets
import stat
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
CONFIG_DIR = os.path.join(REPO_ROOT, "config")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.yml")
SETTINGS_EXAMPLE_PATH = os.path.join(CONFIG_DIR, "settings.yml.example")
SECRET_KEY_PATH = os.path.join(CONFIG_DIR, "secret.key")

# Output format understood by the Windows batch launcher:
#   for /f "delims=" %%K in ('python tools\ensure-secret-key.py') do set "SEARXNG_SECRET=%%K"
# On non-Windows the same line is a harmless `set` definition that the calling
# shell can `eval` if it wishes.
KEY_LINE_PREFIX = "set SEARXNG_SECRET="

MIN_KEY_LEN = 32


def _read_key(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
        return None
    return value or None


def _write_key(path: str, key: str) -> bool:
    try:
        # Write atomically: write to a sibling temp file, fsync, then replace.
        # This avoids leaving a half-written file if the process is killed
        # mid-write, which would force an unnecessary rotation on next launch.
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(key + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except (AttributeError, OSError):
                # fsync isn't critical; the file is small and the worst case
                # is a one-time rotation on the next launch.
                pass
        os.replace(tmp_path, path)
    except OSError as exc:
        print(f"[ERROR] Could not write {path}: {exc}", file=sys.stderr)
        return False

    # Best-effort: lock down permissions on POSIX. Windows ignores the mode
    # bits but NTFS ACL inheritance already keeps the file user-private in
    # the common case.
    try:
        if hasattr(os, "chmod"):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return True


def _ensure_settings_file() -> None:
    """Seed config/settings.yml from the tracked example if it is missing.

    Existing users keep their customised ``settings.yml`` untouched. Fresh
    checkouts get a working default so the launcher can start without manual
    setup. The seeded file is gitignored, so the user can edit it freely
    without affecting the repository.
    """
    if os.path.exists(SETTINGS_PATH):
        return
    if not os.path.exists(SETTINGS_EXAMPLE_PATH):
        print(
            f"[ERROR] Neither {SETTINGS_PATH} nor {SETTINGS_EXAMPLE_PATH} "
            "exists. Cannot seed a default configuration.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        with open(SETTINGS_EXAMPLE_PATH, "r", encoding="utf-8") as src:
            content = src.read()
        with open(SETTINGS_PATH, "w", encoding="utf-8", newline="\n") as dst:
            dst.write(content)
    except OSError as exc:
        print(f"[ERROR] Could not seed {SETTINGS_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"[INFO] Seeded {SETTINGS_PATH} from settings.yml.example", file=sys.stderr)


def _generate_key() -> str:
    # 32 bytes == 64 hex chars == 256 bits of entropy. SearXNG itself uses
    # token_hex(32) so this matches its recommended size.
    return secrets.token_hex(32)


def main() -> int:
    _ensure_settings_file()

    existing = _read_key(SECRET_KEY_PATH)
    if existing and len(existing) >= MIN_KEY_LEN:
        key = existing
    else:
        key = _generate_key()
        if not _write_key(SECRET_KEY_PATH, key):
            return 1
        if existing is None:
            print(f"[INFO] Generated secret_key in {SECRET_KEY_PATH}", file=sys.stderr)
        else:
            print(
                f"[INFO] Replaced short/invalid secret_key in {SECRET_KEY_PATH}",
                file=sys.stderr,
            )

    # The launcher parses this single line via `for /f`. Keep the format
    # stable; downstream code (and the tests) depend on it.
    print(f"{KEY_LINE_PREFIX}{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
