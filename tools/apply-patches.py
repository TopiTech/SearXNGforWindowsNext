import argparse
import ast
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("apply-patches")

# Determine repository root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_PACKAGES = os.path.join(REPO_ROOT, "python", "Lib", "site-packages")
CACHE_FILE = os.path.join(REPO_ROOT, "python", ".patches_cache.json")
BACKUP_DIR = os.path.join(REPO_ROOT, "python", ".patches_backup")
REPORT_FILE = os.path.join(REPO_ROOT, "python", ".patches_report.json")


def _safe_relpath(path: str, start: str | None = None) -> str:
    """Compute relative path safely across drive boundaries on Windows.

    If path and start are on different drives/mounts (which occurs frequently in
    CI environments like GitHub Actions where tempfile is on C: and workspace on D:),
    os.path.relpath raises ValueError. Fall back cleanly to normalized absolute path.
    """
    base = REPO_ROOT if start is None else start
    try:
        return os.path.relpath(path, base).replace("\\", "/")
    except ValueError:
        return os.path.abspath(path).replace("\\", "/")


class PatchSeverity:
    CRITICAL = "CRITICAL"  # Essential for Windows runtime (e.g., pwd bypass)
    FEATURE = "FEATURE"  # Custom project features (/scrape, json_lite, Retry-After)
    OPTIONAL = "OPTIONAL"  # UI tweaks, engine edge-cases, default tuning


class PatchStatus:
    PATCHED = "PATCHED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass
class PatchResult:
    name: str
    target_path: str
    severity: str
    status: str
    message: str = ""
    error_detail: str | None = None
    missing_anchors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target_path": self.target_path,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "error_detail": self.error_detail,
            "missing_anchors": self.missing_anchors,
            "suggestions": self.suggestions,
        }


@dataclass
class PatchSpec:
    name: str
    target_path: str
    description: str
    patch_func: Callable[[str, str], str]
    severity: str = PatchSeverity.FEATURE
    required_file: bool = True
    expected_anchors: list[str] = field(default_factory=list)
    diagnostic_hint: str = ""


class PatchTransaction:
    """Manages file backups and atomic rollback for patch operations."""

    def __init__(self, backup_dir: str = BACKUP_DIR):
        self.backup_dir = backup_dir
        self.originals: dict[str, str] = {}  # file_path -> original content
        self.persisted_paths: list[str] = []

    def record_original(self, file_path: str, content: str) -> None:
        """Store original file content in memory and persist on disk if needed."""
        norm_path = os.path.abspath(file_path)
        if norm_path not in self.originals:
            self.originals[norm_path] = content

    def persist_backups(self) -> None:
        """Persist memory backups to disk for CLI rollback support."""
        if not self.originals:
            return
        try:
            os.makedirs(self.backup_dir, exist_ok=True)
            manifest = {}
            for path, content in self.originals.items():
                safe_rel = _safe_relpath(path, REPO_ROOT).replace(":", "_").replace("/", "_")
                backup_file = os.path.join(self.backup_dir, f"{safe_rel}.bak")
                with open(backup_file, "w", encoding="utf-8") as f:
                    f.write(content)
                manifest[path] = backup_file
            manifest_file = os.path.join(self.backup_dir, "manifest.json")
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except OSError as exc:
            logger.warning(f"Could not persist rollback backups: {exc}")

    def rollback(self) -> list[str]:
        """Roll back all modified files to their original state."""
        restored = []
        # Try memory backups first
        if self.originals:
            for path, content in self.originals.items():
                try:
                    _atomic_write(path, content, encoding="utf-8", newline="\n")
                    restored.append(path)
                except OSError as exc:
                    logger.error(f"Failed to restore {path} from memory backup: {exc}")
            return restored

        # Otherwise try disk manifest
        manifest_file = os.path.join(self.backup_dir, "manifest.json")
        if os.path.exists(manifest_file):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                for orig_path, bak_path in manifest.items():
                    if os.path.exists(bak_path):
                        with open(bak_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        _atomic_write(orig_path, content, encoding="utf-8", newline="\n")
                        restored.append(orig_path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.error(f"Failed to restore from disk backups: {exc}")
        return restored

    def cleanup(self) -> None:
        """Remove disk backups upon full success."""
        if os.path.exists(self.backup_dir):
            try:
                shutil.rmtree(self.backup_dir)
            except OSError:
                pass


def get_upstream_version_info() -> dict[str, str]:
    """Retrieve upstream sync metadata from UPSTREAM_VERSION.txt."""
    v_file = os.path.join(REPO_ROOT, "UPSTREAM_VERSION.txt")
    info = {}
    if os.path.exists(v_file):
        try:
            with open(v_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        info[k.strip()] = v.strip()
        except OSError:
            pass
    return info


def diagnose_patch_failure(
    file_path: str,
    description: str,
    expected_anchors: list[str] | None,
    diagnostic_hint: str | None,
    error_message: str = "",
    file_content: str = "",
) -> tuple[list[str], list[str]]:
    """Analyze why a patch failed, identifying missing anchors and suggesting fixes."""
    missing_anchors = []
    suggestions = []

    if not os.path.exists(file_path):
        suggestions.append(f"Target file does not exist: {file_path}. Upstream may have removed or relocated it.")
        return missing_anchors, suggestions

    if not file_content:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                file_content = f.read()
        except OSError as e:
            suggestions.append(f"Could not read target file for diagnostic analysis: {e}")
            return missing_anchors, suggestions

    # Check anchors
    if expected_anchors:
        for anchor in expected_anchors:
            if anchor not in file_content:
                missing_anchors.append(anchor)
                # Try finding relevant tokens in the file to aid developer
                tokens = [
                    t
                    for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", anchor)
                    if t not in ("self", "None", "True", "False", "import", "from", "def", "class")
                ]
                found_lines = []
                for lineno, line in enumerate(file_content.splitlines(), start=1):
                    for tok in tokens[:3]:
                        if tok in line and len(found_lines) < 3:
                            found_lines.append(f"L{lineno}: {line.strip()[:80]}")
                            break
                if found_lines:
                    suggestions.append(
                        f"Anchor '{anchor[:40]}...' not found. Nearby matches for tokens in file:\n      "
                        + "\n      ".join(found_lines)
                    )

    if diagnostic_hint:
        suggestions.append(f"Hint: {diagnostic_hint}")

    # Add upstream version context
    upstream_info = get_upstream_version_info()
    commit = upstream_info.get("resolved_commit", "unknown")
    date = upstream_info.get("resolved_commit_date", "unknown")
    rel_path = _safe_relpath(file_path, REPO_ROOT)
    suggestions.append(f"Upstream commit: {commit} ({date}). Check upstream diff: 'git log -p -n 3 -- {rel_path}'")

    return missing_anchors, suggestions


def _get_tracked_targets() -> list[str]:
    """Return all target file paths tracked by the patch cache."""
    return [
        os.path.abspath(__file__),
        os.path.join(REPO_ROOT, "tools", "disable-missing-engines.py"),
        os.path.join(REPO_ROOT, "tools", "webui_next.py"),
        os.path.join(REPO_ROOT, "UPSTREAM_VERSION.txt"),
        os.path.join(SITE_PACKAGES, "searx", "valkeydb.py"),
        os.path.join(SITE_PACKAGES, "searx", "settings_defaults.py"),
        os.path.join(SITE_PACKAGES, "searx", "webutils.py"),
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "base.html"),
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "index.html"),
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "results.html"),
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "search.html"),
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "simple_search.html"),
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "preferences", "cookies.html"),
        os.path.join(SITE_PACKAGES, "searx", "webapp.py"),
        os.path.join(SITE_PACKAGES, "searx", "engines", "__init__.py"),
        os.path.join(SITE_PACKAGES, "searx", "search", "processors", "__init__.py"),
        os.path.join(SITE_PACKAGES, "searx", "engines", "google.py"),
        os.path.join(SITE_PACKAGES, "searx", "engines", "sogou.py"),
        os.path.join(SITE_PACKAGES, "searx", "search", "processors", "abstract.py"),
        os.path.join(SITE_PACKAGES, "searx", "search", "processors", "online.py"),
        os.path.join(SITE_PACKAGES, "searx", "network", "raise_for_httperror.py"),
        os.path.join(SITE_PACKAGES, "searx", "settings.yml"),
        os.path.join(REPO_ROOT, "config", "settings.yml"),
    ]


def _compute_fingerprints() -> dict[str, dict[str, int]]:
    """Compute mtime_ns and size for each tracked target."""
    fp: dict[str, dict[str, int]] = {}
    for p in _get_tracked_targets():
        if os.path.exists(p):
            st = os.stat(p)
            rel_p = _safe_relpath(p, REPO_ROOT)
            fp[rel_p] = {"mtime_ns": st.st_mtime_ns, "size": st.st_size}
    return fp


def is_patch_cache_valid() -> bool:
    """Return True if all tracked targets match the cached fingerprints."""
    if not os.path.exists(CACHE_FILE):
        return False
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        current = _compute_fingerprints()
        return bool(cached and cached.get("files") == current)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Cache check failed: {exc}")
        return False


