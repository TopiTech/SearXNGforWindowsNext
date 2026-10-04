# Contributing to SearXNG for Windows Next 🤝

Thank you for your interest in contributing to **SearXNG for Windows Next**!

This project provides an optimized, native Windows distribution of SearXNG with embedded Python and specialized GenAI retrieval enhancements. Because this project bridges upstream Linux code with Windows-native execution, we follow specific development and contribution practices.

---

## 🧭 Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md) in all project interactions.

---

## 🛠️ Development Setup

### Prerequisites

- **Windows 10 / 11** or **Windows Server 2019+** (x64)
- **Git for Windows**
- **PowerShell 5.1+** or **PowerShell Core 7+**

### Initial Setup

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/TopiTech/SearXNGforWindowsNext.git
   cd SearXNGforWindowsNext
   ```

2. **Install runtime and development dependencies:**
   ```powershell
   .\tools\install-requirements.ps1 -Dev
   ```

3. **Verify patches and startup:**
   ```powershell
   # Check patch status
   .\python\python.exe tools/apply-patches.py --check

   # Run test suite
   .\tools\run-tests.ps1
   ```

---

## 🧩 Modifying SearXNG (The Patching System)

**CRITICAL RULE:** Do NOT directly commit manual edits to `python/Lib/site-packages/searx/` without a corresponding patch!

SearXNG for Windows Next automatically synchronizes with upstream `searxng/searxng`. Direct changes to `searx/` will be overwritten during sync.

All modifications to SearXNG core must be registered as **idempotent, atomic patches** in [`tools/apply-patches.py`](tools/apply-patches.py).

### How to Add or Update a Patch:
1. Open [`tools/apply-patches.py`](tools/apply-patches.py).
2. Define a patch function or regex substitution under the appropriate severity (`CRITICAL`, `FEATURE`, or `OPTIONAL`).
3. Ensure the patch is **idempotent** (running it twice produces the same result and returns `PatchStatus.ALREADY_APPLIED`).
4. Add unit test coverage in [`tools/test_patches.py`](tools/test_patches.py).
5. Verify with:
   ```powershell
   .\python\python.exe tools/test_patches.py
   .\python\python.exe tools/apply-patches.py --check
   ```
For more details, see [docs/WINDOWS_PATCHES.md](docs/WINDOWS_PATCHES.md).

---

## 🧪 Testing Guidelines

Before opening a pull request, verify that all test suites pass:

```powershell
# 1. Full test runner (installs deps, checks syntax, executes all test suites)
.\tools\run-tests.ps1

# 2. Individual test suites (if needed)
.\python\python.exe tools/test_patches.py
.\python\python.exe tools/test_agent_tools.py
.\python\python.exe tools/test_agentic_search.py

# 3. Code formatting and linting
.\python\python.exe -m ruff check .
.\python\python.exe -m ruff format --check .
```

---

## 🔒 Security Best Practices

- **Never commit `config/secret.key` or `config/settings.yml`**: These files are gitignored. The server auto-generates secret keys using [`tools/ensure-secret-key.py`](tools/ensure-secret-key.py).
- **Maintain SSRF Protections**: All outbound network requests (e.g., in `/scrape` or `/api/retrieval`) must pass IP/host validation against loopback, private RFC 1918 ranges, and DNS rebinding attacks.
- See [SECURITY.md](SECURITY.md) for full security requirements.

---

## 📝 Pull Request Workflow

1. Fork the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes adhering to code style and patch guidelines.
3. Commit with concise, descriptive commit messages (following Conventional Commits, e.g. `feat:`, `fix:`, `docs:`, `test:`).
4. Push your branch to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
5. Open a Pull Request against `main`. Fill in the PR template completely.

Thank you for helping improve SearXNG for Windows Next!
