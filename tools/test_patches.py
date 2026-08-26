"""Unit tests for the Windows patch tool (apply-patches.py).

These tests run the pure-string patch functions against fake file contents so
they can be exercised without a live searx install or any network access.

Usage:
    python tools/test_patches.py
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

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
    """Tests for the per-install secret_key provider.

    The script used to rotate secret_key inside config/settings.yml on every
    run, polluting git history. It now writes the key to a gitignored file
    (config/secret.key) and only prints a single ``set SEARXNG_SECRET=...``
    line on stdout that the launcher captures.
    """

    def setUp(self):
        self.fn = ensure_secret_key  # alias for readability
        self._tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)

    def _make_paths(self, with_key=None, with_settings=True):
        config_dir = os.path.join(self._tmpdir, "config")
        os.makedirs(config_dir, exist_ok=True)
        secret_path = os.path.join(config_dir, "secret.key")
        settings_path = os.path.join(config_dir, "settings.yml")
        example_path = os.path.join(config_dir, "settings.yml.example")
        if with_settings:
            with open(settings_path, "w", encoding="utf-8") as f:
                f.write("secret_key: 'ultrasecretkey'\n")
        with open(example_path, "w", encoding="utf-8") as f:
            f.write("secret_key: 'ultrasecretkey'\n")
        if with_key is not None:
            with open(secret_path, "w", encoding="utf-8") as f:
                f.write(with_key + "\n")
        return secret_path, settings_path, example_path

    def test_read_key_returns_none_when_missing(self):
        secret_path, _, _ = self._make_paths(with_key=None)
        self.assertIsNone(self.fn._read_key(secret_path))

    def test_read_key_strips_whitespace(self):
        secret_path, _, _ = self._make_paths(with_key="  abc123  \n")
        self.assertEqual(self.fn._read_key(secret_path), "abc123")

    def test_read_key_treats_empty_file_as_missing(self):
        secret_path, _, _ = self._make_paths(with_key="   \n")
        self.assertIsNone(self.fn._read_key(secret_path))

    def test_write_key_creates_file_with_key(self):
        secret_path, _, _ = self._make_paths()
        ok = self.fn._write_key(secret_path, "deadbeef" * 8)
        self.assertTrue(ok)
        with open(secret_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "deadbeef" * 8)
        self.assertFalse(os.path.exists(secret_path + ".tmp"))

    def test_write_key_is_atomic_when_target_locked(self):
        # Simulate a previous run that left a stale .tmp behind; _write_key
        # must still succeed and leave only the final file.
        secret_path, _, _ = self._make_paths()
        with open(secret_path + ".tmp", "w", encoding="utf-8") as f:
            f.write("stale")
        ok = self.fn._write_key(secret_path, "feca" * 16)
        self.assertTrue(ok)
        with open(secret_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "feca" * 16)
        self.assertFalse(os.path.exists(secret_path + ".tmp"))

    def test_generate_key_has_sufficient_entropy(self):
        self.assertGreaterEqual(len(self.fn._generate_key()), 64)
        # token_hex(32) only emits [0-9a-f]
        self.assertRegex(self.fn._generate_key(), r"^[0-9a-f]{64}$")
        # Two draws must differ.
        self.assertNotEqual(self.fn._generate_key(), self.fn._generate_key())

    def test_ensure_settings_seeds_when_missing(self):
        secret_path, settings_path, example_path = self._make_paths()
        os.remove(settings_path)
        # Patch the module-level paths to point at our tempdir.
        with mock.patch.object(self.fn, "SETTINGS_PATH", settings_path), \
             mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path):
            self.fn._ensure_settings_file()
        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertIn("ultrasecretkey", f.read())

    def test_ensure_settings_preserves_existing(self):
        secret_path, settings_path, example_path = self._make_paths()
        sentinel = "# user-custom-marker\n"
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(sentinel)
        with mock.patch.object(self.fn, "SETTINGS_PATH", settings_path), \
             mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path):
            self.fn._ensure_settings_file()
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertIn(sentinel, f.read())

    def test_main_reuses_existing_valid_key(self):
        secret_path, settings_path, example_path = self._make_paths(
            with_key="a" * 64
        )
        with mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path), \
             mock.patch.object(self.fn, "SETTINGS_PATH", settings_path), \
             mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path):
            with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                rc = self.fn.main()
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), f"set SEARXNG_SECRET={'a' * 64}")
        # The file must be untouched (no rewrite).
        with open(secret_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "a" * 64)

    def test_main_generates_when_secret_file_missing(self):
        secret_path, settings_path, example_path = self._make_paths()
        self.assertFalse(os.path.exists(secret_path))
        with mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path), \
             mock.patch.object(self.fn, "SETTINGS_PATH", settings_path), \
             mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path):
            with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                rc = self.fn.main()
        self.assertEqual(rc, 0)
        line = out.getvalue().strip()
        self.assertTrue(line.startswith("set SEARXNG_SECRET="))
        key = line.split("=", 1)[1]
        self.assertGreaterEqual(len(key), 64)
        self.assertTrue(os.path.exists(secret_path))

    def test_main_rotates_short_existing_key(self):
        # A key shorter than MIN_KEY_LEN is treated as invalid and replaced.
        secret_path, settings_path, example_path = self._make_paths(
            with_key="short"
        )
        with mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path), \
             mock.patch.object(self.fn, "SETTINGS_PATH", settings_path), \
             mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path):
            with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                rc = self.fn.main()
        self.assertEqual(rc, 0)
        line = out.getvalue().strip()
        self.assertTrue(line.startswith("set SEARXNG_SECRET="))
        new_key = line.split("=", 1)[1]
        self.assertNotEqual(new_key, "short")
        with open(secret_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), new_key)

    def test_main_does_not_touch_settings_yml(self):
        # Regression: the old design wrote to config/settings.yml, which is
        # git-tracked. The new design must leave the settings file alone.
        secret_path, settings_path, example_path = self._make_paths(
            with_key="a" * 64
        )
        original_mtime = os.path.getmtime(settings_path)
        with mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path), \
             mock.patch.object(self.fn, "SETTINGS_PATH", settings_path), \
             mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path):
            self.fn.main()
        self.assertEqual(os.path.getmtime(settings_path), original_mtime)


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