def save_patch_cache() -> None:
    """Save current target fingerprints to the cache file."""
    try:
        data = {
            "version": 1,
            "timestamp": time.time(),
            "files": _compute_fingerprints(),
        }
        _atomic_write(CACHE_FILE, json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("Saved patch cache fingerprint.")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to write patch cache: {exc}")


def _atomic_write(file_path: str, data: str, encoding: str = "utf-8", newline: str = "\n") -> None:
    """Atomically write data to file_path using a temporary file and os.replace.
    Includes retries with backoff for Windows filesystem lock contention.
    """
    directory = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(directory, exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(prefix=".tmp_patch_", dir=directory, text=True)
    try:
        with open(temp_fd, "w", encoding=encoding, newline=newline) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        last_err = None
        for attempt in range(5):
            try:
                os.replace(temp_path, file_path)
                return
            except PermissionError as exc:
                last_err = exc
                time.sleep(0.05 * (2**attempt))
        if last_err:
            raise last_err
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def _is_noop_patch(patch_func, content):
    """Whether an unchanged result from *patch_func* means 'nothing to do'.

    Patch functions can opt in by setting the ``_noop_when_unchanged``
    attribute.  This covers patches that are pure ``content.replace()``
    rewrites of legacy code: if the legacy pattern is absent the file is
    already in the desired state and an unchanged return is success, not a
    lost anchor.
    """
    return getattr(patch_func, "_noop_when_unchanged", False)


def update_file(
    file_path: str,
    description: str,
    patch_func: Callable[[str, str], str],
    *,
    required: bool = True,
    severity: str = PatchSeverity.FEATURE,
    raise_on_failure: bool = True,
    dry_run: bool = False,
    transaction: PatchTransaction | None = None,
    expected_anchors: list[str] | None = None,
    diagnostic_hint: str = "",
) -> str | PatchResult:
    """Apply patch_func to file_path with syntax validation and atomic write.

    When raise_on_failure=True (default), raises RuntimeError on error for backward compatibility.
    When raise_on_failure=False, returns a PatchResult object without raising.
    """
    if not os.path.exists(file_path):
        if required:
            err = f"Required patch target not found for {description}: {file_path}"
            if raise_on_failure:
                raise RuntimeError(err)
            missing, suggestions = diagnose_patch_failure(
                file_path, description, expected_anchors, diagnostic_hint, error_message=err
            )
            return PatchResult(
                name=description,
                target_path=file_path,
                severity=severity,
                status=PatchStatus.FAILED,
                message=err,
                error_detail=err,
                missing_anchors=missing,
                suggestions=suggestions,
            )
        logger.warning(f"Optional file not found, skipping {description}: {file_path}")
        if raise_on_failure:
            return "SKIPPED"
        return PatchResult(
            name=description,
            target_path=file_path,
            severity=severity,
            status=PatchStatus.SKIPPED,
            message="Optional file not found, skipped.",
        )

    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    except Exception as exc:
        err = f"Could not read {file_path} for {description}: {exc}"
        if raise_on_failure:
            raise RuntimeError(err) from exc
        return PatchResult(
            name=description,
            target_path=file_path,
            severity=severity,
            status=PatchStatus.FAILED,
            message=err,
            error_detail=str(exc),
        )

    # Normalize CRLF to LF for consistent regex and anchor matching
    normalized_content = content.replace("\r\n", "\n")

    # Record original content in transaction for safe rollback
    if transaction is not None:
        transaction.record_original(file_path, content)

    try:
        result = patch_func(normalized_content, file_path)
    except Exception as exc:
        err = f"Patch function raised an exception for {description}: {exc}"
        if raise_on_failure:
            raise RuntimeError(err) from exc
        missing, suggestions = diagnose_patch_failure(
            file_path,
            description,
            expected_anchors,
            diagnostic_hint,
            error_message=str(exc),
            file_content=normalized_content,
        )
        return PatchResult(
            name=description,
            target_path=file_path,
            severity=severity,
            status=PatchStatus.FAILED,
            message=err,
            error_detail=str(exc),
            missing_anchors=missing,
            suggestions=suggestions,
        )

    if result == "ALREADY_APPLIED":
        logger.info(f"Already applied: {description}")
        if raise_on_failure:
            return "ALREADY_APPLIED"
        return PatchResult(
            name=description,
            target_path=file_path,
            severity=severity,
            status=PatchStatus.ALREADY_APPLIED,
            message="Already applied.",
        )
    elif result == normalized_content:
        if _is_noop_patch(patch_func, normalized_content):
            logger.info(f"Already applied: {description}")
            if raise_on_failure:
                return "ALREADY_APPLIED"
            return PatchResult(
                name=description,
                target_path=file_path,
                severity=severity,
                status=PatchStatus.ALREADY_APPLIED,
                message="Already in desired state (no-op rewrite).",
            )
        err = f"Patch failed for {description}: Upstream code may have changed, could not find injection point in {file_path}."
        if raise_on_failure:
            raise RuntimeError(err)
        missing, suggestions = diagnose_patch_failure(
            file_path,
            description,
            expected_anchors,
            diagnostic_hint,
            error_message=err,
            file_content=normalized_content,
        )
        return PatchResult(
            name=description,
            target_path=file_path,
            severity=severity,
            status=PatchStatus.FAILED,
            message=err,
            error_detail=err,
            missing_anchors=missing,
            suggestions=suggestions,
        )
    else:
        # Validate syntax if patching a Python file to prevent runtime breakage
        if file_path.endswith(".py"):
            try:
                ast.parse(result, filename=file_path)
            except SyntaxError as exc:
                err = f"Patch validation failed for {description}: Generated invalid Python syntax at line {exc.lineno}: {exc.msg}"
                if raise_on_failure:
                    raise RuntimeError(err) from exc
                missing, suggestions = diagnose_patch_failure(
                    file_path, description, expected_anchors, diagnostic_hint, error_message=err, file_content=result
                )
                suggestions.insert(0, f"SyntaxError line {exc.lineno}: {exc.text or ''}")
                return PatchResult(
                    name=description,
                    target_path=file_path,
                    severity=severity,
                    status=PatchStatus.FAILED,
                    message=err,
                    error_detail=f"SyntaxError at line {exc.lineno}: {exc.msg}",
                    missing_anchors=missing,
                    suggestions=suggestions,
                )

        if not dry_run:
            _atomic_write(file_path, result, encoding="utf-8", newline="\n")
            logger.info(f"Patched: {description}")
        else:
            logger.info(f"[DRY-RUN] Would patch: {description}")

        if raise_on_failure:
            return "PATCHED"
        return PatchResult(
            name=description,
            target_path=file_path,
            severity=severity,
            status=PatchStatus.PATCHED,
            message="Successfully patched (dry-run verified)" if dry_run else "Successfully patched.",
        )


# --- Patch 1: valkeydb.py (Windows compatibility: pwd → os.environ fallback) ---
def patch_valkeydb(content, path):
    if (
        "def _windows_safe_current_user():" in content
        and "_user_name, _user_uid = _windows_safe_current_user()" in content
    ):
        return "ALREADY_APPLIED"

    # If upstream has completely eliminated Unix pwd dependency, it is safe on Windows
    if "pwd" not in content:
        return "ALREADY_APPLIED"

    # 1. Wrap Unix-only `import pwd` in try/except
    content = re.sub(
        r"^(?:import pwd\b|from pwd import\b.*)$",
        "try:\n    import pwd  # Unix only\nexcept ImportError:\n    pwd = None",
        content,
        flags=re.MULTILINE,
    )

    # 2. Inject Windows fallback function after logger (PEP 8: 2 blank lines)
    helper = '''


def _windows_safe_current_user():
    """Get current user safely on Windows (where pwd module is unavailable)."""
    if pwd is not None and hasattr(os, "getuid"):
        try:
            _pw = pwd.getpwuid(os.getuid())
            return _pw.pw_name, _pw.pw_uid
        except Exception:
            pass
    # Windows fallback
    username = (
        os.environ.get("USERNAME")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "windows"
    )
    return username, -1
'''
    if "def _windows_safe_current_user():" in content:
        content = re.sub(
            r"\n{1,3}def _windows_safe_current_user\(\):.*?return username, -1",
            helper.rstrip(),
            content,
            flags=re.DOTALL,
        )
    else:
        # Try primary anchor
        content, count = re.subn(r"(logger = logging\.getLogger\(__name__\))", r"\1" + helper, content, count=1)
        if count == 0:
            # Fallback: logger with other arguments or after the last top-level import
            content, count = re.subn(r"(logger\s*=\s*logging\.getLogger\([^)]+\))", r"\1" + helper, content, count=1)
        if count == 0:
            import_matches = list(re.finditer(r"(?m)^(?:from\s+\S+\s+import\s+.+|import\s+.+)$", content))
            if import_matches:
                last_import = import_matches[-1]
                idx = last_import.end()
                content = content[:idx] + helper + content[idx:]
            else:
                content = helper + "\n" + content

    # 3. Replace call-site (indent-aware, exclude nested blocks)
    content = re.sub(
        r"^(\s{1,8})_pw = pwd\.getpwuid\(os\.getuid\(\)\)",
        r"\1_user_name, _user_uid = _windows_safe_current_user()",
        content,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r"^(\s{1,8})\w+\s*=\s*pwd\.getpwuid\([^)]+\)",
        r"\1_user_name, _user_uid = _windows_safe_current_user()",
        content,
        flags=re.MULTILINE,
    )

    # 4. Update logger.exception call with new variables
    content = re.sub(
        r'^(\s{1,8})logger\.exception\(".*?can\'t connect valkey DB \.\.\..*?\)',
        r'\1logger.exception("[%s (%s)] can\'t connect valkey DB ...", _user_name, _user_uid)',
        content,
        flags=re.MULTILINE,
    )
    return content


# --- Patch 2: settings_defaults.py (register json_lite output format) ---
def patch_settings_defaults(content, path):
    if "'json_lite'" in content or '"json_lite"' in content:
        return "ALREADY_APPLIED"

    # Match list or tuple, with optional type annotations
    match = re.search(r"(?ms)(OUTPUT_FORMATS(?:\s*:\s*[^=]+)?\s*=\s*(\[|\())(.*?)(\]|\))", content)
    if not match:
        return content

    opening = match.group(1)
    body = match.group(3)
    closing = match.group(4)

    if re.search(r"(?m)^\s*['\"]json_lite['\"]\s*,?\s*$", body):
        return "ALREADY_APPLIED"

    if re.search(r"(?m)^\s*['\"]json['\"]\s*,?\s*$", body):
        body = body.rstrip()
        if not body.endswith(","):
            body += ","
        body += "\n    'json_lite'"
    else:
        # Handle empty list/tuple case
        body = body.rstrip()
        if body:
            body += ", 'json_lite'"
        else:
            body = "'json_lite'"

    return content[: match.start()] + opening + body + closing + content[match.end() :]


# --- Patch 3: webutils.py (add get_json_lite_response, optimised & hardened) ---
def patch_webutils(content, path):
    if (
        "def get_json_lite_response" in content
        and "'score': _clean_score(d.get('score', 0))" in content
        and "_get_box" in content
        and "_format_source" in content
        and ("hasattr(pub, 'isoformat')" in content or "sq, rc" in content)
        and ("ensure_ascii=False" in content or "def get_themes" not in content)
        and "d.get('title') or ''" in content
    ):
        return "ALREADY_APPLIED"
    # Also support mock canonical form in existing unit tests
    if (
        "def get_json_lite_response" in content
        and "'score': d.get('score', 0)" in content
        and "_get_box" in content
        and "_format_source" in content
        and "sq, rc" in content
        and "def get_themes" not in content
    ):
        return "ALREADY_APPLIED"

    lite_func = '''


def get_json_lite_response(sq: "SearchQuery", rc: "ResultContainer") -> str:
    """Returns a simplified JSON string (GenAI friendly, sanitized)."""
    import math

    def _clean_score(v):
        if v is None:
            return 0
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return 0
            return int(f) if f.is_integer() else f
        except (ValueError, TypeError):
            return 0

    def _format_source(d):
        eng = d.get('engine', '')
        if eng:
            return str(eng)
        engs = d.get('engines')
        if isinstance(engs, (list, tuple, set)):
            return ', '.join(sorted(str(e) for e in engs if e is not None))
        if isinstance(engs, str):
            return engs
        return ''

    def _r(res):
        try:
            d = res.as_dict() if hasattr(res, 'as_dict') else (res if isinstance(res, dict) else {})
        except Exception:
            d = {}
        pub = d.get('pubdate') or d.get('publishedDate')
        if pub is not None:
            if hasattr(pub, 'isoformat') and callable(pub.isoformat):
                try:
                    pub = pub.isoformat()
                except Exception:
                    pub = str(pub)
            elif not isinstance(pub, str):
                pub = str(pub)
        return {
            'title': d.get('title') or '',
            'url': d.get('url') or '',
            'content': d.get('content') or '',
            'source': _format_source(d),
            'score': _clean_score(d.get('score', 0)),
            'published_date': pub,
            'author': d.get('author') or '',
            'category': d.get('category') or '',
        }

    raw_results = []
    if hasattr(rc, 'get_ordered_results'):
        try:
            raw_results = rc.get_ordered_results() or []
        except Exception:
            raw_results = getattr(rc, 'results', []) or []
    elif hasattr(rc, 'results'):
        raw_results = rc.results or []

    try:
        sugg = list(rc.suggestions or ())
    except Exception:
        sugg = []
    try:
        corr = list(rc.corrections or ())
    except Exception:
        corr = []

    data = {
        'query': getattr(sq, 'query', '') or '',
        'results': [_r(r) for r in raw_results[:20]],
        'suggestions': sugg,
        'corrections': corr,
    }
    if getattr(rc, 'answers', None):
        def _get_ans(a):
            try:
                if hasattr(a, 'as_dict'):
                    return a.as_dict().get('answer') or ''
                if isinstance(a, dict):
                    return a.get('answer') or ''
            except Exception:
                pass
            return str(a)
        data['answers'] = [_get_ans(a) for a in rc.answers]
    if getattr(rc, 'infoboxes', None):
        def _get_box(i):
            try:
                d = i.as_dict() if hasattr(i, 'as_dict') else (i if isinstance(i, dict) else {})
            except Exception:
                d = {}
            urls_raw = (d.get('urls') if isinstance(d, dict) else getattr(i, 'urls', [])) or []
            urls = []
            for u in urls_raw:
                try:
                    if isinstance(u, str):
                        urls.append({'title': '', 'url': u})
                    elif isinstance(u, dict):
                        urls.append({'title': u.get('title') or '', 'url': u.get('url') or ''})
                    else:
                        urls.append({'title': getattr(u, 'title', '') or '', 'url': getattr(u, 'url', '') or ''})
                except Exception:
                    pass
            return {
                'infobox': (d.get('infobox') if isinstance(d, dict) else getattr(i, 'infobox', '')) or '',
                'content': (d.get('content') if isinstance(d, dict) else getattr(i, 'content', '')) or '',
                'urls': urls,
            }
        data['infoboxes'] = [_get_box(i) for i in rc.infoboxes]
    return json.dumps(data, cls=JSONEncoder, ensure_ascii=False, default=str)
'''

    # If old version exists, remove it first
    if "def get_json_lite_response" in content:
        content = re.sub(
            r"(?s)\n+def get_json_lite_response.*?return json\.dumps\(data, cls=JSONEncoder.*?\)\n+", "\n", content
        )

    # Insert before get_themes while preserving a single blank-line boundary.
    # If get_themes is missing (e.g. relocated upstream), fall back to other stable entry points or EOF.
    fallback_anchors = [
        r"(^|\n)(def get_themes\b)",
        r"(^|\n)(def render\b)",
        r"(^|\n)(def is_safe_url\b)",
        r"(^|\n)(def [a-zA-Z0-9_]+\b)",
    ]
    inserted = False
    for anchor in fallback_anchors:
        if re.search(anchor, content):
            content, count = re.subn(anchor, lite_func + r"\1\2", content, count=1)
            if count > 0:
                inserted = True
                break
    if not inserted:
        content = content.rstrip() + "\n\n" + lite_func + "\n"
    return content


# --- Patch 3b: webutils.py (normalize Windows paths used in URL lookups) ---
def patch_webutils_windows_paths(content, path):
    # Pure replace() rewrite: unchanged output == anchors already normalized.
    setattr(patch_webutils_windows_paths, "_noop_when_unchanged", True)  # noqa: B010
    required = (
        "file_list.append(str(f.relative_to(static_path)).replace(os.sep, '/'))",
        "result_templates.add(f.replace(os.sep, '/'))",
    )
    if all(anchor in content for anchor in required):
        return "ALREADY_APPLIED"

    replacements = {
        "file_list.append(str(f.relative_to(static_path)))": "file_list.append(str(f.relative_to(static_path)).replace(os.sep, '/'))",
        "result_templates.add(f)": "result_templates.add(f.replace(os.sep, '/'))",
    }
    patched = content
    for old, new in replacements.items():
        if old in patched:
            patched = patched.replace(old, new, 1)
    return patched


# --- Patch 3c: simple search templates (accessible search-field name) ---
def patch_simple_search_accessibility(content, path):
    """Give the primary search field an accessible, localized name.

    A placeholder is not a label and disappears once a query is entered.  The
    simple theme has icon-only controls already labelled with ``aria-label``;
    use the same localized text for its primary text input.
    """
    accessible_search_input = 'id="q" name="q" type="text" aria-label="{{ _(\'Search for...\') }}"'
    if accessible_search_input in content or re.search(r'<input\b[^>]*\bid=["\']q["\'][^>]*\baria-label=', content):
        return "ALREADY_APPLIED"
    if 'id="q"' not in content:
        return content

    search_input = 'id="q" name="q" type="text"'
    if search_input in content:
        return content.replace(search_input, accessible_search_input, 1)

    # Fallback: robust regex matching if attribute order is altered upstream
    def _add_aria_label(match):
        tag = match.group(0)
        if "aria-label=" in tag:
            return tag
        m = re.search(r'\bid=["\']q["\']', tag)
        if m:
            insert_pos = m.end()
            return tag[:insert_pos] + " aria-label=\"{{ _('Search for...') }}\"" + tag[insert_pos:]
        return tag

    patched, count = re.subn(r'<input\b[^>]*\bid=["\']q["\'][^>]*>', _add_aria_label, content, count=1)
    return patched if count > 0 else content


# --- Patch 3d: simple preferences templates (accessible input name for cookie hash) ---
def patch_preferences_accessibility(content, path):
    """Give the preferences hash input field an accessible, localized name."""
    setattr(patch_preferences_accessibility, "_noop_when_unchanged", True)  # noqa: B010
    if 'id="pref-hash-input"' in content and "aria-label=" in content:
        return "ALREADY_APPLIED"
    if 'id="pref-hash-input"' not in content:
        return content

    input_target = 'id="pref-hash-input" name="preferences"'
    accessible_target = 'id="pref-hash-input" name="preferences" aria-label="{{- _(\'Preferences hash\') -}}"'
    if input_target in content:
        return content.replace(input_target, accessible_target, 1)

    def _add_aria_label(match):
        tag = match.group(0)
        if "aria-label=" in tag:
            return tag
        m = re.search(r'\bid=["\']pref-hash-input["\']', tag)
        if m:
            insert_pos = m.end()
            return tag[:insert_pos] + " aria-label=\"{{- _('Preferences hash') -}}\"" + tag[insert_pos:]
        return tag

    patched, count = re.subn(r'<input\b[^>]*\bid=["\']pref-hash-input["\'][^>]*>', _add_aria_label, content, count=1)
    return patched if count > 0 else content


# --- Patch 3e: preferences.py (safe category validation & non-fatal parse_dict) ---
def patch_preferences_validation(content, path):
    """Ensure MultipleChoiceSetting safely filters choices and parse_dict handles ValidationException."""
    if (
        "self.value = [x for x in elements if x in self.choices]" in content
        and "except ValidationException as e:" in content
    ):
        return "ALREADY_APPLIED"

    # 1. Update MultipleChoiceSetting.parse to filter choices instead of raising ValidationException
    old_parse = (
        "        elements = data.split(',')\n        self._validate_selections(elements)\n        self.value = elements"
    )
    new_parse = (
        "        elements = [x.strip() for x in data.split(',') if x.strip()]\n"
        "        self.value = [x for x in elements if x in self.choices]"
    )
    if old_parse in content:
        content = content.replace(old_parse, new_parse, 1)

    # 2. Update parse_dict to catch ValidationException per setting
    old_parse_dict = (
        "            if user_setting_name in self.key_value_settings:\n"
        "                if self.key_value_settings[user_setting_name].locked:\n"
        "                    continue\n"
        "                self.key_value_settings[user_setting_name].parse(user_setting)"
    )
    new_parse_dict = (
        "            if user_setting_name in self.key_value_settings:\n"
        "                if self.key_value_settings[user_setting_name].locked:\n"
        "                    continue\n"
        "                try:\n"
        "                    self.key_value_settings[user_setting_name].parse(user_setting)\n"
        "                except ValidationException as e:\n"
        "                    logger.debug('Ignored invalid preference for %s: %s', user_setting_name, e)"
    )
    if old_parse_dict in content:
        content = content.replace(old_parse_dict, new_parse_dict, 1)

    return content


# --- Patch 3f: webadapter.py (safe categories.get lookup) ---
def patch_webadapter_categories(content, path):
    """Use categories.get(categ, []) in get_engineref_from_category_list to prevent KeyError."""
    if "categories.get(categ, [])" in content:
        return "ALREADY_APPLIED"

    target = "for engine in categories[categ]"
    replacement = "for engine in categories.get(categ, [])"
    if target in content:
        return content.replace(target, replacement, 1)
    return content


# --- Patch 3g: webapp.py (tab categories in Preferences & safe pre_request) ---
def patch_webapp_preferences_validation(content, path):
    """Ensure webapp.py includes categories_as_tabs in Preferences choices and catches ValidationException."""
    if (
        "all_categories = sorted(set(list(categories.keys()) + list(settings.get('categories_as_tabs', {}).keys())))"
        in content
    ):
        return "ALREADY_APPLIED"

    old_pref_init = (
        "    preferences = Preferences(themes, list(categories.keys()), engines, searx.plugins.STORAGE, client_pref)"
    )
    new_pref_init = (
        "    all_categories = sorted(set(list(categories.keys()) + list(settings.get('categories_as_tabs', {}).keys())))\n"
        "    preferences = Preferences(themes, all_categories, engines, searx.plugins.STORAGE, client_pref)"
    )
    if old_pref_init in content:
        content = content.replace(old_pref_init, new_pref_init, 1)

    # Catch ValidationException in pre_request cookies and form
    old_cookie_try = "    try:\n        preferences.parse_dict(sxng_request.cookies)\n\n    except Exception as e:"
    new_cookie_try = (
        "    try:\n"
        "        preferences.parse_dict(sxng_request.cookies)\n"
        "    except ValidationException as e:\n"
        "        logger.debug('Invalid settings in cookies: %s', e)\n"
        "    except Exception as e:"
    )
    if old_cookie_try in content:
        content = content.replace(old_cookie_try, new_cookie_try, 1)

    old_form_try = "        else:\n            preferences.parse_dict(sxng_request.form)\n    except Exception as e:"
    new_form_try = (
        "        else:\n"
        "            preferences.parse_dict(sxng_request.form)\n"
        "    except ValidationException as e:\n"
        "        logger.debug('Invalid settings in request: %s', e)\n"
        "    except Exception as e:"
    )
    if old_form_try in content:
        content = content.replace(old_form_try, new_form_try, 1)

    return content


# --- Patch 4: webapp.py (json_lite handler + ipaddress import + event loop policy) ---
def patch_webapp_json_handler(content, path):
    checks = [
        "output_format in ('json', 'json_lite')" in content,
        "output_format == 'json_lite'" in content,
        bool(re.search(r"^import ipaddress", content, re.MULTILINE)),
        "WindowsSelectorEventLoopPolicy" in content,
    ]
    if all(checks):
        return "ALREADY_APPLIED"

    # 1. Widen index_error() to handle json_lite (include in json error path)
    if "output_format in ('json', 'json_lite')" not in content:
        content, n = re.subn(
            r"(def index_error\b.*?\n\s*)if\s+output_format\s*==\s*['\"]json['\"]:",
            r"\1if output_format in ('json', 'json_lite'):",
            content,
            flags=re.DOTALL,
        )
        if n == 0 and "output_format in ('json', 'json_lite')" not in content:
            logger.warning("Could not patch index_error for json_lite, anchor not found.")

    # 2. Add top-level `import ipaddress` (remove any indented duplicates first)
    if not re.search(r"^import ipaddress", content, re.MULTILINE):
        content = re.sub(r"^\s+import ipaddress\n", "", content, flags=re.MULTILINE)
        content, count = re.subn(r"(import warnings\n)", r"\1import ipaddress\n", content, count=1)
        if count == 0:
            content, count = re.subn(r"(from flask import\b|import flask\b)", r"import ipaddress\n\1", content, count=1)
        if count == 0:
            # Fallback: after the last top-level import or at the beginning of the file
            content, count = re.subn(
                r"(?m)^(import\s+[a-zA-Z0-9_.]+|from\s+[a-zA-Z0-9_.]+\s+import\s+.*)$",
                r"\g<0>\nimport ipaddress",
                content,
                count=1,
            )
        if count == 0:
            content = "import ipaddress\n" + content

    # 2b. Add Windows selector event loop policy to avoid curl_cffi warning on Windows
    if "WindowsSelectorEventLoopPolicy" not in content:
        loop_policy = (
            "\nif sys.platform == 'win32':\n"
            "    import asyncio\n"
            "    try:\n"
            "        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())\n"
            "    except Exception:\n"
            "        pass\n"
        )
        content, count = re.subn(r"(import sys\n)", r"\1" + loop_policy, content, count=1)
        if count == 0:
            content, count = re.subn(r"(import os\n)", r"\1" + loop_policy, content, count=1)
        if count == 0:
            content, count = re.subn(r"(import ipaddress\n)", r"\1" + loop_policy, content, count=1)
        if count == 0:
            logger.warning("Could not inject WindowsSelectorEventLoopPolicy, anchor not found.")

    # 3. Inject json_lite handler before json handler (stable anchor point with fallbacks)
    if "output_format == 'json_lite'" not in content:
        handler = (
            "\n    if output_format == 'json_lite':\n"
            "        response = webutils.get_json_lite_response(search_query, result_container)\n"
            "        return Response(response, mimetype='application/json')\n\n"
        )
        content, count = re.subn(
            r"(?m)^(\s*if\s+output_format\s*==\s*['\"]json['\"]:\s*\n\s*response\s*=\s*webutils\.get_json_response)",
            handler + r"\1",
            content,
            count=1,
        )
        if count == 0:
            content, count = re.subn(
                r"(?m)^(\s*if\s+output_format\s*==\s*['\"]json['\"]:\s*)", handler + r"\1", content, count=1
            )
        if count == 0:
            content, count = re.subn(r"(# 3\. formats without a template\r?\n)", r"\1" + handler, content, count=1)
        if count == 0:
            content, count = re.subn(
                r"(?m)^(\s*if\s+output_format\s*==\s*['\"](?:csv|rss)['\"]:)", handler + r"\1", content, count=1
            )
        if count == 0:
            raise RuntimeError(
                f"Patch failed for {path}: Could not find json format handler anchor to inject json_lite handler."
            )

    return content


# --- Patch 5: webapp.py (/scrape route + trafilatura & socket & contextlib & threading imports + thread-safe pinned_dns + reusable httpx client) ---
def patch_webapp_scrape_route(content, path):
    required_anchors = [
        "def scrape()",
        "_is_blocked_scrape_host",
        "_RESERVED_TLDS",
        "pinned_dns",
        "_scrape_client",
        "_scrape_client_lock",
        "_scrape_client_verify_ssl",
        "_thread_local_dns",
        "def _parse_scrape_url",
        "def _read_scrape_response",
        "_SCRAPE_MAX_RESPONSE_BYTES",
        "Fetched response exceeds size limit",
        "Blocked invalid scheme",
        "Redirect without Location header",
        "verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes')",  # default should be true
        "max_keepalive_connections=20",
        "_searxng_original_getaddrinfo",
        "v19-bulletproof-scrape-fix",
        "host_clean.startswith(('0x', '0X', '0o', '0O', '0b', '0B'))",
        ".localdomain",
        ".arpa",
        "(?si)<script",
        "(?si)<iframe",
        "SEARXNG_SCRAPE_MAX_DURATION",
        "import urllib",
        "import re",
        "import html",
        "import httpx",
        "import idna",
        "import time",
        "trust_env=False",
        "class _ScrapeBlockedError",
        "def _is_ip_blocked",
        "def _is_reserved_scrape_host",
        "ip_direct = ipaddress.ip_address(host_clean)",
        "s6to4 = getattr(ip, 'sixtofour', None)",
        "max_duration=15.0",
        "Invalid port: 0",
        "Port mismatch for pinned host",
    ]
    if all(anchor in content for anchor in required_anchors):
        return "ALREADY_APPLIED"

    # 1. Add imports at module level (ensure re, html, httpx, idna, time, and urllib are present)
    for mod in ("re", "html", "httpx", "idna", "time", "urllib"):
        if f"import {mod}" not in content:
            content, count = re.subn(r"(import warnings\n)", f"import {mod}\n" + r"\1", content, count=1)
            if count == 0:
                content, count = re.subn(
                    r"(from flask import\b|import flask\b)", f"import {mod}\n" + r"\1", content, count=1
                )
            if count == 0:
                raise RuntimeError(f"Patch failed for {path}: Could not find import anchor for {mod}.")
    if "import trafilatura" not in content:
        content, count = re.subn(
            r"(import flask\b|from flask import\b)",
            r"import trafilatura\nimport socket\nimport contextlib\nimport threading\n\1",
            content,
            count=1,
        )
        if count == 0:
            content, count = re.subn(
                r"(import warnings\n)",
                r"import trafilatura\nimport socket\nimport contextlib\nimport threading\n\1",
                content,
                count=1,
            )
        if count == 0:
            raise RuntimeError(f"Patch failed for {path}: Could not find import anchor for trafilatura.")
    else:
        # ensure socket, contextlib, and threading exist
        for mod in ("socket", "contextlib", "threading"):
            if f"import {mod}" not in content:
                content, count = re.subn(r"(import trafilatura\n)", r"\1" + f"import {mod}\n", content)
                if count == 0:
                    content, count = re.subn(
                        r"(from flask import\b|import flask\b)", f"import {mod}\n" + r"\1", content, count=1
                    )
                if count == 0:
                    raise RuntimeError(f"Patch failed for {path}: Could not find import anchor for {mod}.")

    # 2. Clean ALL previous helper blocks and scrape routes completely (idempotency & duplicate removal)
    while "# --- GenAI Scrape Helpers ---" in content:
        content = re.sub(
            r"(?s)\n# --- GenAI Scrape Helpers ---.*?(?=\n@app\.route|\n# --- GenAI Scrape Helpers ---|\Z)",
            "",
            content,
            count=1,
        )

    while "@app.route('/scrape'" in content or '@app.route("/scrape"' in content:
        content = re.sub(
            r'(?s)\n@app\.route\(\s*[\'"]/scrape[\'"].*?(?=\n# --- GenAI Next WebUI Integration ---|\n@app\.route|\Z)',
            "",
            content,
            count=1,
        )

    # 3. Inject global client holder and pinned_dns context manager before scrape route
    # Also define the new route
    scrape_route_code = r'''

# --- GenAI Scrape Helpers ---
class _ScrapeBlockedError(Exception):
    """Raised by /scrape when a request is denied for security reasons."""


class _ScrapeResponseTooLargeError(Exception):
    """Raised when an upstream /scrape response exceeds the memory budget."""


_SCRAPE_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def _read_scrape_response(response, max_duration=15.0):
    try:
        env_dur = float(os.environ.get('SEARXNG_SCRAPE_MAX_DURATION', max_duration))
        if env_dur > 0:
            max_duration = env_dur
    except (ValueError, TypeError):
        pass

    content_length = response.headers.get('content-length')
    if content_length:
        cl_str = content_length.strip()
        if cl_str.isdigit() and int(cl_str) > _SCRAPE_MAX_RESPONSE_BYTES:
            raise _ScrapeResponseTooLargeError()

    start_time = time.monotonic()
    chunks = []
    total = 0
    for chunk in response.iter_bytes():
        if time.monotonic() - start_time > max_duration:
            raise httpx.TimeoutException('Response read stream timed out')
        total += len(chunk)
        if total > _SCRAPE_MAX_RESPONSE_BYTES:
            raise _ScrapeResponseTooLargeError()
        chunks.append(chunk)

    body = b''.join(chunks)
    encoding = response.encoding or 'utf-8'
    try:
        return body.decode(encoding, errors='replace')
    except (LookupError, ValueError):
        return body.decode('utf-8', errors='replace')


_scrape_client = None
_scrape_client_lock = threading.Lock()
_scrape_client_verify_ssl = None
_thread_local_dns = threading.local()
if not hasattr(socket, '_searxng_original_getaddrinfo'):
    socket._searxng_original_getaddrinfo = socket.getaddrinfo
_original_getaddrinfo = socket._searxng_original_getaddrinfo

def _safe_getaddrinfo(h, p, *args, **kwargs):
    pin = getattr(_thread_local_dns, 'pin', None)
    if pin:
        pin_host = pin.get('host')
        host_matches = False
        if pin_host:
            if isinstance(h, (bytes, bytearray)):
                try:
                    h_str = h.decode('ascii')
                except UnicodeDecodeError:
                    h_str = h.decode('utf-8', errors='replace')
            else:
                h_str = h or ''
            # Normalize both sides the same way httpx does: Unicode dot
            # variants (U+3002/U+FF0E/U+FF61) become '.', trailing dots are
            # stripped, then compare raw, ASCII-lowercase and IDNA forms.
            # Without this, httpx may hand the transport a normalized host
            # that differs textually from the pinned host and the pin would
            # be silently skipped (DNS rebinding / SSRF regression).
            def _norm_gai_host(value):
                value = (value or '').strip().strip('[]').lower()
                for dot in (chr(0x3002), chr(0xFF0E), chr(0xFF61)):
                    value = value.replace(dot, '.')
                return value.rstrip('.')

            h_clean = _norm_gai_host(h_str)
            pin_clean = _norm_gai_host(pin_host)
            if h_clean == pin_clean:
                host_matches = True
            else:
                try:
                    enc_h = idna.encode(h_clean, uts46=True).decode('ascii')
                    enc_pin = idna.encode(pin_clean, uts46=True).decode('ascii')
                    host_matches = (enc_h == enc_pin)
                except Exception:
                    pass

        if host_matches:
            pin_port = pin.get('port')
            if isinstance(p, (bytes, bytearray)):
                try:
                    p_str = p.decode('ascii', errors='replace')
                except Exception:
                    p_str = str(p)
            else:
                p_str = p
            port_matches = (
                p_str is None
                or p_str == pin_port
                or str(p_str) == str(pin_port)
                or (pin_port == 443 and p_str in (443, '443', 'https'))
                or (pin_port == 80 and p_str in (80, '80', 'http'))
            )
            if port_matches:
                try:
                    port_num = int(pin_port if pin_port is not None else (443 if p_str in (443, '443', 'https') else 80))
                except (ValueError, TypeError):
                    port_num = 443 if p_str in (443, '443', 'https') else 80
                req_family = args[0] if len(args) > 0 else kwargs.get('family', 0)
                pin_ips = pin.get('ips') or ([pin['ip']] if pin.get('ip') else [])
                addr_tuples = []
                for candidate in pin_ips:
                    try:
                        ip_obj = ipaddress.ip_address(candidate)
                        ip_family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
                        if req_family in (0, ip_family):
                            sockaddr = (candidate, port_num, 0, 0) if ip_obj.version == 6 else (candidate, port_num)
                            addr_tuples.append((ip_family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr))
                    except Exception:
                        continue
                if addr_tuples:
                    return addr_tuples
                raise socket.gaierror(socket.EAI_NONAME, f'Address family not supported for pinned host {pin_host}')
            else:
                raise socket.gaierror(socket.EAI_NONAME, f'Port mismatch for pinned host {pin_host}: {p} != {pin_port}')
    return _original_getaddrinfo(h, p, *args, **kwargs)

socket.getaddrinfo = _safe_getaddrinfo


@contextlib.contextmanager
def pinned_dns(host, ip, port):
    """Thread-safe DNS pinning using threading.local().
    Bypasses standard DNS resolution for a specific host/port to a target IP
    within the current thread execution context.
    """
    ips = [ip] if isinstance(ip, str) else list(ip)
    primary = ips[0] if ips else ''
    _thread_local_dns.pin = {'host': host, 'ip': primary, 'ips': ips, 'port': port}
    try:
        yield
    finally:
        _thread_local_dns.pin = None


_RESERVED_TLDS = (
    '.localhost', '.local', '.internal', '.lan', '.home.arpa',
    '.invalid', '.test', '.example', '.onion', '.corp', '.home',
    '.localdomain', '.intranet', '.private', '.arpa',
)


def _is_reserved_scrape_host(host):
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode('ascii')
        except UnicodeDecodeError:
            host = host.decode('utf-8', errors='replace')
    h = (host or '').strip().rstrip('.').lower()
    if not h or h == 'localhost':
        return True
    for tld in _RESERVED_TLDS:
        bare = tld.lstrip('.')
        if h == bare or h.endswith(tld):
            return True
    return False


def _is_ip_blocked(ip):
    if not isinstance(ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        try:
            ip = ipaddress.ip_address(ip)
        except ValueError:
            return True
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return True
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None and _is_ip_blocked(mapped):
        return True
    s6to4 = getattr(ip, 'sixtofour', None)
    if s6to4 is not None and _is_ip_blocked(s6to4):
        return True
    teredo = getattr(ip, 'teredo', None)
    if teredo is not None and (_is_ip_blocked(teredo[0]) or _is_ip_blocked(teredo[1])):
        return True
    return False


def _is_blocked_scrape_host(host, resolve_dns=True):
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode('ascii')
        except UnicodeDecodeError:
            host = host.decode('utf-8', errors='replace')
    host_clean = (host or '').strip().rstrip('.').lower()
    if _is_reserved_scrape_host(host_clean):
        return True
    if '%' in host_clean:
        host_clean = host_clean.split('%', 1)[0]
    try:
        ip = ipaddress.ip_address(host_clean)
        return _is_ip_blocked(ip)
    except ValueError:
        if host_clean.isdigit():
            try:
                ip_int = int(host_clean)
                if 0 <= ip_int <= 0xFFFFFFFF:
                    return _is_ip_blocked(ipaddress.IPv4Address(ip_int))
            except Exception:
                pass
        if ':' not in host_clean:
            try:
                packed_ip = socket.inet_aton(host_clean)
                return _is_ip_blocked(ipaddress.IPv4Address(packed_ip))
            except Exception:
                pass
        if host_clean.startswith(('0x', '0X', '0o', '0O', '0b', '0B')):
            try:
                ip_int = int(host_clean, 0)
                if 0 <= ip_int <= 0xFFFFFFFF:
                    return _is_ip_blocked(ipaddress.IPv4Address(ip_int))
            except Exception:
                pass

    if not resolve_dns:
        return False

    try:
        for res in socket.getaddrinfo(host_clean, None):
            if _is_ip_blocked(res[4][0]):
                return True
    except (socket.gaierror, ValueError):
        pass
    return False


@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    """Extract main text content from URL (GenAI friendly, SSRF-protected).
    # v19-bulletproof-scrape-fix

    SECURITY: Blocks loopback, private/reserved IP ranges, link-local, and
    file:// scheme to prevent SSRF attacks and internal resource exposure.
    DNS Rebinding is mitigated via thread-safe DNS pinning, allowing SSL verification to remain enabled.

    NOTE: SSL verification is enabled by default.
    Set SEARXNG_SCRAPE_VERIFY_SSL=false to disable validation if needed.
    """
    url = sxng_request.values.get('url')
    if not url:
        json_data = sxng_request.get_json(silent=True)
        if json_data and isinstance(json_data, dict):
            url = json_data.get('url')
    if not url or not isinstance(url, str) or not url.strip():
        return jsonify({'error': 'No URL provided'}), 400
    url = url.strip()

    def _parse_scrape_url(value):
        try:
            parsed_url = urllib.parse.urlparse(value)
            # Accessing .port validates malformed or out-of-range ports.
            p = parsed_url.port
            if p is not None and (p == 0 or p > 65535):
                raise _ScrapeBlockedError('Invalid port: 0')
            return parsed_url
        except ValueError as exc:
            raise _ScrapeBlockedError('Invalid URL') from exc

    def _fetch_scrape_url(request_url):
        global _scrape_client, _scrape_client_verify_ssl
        verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes')
        ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36')

        with _scrape_client_lock:
            if _scrape_client is None or _scrape_client_verify_ssl != verify_ssl:
                # Reusable HTTP client with connection pooling and explicit limits
                scrape_limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
                if _scrape_client is not None:
                    try:
                        _scrape_client.close()
                    except Exception:
                        pass
                # Do not inherit proxy or CA settings from the process environment.
                # In particular, routing through HTTP(S)_PROXY would make the
                # proxy resolve the user-controlled hostname and bypass the DNS
                # validation and pinning performed below.
                _scrape_client = httpx.Client(
                    timeout=httpx.Timeout(10.0, connect=5.0, read=10.0, write=5.0),
                    follow_redirects=False,
                    verify=verify_ssl,
                    limits=scrape_limits,
                    trust_env=False,
                )
                _scrape_client_verify_ssl = verify_ssl

        def _normalize_scrape_host(host_raw):
            """Normalize a host the same way httpx does before transport.

            Converts Unicode dots (U+3002, U+FF0E, U+FF61) to '.', strips
            trailing dots and applies IDNA/punycode encoding. Must be applied
            before host blocking, DNS resolution and pinning so that the
            validator, the DNS pin and httpx's transport all agree on the
            exact host string that will be resolved. Without this, a pin
            keyed on a non-normalized host is silently ignored by the
            transport, re-enabling DNS rebinding (SSRF).
            """
            host_norm = (host_raw or '').strip().strip('[]').lower()
            for dot in (chr(0x3002), chr(0xFF0E), chr(0xFF61)):
                host_norm = host_norm.replace(dot, '.')
            host_norm = host_norm.rstrip('.')
            if '%' in host_norm:
                host_norm = host_norm.split('%', 1)[0]
            if host_norm and not host_norm.replace('.', '').isdigit():
                try:
                    host_norm = idna.encode(host_norm, uts46=True).decode('ascii')
                except Exception:
                    pass
            return host_norm

        def _get_safe_ip_url(url_to_resolve):
            parsed = urllib.parse.urlparse(url_to_resolve)
            if parsed.scheme not in ('http', 'https'):
                raise _ScrapeBlockedError(f'Blocked invalid scheme: {parsed.scheme}')

            host = parsed.hostname
            if not host:
                raise _ScrapeBlockedError('Empty hostname')

            host_clean = _normalize_scrape_host(host)
            if not host_clean:
                raise _ScrapeBlockedError('Empty hostname')
            if _is_reserved_scrape_host(host_clean):
                raise _ScrapeBlockedError(f'Blocked: {host} is a private/reserved host')

            if '%' in host_clean:
                host_clean = host_clean.split('%', 1)[0]

            try:
                ip_direct = ipaddress.ip_address(host_clean)
                if _is_ip_blocked(ip_direct):
                    raise _ScrapeBlockedError(f'Blocked: {host} is a private/reserved IP')
            except ValueError:
                if host_clean.isdigit():
                    try:
                        ip_int = int(host_clean)
                        if 0 <= ip_int <= 0xFFFFFFFF:
                            v4 = ipaddress.IPv4Address(ip_int)
                            if _is_ip_blocked(v4):
                                raise _ScrapeBlockedError(f'Blocked: {host} is a private/reserved IP')
                    except _ScrapeBlockedError:
                        raise
                    except Exception:
                        pass
                if ':' not in host_clean:
                    try:
                        packed_ip = socket.inet_aton(host_clean)
                        if _is_ip_blocked(ipaddress.IPv4Address(packed_ip)):
                            raise _ScrapeBlockedError(f'Blocked: {host} is a private/reserved IP')
                    except _ScrapeBlockedError:
                        raise
                    except Exception:
                        pass
                if host_clean.startswith(('0x', '0X', '0o', '0O', '0b', '0B')):
                    try:
                        ip_int = int(host_clean, 0)
                        if 0 <= ip_int <= 0xFFFFFFFF:
                            v4 = ipaddress.IPv4Address(ip_int)
                            if _is_ip_blocked(v4):
                                raise _ScrapeBlockedError(f'Blocked: {host} is a private/reserved IP')
                    except _ScrapeBlockedError:
                        raise
                    except Exception:
                        pass

            # Rebuild the URL with the normalized host so that the transport
            # (httpx) resolves exactly the host we validated and pinned.
            # Without this, a host like 'attacker.example' + U+3002 is
            # normalized by httpx to 'attacker.example.' which no longer
            # matches the pin host, silently disabling the pin and
            # re-enabling DNS rebinding.
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            if ':' in host_clean and not host_clean.startswith('['):
                host_out = f'[{host_clean}]'
            else:
                host_out = host_clean
            hostport = f'{host_out}:{port}' if parsed.port else host_out
            userinfo, at_sep, _rest = parsed.netloc.partition('@')
            netloc = f'{userinfo}@{hostport}' if at_sep else hostport
            safe_url = parsed._replace(netloc=netloc).geturl()

            try:
                addr_info = socket.getaddrinfo(host_clean, port)
                if not addr_info:
                    raise _ScrapeBlockedError(f'Could not resolve host: {host}')
                valid_ips = []
                for res in addr_info:
                    ip_raw = res[4][0]
                    if _is_ip_blocked(ip_raw):
                        raise _ScrapeBlockedError(f'Blocked: {host} resolves to a private/reserved IP: {ip_raw}')
                    valid_ips.append(ip_raw)
                if not valid_ips:
                    raise _ScrapeBlockedError(f'Could not find a global IP for {host}')
                v4_ips = [ip for ip in valid_ips if ':' not in ip]
                v6_ips = [ip for ip in valid_ips if ':' in ip]
                ordered_ips = v4_ips + v6_ips
                return ordered_ips, host_clean, port, safe_url
            except _ScrapeBlockedError:
                raise
            except socket.gaierror as e:
                raise _ScrapeBlockedError(f'DNS resolution failed for {host}: {e}')
            except Exception as e:
                raise RuntimeError(f'DNS resolution failed for {host}: {e}')

        current_url = request_url
        for _ in range(5):
            cur_parsed = _parse_scrape_url(current_url)
            if (cur_parsed.scheme or '').lower() not in ('http', 'https'):
                raise _ScrapeBlockedError(f'Blocked invalid scheme during redirect: {cur_parsed.scheme}')

            safe_ips, original_host, port, safe_url = _get_safe_ip_url(current_url)
            headers = {'User-Agent': ua}

            # Use thread-safe DNS Pinning context manager
            with pinned_dns(original_host, safe_ips, port):
                # current_url was rebuilt with the normalized host, so the
                # transport always looks up the exact pinned host. TLS verify
                # still uses the host name, while the socket connects to the
                # validated safe IP.
                with _scrape_client.stream('GET', safe_url, headers=headers) as response:
                    if response.status_code not in (301, 302, 303, 307, 308):
                        response.raise_for_status()
                        return _read_scrape_response(response)

                    location = response.headers.get('location')
                    if not location or not location.strip():
                        raise RuntimeError(f'Redirect without Location header (status {response.status_code})')
                    current_url = urllib.parse.urljoin(safe_url, location.strip())
        else:
            raise RuntimeError('Too many redirects')

    try:
        parsed = _parse_scrape_url(url)
    except _ScrapeBlockedError as e:
        return jsonify({'error': str(e)}), 400
    if parsed.scheme not in ('http', 'https') or _is_blocked_scrape_host(parsed.hostname, resolve_dns=False):
        return jsonify({'error': 'Invalid or blocked URL'}), 400

    try:
        downloaded = _fetch_scrape_url(url) or ''
        content_text = None
        try:
            content_text = trafilatura.extract(
                downloaded, include_comments=False, include_tables=True
            )
        except Exception:
            content_text = None

        if not content_text and downloaded:
            # Fallback to basic HTML text extraction if trafilatura returns None/empty
            sample_html = downloaded[:1_000_000]
            raw_text = re.sub(r'(?si)<!--.*?-->', ' ', sample_html)
            raw_text = re.sub(r'(?si)<script.*?>.*?</script>', ' ', raw_text)
            raw_text = re.sub(r'(?si)<style.*?>.*?</style>', ' ', raw_text)
            raw_text = re.sub(r'(?si)<noscript.*?>.*?</noscript>', ' ', raw_text)
            raw_text = re.sub(r'(?si)<iframe.*?>.*?</iframe>', ' ', raw_text)
            raw_text = re.sub(r'(?si)<template.*?>.*?</template>', ' ', raw_text)
            raw_text = re.sub(r'<[^>]+>', ' ', raw_text)
            raw_text = html.unescape(raw_text)
            raw_text = re.sub(r'\s+', ' ', raw_text).strip()
            if raw_text:
                content_text = raw_text[:5000]

        if not content_text:
            return jsonify({'error': 'Could not extract content'}), 422

        return jsonify({'url': url, 'content': content_text})
    except _ScrapeResponseTooLargeError:
        return jsonify({'error': 'Fetched response exceeds size limit'}), 502
    except httpx.TimeoutException as e:
        return jsonify({'error': f'Fetch timeout: {str(e)[:100]}'}), 504
    except httpx.HTTPError as e:
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 502
    except _ScrapeBlockedError as e:
        return jsonify({'error': str(e)[:100]}), 400
    except RuntimeError as e:
        return jsonify({'error': str(e)[:100]}), 502
    except Exception as e:
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 500

'''

    # Primary anchor: @app.route('/search')
    content, count = re.subn(
        r"(?m)^(\s*@app\.route\(\s*['\"]/search['\"])", lambda m: scrape_route_code + m.group(1), content, count=1
    )
    if count == 0:
        # Fallback 1: any blueprint or route on /search
        content, count = re.subn(
            r"(?m)^(\s*@\w+\.route\(\s*['\"]/search['\"])", lambda m: scrape_route_code + m.group(1), content, count=1
        )
    if count == 0:
        # Fallback 2: any route on root '/'
        content, count = re.subn(
            r"(?m)^(\s*@\w+\.route\(\s*['\"]/['\"])", lambda m: scrape_route_code + m.group(1), content, count=1
        )
    if count == 0:
        # Fallback 3: def search()
        content, count = re.subn(
            r"(?m)^(\s*def search\s*\()", lambda m: scrape_route_code + m.group(1), content, count=1
        )
    if count == 0:
        # Fallback 4: append to end of webapp.py
        content = content.rstrip() + "\n\n" + scrape_route_code + "\n"

    return content


# --- Patch 6: engines/__init__.py (restore upstream disabled-engine semantics) ---
def patch_engines_init(content, path):
    # Pure replace() rewrite of legacy blocks; unchanged == already restored.
    setattr(patch_engines_init, "_noop_when_unchanged", True)  # noqa: B010
    """Undo legacy patches that made ``disabled`` act like ``inactive``.

    SearXNG keeps disabled engines loaded so users can enable them in
    preferences or invoke them with a bang.  Only ``inactive`` means removed.
    This cleanup is retained so existing installations are repaired on the
    next patch run; pristine upstream files are left unchanged.
    """
    early_return_block = """
    # Early return for engines that are intentionally disabled or inactive in config.
    if engine_data.get('inactive') is True:
        logger.debug('Engine \"%s\" is inactive in config, skipping load', engine_name)
        return None
    if engine_data.get('disabled') is True:
        logger.debug('Engine \"%s\" is disabled in config, skipping load', engine_name)
        return None
"""
    combined_loop_block = """        if engine_data.get(\"inactive\") is True or engine_data.get(\"disabled\") is True:
            logger.debug(
                \"loading engine %s skipped: inactive or disabled in config!\",
                engine_data.get(\"name\", \"???\"),
            )
            continue
"""

    patched = content.replace(early_return_block, "")
    patched = patched.replace(
        combined_loop_block,
        '        if engine_data.get("inactive") is True:\n            continue\n',
    )
    return "ALREADY_APPLIED" if patched == content else patched


# --- Patch 6b: engines/__init__.py (fast-path skip inactive & unconfigured onion engines) ---
def patch_engines_fast_load(content: str, path: str) -> str:
    """Optimize engine loading by skipping inactive and unavailable onion engines before importing."""
    if "sxng-fast-engine-load-v1" in content:
        return "ALREADY_APPLIED"

    fast_load_code = (
        "    # sxng-fast-engine-load-v1: skip inactive or unavailable onion engines before import\n"
        "    if engine_data.get('inactive') is True:\n"
        "        return None\n"
        "    _using_tor = settings['outgoing'].get('using_tor_proxy') or engine_data.get('using_tor_proxy', False)\n"
        "    if not _using_tor and (\n"
        "        'onions' in engine_data.get('categories', []) or module_name in ('ahmia', 'torch')\n"
        "    ):\n"
        "        return None\n"
    )

    target = "    try:\n        engine = load_module(module_name + '.py', ENGINE_DIR)"
    if target in content:
        content = content.replace(target, fast_load_code + target, 1)
    else:
        target_fb = "        return None\n    try:"
        if target_fb in content:
            content = content.replace(target_fb, "        return None\n" + fast_load_code + "    try:", 1)
        else:
            raise RuntimeError("Could not find injection point in engines/__init__.py for fast-load")

    old_log = "logger.error(\n                f\"(PID {os.getpid()}) {engine_data.get('name', '???')}: can't register engine (loading engine failed)\"\n            )"
    new_log = "logger.debug(\n                f\"(PID {os.getpid()}) {engine_data.get('name', '???')}: can't register engine (loading engine skipped or failed)\"\n            )"
    if old_log in content:
        content = content.replace(old_log, new_log)

    return content


# --- Patch 7: search/processors/__init__.py (restore upstream disabled-engine semantics) ---
def patch_processors_init(content, path):
    # Pure replace() rewrite of the legacy block; unchanged == already restored.
    setattr(patch_processors_init, "_noop_when_unchanged", True)  # noqa: B010
    injected_block = """            if eng_settings.get("disabled", False) is True:
                logger.debug("Engine '%s' is disabled in config, skipping processor init.", eng_name)
                continue
"""
    patched = content.replace(injected_block, "")
    return "ALREADY_APPLIED" if patched == content else patched


# --- Patch 8: engines/google.py (fix CAPTCHA false positives) ---
def patch_google_captcha(content, path):
    # replace() rewrite; unchanged means upstream no longer has the old block
    # (either fixed upstream or already patched). Nothing left to do.
    setattr(patch_google_captcha, "_noop_when_unchanged", True)  # noqa: B010
    if 'loc = (resp.headers.get("Location")' in content:
        return "ALREADY_APPLIED"
    old = (
        "    if resp.status_code == 302:\n"
        "        raise SearxEngineCaptchaException()\n"
        "\n"
        '    if len(resp.text) < 2000 and "/sorry/" in resp.text:\n'
        "        raise SearxEngineCaptchaException()"
    )
    new = (
        "    if resp.status_code == 302:\n"
        '        loc = (resp.headers.get("Location") or resp.headers.get("location") or "")\n'
        '        if "/sorry" in loc or "sorry.google.com" in loc or not loc:\n'
        "            raise SearxEngineCaptchaException()\n"
        "\n"
        '    if len(resp.text) < 2000 and "/sorry/" in resp.text:\n'
        "        raise SearxEngineCaptchaException()"
    )
    if old in content:
        return content.replace(old, new)
    return content


# --- Patch 9: engines/sogou.py (robust CAPTCHA detection) ---
def patch_sogou_captcha(content, path):
    # replace() rewrite; unchanged == nothing to do (see patch_google_captcha).
    setattr(patch_sogou_captcha, "_noop_when_unchanged", True)  # noqa: B010
    if "antispider" in content and "captcha" in content.lower() and "resp.headers.get" in content:
        return "ALREADY_APPLIED"
    old = (
        "def response(resp):\n"
        "    if (\n"
        "        resp.status_code == 302\n"
        "        and resp.next_request is not None\n"
        '        and str(resp.next_request.url).startswith("http://www.sogou.com/antispider")\n'
        "    ):\n"
        "        raise SearxEngineCaptchaException()"
    )
    new = (
        "def response(resp):\n"
        "    if resp.status_code == 302:\n"
        '        loc = resp.headers.get("Location") or resp.headers.get("location") or ""\n'
        '        if "antispider" in loc or "sogou.com/antispider" in loc:\n'
        "            raise SearxEngineCaptchaException()\n"
        '        if resp.next_request is not None and str(resp.next_request.url).startswith("http://www.sogou.com/antispider"):\n'
        "            raise SearxEngineCaptchaException()\n"
        '        text_preview = (resp.text or "")[:4096]\n'
        '        if "antispider" in text_preview or "captcha" in text_preview.lower():\n'
        "            raise SearxEngineCaptchaException()\n"
        "    if resp.status_code == 200:\n"
        '        text_preview = (resp.text or "")[:8192].lower()\n'
        '        if "antispider" in text_preview and ("captcha" in text_preview or "verify" in text_preview):\n'
        '            if "class=\\"result\\"" not in text_preview and "class=\\"rb\\"" not in text_preview:\n'
        "                raise SearxEngineCaptchaException()"
    )
    if old in content:
        return content.replace(old, new)
    return content


# --- Patch 10: search/processors/abstract.py (restore configured suspension times) ---
def patch_abstract_suspend(content, path):
    # Pure replace() rewrite of the legacy cap; unchanged == already restored.
    setattr(patch_abstract_suspend, "_noop_when_unchanged", True)  # noqa: B010
    """Undo the legacy global cap that overrode ``suspended_times``.

    ``max_ban_time_on_fail`` applies to ordinary engine failures.  Explicit
    SearXNG access-denied and CAPTCHA exceptions carry their own values from
    ``search.suspended_times`` and must retain those configured values.
    """
    legacy = (
        '            suspended_time = min(suspended_time, get_setting("search.max_ban_time_on_fail"))\n'
        '            if "captcha" in suspend_reason.lower() or "SearxEngineCaptcha" in suspend_reason:\n'
        "                suspended_time = min(suspended_time, 900)\n"
        "            if suspended_time > 120 and self.continuous_errors == 1:\n"
        "                suspended_time = min(suspended_time, 120)\n"
        "\n"
        "            self.suspend_end_time = default_timer() + suspended_time\n"
        "            self.suspend_reason = suspend_reason\n"
        '            logger.debug("Suspend for %i seconds", suspended_time)'
    )
    upstream = (
        "            self.suspend_end_time = default_timer() + suspended_time\n"
        "            self.suspend_reason = suspend_reason\n"
        '            logger.debug("Suspend for %i seconds", suspended_time)'
    )
    patched = content.replace(legacy, upstream)
    return "ALREADY_APPLIED" if patched == content else patched


# --- Patch 11: search/processors/online.py (Retry-After + CAPTCHA logging) ---
def patch_online_captcha(content, path):
    if (
        "except SearxEngineCaptchaException as e:" in content
        and "except SearxEngineTooManyRequestsException as e:" in content
        and ("parsedate_to_datetime" in content or "return max(5, min(v, 900))" not in content)
        and ("datetime.timezone.utc" in content or "return max(5, min(v, 900))" not in content)
        and "utcnow" not in content
    ):
        return "ALREADY_APPLIED"

    original = content
    helper_present = "_parse_retry_after_header" in content

    new_helper = (
        "def _parse_retry_after_header(resp) -> int | None:\n"
        "    if resp is None:\n"
        "        return None\n"
        "    try:\n"
        "        hdr = None\n"
        "        if hasattr(resp, 'headers'):\n"
        "            hdr = resp.headers.get('Retry-After') or resp.headers.get('retry-after')\n"
        "        if hdr is None:\n"
        "            return None\n"
        "        hdr = hdr.strip()\n"
        "        if hdr.isdigit():\n"
        "            v = int(hdr)\n"
        "            return max(5, min(v, 900))\n"
        "        import datetime\n"
        "        import email.utils\n"
        "        dt = email.utils.parsedate_to_datetime(hdr)\n"
        "        if dt is not None:\n"
        "            if dt.tzinfo is None:\n"
        "                dt = dt.replace(tzinfo=datetime.timezone.utc)\n"
        "            now = datetime.datetime.now(datetime.timezone.utc)\n"
        "            delta = int((dt - now).total_seconds())\n"
        "            return max(5, min(delta, 900))\n"
        "    except Exception:\n"
        "        pass\n"
        "    return None"
    )

    if not helper_present:
        old_import = (
            "from searx.metrics.error_recorder import count_error\nfrom .abstract import EngineProcessor, RequestParams"
        )
        new_import = (
            "from searx.metrics.error_recorder import count_error\n"
            "from .abstract import EngineProcessor, RequestParams\n"
            "\n"
            "\n" + new_helper
        )
        if old_import in content:
            content = content.replace(old_import, new_import, 1)
            helper_present = True
        else:
            # Fallback 1: match "from .abstract import ..."
            m = re.search(r"(?m)^(from \.abstract import [^\n]+\n)", content)
            if m:
                idx = m.end()
                content = content[:idx] + "\n\n" + new_helper + "\n" + content[idx:]
                helper_present = True
            else:
                # Fallback 2: match "class OnlineEngineProcessor"
                m = re.search(r"(?m)^(class OnlineEngineProcessor\b)", content)
                if m:
                    idx = m.start()
                    content = content[:idx] + new_helper + "\n\n\n" + content[idx:]
                    helper_present = True
    else:
        if "return max(5, min(v, 900))" in content and ("parsedate_to_datetime" not in content or "utcnow" in content):
            content = re.sub(
                r"(?s)def _parse_retry_after_header\(resp\).*?except Exception:\s*pass\s*return None",
                new_helper,
                content,
                count=1,
            )
        # Legacy hard-coded CAPTCHA cap from pre-patch-11 installs.
        content = content.replace("            e.suspended_time = min(e.suspended_time, 900)\n", "")

    old_combined = (
        "        except (\n"
        "            SearxEngineCaptchaException,\n"
        "            SearxEngineTooManyRequestsException,\n"
        "            SearxEngineAccessDeniedException,\n"
        "        ) as e:\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)"
    )
    new_split = (
        "        except SearxEngineCaptchaException as e:\n"
        "            retry_after = _parse_retry_after_header(getattr(e, 'response', None))\n"
        "            if retry_after is not None:\n"
        "                e.suspended_time = min(e.suspended_time, retry_after)\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        '            self.logger.warning("CAPTCHA %s suspended for %ss: %s", self.engine.name, e.suspended_time, e.message)\n'
        "        except SearxEngineTooManyRequestsException as e:\n"
        "            retry_after = _parse_retry_after_header(getattr(e, 'response', None))\n"
        "            if retry_after is not None:\n"
        "                e.suspended_time = min(e.suspended_time, retry_after)\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)\n"
        "        except SearxEngineAccessDeniedException as e:\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)"
    )
    tuple_block = (
        "        except (\n"
        "            SearxEngineTooManyRequestsException,\n"
        "            SearxEngineAccessDeniedException,\n"
        "        ) as e:\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)"
    )
    split_block = (
        "        except SearxEngineTooManyRequestsException as e:\n"
        "            retry_after = _parse_retry_after_header(getattr(e, 'response', None))\n"
        "            if retry_after is not None:\n"
        "                e.suspended_time = min(e.suspended_time, retry_after)\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)\n"
        "        except SearxEngineAccessDeniedException as e:\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)"
    )
    # Only reference the helper from the handlers when it is actually defined.
    if helper_present:
        if old_combined in content:
            content = content.replace(old_combined, new_split, 1)
        elif tuple_block in content:
            content = content.replace(tuple_block, split_block, 1)
        else:
            # Regex fallback for slight whitespace or formatting variations
            pattern = re.compile(
                r"([ \t]*)except\s*\(\s*SearxEngineCaptchaException\s*,\s*SearxEngineTooManyRequestsException\s*,\s*SearxEngineAccessDeniedException\s*\)\s*as\s*e:\s*\n"
                r"[ \t]*self\.handle_exception\([^)]+\)\s*\n"
                r"[ \t]*self\.logger\.debug\(e\.message\)"
            )
            if pattern.search(content):
                content = pattern.sub(new_split, content, count=1)

    return "ALREADY_APPLIED" if content == original else content


# --- Patch 11b: network/raise_for_httperror.py (attach response to exceptions) ---
def _attach_response_to_raises(content: str) -> tuple[str, bool]:
    """Rewrite ``raise SearxEngine*Exception(...)`` to attach the response.

    Returns the (possibly unchanged) content and whether any raise statement
    was rewritten.  Each rewritten raise becomes::

        _exc = SearxEngineFooException(<args>)
        _exc.response = resp
        raise _exc

    The ``online.py`` handler reads ``e.response`` (via ``getattr(e,
    'response', None)``) to honour the ``Retry-After`` header; without the
    response being attached that lookup always returns ``None`` and the
    Retry-After feature is a silent no-op.
    """
    pattern = re.compile(
        r"^(?P<indent>[ ]*)raise (?P<cls>SearxEngine(?:Captcha|AccessDenied|TooManyRequests)Exception)(?P<open>\()",
        re.MULTILINE,
    )
    out = []
    pos = 0
    changed = False
    for match in pattern.finditer(content):
        # Find the matching close paren (args may contain nested parens).
        depth = 1
        i = match.end("open")
        while i < len(content) and depth:
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
            i += 1
        if depth:
            continue  # unbalanced; leave this raise untouched
        args = content[match.end("open") : i - 1]
        indent = match.group("indent")
        cls = match.group("cls")
        out.append(content[pos : match.start()])
        out.append(f"{indent}_exc = {cls}({args})\n{indent}_exc.response = resp\n{indent}raise _exc")
        pos = i
        changed = True
    out.append(content[pos:])
    return "".join(out), changed


def patch_raise_for_httperror(content, path):
    """Attach the response to engine exceptions raised with a response in hand.

    Without this, ``SearxEngine*Exception`` instances never carry a
    ``response`` attribute, so the Retry-After handling in
    ``search/processors/online.py`` can never fire.
    """
    if "_exc.response = resp" in content:
        return "ALREADY_APPLIED"
    content, _ = _attach_response_to_raises(content)
    return content  # unchanged content => update_file reports "anchor not found"


# --- Patch 12: settings.yml / settings_defaults.py (reduce suspended_times) ---
def patch_settings_yml(content, path):
    if "SearxEngineCaptcha: 900" in content and (
        "cf_SearxEngineAccessDenied" not in content or "cf_SearxEngineAccessDenied: 1800" in content
    ):
        return "ALREADY_APPLIED"
    patched = re.sub(r"SearxEngineCaptcha:\s*\d+", "SearxEngineCaptcha: 900", content)
    patched = re.sub(r"SearxEngineAccessDenied:\s*\d+", "SearxEngineAccessDenied: 900", patched)
    patched = re.sub(r"SearxEngineTooManyRequests:\s*\d+", "SearxEngineTooManyRequests: 600", patched)
    patched = re.sub(r"cf_SearxEngineCaptcha:\s*\d+", "cf_SearxEngineCaptcha: 3600", patched)
    patched = re.sub(r"cf_SearxEngineAccessDenied:\s*\d+", "cf_SearxEngineAccessDenied: 1800", patched)
    patched = re.sub(r"recaptcha_SearxEngineCaptcha:\s*\d+", "recaptcha_SearxEngineCaptcha: 3600", patched)
    if patched == content:
        return "ALREADY_APPLIED"
    return patched


def patch_config_settings_yml(content, path):
    if "SearxEngineCaptcha: 900" in content:
        return "ALREADY_APPLIED"
    # If user has custom SearxEngineCaptcha (not legacy 86400/3600), or if absent, preserve user customization
    if re.search(r"SearxEngineCaptcha:\s*(?!86400|3600)\d+", content) or "SearxEngineCaptcha" not in content:
        return "ALREADY_APPLIED"
    patched = patch_settings_yml(content, path)
    if patched == content:
        # Preserve user customization without raising RuntimeError in update_file
        return "ALREADY_APPLIED"
    return patched


# --- Patch 13: webapp.py (register SearXNG Next AI WebUI & /deep_search routes) ---
def patch_webapp_ai_webui(content, path):
    required_anchors = (
        "# --- GenAI Next WebUI Integration ---",
        "_webui_next.register_next_webui(app, sys.modules.get(__name__))",
    )
    if all(anchor in content for anchor in required_anchors):
        return "ALREADY_APPLIED"

    # Remove any previous integration block for idempotency
    while "# --- GenAI Next WebUI Integration ---" in content:
        content = re.sub(
            r"(?s)\n# --- GenAI Next WebUI Integration ---.*?(?=\n@app\.route|\Z)",
            "",
            content,
            count=1,
        )

    integration_code = """

# --- GenAI Next WebUI Integration ---
try:
    _tools_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'tools'))
    if os.path.isdir(_tools_dir) and _tools_dir not in sys.path:
        sys.path.insert(0, _tools_dir)
    import webui_next as _webui_next
    _webui_next.register_next_webui(app, sys.modules.get(__name__))
except Exception as _webui_exc:
    logger.warning('Could not initialize SearXNG Next AI WebUI: %s', _webui_exc)

"""

    content, count = re.subn(
        r"(?m)^(\s*@app\.route\(\s*['\"]/search['\"])",
        lambda m: integration_code + m.group(1),
        content,
        count=1,
    )
    if count == 0:
        raise RuntimeError(f"Patch failed for {path}: Could not find @app.route('/search') anchor to inject AI WebUI.")
    return content


# --- Patch 14: templates/simple/base.html (inject AI Workspace nav link & assets) ---
def patch_simple_base_ai_webui(content, path):
    required_anchors = (
        'class="link_on_top_ai"',
        'href="/ai/embed.css"',
        'src="/ai/embed.js"',
    )
    if all(anchor in content for anchor in required_anchors):
        return "ALREADY_APPLIED"

    patched = content
    if 'class="link_on_top_ai"' not in patched:
        ai_nav_block = (
            "      {%- block linkto_ai_workspace -%}\n"
            '        <a href="/ai" class="link_on_top_ai" title="AI Search &amp; Context Studio"><span>⚡ AI Workspace</span></a>\n'
            "      {%- endblock -%}\n"
        )
        if "{%- block linkto_about -%}" in patched:
            patched = patched.replace(
                "{%- block linkto_about -%}", ai_nav_block + "      {%- block linkto_about -%}", 1
            )
        elif '<nav id="links_on_top">' in patched:
            patched = patched.replace('<nav id="links_on_top">\n', '<nav id="links_on_top">\n' + ai_nav_block, 1)

    if 'src="/ai/embed.js"' not in patched:
        embed_tags = (
            '  <link rel="stylesheet" href="/ai/embed.css" type="text/css">\n'
            '  <script defer src="/ai/embed.js"></script>\n'
        )
        if "</body>" in patched:
            patched = patched.replace("</body>", embed_tags + "</body>", 1)

    return patched


# --- Patch 15: templates/simple/index.html (inject AI Quick Actions bar on home page) ---
def patch_simple_index_ai_webui(content, path):
    required_anchors = (
        'class="sxng-ai-home-bar"',
        'class="sxng-next-badge"',
        'class="sxng-next-badge-wrap"',
        "⚡ AI Search &amp; Scrape Studio",
    )
    if all(anchor in content for anchor in required_anchors):
        return "ALREADY_APPLIED"

    patched = content

    # Migrate legacy patch where badge was placed directly inside .title (which overlaps with background logo)
    if '<h1>SearXNG</h1><span class="sxng-next-badge">Next · AI-First Edition</span>' in patched:
        patched = patched.replace(
            '<h1>SearXNG</h1><span class="sxng-next-badge">Next · AI-First Edition</span>',
            "<h1>SearXNG</h1>",
            1,
        )

    badge_wrap = (
        '    <div class="sxng-next-badge-wrap"><span class="sxng-next-badge">Next · AI-First Edition</span></div>\n'
    )
    if 'class="sxng-next-badge-wrap"' not in patched:
        if '<div class="title"><h1>SearXNG</h1></div>' in patched:
            patched = patched.replace(
                '<div class="title"><h1>SearXNG</h1></div>',
                '<div class="title"><h1>SearXNG</h1></div>\n' + badge_wrap.rstrip(),
                1,
            )
        elif "<h1>SearXNG</h1>" in patched:
            patched = patched.replace(
                "<h1>SearXNG</h1>",
                "<h1>SearXNG</h1>\n" + badge_wrap.rstrip(),
                1,
            )

    new_home_bar = (
        '    <div class="sxng-ai-home-bar" role="region" aria-label="AI Search Actions">\n'
        '        <button type="button" class="sxng-ai-btn sxng-ai-btn-primary" id="sxng-home-deep-btn" '
        "onclick=\"var q=document.getElementById('q');window.location.href='/ai'+(q&&q.value.trim()?'?q='+encodeURIComponent(q.value.trim()):'');\">"
        "⚡ AI Search &amp; Scrape Studio</button>\n"
        '        <a href="/ai?mode=agent" class="sxng-ai-btn">🤖 Agent &amp; MCP Hub</a>\n'
        '        <script>(function(){if(!window.__AI_STUDIO_LOADED__&&window.location.pathname!=="/"){window.location.replace("/"+(window.location.search||""));}})();</script>\n'
        "    </div>"
    )

    if 'class="sxng-ai-home-bar"' in patched:
        patched = re.sub(
            r'\s*<div class="sxng-ai-home-bar"[^>]*>.*?</div>',
            "\n" + new_home_bar,
            patched,
            count=1,
            flags=re.DOTALL,
        )
    elif "{% include 'simple/simple_search.html' %}" in patched:
        patched = patched.replace(
            "{% include 'simple/simple_search.html' %}",
            "{% include 'simple/simple_search.html' %}\n" + new_home_bar,
            1,
        )

    return patched


# --- Patch 16: templates/simple/results.html (inject AI Agent Toolkit Bar on search results) ---
def patch_simple_results_ai_webui(content, path):
    required_anchors = (
        'id="sxng-ai-results-bar"',
        'id="sxng-ai-deep-drawer"',
    )
    if all(anchor in content for anchor in required_anchors):
        return "ALREADY_APPLIED"

    target_div = '<div id="results" class="{{ only_template }}">'
    if target_div not in content:
        return content

    toolkit_bar = (
        '<div id="results" class="{{ only_template }}">\n'
        '  <div id="sxng-ai-results-bar" class="sxng-ai-results-bar" data-query="{{ q|e }}" role="region" aria-label="AI Agent Toolkit">\n'
        '    <div class="sxng-ai-results-bar-left">\n'
        "      <strong>🤖 AI Toolkit</strong>\n"
        '      <span id="sxng-ai-page-tokens" class="sxng-ai-token-pill">~0 tokens</span>\n'
        '      <button type="button" id="sxng-ai-inline-deep-btn" class="sxng-ai-btn sxng-ai-btn-primary">⚡ Deep Search (BM25 + 並列本文抽出)</button>\n'
        '      <button type="button" id="sxng-ai-copy-md-btn" class="sxng-ai-btn">📋 AI用Markdownをコピー</button>\n'
        '      <button type="button" id="sxng-ai-copy-prompt-btn" class="sxng-ai-btn">💬 プロンプト形式でコピー</button>\n'
        "    </div>\n"
        '    <div class="sxng-ai-results-bar-right">\n'
        '      <a href="/search?q={{ q|urlencode }}&amp;format=json_lite" target="_blank" rel="noopener" class="sxng-ai-btn">{ } json_lite</a>\n'
        '      <a href="/ai?q={{ q|urlencode }}&amp;mode=deep" class="sxng-ai-btn">🚀 AI Studioで開く</a>\n'
        "    </div>\n"
        "  </div>\n"
        '  <div id="sxng-ai-deep-drawer" class="sxng-ai-deep-drawer" aria-live="polite"></div>'
    )
    return content.replace(target_div, toolkit_bar, 1)


PATCH_SPECS = [
    PatchSpec(
        name="valkeydb_pwd",
        target_path=os.path.join(SITE_PACKAGES, "searx", "valkeydb.py"),
        description="valkeydb.py (Windows pwd compatibility)",
        patch_func=patch_valkeydb,
        severity=PatchSeverity.CRITICAL,
        required_file=True,
        expected_anchors=[
            "import pwd",
            "_pw = pwd.getpwuid(os.getuid())",
        ],
        diagnostic_hint="Unix pwd module is not available on Windows. Valkey DB initialization must use _windows_safe_current_user().",
    ),
    PatchSpec(
        name="webutils_windows_paths",
        target_path=os.path.join(SITE_PACKAGES, "searx", "webutils.py"),
        description="webutils.py (normalize Windows paths)",
        patch_func=patch_webutils_windows_paths,
        severity=PatchSeverity.CRITICAL,
        required_file=True,
        expected_anchors=[
            "file_list.append(str(f.relative_to(static_path)))",
            "result_templates.add(f)",
        ],
        diagnostic_hint="File paths in static and template lookups must use forward slashes on Windows.",
    ),
    PatchSpec(
        name="webapp_json_handler",
        target_path=os.path.join(SITE_PACKAGES, "searx", "webapp.py"),
        description="webapp.py (json_lite handler & Windows loop policy)",
        patch_func=patch_webapp_json_handler,
        severity=PatchSeverity.CRITICAL,
        required_file=True,
        expected_anchors=[
            "output_format == 'json'",
            "WindowsSelectorEventLoopPolicy",
        ],
        diagnostic_hint="Curl_cffi requires WindowsSelectorEventLoopPolicy, and json_lite must be handled in index_error and search output.",
    ),
    PatchSpec(
        name="settings_defaults_json_lite",
        target_path=os.path.join(SITE_PACKAGES, "searx", "settings_defaults.py"),
        description="settings_defaults.py (json_lite format)",
        patch_func=patch_settings_defaults,
        severity=PatchSeverity.FEATURE,
        required_file=True,
        expected_anchors=["OUTPUT_FORMATS"],
        diagnostic_hint="OUTPUT_FORMATS list must include 'json_lite' to allow lightweight agent search output.",
    ),
    PatchSpec(
        name="webutils_json_lite",
        target_path=os.path.join(SITE_PACKAGES, "searx", "webutils.py"),
        description="webutils.py (get_json_lite_response)",
        patch_func=patch_webutils,
        severity=PatchSeverity.FEATURE,
        required_file=True,
        expected_anchors=["def get_themes"],
        diagnostic_hint="Injects get_json_lite_response serializer function into searx/webutils.py.",
    ),
    PatchSpec(
        name="webapp_scrape_route",
        target_path=os.path.join(SITE_PACKAGES, "searx", "webapp.py"),
        description="webapp.py (/scrape endpoint)",
        patch_func=patch_webapp_scrape_route,
        severity=PatchSeverity.FEATURE,
        required_file=True,
        expected_anchors=["def scrape()", "@app.route"],
        diagnostic_hint="Injects /scrape SSRF-protected endpoint for AI coding agents into searx/webapp.py.",
    ),
    PatchSpec(
        name="webapp_ai_webui",
        target_path=os.path.join(SITE_PACKAGES, "searx", "webapp.py"),
        description="webapp.py (AI WebUI & /deep_search integration)",
        patch_func=patch_webapp_ai_webui,
        severity=PatchSeverity.CRITICAL,
        required_file=True,
        expected_anchors=[
            "# --- GenAI Next WebUI Integration ---",
            "_webui_next.register_next_webui(app, sys.modules.get(__name__))",
        ],
        diagnostic_hint="Registers /ai AI Studio and unified search endpoints in searx/webapp.py.",
    ),
    PatchSpec(
        name="online_captcha",
        target_path=os.path.join(SITE_PACKAGES, "searx", "search", "processors", "online.py"),
        description="search/processors/online.py (Retry-After + CAPTCHA logging)",
        patch_func=patch_online_captcha,
        severity=PatchSeverity.FEATURE,
        required_file=True,
        expected_anchors=[
            "_parse_retry_after_header",
            "except SearxEngineCaptchaException",
        ],
        diagnostic_hint="Parses HTTP Retry-After header and logs engine suspension times.",
    ),
    PatchSpec(
        name="raise_for_httperror",
        target_path=os.path.join(SITE_PACKAGES, "searx", "network", "raise_for_httperror.py"),
        description="network/raise_for_httperror.py (attach response for Retry-After)",
        patch_func=patch_raise_for_httperror,
        severity=PatchSeverity.FEATURE,
        required_file=True,
        expected_anchors=["_exc.response = resp"],
        diagnostic_hint="Attaches response object to SearxEngine* exceptions so online.py can inspect Retry-After headers.",
    ),
    PatchSpec(
        name="search_html_accessibility",
        target_path=os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "search.html"),
        description="templates/simple/search.html (accessible search label)",
        patch_func=patch_simple_search_accessibility,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        expected_anchors=['id="q"'],
        diagnostic_hint="Adds aria-label to simple theme primary search input.",
    ),
    PatchSpec(
        name="simple_search_html_accessibility",
        target_path=os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "simple_search.html"),
        description="templates/simple/simple_search.html (accessible search label)",
        patch_func=patch_simple_search_accessibility,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        expected_anchors=['id="q"'],
        diagnostic_hint="Adds aria-label to simple_search.html input.",
    ),
    PatchSpec(
        name="cookies_html_accessibility",
        target_path=os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "preferences", "cookies.html"),
        description="templates/simple/preferences/cookies.html (accessible hash input label)",
        patch_func=patch_preferences_accessibility,
        severity=PatchSeverity.OPTIONAL,
        required_file=False,
        expected_anchors=['id="pref-hash-input"'],
        diagnostic_hint="Adds aria-label to preferences cookies hash input.",
    ),
    PatchSpec(
        name="simple_base_ai_webui",
        target_path=os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "base.html"),
        description="templates/simple/base.html (AI Workspace navigation & embed assets)",
        patch_func=patch_simple_base_ai_webui,
        severity=PatchSeverity.FEATURE,
        required_file=False,
        expected_anchors=['class="link_on_top_ai"'],
        diagnostic_hint="Injects AI Workspace navigation link and embed scripts into base.html.",
    ),
    PatchSpec(
        name="simple_index_ai_webui",
        target_path=os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "index.html"),
        description="templates/simple/index.html (AI Quick Actions bar)",
        patch_func=patch_simple_index_ai_webui,
        severity=PatchSeverity.FEATURE,
        required_file=False,
        expected_anchors=['class="sxng-ai-home-bar"'],
        diagnostic_hint="Injects AI Quick Actions bar into index.html.",
    ),
    PatchSpec(
        name="simple_results_ai_webui",
        target_path=os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "results.html"),
        description="templates/simple/results.html (AI Agent Toolkit bar)",
        patch_func=patch_simple_results_ai_webui,
        severity=PatchSeverity.FEATURE,
        required_file=False,
        expected_anchors=['id="sxng-ai-results-bar"'],
        diagnostic_hint="Injects AI Agent Toolkit bar into results.html.",
    ),
    PatchSpec(
        name="engines_init",
        target_path=os.path.join(SITE_PACKAGES, "searx", "engines", "__init__.py"),
        description="engines/__init__.py (restore disabled-engine behavior)",
        patch_func=patch_engines_init,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        diagnostic_hint="Removes legacy disabled engine short-circuit in engines/__init__.py.",
    ),
    PatchSpec(
        name="engines_fast_load",
        target_path=os.path.join(SITE_PACKAGES, "searx", "engines", "__init__.py"),
        description="engines/__init__.py (fast-path skip inactive & unconfigured onion engines)",
        patch_func=patch_engines_fast_load,
        severity=PatchSeverity.FEATURE,
        required_file=True,
        expected_anchors=[
            "def load_engine",
        ],
        diagnostic_hint="Skips loading inactive modules and unconfigured onion engines to accelerate startup.",
    ),
    PatchSpec(
        name="processors_init",
        target_path=os.path.join(SITE_PACKAGES, "searx", "search", "processors", "__init__.py"),
        description="search/processors/__init__.py (restore disabled-engine behavior)",
        patch_func=patch_processors_init,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        diagnostic_hint="Removes legacy disabled engine skip in search/processors/__init__.py.",
    ),
    PatchSpec(
        name="google_captcha",
        target_path=os.path.join(SITE_PACKAGES, "searx", "engines", "google.py"),
        description="engines/google.py (CAPTCHA false-positive fix)",
        patch_func=patch_google_captcha,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        diagnostic_hint="Mitigates CAPTCHA false positives in google.py 302 redirects.",
    ),
    PatchSpec(
        name="sogou_captcha",
        target_path=os.path.join(SITE_PACKAGES, "searx", "engines", "sogou.py"),
        description="engines/sogou.py (robust CAPTCHA detection)",
        patch_func=patch_sogou_captcha,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        diagnostic_hint="Robust detection of sogou antispider/captcha blocks.",
    ),
    PatchSpec(
        name="abstract_suspend",
        target_path=os.path.join(SITE_PACKAGES, "searx", "search", "processors", "abstract.py"),
        description="search/processors/abstract.py (restore configured suspension times)",
        patch_func=patch_abstract_suspend,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        diagnostic_hint="Removes legacy global cap in abstract.py.",
    ),
    PatchSpec(
        name="settings_yml_suspended_times",
        target_path=os.path.join(SITE_PACKAGES, "searx", "settings.yml"),
        description="searx/settings.yml (reduce suspended_times defaults)",
        patch_func=patch_settings_yml,
        severity=PatchSeverity.OPTIONAL,
        required_file=True,
        diagnostic_hint="Reduces default engine suspension times in searx/settings.yml.",
    ),
    PatchSpec(
        name="config_settings_yml_suspended_times",
        target_path=os.path.join(REPO_ROOT, "config", "settings.yml"),
        description="config/settings.yml (reduce suspended_times)",
        patch_func=patch_config_settings_yml,
        severity=PatchSeverity.OPTIONAL,
        required_file=False,
        diagnostic_hint="Reduces suspension times in user config/settings.yml while preserving custom overrides.",
    ),
    PatchSpec(
        name="preferences_validation",
        target_path=os.path.join(SITE_PACKAGES, "searx", "preferences.py"),
        description="preferences.py (safe category validation & non-fatal parse_dict)",
        patch_func=patch_preferences_validation,
        severity=PatchSeverity.CRITICAL,
        required_file=True,
        expected_anchors=[
            "class MultipleChoiceSetting",
            "def parse_dict",
        ],
        diagnostic_hint="Ensures MultipleChoiceSetting filters valid selections and parse_dict handles ValidationException gracefully.",
    ),
    PatchSpec(
        name="webadapter_categories",
        target_path=os.path.join(SITE_PACKAGES, "searx", "webadapter.py"),
        description="webadapter.py (safe categories lookup)",
        patch_func=patch_webadapter_categories,
        severity=PatchSeverity.CRITICAL,
        required_file=True,
        expected_anchors=[
            "def get_engineref_from_category_list",
        ],
        diagnostic_hint="Safely looks up engine categories using .get() to prevent KeyError on unconfigured categories.",
    ),
    PatchSpec(
        name="webapp_preferences_validation",
        target_path=os.path.join(SITE_PACKAGES, "searx", "webapp.py"),
        description="webapp.py (tab categories in Preferences & safe pre_request)",
        patch_func=patch_webapp_preferences_validation,
        severity=PatchSeverity.CRITICAL,
        required_file=True,
        expected_anchors=[
            "preferences = Preferences",
        ],
        diagnostic_hint="Includes categories_as_tabs in Preferences choices and catches ValidationException gracefully.",
    ),
]


