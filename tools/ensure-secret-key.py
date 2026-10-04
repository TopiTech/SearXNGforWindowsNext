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

import errno
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time

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

_SAFE_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _read_key(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            value = f.read().strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
        return None
    return value or None


def set_file_permissions(path: str) -> None:
    """Lock down file permissions: icacls on Windows, chmod 600 on POSIX."""
    if sys.platform == "win32":
        username = os.environ.get("USERNAME")
        if username:
            try:
                subprocess.run(
                    ["icacls", path, "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
                    check=False,
                    capture_output=True,
                )
            except (subprocess.SubprocessError, OSError):
                pass
    else:
        try:
            if hasattr(os, "chmod"):
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def _write_key(path: str, key: str) -> bool:
    try:
        config_dir = os.path.dirname(os.path.abspath(path))
        os.makedirs(config_dir, exist_ok=True)
        temp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp_key_", dir=config_dir, text=True)
        fd_closed = False
        try:
            try:
                with open(temp_fd, "w", encoding="utf-8", newline="\n") as f:
                    fd_closed = True
                    f.write(key + "\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except (AttributeError, OSError):
                        pass
            finally:
                if not fd_closed:
                    try:
                        os.close(temp_fd)
                    except OSError:
                        pass
                    fd_closed = True

            replace_success = False
            last_exc: OSError | None = None
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    os.replace(tmp_path, path)
                    replace_success = True
                    break
                except OSError as exc:
                    last_exc = exc
                    if getattr(exc, "winerror", None) == 17 or getattr(exc, "errno", None) == errno.EXDEV:
                        try:
                            shutil.move(tmp_path, path)
                            replace_success = True
                            break
                        except OSError as move_exc:
                            last_exc = move_exc
                    # If another process wrote a valid key, adopt it
                    existing = _read_key(path)
                    if existing and _SAFE_KEY_RE.fullmatch(existing):
                        replace_success = True
                        break
                    if attempt < max_attempts - 1:
                        time.sleep(0.05 * (2**attempt))
                        existing = _read_key(path)
                        if existing and _SAFE_KEY_RE.fullmatch(existing):
                            replace_success = True
                            break

            if not replace_success:
                existing = _read_key(path)
                if existing and _SAFE_KEY_RE.fullmatch(existing):
                    replace_success = True
                elif last_exc:
                    raise last_exc

            legacy_tmp = f"{path}.tmp"
            if os.path.exists(legacy_tmp):
                try:
                    os.remove(legacy_tmp)
                except OSError:
                    pass
        finally:
            if not fd_closed:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
                fd_closed = True
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except OSError as exc:
        print(f"[ERROR] Could not write {path}: {exc}", file=sys.stderr)
        return False

    set_file_permissions(path)
    return True


def _ensure_settings_file() -> None:
    """Seed config/settings.yml from the tracked example if it is missing or empty.

    Existing users keep their customised ``settings.yml`` untouched. Fresh
    checkouts get a working default so the launcher can start without manual
    setup. The seeded file is gitignored, so the user can edit it freely
    without affecting the repository.
    """
    if os.path.exists(SETTINGS_PATH):
        try:
            if os.path.getsize(SETTINGS_PATH) > 0:
                return
            print(
                f"[WARN] {SETTINGS_PATH} exists but is empty (0 bytes). Re-seeding from {SETTINGS_EXAMPLE_PATH}...",
                file=sys.stderr,
            )
        except OSError:
            pass

    if not os.path.exists(SETTINGS_EXAMPLE_PATH):
        print(
            f"[ERROR] Neither {SETTINGS_PATH} nor {SETTINGS_EXAMPLE_PATH} exists. Cannot seed a default configuration.",
            file=sys.stderr,
        )
        sys.exit(1)
    target_dir = os.path.dirname(os.path.abspath(SETTINGS_PATH))
    try:
        os.makedirs(target_dir, exist_ok=True)
        with open(SETTINGS_EXAMPLE_PATH, "r", encoding="utf-8") as src:
            content = src.read()
        temp_fd, tmp_settings = tempfile.mkstemp(prefix=".tmp_settings_", dir=target_dir, text=True)
        fd_closed = False
        try:
            try:
                with open(temp_fd, "w", encoding="utf-8", newline="\n") as dst:
                    fd_closed = True
                    dst.write(content)
                    dst.flush()
            finally:
                if not fd_closed:
                    try:
                        os.close(temp_fd)
                    except OSError:
                        pass
                    fd_closed = True

            replace_success = False
            last_exc: OSError | None = None
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    os.replace(tmp_settings, SETTINGS_PATH)
                    replace_success = True
                    break
                except OSError as exc:
                    last_exc = exc
                    if getattr(exc, "winerror", None) == 17 or getattr(exc, "errno", None) == errno.EXDEV:
                        try:
                            shutil.move(tmp_settings, SETTINGS_PATH)
                            replace_success = True
                            break
                        except OSError as move_exc:
                            last_exc = move_exc
                    if os.path.exists(SETTINGS_PATH) and os.path.getsize(SETTINGS_PATH) > 0:
                        replace_success = True
                        break
                    if attempt < max_attempts - 1:
                        time.sleep(0.05 * (2**attempt))
                        if os.path.exists(SETTINGS_PATH) and os.path.getsize(SETTINGS_PATH) > 0:
                            replace_success = True
                            break

            if not replace_success:
                if os.path.exists(SETTINGS_PATH) and os.path.getsize(SETTINGS_PATH) > 0:
                    replace_success = True
                elif last_exc:
                    raise last_exc
        finally:
            if not fd_closed:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
                fd_closed = True
            if os.path.exists(tmp_settings):
                try:
                    os.remove(tmp_settings)
                except OSError:
                    pass
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
    if existing and _SAFE_KEY_RE.fullmatch(existing):
        key = existing
    else:
        key = _generate_key()
        if not _write_key(SECRET_KEY_PATH, key):
            return 1
        persisted = _read_key(SECRET_KEY_PATH)
        if persisted and _SAFE_KEY_RE.fullmatch(persisted):
            key = persisted
        if existing is None:
            print(f"[INFO] Generated secret_key in {SECRET_KEY_PATH}", file=sys.stderr)
        else:
            print(
                f"[INFO] Replaced invalid or unsafe secret_key in {SECRET_KEY_PATH}",
                file=sys.stderr,
            )

    set_file_permissions(SECRET_KEY_PATH)

    # The launcher parses this single line via `for /f`. Keep the format
    # stable; downstream code (and the tests) depend on it.
    print(f"{KEY_LINE_PREFIX}{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
