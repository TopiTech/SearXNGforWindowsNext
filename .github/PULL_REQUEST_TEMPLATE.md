## Description

<!-- Describe the changes made and the motivation/context behind them. -->

## Type of Change

- [ ] 🐛 Bug fix (non-breaking change fixing an issue)
- [ ] ✨ New feature (non-breaking change adding functionality)
- [ ] 🔧 Compatibility patch (modifications to `tools/apply-patches.py`)
- [ ] 📝 Documentation update
- [ ] 🧪 Tests / CI improvement
- [ ] ⚡ Performance optimization

## Checklist

- [ ] My code follows the code style and guidelines of this project.
- [ ] If changing SearXNG core code, changes are codified as idempotent patches in `tools/apply-patches.py`.
- [ ] I have verified `python tools/apply-patches.py --check` passes.
- [ ] I have run tests via `.\tools\run-tests.ps1` (or individual test suites) and all pass.
- [ ] I have not committed any secret keys, credentials, or personal local paths (`config/secret.key`, `config/settings.yml`, `.env`, etc.).
- [ ] My changes are cross-platform friendly and respect Windows CRLF/LF line endings.