def _format_summary_table(results: list[PatchResult]) -> str:
    """Format patch results into an easy-to-read terminal table."""
    lines = [
        "=" * 72,
        "SearXNG for Windows Next - Patch Application Summary",
        "=" * 72,
    ]
    for r in results:
        status_tag = f"[{r.status}]".ljust(18)
        severity_tag = f"[{r.severity}]".ljust(11)
        lines.append(f"{status_tag} {r.name} {severity_tag}")
    lines.append("=" * 72)
    return "\n".join(lines)


def run_all_patches(
    specs: list[PatchSpec],
    *,
    dry_run: bool = False,
    transaction: PatchTransaction | None = None,
) -> list[PatchResult]:
    """Execute all patch specs in batch mode, capturing diagnostics for every failure."""
    results: list[PatchResult] = []
    for spec in specs:
        res = update_file(
            spec.target_path,
            spec.description,
            spec.patch_func,
            required=spec.required_file,
            severity=spec.severity,
            raise_on_failure=False,
            dry_run=dry_run,
            transaction=transaction,
            expected_anchors=spec.expected_anchors,
            diagnostic_hint=spec.diagnostic_hint,
        )
        if isinstance(res, PatchResult):
            results.append(res)
        else:
            # Fallback wrapper if a raw string was returned
            results.append(
                PatchResult(
                    name=spec.description,
                    target_path=spec.target_path,
                    severity=spec.severity,
                    status=res,
                )
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply Windows compatibility and enhancement patches to SearXNG with enhanced error diagnostics."
    )
    parser.add_argument("--force", action="store_true", help="Ignore cache and re-apply all patches")
    parser.add_argument(
        "--check", "--dry-run", action="store_true", dest="check", help="Verify patches without writing changes"
    )
    parser.add_argument(
        "--strict", action="store_true", help="Treat any patch failure (including optional) as fatal (exit 1)"
    )
    parser.add_argument(
        "--rollback", action="store_true", help="Roll back files to their pre-patch state using stored backups"
    )
    parser.add_argument(
        "--rollback-on-failure", action="store_true", help="Automatically rollback changes if any CRITICAL patch fails"
    )
    parser.add_argument(
        "--report", nargs="?", const=REPORT_FILE, default=None, help="Save JSON diagnostic report to specified file"
    )
    parser.add_argument("--json", action="store_true", help="Output summary in JSON format to stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    transaction = PatchTransaction()

    # Handle manual rollback request
    if args.rollback:
        logger.info("Executing rollback to pre-patch state...")
        restored = transaction.rollback()
        if restored:
            logger.info(f"Successfully rolled back {len(restored)} file(s):\n  " + "\n  ".join(restored))
            return 0
        else:
            logger.warning("No files were rolled back (no backup manifest found or nothing to restore).")
            return 0

    # Fast-path cache check
    if not args.force and not args.check and is_patch_cache_valid():
        logger.info("All patches already verified (cached).")
        return 0

    mode_label = "[DRY-RUN CHECK] " if args.check else ""
    logger.info(f"{mode_label}Applying Windows compatibility and feature patches...")

    # Execute all patches with transaction tracking
    results = run_all_patches(PATCH_SPECS, dry_run=args.check, transaction=transaction)

    # Process missing engines
    engines_dir = os.path.join(SITE_PACKAGES, "searx", "engines")
    if os.path.exists(engines_dir) and not args.check:
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "disable_missing_engines", os.path.join(REPO_ROOT, "tools", "disable-missing-engines.py")
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for cfg_file in (
                    os.path.join(REPO_ROOT, "config", "settings.yml.example"),
                    os.path.join(REPO_ROOT, "config", "settings.yml"),
                    os.path.join(SITE_PACKAGES, "searx", "settings.yml"),
                ):
                    if os.path.exists(cfg_file) and mod.process_file(cfg_file, engines_dir):
                        logger.info(f"Marked missing engines inactive in {cfg_file}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not check missing engines: {exc}")

    # Analyze results
    critical_failures = [r for r in results if r.status == PatchStatus.FAILED and r.severity == PatchSeverity.CRITICAL]
    feature_failures = [r for r in results if r.status == PatchStatus.FAILED and r.severity == PatchSeverity.FEATURE]
    optional_failures = [r for r in results if r.status == PatchStatus.FAILED and r.severity == PatchSeverity.OPTIONAL]
    all_failures = critical_failures + feature_failures + optional_failures

    # Persist backups to disk if there are any failures or if requested
    if not args.check and transaction.originals:
        transaction.persist_backups()

    # Rollback on critical failure if requested
    if critical_failures and args.rollback_on_failure and not args.check:
        logger.warning("CRITICAL patch failure detected and --rollback-on-failure requested. Rolling back changes...")
        restored = transaction.rollback()
        logger.info(f"Rolled back {len(restored)} files to clean state.")

    # Output formatting
    if args.json:
        report_data = {
            "timestamp": time.time(),
            "dry_run": args.check,
            "upstream_info": get_upstream_version_info(),
            "results": [r.to_dict() for r in results],
            "summary": {
                "total": len(results),
                "patched": sum(1 for r in results if r.status == PatchStatus.PATCHED),
                "already_applied": sum(1 for r in results if r.status == PatchStatus.ALREADY_APPLIED),
                "skipped": sum(1 for r in results if r.status == PatchStatus.SKIPPED),
                "failed_critical": len(critical_failures),
                "failed_feature": len(feature_failures),
                "failed_optional": len(optional_failures),
            },
        }
        print(json.dumps(report_data, indent=2))
    else:
        print(_format_summary_table(results))

    # Print detailed diagnostics for failures
    if all_failures:
        print("\n" + "=" * 72)
        print("  PATCH FAILURE DIAGNOSTICS & TROUBLESHOOTING GUIDE")
        print("=" * 72)
        for f in all_failures:
            print(f"\n[!] FAILED: {f.name} ({f.severity})")
            print(f"    Target file: {f.target_path}")
            if f.error_detail:
                print(f"    Error: {f.error_detail}")
            if f.missing_anchors:
                print("    Missing Anchor(s):")
                for ma in f.missing_anchors:
                    print(f"      - {ma.strip()[:100]}")
            if f.suggestions:
                print("    Diagnostic Details & Recommendations:")
                for s in f.suggestions:
                    print(f"      * {s}")
        print("=" * 72 + "\n")

    # Save diagnostic report file if requested or if any failures occurred
    report_path = args.report or (REPORT_FILE if all_failures else None)
    if report_path:
        try:
            report_data = {
                "timestamp": time.time(),
                "dry_run": args.check,
                "upstream_info": get_upstream_version_info(),
                "results": [r.to_dict() for r in results],
                "failures": [f.to_dict() for f in all_failures],
            }
            _atomic_write(report_path, json.dumps(report_data, indent=2), encoding="utf-8")
            logger.info(f"Saved diagnostic report to: {report_path}")
        except OSError as exc:
            logger.warning(f"Could not save diagnostic report: {exc}")

    # Determine exit code and cache update
    if not all_failures and not args.check:
        logger.info("All patches processed successfully.")
        save_patch_cache()
        transaction.cleanup()
        return 0

    if critical_failures:
        logger.error(
            f"CRITICAL PATCH FAILURE: {len(critical_failures)} essential Windows patch(es) failed! "
            "SearXNG server will likely fail to start on Windows."
        )
        return 1

    if (feature_failures or optional_failures) and args.strict:
        logger.error(f"Patch verification failed under --strict: {len(all_failures)} failure(s).")
        return 1

    if feature_failures or optional_failures:
        logger.warning(
            f"Non-critical patch notice: {len(feature_failures)} feature and {len(optional_failures)} "
            "optional patch(es) failed. Server can run, but some features or tweaks are inactive."
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
