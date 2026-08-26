"""Unit tests for the Windows patch tool (apply-patches.py).

These tests run the pure-string patch functions against fake file contents so
they can be exercised without a live searx install or any network access.

Usage:
    python tools/test_patches.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import importlib.util  # noqa: E402

# Both apply-patches.py and ensure-secret-key.py have hyphens in their file
# names, which prevents plain `import` statements. Load them via importlib.
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply_patches = _load("apply_patches", os.path.join(HERE, "apply-patches.py"))
ensure_secret_key = _load("ensure_secret_key", os.path.join(HERE, "ensure-secret-key.py"))


class TestEnsureSecretKey(unittest.TestCase):
    """Tests for the secret_key detection helper."""

    def setUp(self):
        self.fn = ensure_secret_key  # alias for readability

    def test_get_current_secret_handles_quoted_and_unquoted(self):
        self.assertEqual(
            self.fn.get_current_secret('secret_key: "abc123"'),
            "abc123",
        )
        self.assertEqual(
            self.fn.get_current_secret("secret_key: 'xyz'"),
            "xyz",
        )
        self.assertIsNone(self.fn.get_current_secret("# nothing here"))
        self.assertIsNone(self.fn.get_current_secret(""))

    def test_rotate_secret_replaces_known_value(self):
        content = 'secret_key: "old-value"\n'
        new_content, rotated = self.fn.rotate_secret(content, "old-value", reason="test")
        self.assertTrue(rotated)
        self.assertNotIn("old-value", new_content)
        self.assertIn("secret_key:", new_content)

    def test_rotate_secret_no_match_returns_unchanged(self):
        content = 'secret_key: "current"\n'
        new_content, rotated = self.fn.rotate_secret(content, "different", reason="test")
        self.assertFalse(rotated)
        self.assertEqual(new_content, content)

    def test_get_committed_secrets_handles_no_git(self):
        # Should not raise even when .git is missing.
        secrets = self.fn.get_committed_secrets_from_git()
        self.assertIsInstance(secrets, set)


class TestPatchValKeyDB(unittest.TestCase):
    """Verify the valkeydb.py idempotency markers."""

    def setUp(self):
        self.fn = apply_patches.patch_valkeydb

    def test_already_applied_marker(self):
        content = (
            "try:\n    import pwd  # Unix only\nexcept ImportError:\n    pwd = None\n"
            "\n\n"
            "def _windows_safe_current_user():\n    return 'x', -1\n"
            "\n"
            "def initialize():\n"
            "    _user_name, _user_uid = _windows_safe_current_user()\n"
        )
        result = self.fn(content, "valkeydb.py")
        self.assertEqual(result, "ALREADY_APPLIED")


class TestPatchSettingsDefaults(unittest.TestCase):
    """Verify settings_defaults.py json_lite registration."""

    def setUp(self):
        self.fn = apply_patches.patch_settings_defaults

    def test_already_applied_when_present(self):
        content = "OUTPUT_FORMATS = ['html', 'json', 'json_lite']"
        self.assertEqual(self.fn(content, "settings_defaults.py"), "ALREADY_APPLIED")

    def test_appends_json_lite_when_json_present(self):
        content = "OUTPUT_FORMATS = ['html', 'json']"
        result = self.fn(content, "settings_defaults.py")
        self.assertIn("'json_lite'", result)
        self.assertIn("'json'", result)

    def test_handles_multiline_list(self):
        content = "OUTPUT_FORMATS = [\n    'html',\n    'json',\n]\n"
        result = self.fn(content, "settings_defaults.py")
        self.assertIn("'json_lite'", result)


class TestPatchWebUtils(unittest.TestCase):
    """Verify webutils.py get_json_lite_response insertion."""

    def setUp(self):
        self.fn = apply_patches.patch_webutils

    def test_already_applied_when_canonical_form_present(self):
        # The canonical injected function references the 'score' key and the
        # `_get_box` nested helper. Both must be present for the idempotency
        # check to fire.
        content = (
            "def get_json_lite_response(sq, rc):\n"
            "    # 'score': d.get('score', 0)\n"
            "    def _get_box(i):\n        pass\n"
        )
        self.assertEqual(self.fn(content, "webutils.py"), "ALREADY_APPLIED")

    def test_inserts_function_before_get_themes(self):
        content = "def get_themes(p):\n    return []\n"
        result = self.fn(content, "webutils.py")
        self.assertIn("def get_json_lite_response", result)
        idx_func = result.index("def get_json_lite_response")
        idx_themes = result.index("def get_themes")
        self.assertLess(idx_func, idx_themes)


class TestPatchEnginesInit(unittest.TestCase):
    """Verify engines/__init__.py patching logic."""

    def setUp(self):
        self.fn = apply_patches.patch_engines_init

    def _sample_content(self, *, with_engine_block=False, with_engines_block=False,
                       with_legacy_dup=False):
        lines = [
            "def load_engine(engine_data):",
            "    if engine_name.lower() != engine_name:",
            "        engine_name = engine_name.lower()",
            "        engine_data['name'] = engine_name",
            "",
            "def load_engines(engine_list):",
            "    for engine_data in engine_list:",
        ]
        if with_legacy_dup:
            lines.append("        if engine_data.get('inactive') is True:")
            lines.append("            continue")
        if with_engine_block:
            lines.append("    # Early return for engines that are intentionally disabled or inactive in config.")
            lines.append("    if engine_data.get('inactive') is True:")
            lines.append("        logger.debug('skipping load', engine_name)")
            lines.append("        return None")
            lines.append("    if engine_data.get('disabled') is True:")
            lines.append("        logger.debug('skipping load', engine_name)")
            lines.append("        return None")
        if with_engines_block:
            lines.append("        if engine_data.get(\"inactive\") is True or engine_data.get(\"disabled\") is True:")
            lines.append("            logger.debug(\"inactive or disabled in config!\")")
            lines.append("            continue")
        return "\n".join(lines) + "\n"

    def test_already_applied_clean_state(self):
        content = self._sample_content(with_engine_block=True, with_engines_block=True)
        result = self.fn(content, "engines/__init__.py")
        self.assertEqual(result, "ALREADY_APPLIED")

    def test_re_patches_when_legacy_duplicate_present(self):
        # The legacy duplicate is the narrow `inactive is True: continue` from
        # the upstream code, which our combined check subsumes.
        content = self._sample_content(
            with_engine_block=True,
            with_engines_block=True,
            with_legacy_dup=True,
        )
        result = self.fn(content, "engines/__init__.py")
        self.assertNotEqual(result, "ALREADY_APPLIED")
        self.assertIn("intentionally disabled or inactive in config.", result)


class TestPatchSettingsYml(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_settings_yml

    def test_replaces_known_long_values(self):
        content = (
            "SearxEngineCaptcha: 86400\n"
            "SearxEngineAccessDenied: 86400\n"
            "SearxEngineTooManyRequests: 3600\n"
        )
        result = self.fn(content, "settings.yml")
        self.assertIn("SearxEngineCaptcha: 900", result)
        self.assertIn("SearxEngineAccessDenied: 900", result)
        self.assertIn("SearxEngineTooManyRequests: 600", result)

    def test_idempotent_when_already_reduced(self):
        content = "SearxEngineCaptcha: 900\n"
        self.assertEqual(self.fn(content, "settings.yml"), "ALREADY_APPLIED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
