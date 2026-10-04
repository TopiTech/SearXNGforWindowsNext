# Windows Compatibility & Custom Patches

This document outlines the patching architecture, policies, and list of compatibility patches maintained in SearXNG for Windows Next.

---

## 🎯 Purpose and Architecture

SearXNG upstream (`searxng/searxng`) is primarily developed for Linux/POSIX container environments. Running on Windows natively without Docker requires specific adaptations:
1. **POSIX Module Bypasses**: Substituting Unix-specific calls (`pwd`, `os.getuid`, etc.) with cross-platform fallbacks.
2. **Network & Concurrency Adjustments**: Windows-specific socket error codes (`WSAECONNRESET`, `WSAETIMEDOUT`), DNS pinning, and asyncio loop policies.
3. **GenAI Features**: Dedicated endpoints (`/api/retrieval`, `/deep_search`, `/scrape`, `json_lite`, `json_ai`) and dedicated AI Search & Context Studio UI (`/`).

All modifications to upstream files are codified as **idempotent, atomic Python patches** in [`tools/apply-patches.py`](../tools/apply-patches.py). This ensures that upstream updates can be pulled cleanly without losing custom functionality.

---

## 🛡️ Source of Truth & Upstream Sync

- **Upstream Source**: `searxng/searxng` (official upstream)
- **Base Fork**: `mbaozi/SearXNGforWindows`
- **Sync Script**: `tools/sync-upstream.ps1` and GitHub Actions workflow `.github/workflows/upstream-sync.yml`
- **Tracked Version**: Resolved upstream commit SHA is stored in `UPSTREAM_VERSION.txt`.

### Upstream Sync Workflow

1. Fetch latest commits from `searxng/searxng` (or target ref).
2. Update `python/Lib/site-packages/searx` and related requirements.
3. Run `python tools/apply-patches.py` to re-apply all patches.
4. Run `tools/run-tests.ps1` to verify syntax and functionality.
5. Record the new commit SHA in `UPSTREAM_VERSION.txt`.

---

## 📋 Managed Patch Categories

| Severity | Description | Examples |
|---|---|---|
| **CRITICAL** | Required for server startup on Windows | `valkeydb_pwd` (replaces Unix `pwd`), `metrics_null` |
| **FEATURE** | GenAI retrieval features & AI-First UI | `webapp_ai_webui` (dedicated `/` UI), `/scrape`, `json_lite`, `json_ai` |
| **OPTIONAL** | Engine optimizations & default tuning | Default engine timeouts, retry headers, Windows file paths |

---

## 🛠️ Verification & Patch Commands

```powershell
# Check patch status without modifying files
python tools/apply-patches.py --check

# Apply all patches with automated backup
python tools/apply-patches.py

# Revert patches using backups
python tools/apply-patches.py --revert

# Run test suite for patch idempotency and regression
python tools/test_patches.py
```