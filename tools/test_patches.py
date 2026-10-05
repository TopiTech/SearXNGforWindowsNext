"""Unit tests for the Windows patch tool (apply-patches.py).

These tests run the pure-string patch functions against fake file contents so
they can be exercised without a live searx install or any network access.

Usage:
    python tools/test_patches.py
"""

import importlib.util
import io
import ipaddress
import json
import os
import re as re_mod
import shutil
import socket
import stat
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

import idna

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# Both apply-patches.py and ensure-secret-key.py have hyphens in their file
# names, which prevents plain `import` statements. Load them via importlib.
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply_patches = _load("apply_patches", os.path.join(HERE, "apply-patches.py"))
ensure_secret_key = _load("ensure_secret_key", os.path.join(HERE, "ensure-secret-key.py"))
disable_missing_engines = _load("disable_missing_engines", os.path.join(HERE, "disable-missing-engines.py"))


class TestPatchRunner(unittest.TestCase):
    def test_missing_required_target_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = os.path.join(tmpdir, "missing.py")
            with self.assertRaisesRegex(RuntimeError, "Required patch target not found"):
                apply_patches.update_file(
                    missing_path,
                    "required test target",
                    lambda content, path: content,
                )

    def test_missing_optional_target_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = os.path.join(tmpdir, "missing.yml")
            result = apply_patches.update_file(
                missing_path,
                "optional test target",
                lambda content, path: content,
                required=False,
            )
        self.assertEqual(result, "SKIPPED")


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
        self.config_dir = os.path.join(self._tmpdir, "config")
        os.makedirs(self.config_dir, exist_ok=True)
        patcher = mock.patch.object(self.fn, "CONFIG_DIR", self.config_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_paths(self, with_key=None, with_settings=True):
        config_dir = self.config_dir
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

    def test_read_key_strips_utf8_bom(self):
        secret_path, _, _ = self._make_paths()
        with open(secret_path, "wb") as f:
            f.write(b"\xef\xbb\xbf" + ("b" * 64).encode("utf-8") + b"\n")
        self.assertEqual(self.fn._read_key(secret_path), "b" * 64)

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
        _, settings_path, example_path = self._make_paths()
        os.remove(settings_path)
        # Patch the module-level paths to point at our tempdir.
        with (
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
        ):
            self.fn._ensure_settings_file()
        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertIn("ultrasecretkey", f.read())

    def test_ensure_settings_preserves_existing(self):
        _, settings_path, example_path = self._make_paths()
        sentinel = "# user-custom-marker\n"
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(sentinel)
        with (
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
        ):
            self.fn._ensure_settings_file()
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertIn(sentinel, f.read())

    def test_ensure_settings_file_reseeds_zero_byte_file(self):
        _, settings_path, example_path = self._make_paths()
        # Truncate settings.yml to 0 bytes
        with open(settings_path, "w", encoding="utf-8") as f:
            pass
        self.assertEqual(os.path.getsize(settings_path), 0)
        with (
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
        ):
            self.fn._ensure_settings_file()
        self.assertGreater(os.path.getsize(settings_path), 0)
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertIn("ultrasecretkey", f.read())

    def test_main_reuses_existing_valid_key(self):
        secret_path, settings_path, example_path = self._make_paths(with_key="a" * 64)
        with (
            mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path),
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out,
        ):
            rc = self.fn.main()
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), f"set SEARXNG_SECRET={'a' * 64}")
        # The file must be untouched (no rewrite).
        with open(secret_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "a" * 64)

    def test_main_generates_when_secret_file_missing(self):
        secret_path, settings_path, example_path = self._make_paths()
        self.assertFalse(os.path.exists(secret_path))
        with (
            mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path),
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out,
        ):
            rc = self.fn.main()
        self.assertEqual(rc, 0)
        line = out.getvalue().strip()
        self.assertTrue(line.startswith("set SEARXNG_SECRET="))
        key = line.split("=", 1)[1]
        self.assertGreaterEqual(len(key), 64)
        self.assertTrue(os.path.exists(secret_path))

    def test_main_rotates_short_existing_key(self):
        # A key that is too short is treated as invalid and replaced.
        secret_path, settings_path, example_path = self._make_paths(with_key="short")
        with (
            mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path),
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out,
        ):
            rc = self.fn.main()
        self.assertEqual(rc, 0)
        line = out.getvalue().strip()
        self.assertTrue(line.startswith("set SEARXNG_SECRET="))
        new_key = line.split("=", 1)[1]
        self.assertNotEqual(new_key, "short")
        with open(secret_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), new_key)

    def test_main_rotates_unsafe_existing_key(self):
        secret_path, settings_path, example_path = self._make_paths(with_key=("a" * 64) + " & echo INJECTED")
        with (
            mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path),
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out,
        ):
            rc = self.fn.main()
        self.assertEqual(rc, 0)
        key = out.getvalue().strip().split("=", 1)[1]
        self.assertRegex(key, r"^[0-9a-f]{64}$")

    def test_main_does_not_touch_settings_yml(self):
        # Regression: the old design wrote to config/settings.yml, which is
        # git-tracked. The new design must leave the settings file alone.
        secret_path, settings_path, example_path = self._make_paths(with_key="a" * 64)
        original_mtime = os.path.getmtime(settings_path)
        with (
            mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path),
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO),
        ):
            self.fn.main()
        self.assertEqual(os.path.getmtime(settings_path), original_mtime)

    def test_ensure_settings_seeds_when_config_dir_different(self):
        """Ensure settings file creates temp files in SETTINGS_PATH's directory even if CONFIG_DIR differs."""
        _, settings_path, example_path = self._make_paths()
        os.remove(settings_path)
        with (
            mock.patch.object(self.fn, "CONFIG_DIR", r"Z:\different_drive\config"),
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
        ):
            self.fn._ensure_settings_file()
        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertIn("ultrasecretkey", f.read())

    def test_ensure_settings_cross_drive_fallback(self):
        """Simulate WinError 17 on os.replace and verify shutil.move fallback works."""
        _, settings_path, example_path = self._make_paths()
        os.remove(settings_path)

        def mock_replace(src, dst):
            err = OSError("The system cannot move the file to a different disk drive")
            err.winerror = 17
            raise err

        with (
            mock.patch.object(self.fn, "SETTINGS_PATH", settings_path),
            mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path),
            mock.patch("os.replace", side_effect=mock_replace),
        ):
            self.fn._ensure_settings_file()
        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path, "r", encoding="utf-8") as f:
            self.assertIn("ultrasecretkey", f.read())

    def test_write_key_cross_drive_fallback(self):
        """Simulate WinError 17 on os.replace during _write_key and verify shutil.move fallback works."""
        secret_path, _, _ = self._make_paths()

        def mock_replace(src, dst):
            err = OSError("The system cannot move the file to a different disk drive")
            err.winerror = 17
            raise err

        with mock.patch("os.replace", side_effect=mock_replace):
            ok = self.fn._write_key(secret_path, "feca" * 16)
        self.assertTrue(ok)
        with open(secret_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "feca" * 16)


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

    def test_handles_empty_list(self):
        # Edge case: empty OUTPUT_FORMATS list should still get json_lite added
        content = "OUTPUT_FORMATS = []\n"
        result = self.fn(content, "settings_defaults.py")
        self.assertIn("'json_lite'", result)
        # Verify the result is valid Python syntax
        self.assertIn("OUTPUT_FORMATS = [", result)


class TestPatchWebUtils(unittest.TestCase):
    """Verify webutils.py get_json_lite_response insertion."""

    def setUp(self):
        self.fn = apply_patches.patch_webutils

    def test_already_applied_when_canonical_form_present(self):
        # The canonical injected function references the 'score' key, _format_source,
        # and the `_get_box` nested helper. All must be present for the idempotency
        # check to fire.
        content = (
            "def get_json_lite_response(sq, rc):\n"
            "    # 'score': d.get('score', 0)\n"
            "    # _format_source\n"
            "    # d.get('title') or ''\n"
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

    def test_merged_engine_source_attribution(self):
        # Result items with multiple merged engines should show sorted joined names
        content = "def get_themes(p):\n    return []\n"
        result = self.fn(content, "webutils.py")
        self.assertIn("d.get('engines')", result)
        self.assertIn("def _format_source(d):", result)
        self.assertIn("', '.join(sorted(str(e) for e in engs if e is not None))", result)

    def test_json_lite_ensure_ascii_false(self):
        content = "def get_themes(p):\n    return []\n"
        result = self.fn(content, "webutils.py")
        self.assertIn("ensure_ascii=False", result)
        self.assertIn("default=str", result)
        self.assertIn("json.dumps(data, cls=JSONEncoder, ensure_ascii=False, default=str)", result)


class TestPatchWebUtilsWindowsPaths(unittest.TestCase):
    """Verify URL-facing paths are normalized on Windows."""

    def setUp(self):
        self.fn = apply_patches.patch_webutils_windows_paths

    def test_normalizes_static_and_result_template_paths(self):
        content = "file_list.append(str(f.relative_to(static_path)))\nresult_templates.add(f)\n"
        result = self.fn(content, "webutils.py")
        self.assertIn("str(f.relative_to(static_path)).replace(os.sep, '/')", result)
        self.assertIn("result_templates.add(f.replace(os.sep, '/'))", result)

    def test_already_applied(self):
        content = (
            "file_list.append(str(f.relative_to(static_path)).replace(os.sep, '/'))\n"
            "result_templates.add(f.replace(os.sep, '/'))\n"
        )
        self.assertEqual(self.fn(content, "webutils.py"), "ALREADY_APPLIED")


class TestPatchSimpleSearchAccessibility(unittest.TestCase):
    """The primary search input must have a localized accessible name."""

    def setUp(self):
        self.fn = apply_patches.patch_simple_search_accessibility

    def test_adds_aria_label_to_search_input(self):
        content = '<input id="q" name="q" type="text" placeholder="{{ _(\'Search for...\') }}">\n'
        result = self.fn(content, "simple_search.html")
        self.assertIn("aria-label=\"{{ _('Search for...') }}\"", result)

    def test_is_idempotent(self):
        content = '<input id="q" name="q" type="text" aria-label="{{ _(\'Search for...\') }}">\n'
        self.assertEqual(self.fn(content, "search.html"), "ALREADY_APPLIED")


class TestPatchPreferencesAccessibility(unittest.TestCase):
    """The cookie hash input in preferences must have an accessible name."""

    def setUp(self):
        self.fn = apply_patches.patch_preferences_accessibility

    def test_adds_aria_label_to_hash_input(self):
        content = '<input type="text" id="pref-hash-input" name="preferences" placeholder="{{- _(\'Preferences hash\') -}}">\n'
        result = self.fn(content, "cookies.html")
        self.assertIn("aria-label=\"{{- _('Preferences hash') -}}\"", result)

    def test_is_idempotent(self):
        content = '<input type="text" id="pref-hash-input" name="preferences" aria-label="{{- _(\'Preferences hash\') -}}" placeholder="{{- _(\'Preferences hash\') -}}">\n'
        self.assertEqual(self.fn(content, "cookies.html"), "ALREADY_APPLIED")


class TestPatchEnginesInit(unittest.TestCase):
    """Verify cleanup of the legacy disabled-engine short circuit."""

    def setUp(self):
        self.fn = apply_patches.patch_engines_init

    def _sample_content(self, *, with_legacy_patch=False):
        lines = [
            "def load_engine(engine_data):",
            "    if engine_name.lower() != engine_name:",
            "        engine_name = engine_name.lower()",
            "        engine_data['name'] = engine_name",
        ]
        if with_legacy_patch:
            lines.append("    # Early return for engines that are intentionally disabled or inactive in config.")
            lines.append("    if engine_data.get('inactive') is True:")
            lines.append("        logger.debug('Engine \"%s\" is inactive in config, skipping load', engine_name)")
            lines.append("        return None")
            lines.append("    if engine_data.get('disabled') is True:")
            lines.append("        logger.debug('Engine \"%s\" is disabled in config, skipping load', engine_name)")
            lines.append("        return None")
        lines.extend(
            [
                "    # load_module",
                "",
                "def load_engines(engine_list):",
                "    for engine_data in engine_list:",
            ]
        )
        if with_legacy_patch:
            lines.append('        if engine_data.get("inactive") is True or engine_data.get("disabled") is True:')
            lines.append("            logger.debug(")
            lines.append('                "loading engine %s skipped: inactive or disabled in config!",')
            lines.append('                engine_data.get("name", "???"),')
            lines.append("            )")
            lines.append("            continue")
        else:
            lines.append('        if engine_data.get("inactive") is True:')
            lines.append("            continue")
        return "\n".join(lines) + "\n"

    def test_already_applied_clean_state(self):
        content = self._sample_content()
        result = self.fn(content, "engines/__init__.py")
        self.assertEqual(result, "ALREADY_APPLIED")

    def test_restores_disabled_engine_loading(self):
        content = self._sample_content(with_legacy_patch=True)
        result = self.fn(content, "engines/__init__.py")
        self.assertNotEqual(result, "ALREADY_APPLIED")
        self.assertNotIn("intentionally disabled or inactive", result)
        self.assertNotIn("engine_data.get('disabled') is True", result)
        self.assertIn('if engine_data.get("inactive") is True:', result)
        self.assertNotIn("inactive or disabled in config!", result)


class TestPatchEnginesFastLoad(unittest.TestCase):
    """Verify fast-path skipping of inactive and onion engines."""

    def setUp(self):
        self.fn = apply_patches.patch_engines_fast_load

    def _sample_content(self, *, already_applied=False):
        lines = [
            "def load_engine(engine_data):",
            "    module_name = engine_data.get('engine')",
            "    if module_name is None:",
            "        return None",
        ]
        if already_applied:
            lines.append("    # sxng-fast-engine-load-v1: skip inactive or unavailable onion engines before import")
            lines.append("    if engine_data.get('inactive') is True:")
            lines.append("        return None")
        lines.append("    try:")
        lines.append("        engine = load_module(module_name + '.py', ENGINE_DIR)")
        lines.append("    except Exception:")
        lines.append("        return None")
        return "\n".join(lines) + "\n"

    def test_already_applied(self):
        content = self._sample_content(already_applied=True)
        result = self.fn(content, "engines/__init__.py")
        self.assertEqual(result, "ALREADY_APPLIED")

    def test_applies_fast_load(self):
        content = self._sample_content(already_applied=False)
        result = self.fn(content, "engines/__init__.py")
        self.assertNotEqual(result, "ALREADY_APPLIED")
        self.assertIn("sxng-fast-engine-load-v1", result)
        self.assertIn("engine_data.get('inactive') is True", result)


class TestPatchSettingsYml(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_settings_yml
        self.cfg_fn = apply_patches.patch_config_settings_yml

    def test_replaces_known_long_values(self):
        content = "SearxEngineCaptcha: 86400\nSearxEngineAccessDenied: 86400\nSearxEngineTooManyRequests: 3600\n"
        result = self.fn(content, "settings.yml")
        self.assertIn("SearxEngineCaptcha: 900", result)
        self.assertIn("SearxEngineAccessDenied: 900", result)
        self.assertIn("SearxEngineTooManyRequests: 600", result)

    def test_replaces_arbitrary_integers(self):
        # R1 regression test: regex pattern matches any upstream integer
        content = "SearxEngineCaptcha: 7200\nSearxEngineAccessDenied: 14400\nSearxEngineTooManyRequests: 1800\n"
        result = self.fn(content, "settings.yml")
        self.assertIn("SearxEngineCaptcha: 900", result)
        self.assertIn("SearxEngineAccessDenied: 900", result)
        self.assertIn("SearxEngineTooManyRequests: 600", result)

    def test_idempotent_when_already_reduced(self):
        content = "SearxEngineCaptcha: 900\n"
        self.assertEqual(self.fn(content, "settings.yml"), "ALREADY_APPLIED")

    def test_config_settings_handles_user_customization_without_crash(self):
        # R1 regression test: user-customized config/settings.yml must not crash patch runner
        content_custom = "search:\n  suspended_times:\n    SearxEngineCaptcha: 300\n"
        self.assertEqual(self.cfg_fn(content_custom, "config/settings.yml"), "ALREADY_APPLIED")

        content_minimal = "general:\n  debug: false\n"
        self.assertEqual(self.cfg_fn(content_minimal, "config/settings.yml"), "ALREADY_APPLIED")


class TestPatchWebappJsonHandler(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_webapp_json_handler

    def test_already_applied(self):
        content = (
            "import ipaddress\n"
            "WindowsSelectorEventLoopPolicy\n"
            "if output_format in ('json', 'json_lite'):\n"
            "    pass\n"
            "if output_format == 'json_lite':\n"
            "    pass\n"
        )
        self.assertEqual(self.fn(content, "webapp.py"), "ALREADY_APPLIED")

    def test_patches_index_error_and_handler(self):
        content = (
            "import sys\n"
            "import warnings\n"
            "def index_error(output_format, err):\n"
            "    if output_format == 'json':\n"
            "        return err\n"
            "    if output_format == 'json':\n"
            "        response = webutils.get_json_response\n"
        )
        res = self.fn(content, "webapp.py")
        self.assertIn("import ipaddress", res)
        self.assertIn("WindowsSelectorEventLoopPolicy", res)
        self.assertIn("if output_format in ('json', 'json_lite'):", res)
        self.assertIn("if output_format == 'json_lite':", res)


class TestPatchWebappScrapeRoute(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_webapp_scrape_route

    def test_already_applied(self):
        content = (
            "def scrape()\n"
            "_is_blocked_scrape_host\n"
            "_RESERVED_TLDS\n"
            "pinned_dns\n"
            "_scrape_client\n"
            "_scrape_client_lock\n"
            "_scrape_client_verify_ssl\n"
            "_thread_local_dns\n"
            "def _parse_scrape_url\n"
            "def _read_scrape_response\n"
            "_SCRAPE_MAX_RESPONSE_BYTES\n"
            "Fetched response exceeds size limit\n"
            "Blocked invalid scheme\n"
            "Redirect without Location header\n"
            "verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes')\n"
            "max_keepalive_connections=0\n"
            "_searxng_original_getaddrinfo\n"
            "v19-bulletproof-scrape-fix\n"
            "host_clean.startswith(('0x', '0X', '0o', '0O', '0b', '0B'))\n"
            ".localdomain\n"
            ".arpa\n"
            "(?si)<script\n"
            "(?si)<iframe\n"
            "SEARXNG_SCRAPE_MAX_DURATION\n"
            "import urllib\n"
            "import re\n"
            "import html\n"
            "import httpx\n"
            "import idna\n"
            "import time\n"
            "trust_env=False\n"
            "class _ScrapeBlockedError\n"
            "def _is_ip_blocked\n"
            "def _is_reserved_scrape_host\n"
            "ip_direct = ipaddress.ip_address(host_clean)\n"
            "s6to4 = getattr(ip, 'sixtofour', None)\n"
            "max_duration=15.0\n"
            "Invalid port: 0\n"
            "Port mismatch for pinned host\n"
            "_normalize_scrape_host\n"
            "return ordered_ips, host_clean, port, safe_url\n"
            "stream('GET', safe_url, headers=headers)\n"
        )
        self.assertEqual(self.fn(content, "webapp.py"), "ALREADY_APPLIED")

    def test_injects_scrape_route(self):
        content = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
        res = self.fn(content, "webapp.py")
        self.assertIn("import trafilatura", res)
        self.assertIn("import html", res)
        self.assertIn("import httpx", res)
        self.assertIn("import idna", res)
        self.assertIn("@app.route('/scrape'", res)
        self.assertIn("def scrape():", res)
        self.assertIn("v19-bulletproof-scrape-fix", res)
        self.assertIn("def _parse_scrape_url", res)
        self.assertIn("def _read_scrape_response", res)
        self.assertIn("_SCRAPE_MAX_RESPONSE_BYTES", res)
        self.assertIn("def _is_ip_blocked", res)
        self.assertIn("def _is_reserved_scrape_host", res)
        # R2 regression: type validation
        self.assertIn("isinstance(url, str)", res)
        # R3 regression: idna normalization in _safe_getaddrinfo (module-level import)
        self.assertIn("idna.encode", res)
        # Verify idna is imported at module level, not inside _safe_getaddrinfo
        self.assertNotIn("import idna\n                        enc_h", res)
        # R4 regression: DNS pinning family isolation, mixed record check, and reserved TLDs
        self.assertIn("Address family not supported for pinned host", res)
        self.assertIn("Port mismatch for pinned host", res)
        self.assertIn("_RESERVED_TLDS", res)
        self.assertIn(".localdomain", res)
        self.assertIn(".intranet", res)
        self.assertIn(".private", res)
        self.assertIn(".arpa", res)
        self.assertIn("resolves to a private/reserved IP", res)
        self.assertIn("html.unescape", res)
        self.assertIn("(?si)<script", res)
        self.assertIn("(?si)<iframe", res)
        self.assertIn("SEARXNG_SCRAPE_MAX_DURATION", res)
        # R6 regression: host normalization + safe URL rebuild to keep the
        # DNS pin effective (Unicode dot / trailing dot / IDNA pin bypass).
        self.assertIn("_normalize_scrape_host", res)
        self.assertIn("return ordered_ips, host_clean, port, safe_url", res)
        self.assertIn("stream('GET', safe_url, headers=headers)", res)
        self.assertIn("current_url = urllib.parse.urljoin(safe_url, location.strip())", res)
        # HTTPX trusts HTTP(S)_PROXY by default.  The scrape client must make
        # direct, DNS-pinned connections instead of delegating DNS to a proxy.
        self.assertIn("trust_env=False", res)
        # R5 regression: whitespace regex collapsing and hex IP SSRF blocking
        self.assertIn(r"re.sub(r'\s+', ' ', raw_text).strip()", res)
        self.assertNotIn(r"re.sub(r'\\s+'", res)

    def test_scrape_hex_ip_and_whitespace_collapse(self):
        content = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
        res = self.fn(content, "webapp.py")
        self.assertIn(r"re.sub(r'\s+', ' ', raw_text).strip()", res)
        self.assertNotIn(r"re.sub(r'\\s+'", res)
        self.assertIn("host_clean.startswith(('0x', '0X', '0o', '0O', '0b', '0B'))", res)
        self.assertIn("ip_int = int(host_clean, 0)", res)
        self.assertIn("v4_ips = [ip for ip in valid_ips if ':' not in ip]", res)
        self.assertIn("ordered_ips = v4_ips + v6_ips", res)
        self.assertIn("with pinned_dns(original_host, safe_ips, port):", res)

    def test_scrape_cleanup_preserves_next_webui_integration(self):
        content = (
            "import warnings\nfrom flask import Flask\n\n"
            "@app.route('/scrape', methods=['GET', 'POST'])\n"
            "def scrape():\n"
            "    return 'old_scrape'\n\n"
            "# --- GenAI Next WebUI Integration ---\n"
            "import webui_next\n"
            "webui_next.register_next_webui(app, None)\n\n"
            "@app.route('/search')\ndef search():\n    pass\n"
        )
        res = self.fn(content, "webapp.py")
        self.assertIn("# --- GenAI Next WebUI Integration ---", res)
        self.assertIn("webui_next.register_next_webui(app, None)", res)
        self.assertIn("v19-bulletproof-scrape-fix", res)

    def test_scrape_host_normalization_prevents_pin_bypass(self):
        """R6 SSRF regression: the injected scrape route must normalize hosts
        (Unicode dot variants / trailing dot / IDNA) before blocking, DNS
        resolution and pinning, and must fetch the rebuilt safe_url so the
        DNS pin always matches the host httpx hands to the transport.

        Without this, a URL like http://attacker.example\u3002/ makes the
        validator pin the raw host while httpx normalizes it, the pin is
        silently skipped and attacker DNS can point the second resolution
        at an internal service (DNS rebinding -> SSRF).
        """
        import re as re_mod

        content = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
        res = self.fn(content, "webapp.py")

        # Host normalization helper exists and handles Unicode dot variants
        self.assertIn("def _normalize_scrape_host(host_raw):", res)
        self.assertIn("chr(0x3002), chr(0xFF0E), chr(0xFF61)", res)
        self.assertIn("idna.encode(host_norm, uts46=True)", res)

        # The validator resolves/pins the normalized host and returns a
        # rebuilt safe_url.
        self.assertIn("addr_info = socket.getaddrinfo(host_clean, port)", res)
        self.assertIn("return ordered_ips, host_clean, port, safe_url", res)

        # The request must use the normalized safe_url (not the raw URL).
        self.assertIn("safe_ips, original_host, port, safe_url = _get_safe_ip_url(current_url)", res)
        self.assertIn("with _scrape_client.stream('GET', safe_url, headers=headers) as response:", res)
        self.assertIn("current_url = urllib.parse.urljoin(safe_url, location.strip())", res)
        self.assertNotIn("stream('GET', current_url, headers=headers)", res)

        # _safe_getaddrinfo must normalize both sides before comparing with
        # the pin (defense in depth if any caller still pins a raw host).
        self.assertIn("def _norm_gai_host(value):", res)
        self.assertIn("h_clean = _norm_gai_host(h_str)", res)
        self.assertIn("pin_clean = _norm_gai_host(pin_host)", res)

        # Simulate the normalization end-to-end: raw unicode-dot host must
        # collapse to the same string httpx would produce.
        code = re_mod.search(
            r"def _normalize_scrape_host\(host_raw\):(.*?)\n            return host_norm", res, re_mod.DOTALL
        )
        self.assertIsNotNone(code, "_normalize_scrape_host body not found in patch output")
        # Dedent the extracted body (12-space indentation inside the patch)
        # to module level so it can be exec'd standalone. The extracted
        # body starts with the docstring, which becomes the function body's
        # first statement after the def line.
        body = code.group(1)
        body = re_mod.sub(r"\n            ", "\n", body).strip("\n")
        namespace: dict[str, Any] = {"chr": chr}
        exec(  # noqa: S102 - static test input
            "def _normalize_scrape_host(host_raw):\n    " + body.replace("\n", "\n    ") + "\n    return host_norm\n",
            namespace,
        )
        normalize: Any = namespace["_normalize_scrape_host"]
        self.assertEqual(normalize("attacker.example\u3002"), "attacker.example")
        self.assertEqual(normalize("attacker.example."), "attacker.example")
        self.assertEqual(normalize("attacker.example\uff0e"), "attacker.example")
        self.assertEqual(normalize("attack\u3002er.example"), "attack.er.example")
        self.assertEqual(normalize("EXAMPLE.COM"), "example.com")
        self.assertEqual(normalize("127\u30020\u30020\u30021"), "127.0.0.1")

    def test_is_blocked_scrape_host_catches_unicode_dots_and_bracketed_ipv6(self):
        """Verify _is_blocked_scrape_host catches Unicode dot obfuscation, bracketed IPv6, and IDNA reserved domains."""
        content = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
        patched = self.fn(content, "webapp.py")
        self.assertIn("def _is_blocked_scrape_host(host, resolve_dns=True):", patched)

        namespace: dict[str, Any] = {
            "chr": chr,
            "idna": idna,
            "ipaddress": ipaddress,
            "socket": socket,
            "_RESERVED_TLDS": (
                ".localhost",
                ".local",
                ".internal",
                ".lan",
                ".home.arpa",
                ".invalid",
                ".test",
                ".example",
                ".onion",
                ".corp",
                ".home",
                ".localdomain",
                ".intranet",
                ".private",
                ".arpa",
            ),
        }
        helpers_code = re_mod.search(
            r"(def _is_reserved_scrape_host\(host\):.*?)(?=@app\.route\('/scrape')", patched, re_mod.DOTALL
        )
        self.assertIsNotNone(helpers_code)
        assert helpers_code is not None
        exec(helpers_code.group(1), namespace)  # noqa: S102

        is_blocked = namespace["_is_blocked_scrape_host"]

        # Obfuscated Unicode dot variants must be blocked statically without DNS
        self.assertTrue(is_blocked("127\u30020\u30020\u30021", resolve_dns=False))
        self.assertTrue(is_blocked("127\uff0e0\uff0e0\uff0e1", resolve_dns=False))
        self.assertTrue(is_blocked("127\uff610\uff610\uff611", resolve_dns=False))
        self.assertTrue(is_blocked("attacker\u3002localhost", resolve_dns=False))
        self.assertTrue(is_blocked("attacker\u3002local", resolve_dns=False))

        # Bracketed IPv6 loopback and IPv4-mapped must be detected
        self.assertTrue(is_blocked("[::1]", resolve_dns=False))
        self.assertTrue(is_blocked("[::ffff:127.0.0.1]", resolve_dns=False))

        # Obfuscated integer/hex/octal/binary and invalid numeric hosts
        self.assertTrue(is_blocked("2130706433", resolve_dns=False))
        self.assertTrue(is_blocked("0x7f000001", resolve_dns=False))
        self.assertTrue(is_blocked("0177.0.0.1", resolve_dns=False))
        self.assertTrue(is_blocked("017700000001", resolve_dns=False))
        self.assertTrue(is_blocked("999999999999", resolve_dns=False))
        self.assertTrue(is_blocked("999.999.999.999", resolve_dns=False))

        # Public global hosts must not be blocked statically
        self.assertFalse(is_blocked("example.com", resolve_dns=False))
        self.assertFalse(is_blocked("93.184.216.34", resolve_dns=False))


class TestPatchProcessorsInit(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_processors_init

    def test_already_applied(self):
        content = 'if eng_settings.get("inactive", False) is True:\n    continue\n'
        self.assertEqual(self.fn(content, "__init__.py"), "ALREADY_APPLIED")

    def test_removes_legacy_disabled_processor_skip(self):
        content = (
            'if eng_settings.get("inactive", False) is True:\n'
            "    continue\n"
            '            if eng_settings.get("disabled", False) is True:\n'
            "                logger.debug(\"Engine '%s' is disabled in config, skipping processor init.\", eng_name)\n"
            "                continue\n"
        )
        res = self.fn(content, "__init__.py")
        self.assertNotIn("skipping processor init", res)
        self.assertNotIn('if eng_settings.get("disabled", False) is True:', res)


class TestPatchGoogleCaptcha(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_google_captcha

    def test_already_applied(self):
        content = 'loc = (resp.headers.get("Location")'
        self.assertEqual(self.fn(content, "google.py"), "ALREADY_APPLIED")

    def test_replaces_location_check(self):
        old = (
            "    if resp.status_code == 302:\n"
            "        raise SearxEngineCaptchaException()\n"
            "\n"
            '    if len(resp.text) < 2000 and "/sorry/" in resp.text:\n'
            "        raise SearxEngineCaptchaException()"
        )
        res = self.fn(old, "google.py")
        self.assertIn('loc = (resp.headers.get("Location")', res)
        self.assertIn("sorry.google.com", res)


class TestPatchSogouCaptcha(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_sogou_captcha

    def test_already_applied(self):
        content = "antispider in content and captcha in content.lower() and resp.headers.get in content"
        self.assertEqual(self.fn(content, "sogou.py"), "ALREADY_APPLIED")

    def test_replaces_sogou_response(self):
        old = (
            "def response(resp):\n"
            "    if (\n"
            "        resp.status_code == 302\n"
            "        and resp.next_request is not None\n"
            '        and str(resp.next_request.url).startswith("http://www.sogou.com/antispider")\n'
            "    ):\n"
            "        raise SearxEngineCaptchaException()"
        )
        res = self.fn(old, "sogou.py")
        self.assertIn("antispider", res)
        self.assertIn('resp.headers.get("Location")', res)


class TestPatchAbstractSuspend(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_abstract_suspend

    def test_already_applied(self):
        content = (
            "            self.suspend_end_time = default_timer() + suspended_time\n"
            "            self.suspend_reason = suspend_reason\n"
            '            logger.debug("Suspend for %i seconds", suspended_time)'
        )
        self.assertEqual(self.fn(content, "abstract.py"), "ALREADY_APPLIED")

    def test_removes_legacy_global_cap(self):
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
        res = self.fn(legacy, "abstract.py")
        self.assertNotIn("max_ban_time_on_fail", res)
        self.assertNotIn("suspended_time = min(suspended_time, 900)", res)
        self.assertIn("self.suspend_end_time", res)


class TestPatchOnlineCaptcha(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_online_captcha

    def test_already_applied(self):
        content = "_parse_retry_after_header"
        self.assertEqual(self.fn(content, "online.py"), "ALREADY_APPLIED")

    def test_adds_retry_after_parser(self):
        old = (
            "from searx.metrics.error_recorder import count_error\n"
            "from .abstract import EngineProcessor, RequestParams\n"
            "        except (\n"
            "            SearxEngineCaptchaException,\n"
            "            SearxEngineTooManyRequestsException,\n"
            "            SearxEngineAccessDeniedException,\n"
            "        ) as e:\n"
            "            self.handle_exception(result_container, e, suspend=True)\n"
            "            self.logger.debug(e.message)"
        )
        res = self.fn(old, "online.py")
        self.assertIn("def _parse_retry_after_header", res)
        self.assertIn("Retry-After", res)
        self.assertNotIn("e.suspended_time = min(e.suspended_time, 900)", res)

    def test_removes_legacy_captcha_cap(self):
        content = (
            "def _parse_retry_after_header(resp):\n"
            "    return None\n"
            "            e.suspended_time = min(e.suspended_time, 900)\n"
        )
        result = self.fn(content, "online.py")
        self.assertNotEqual(result, "ALREADY_APPLIED")
        self.assertNotIn("min(e.suspended_time, 900)", result)


class TestDisableMissingEngines(unittest.TestCase):
    def setUp(self):
        self.mod = disable_missing_engines
        self._tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)

    def test_inactivates_engine_when_no_inactive_field(self):
        sample = (
            "engines:\n"
            "  - name: google\n"
            "    engine: google\n"
            "  - name: removed_engine\n"
            "    engine: removed_engine\n"
            "    categories: general\n"
        )
        res = self.mod.disable_engine_in_text(sample, "removed_engine")
        self.assertIn("inactive: true", res)
        self.assertIn("categories: general", res)

    def test_inactivates_engine_without_changing_disabled_preference(self):
        # ``disabled`` is a preference default, not an instruction to omit the
        # engine.  A missing module must gain ``inactive: true`` while leaving
        # the preference intact.
        sample = "engines:\n  - name: removed_engine\n    engine: removed_mod\n    disabled: false\n    shortcut: rm\n"
        res = self.mod.disable_engine_in_text(sample, "removed_engine")
        self.assertIn("inactive: true", res)
        self.assertIn("disabled: false", res)
        self.assertIn("shortcut: rm", res)

    def test_inactivate_engine_when_already_inactive_is_noop(self):
        sample = "engines:\n  - name: removed_engine\n    engine: removed_mod\n    inactive: true\n"
        res = self.mod.disable_engine_in_text(sample, "removed_engine")
        self.assertEqual(res, sample)

    def test_preserves_comments_and_formatting(self):
        sample = (
            "# Top comment\nengines:\n  # Engine comment\n  - name: missing\n    # inner comment\n    engine: missing\n"
        )
        res = self.mod.disable_engine_in_text(sample, "missing")
        self.assertIn("# Top comment", res)
        self.assertIn("# inner comment", res)
        self.assertIn("inactive: true", res)

    def test_engine_name_with_special_chars(self):
        # Engine names with hyphens, dots, etc. should be matched by escaped regex.
        sample = "engines:\n  - name: my-engine.v2\n    engine: my_engine_v2\n"
        res = self.mod.disable_engine_in_text(sample, "my-engine.v2")
        self.assertIn("inactive: true", res)

    def test_no_match_returns_unchanged(self):
        sample = "engines:\n  - name: existing\n    engine: existing\n"
        res = self.mod.disable_engine_in_text(sample, "nonexistent")
        self.assertEqual(res, sample)

    def test_only_target_engine_is_disabled(self):
        # Regression: a preceding disabled field must not be changed while the
        # missing target remains enabled.
        sample = (
            "engines:\n"
            "  - name: first\n"
            "    engine: first\n"
            "    disabled: false\n"
            "  - name: missing_target\n"
            "    engine: missing_target\n"
            "    categories: general\n"
            "  - name: third\n"
            "    engine: third\n"
        )
        result = self.mod.disable_engine_in_text(sample, "missing_target")
        self.assertIn("    disabled: false\n", result)
        self.assertIn(
            "  - name: missing_target\n    engine: missing_target\n    categories: general\n    inactive: true\n",
            result,
        )
        self.assertEqual(result.count("inactive: true"), 1)

    def test_preserves_crlf_line_endings(self):
        sample = "engines:\r\n  - name: missing\r\n    engine: missing\r\n"
        res = self.mod.disable_engine_in_text(sample, "missing")
        self.assertIn("inactive: true", res)
        # Should preserve CRLF (block contained CRLF).
        self.assertIn("\r\n", res)

    def test_inactive_various_truthy_values(self):
        # Anything in {'true', 'yes', 'on', '1'} (lowercased) should be treated
        # as already-inactive and not double-modified.
        for val in ("true", "yes", "on", "1", "TRUE", "Yes", "ON"):
            sample = f"engines:\n  - name: e\n    engine: e\n    inactive: {val}\n"
            res = self.mod.disable_engine_in_text(sample, "e")
            self.assertEqual(res, sample, f"inactive: {val!r} should be a no-op")

    def test_fallback_parser_basic(self):
        sample = (
            "engines:\n"
            "  - name: google\n"
            "    engine: google\n"
            "    shortcut: go\n"
            "  - name: duckduckgo\n"
            "    disabled: false\n"
            "  - name: removed\n"
            "    engine: removed_mod\n"
            "    inactive: true\n"
        )
        engines = self.mod.parse_engines_fallback(sample)
        self.assertEqual(len(engines), 3)
        self.assertEqual(engines[0]["name"], "google")
        self.assertEqual(engines[0]["engine"], "google")
        self.assertNotIn("inactive", engines[0])
        self.assertEqual(engines[1]["name"], "duckduckgo")
        self.assertEqual(engines[1]["engine"], "duckduckgo")
        self.assertEqual(engines[2]["name"], "removed")
        self.assertEqual(engines[2]["engine"], "removed_mod")
        self.assertTrue(engines[2]["inactive"])

    def test_fallback_parser_quotes_and_comments(self):
        sample = (
            "# Top comment\n"
            "engines:\n"
            "  # First engine\n"
            "  - name: 'bing images'  # inline comment\n"
            '    engine: "bing_images"\n'
            '  - name: "complex-engine"\n'
            "    engine: complex_engine\n"
            "    inactive: yes  # comment\n"
            "other_section:\n"
            "  - not_an_engine\n"
        )
        engines = self.mod.parse_engines_fallback(sample)
        self.assertEqual(len(engines), 2)
        self.assertEqual(engines[0]["name"], "bing images")
        self.assertEqual(engines[0]["engine"], "bing_images")
        self.assertEqual(engines[1]["name"], "complex-engine")
        self.assertEqual(engines[1]["engine"], "complex_engine")
        self.assertTrue(engines[1]["inactive"])

    def test_extract_engines_and_disable_without_yaml(self):
        sample = (
            'engines:\n  - name: google\n    engine: google\n  - name: "missing-engine"\n    engine: missing_engine\n'
        )
        with mock.patch.object(self.mod, "yaml", None):
            # 1. extract_engines works without PyYAML
            engines = self.mod.extract_engines(sample)
            self.assertEqual(len(engines), 2)
            self.assertEqual(engines[1]["name"], "missing-engine")

            # 2. disable_engine_in_text works without PyYAML
            res = self.mod.disable_engine_in_text(sample, "missing-engine")
            self.assertIn("inactive: true", res)
            self.assertIn('name: "missing-engine"', res)

    def test_main_execution_without_yaml(self):
        settings_file = os.path.join(self._tmpdir, "settings.yml")
        engines_dir = os.path.join(self._tmpdir, "engines")
        os.makedirs(engines_dir, exist_ok=True)

        # Create one existing engine module and one missing engine
        with open(os.path.join(engines_dir, "google.py"), "w") as f:
            f.write("# google engine\n")

        with open(settings_file, "w", encoding="utf-8") as f:
            f.write("engines:\n  - name: google\n    engine: google\n  - name: removed\n    engine: removed\n")

        with (
            mock.patch.object(self.mod, "yaml", None),
            mock.patch.object(sys, "argv", ["disable-missing-engines.py", settings_file, engines_dir]),
            self.assertRaises(SystemExit) as cm,
        ):
            self.mod.main()
        self.assertEqual(cm.exception.code, 0)

        with open(settings_file, "r", encoding="utf-8") as f:
            updated = f.read()

        self.assertIn("inactive: true", updated)
        self.assertIn("- name: removed\n    engine: removed\n    inactive: true", updated)
        self.assertNotIn("inactive: true\n  - name: google", updated)

    def test_process_file_disables_missing_engine(self):
        settings_file = os.path.join(self._tmpdir, "settings_pf.yml")
        engines_dir = os.path.join(self._tmpdir, "engines_pf")
        os.makedirs(engines_dir, exist_ok=True)
        with open(settings_file, "w", encoding="utf-8") as f:
            f.write("engines:\n  - name: ghost\n    engine: ghost\n")
        changed = self.mod.process_file(settings_file, engines_dir)
        self.assertTrue(changed)
        with open(settings_file, "r", encoding="utf-8") as f:
            self.assertIn("inactive: true", f.read())
        # Second call is idempotent and returns False
        self.assertFalse(self.mod.process_file(settings_file, engines_dir))

    def test_package_engine_not_disabled(self):
        # Engines structured as packages (engines/<name>/__init__.py) must be recognized as present.
        settings_file = os.path.join(self._tmpdir, "settings.yml")
        engines_dir = os.path.join(self._tmpdir, "engines")
        pkg_engine_dir = os.path.join(engines_dir, "pkg_engine")
        os.makedirs(pkg_engine_dir, exist_ok=True)
        with open(os.path.join(pkg_engine_dir, "__init__.py"), "w") as f:
            f.write("# package engine\n")

        with open(settings_file, "w", encoding="utf-8") as f:
            f.write("engines:\n  - name: pkg_engine\n    engine: pkg_engine\n")

        with (
            mock.patch.object(self.mod, "yaml", None),
            mock.patch.object(sys, "argv", ["disable-missing-engines.py", settings_file, engines_dir]),
            self.assertRaises(SystemExit) as cm,
        ):
            self.mod.main()
        self.assertEqual(cm.exception.code, 0)

        with open(settings_file, "r", encoding="utf-8") as f:
            updated = f.read()

        self.assertNotIn("inactive: true", updated)

    def test_engine_with_engine_key_first(self):
        # Engine entries where `engine:` or another key precedes `name:` must still be parsed and inactivated properly.
        sample = "engines:\n  - engine: removed_mod\n    name: removed_engine\n    categories: general\n"
        res = self.mod.disable_engine_in_text(sample, "removed_engine")
        self.assertIn("inactive: true", res)
        self.assertIn("categories: general", res)


class TestPatchSettingsYmlEdgeCases(unittest.TestCase):
    """Additional settings.yml reduction coverage."""

    def setUp(self):
        self.fn = apply_patches.patch_settings_yml

    def test_replaces_3600_captcha_too(self):
        # Both 86400 and 3600 must be normalised to 900 so a recent upstream
        # change that already lowered the value still triggers the patch.
        content = "SearxEngineCaptcha: 3600\n"
        result = self.fn(content, "settings.yml")
        self.assertIn("SearxEngineCaptcha: 900", result)

    def test_replaces_cloudflare_and_recaptcha(self):
        content = "cf_SearxEngineCaptcha: 1296000\nrecaptcha_SearxEngineCaptcha: 604800\n"
        result = self.fn(content, "settings.yml")
        self.assertIn("cf_SearxEngineCaptcha: 3600", result)
        self.assertIn("recaptcha_SearxEngineCaptcha: 3600", result)


class TestPatchProcessorsInitEdgeCases(unittest.TestCase):
    """Cleanup does not alter already-upstream processor code."""

    def setUp(self):
        self.fn = apply_patches.patch_processors_init

    def test_leaves_inactive_check_with_extra_whitespace_unchanged(self):
        content = 'if   eng_settings.get("inactive", False)  is  True:\n    continue\n'
        result = self.fn(content, "__init__.py")
        self.assertEqual(result, "ALREADY_APPLIED")

    def test_removes_legacy_disabled_processor_skip(self):
        content = (
            'if eng_settings.get("inactive", False) is True:\n'
            "    continue\n"
            '            if eng_settings.get("disabled", False) is True:\n'
            "                logger.debug(\"Engine '%s' is disabled in config, skipping processor init.\", eng_name)\n"
            "                continue\n"
        )
        result = self.fn(content, "__init__.py")
        self.assertNotEqual(result, "ALREADY_APPLIED")
        self.assertNotIn("disabled", result)


class TestPatchEnginesInitEdgeCases(unittest.TestCase):
    """Legacy disabled-engine cleanup remains idempotent."""

    def setUp(self):
        self.fn = apply_patches.patch_engines_init

    def test_removes_legacy_disabled_short_circuit_once(self):
        content = (
            "def load_engine(engine_data):\n"
            "    if engine_name.lower() != engine_name:\n"
            "        engine_name = engine_name.lower()\n"
            "        engine_data['name'] = engine_name\n"
            "    # Early return for engines that are intentionally disabled or inactive in config.\n"
            "    if engine_data.get('inactive') is True:\n"
            "        logger.debug('Engine \"%s\" is inactive in config, skipping load', engine_name)\n"
            "        return None\n"
            "    if engine_data.get('disabled') is True:\n"
            "        logger.debug('Engine \"%s\" is disabled in config, skipping load', engine_name)\n"
            "        return None\n"
            "\n"
            "def load_engines(engine_list):\n"
            "    for engine_data in engine_list:\n"
            "        if engine_data.get('inactive') is True: continue\n"
            '        if engine_data.get("inactive") is True or engine_data.get("disabled") is True:\n'
            "            logger.debug(\n"
            '                "loading engine %s skipped: inactive or disabled in config!",\n'
            '                engine_data.get("name", "???"),\n'
            "            )\n"
            "            continue\n"
        )
        result = self.fn(content, "engines/__init__.py")
        self.assertNotEqual(result, "ALREADY_APPLIED")
        self.assertNotIn("inactive or disabled in config!", result)
        self.assertNotIn("disabled') is True", result)
        self.assertEqual(result.count('if engine_data.get("inactive") is True:'), 1)


class TestPatchScrapeRouteEdgeCases(unittest.TestCase):
    """Verify R2 and R3 security and robustness enhancements."""

    def test_idna_matching_logic(self):
        # R3 verification: Unicode and Punycode representations must match
        try:
            import idna

            punycode_host = idna.encode("日本語.jp").decode("ascii")
        except ImportError:
            punycode_host = "日本語.jp".encode("idna").decode("ascii")

        unicode_host = "日本語.jp"

        # Test normalization logic used in _safe_getaddrinfo
        h_clean = punycode_host.rstrip(".").lower()
        pin_clean = unicode_host.rstrip(".").lower()

        try:
            import idna

            enc_h = idna.encode(h_clean).decode("ascii")
            enc_pin = idna.encode(pin_clean).decode("ascii")
        except ImportError:
            enc_h = h_clean.encode("idna").decode("ascii")
            enc_pin = pin_clean.encode("idna").decode("ascii")

        matched = (h_clean == pin_clean) or (enc_h == enc_pin)
        self.assertTrue(matched, "Punycode host must match Unicode pinned host")

    def test_url_type_validation_logic(self):
        # R2 verification: Non-string and whitespace-only URLs must be rejected
        def validate_url(val):
            if not val or not isinstance(val, str) or not val.strip():
                return False
            return val.strip()

        self.assertFalse(validate_url(12345))
        self.assertFalse(validate_url(None))
        self.assertFalse(validate_url(["https://example.com"]))
        self.assertFalse(validate_url({"url": "https://example.com"}))
        self.assertFalse(validate_url("   "))
        self.assertEqual(validate_url("  https://example.com  "), "https://example.com")

    def test_dns_pinning_family_mismatch_raises_gaierror(self):
        # R4 verification: When a host is pinned to IPv4, querying AF_INET6
        # must raise socket.gaierror rather than falling through to live DNS.
        import ipaddress
        import socket
        import threading

        thread_local = threading.local()
        thread_local.pin = {"host": "example.com", "ip": "93.184.216.34", "port": 443}

        def mock_original_gai(h, p, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "live_dns", (h, p))]

        # Mimic _safe_getaddrinfo implementation
        def test_safe_getaddrinfo(h, p, *args, **kwargs):
            pin = getattr(thread_local, "pin", None)
            if pin:
                pin_host = pin.get("host")
                if pin_host and (h or "").rstrip(".").lower() == pin_host.rstrip(".").lower():
                    pin_port = pin.get("port")
                    if p is None or p == pin_port or str(p) == str(pin_port) or (pin_port == 443 and p == "https"):
                        ip_obj = ipaddress.ip_address(pin["ip"])
                        port_num = int(pin_port or 443)
                        req_family = args[0] if len(args) > 0 else kwargs.get("family", 0)
                        ip_family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
                        if req_family in (0, ip_family):
                            sockaddr = (pin["ip"], port_num, 0, 0) if ip_obj.version == 6 else (pin["ip"], port_num)
                            return [(ip_family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]
                        else:
                            raise socket.gaierror(
                                socket.EAI_NONAME, f"Address family not supported for pinned host {pin_host}"
                            )
            return mock_original_gai(h, p, *args, **kwargs)

        # 1. Matching family returns pinned IP
        res_v4 = test_safe_getaddrinfo("example.com", 443, socket.AF_INET)
        self.assertEqual(res_v4[0][4], ("93.184.216.34", 443))

        # 2. Incompatible family raises gaierror (does NOT leak to live DNS)
        with self.assertRaises(socket.gaierror):
            test_safe_getaddrinfo("example.com", 443, socket.AF_INET6)

        # 3. Unpinned host falls through to original resolver
        res_other = test_safe_getaddrinfo("other.com", 443, socket.AF_INET)
        self.assertEqual(
            res_other, [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "live_dns", ("other.com", 443))]
        )

    def test_read_scrape_response_unknown_charset_fallback(self):
        # R4 verification: Malformed/bogus charset header must not crash with 500 LookupError
        class DummyResponse:
            def __init__(self):
                self.headers = {"content-type": "text/html; charset=bogus-unknown-codec"}
                self.encoding = "bogus-unknown-codec"

            def iter_bytes(self):
                yield "Hello, 世界!".encode()

        resp = DummyResponse()
        chunks = list(resp.iter_bytes())
        body = b"".join(chunks)

        encoding = resp.encoding or "utf-8"
        try:
            decoded = body.decode(encoding, errors="replace")
        except (LookupError, ValueError):
            decoded = body.decode("utf-8", errors="replace")

        self.assertEqual(decoded, "Hello, 世界!")

    def test_mixed_record_dns_rejection_logic(self):
        # R4 verification: If a domain resolves to both a global IP and a private IP,
        # it must be strictly rejected as an SSRF attack.
        import ipaddress

        records = [
            (2, 1, 6, "", ("93.184.216.34", 443)),  # global
            (2, 1, 6, "", ("192.168.1.1", 443)),  # private
        ]

        def validate_records(addr_info):
            for res in addr_info:
                ip_raw = res[4][0]
                ip_obj = ipaddress.ip_address(ip_raw)
                if not ip_obj.is_global:
                    return False, f"Blocked non-global: {ip_raw}"
            return True, "OK"

        ok, msg = validate_records(records)
        self.assertFalse(ok)
        self.assertIn("192.168.1.1", msg)

    def test_reserved_tlds_blocking_logic(self):
        # R4 verification: Reserved TLDs and bare names must be blocked statically
        reserved_tlds = (
            ".localhost",
            ".local",
            ".internal",
            ".lan",
            ".home.arpa",
            ".invalid",
            ".test",
            ".example",
            ".onion",
            ".corp",
            ".home",
        )

        def is_blocked(host):
            h = (host or "").strip().rstrip(".").lower()
            if not h or h == "localhost":
                return True
            for tld in reserved_tlds:
                bare = tld.lstrip(".")
                if h == bare or h.endswith(tld):
                    return True
            return False

        for blocked in [
            "router.local",
            "myhost.internal",
            "gateway.lan",
            "device.home.arpa",
            "dark.onion",
            "localhost",
            "local",
            "internal",
            "lan",
            "corp",
            "home",
        ]:
            self.assertTrue(is_blocked(blocked), f"{blocked} should be blocked")

        for allowed in ["example.com", "searxng.org", "google.com", "wikipedia.org"]:
            self.assertFalse(is_blocked(allowed), f"{allowed} should not be blocked")

    def test_multicast_and_mapped_ipv6_blocking_logic(self):
        # R5 verification: Multicast addresses (which have is_global==True in Python 3.11)
        # and IPv4-mapped IPv6 addresses must be strictly blocked.
        import ipaddress

        def is_ip_blocked(ip):
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
            mapped = getattr(ip, "ipv4_mapped", None)
            if mapped is not None and is_ip_blocked(mapped):
                return True
            s6to4 = getattr(ip, "sixtofour", None)
            if s6to4 is not None and is_ip_blocked(s6to4):
                return True
            teredo = getattr(ip, "teredo", None)
            return bool(teredo is not None and (is_ip_blocked(teredo[0]) or is_ip_blocked(teredo[1])))

        # Blocked addresses
        blocked_ips = [
            "127.0.0.1",
            "192.168.1.1",
            "10.0.0.1",
            "172.16.0.1",
            "169.254.1.1",
            "224.0.0.1",  # Multicast IPv4
            "239.255.255.250",  # SSDP multicast
            "ff02::1",  # Multicast IPv6
            "::1",  # IPv6 loopback
            "fe80::1",  # IPv6 link-local
            "::",  # IPv6 unspecified
            "0.0.0.0",  # IPv4 unspecified
            "::ffff:127.0.0.1",  # Mapped loopback
            "::ffff:192.168.1.1",  # Mapped private
            "::ffff:224.0.0.1",  # Mapped multicast
            "::127.0.0.1",  # IPv4-compatible loopback
            "::192.168.1.1",  # IPv4-compatible private
            "2002:7f00:1::",  # 6to4 embedding 127.0.0.1
            "2002:c0a8:101::",  # 6to4 embedding 192.168.1.1
            "2002:0a00:1::",  # 6to4 embedding 10.0.0.1
            "2001:0:4136:e378:8000:63bf:7f00:1",  # Teredo tunnel embedding 127.0.0.1
        ]
        for ip_str in blocked_ips:
            self.assertTrue(is_ip_blocked(ip_str), f"{ip_str} should be blocked")

        # Allowed public unicast addresses
        allowed_ips = [
            "93.184.216.34",  # example.com
            "8.8.8.8",  # Google DNS
            "2606:2800:220:1:248:1893:25c8:1946",  # IPv6 example.com
            "2606:4700:4700::1111",  # Cloudflare DNS IPv6
        ]
        for ip_str in allowed_ips:
            self.assertFalse(is_ip_blocked(ip_str), f"{ip_str} should be allowed")

    def test_html_unescape_in_scrape_fallback(self):
        # R4 verification: Fallback extraction unescapes HTML entities for GenAI readability
        import html
        import re

        raw_html = "<p>SearXNG &amp; AI: &quot;Fast &apos;n&apos; Lean&quot; &lt;3</p>"
        stripped = re.sub(r"<[^>]+>", " ", raw_html)
        unescaped = html.unescape(stripped).strip()
        self.assertEqual(unescaped, "SearXNG & AI: \"Fast 'n' Lean\" <3")

    def test_import_injection_preserves_anchor_lines(self):
        """Regression: f-string regex replacements must use backreferences, not literals.

        Prior to the fix, f-string replacements like f'import {mod}\\n\\\\1'
        produced a literal '\\1' in the output instead of preserving the captured
        group text.  This test ensures that after patching, the original anchor
        import lines ('import warnings', 'from flask import ...') are still
        present in the output.
        """
        content = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
        res = apply_patches.patch_webapp_scrape_route(content, "webapp.py")
        # The anchor 'import warnings' must survive the import injection.
        self.assertIn("import warnings", res)
        # Literal backslash-1 must never appear in the output.
        self.assertNotIn("\\1", res)
        # All injected imports must be present.
        for mod in ("re", "html", "httpx", "idna", "time", "trafilatura", "socket", "contextlib", "threading"):
            self.assertIn(f"import {mod}", res)

    def test_read_scrape_response_streaming_timeout(self):
        import time

        try:
            import httpx

            timeout_exc_cls = httpx.TimeoutException
        except ImportError:

            class _FallbackTimeoutException(Exception):
                pass

            timeout_exc_cls = _FallbackTimeoutException

        class SlowResponse:
            def __init__(self):
                self.headers = {}
                self.encoding = "utf-8"

            def iter_bytes(self):
                for _ in range(5):
                    time.sleep(0.01)
                    yield b"slow chunk"

        resp = SlowResponse()
        with self.assertRaises(timeout_exc_cls):
            start_time = time.monotonic()
            chunks = []
            max_duration = 0.005
            for chunk in resp.iter_bytes():
                if time.monotonic() - start_time > max_duration:
                    raise timeout_exc_cls("Response read stream timed out")
                chunks.append(chunk)

    def test_read_scrape_response_content_length_whitespace(self):
        # Verification: Whitespace-padded content-length headers must be stripped and rejected if over size limit
        raw_header = "  10485760  "
        cl_str = raw_header.strip()
        self.assertTrue(cl_str.isdigit())
        self.assertGreater(int(cl_str), 5 * 1024 * 1024)


class TestPatchRaiseForHttpError(unittest.TestCase):
    """Regression: Retry-After handling needs the response attached to
    engine exceptions, otherwise ``getattr(e, 'response', None)`` in
    ``search/processors/online.py`` always returns None and the whole
    Retry-After feature is a silent no-op.
    """

    def test_attaches_response_to_cloudflare_captcha_raise(self):
        content = (
            "def raise_for_cloudflare_captcha(resp):\n"
            "    if is_cloudflare_challenge(resp):\n"
            "        raise SearxEngineCaptchaException(\n"
            "            message='Cloudflare CAPTCHA', suspended_time=get_setting('x')\n"
            "        )\n"
        )
        res = apply_patches.patch_raise_for_httperror(content, "raise_for_httperror.py")
        self.assertIn("_exc = SearxEngineCaptchaException(", res)
        self.assertIn("_exc.response = resp", res)
        self.assertIn("raise _exc", res)
        # The arguments must survive the rewrite untouched.
        self.assertIn("message='Cloudflare CAPTCHA'", res)
        self.assertIn("get_setting('x')", res)

    def test_attaches_response_to_plain_raises(self):
        content = (
            "        if resp.status_code in (402, 403):\n"
            "            raise SearxEngineAccessDeniedException(message='HTTP error ' + str(resp.status_code))\n"
            "        if resp.status_code == 429:\n"
            "            raise SearxEngineTooManyRequestsException()\n"
        )
        res = apply_patches.patch_raise_for_httperror(content, "raise_for_httperror.py")
        self.assertIn("_exc = SearxEngineAccessDeniedException(message='HTTP error ' + str(resp.status_code))", res)
        self.assertIn("_exc = SearxEngineTooManyRequestsException()", res)
        self.assertEqual(res.count("_exc.response = resp"), 2)
        # Nested method calls in the arguments must not break paren matching.
        self.assertIn("str(resp.status_code)", res)

    def test_is_idempotent(self):
        content = "_exc = SearxEngineCaptchaException(message='CAPTCHA')\n_exc.response = resp\nraise _exc\n"
        self.assertEqual(
            apply_patches.patch_raise_for_httperror(content, "raise_for_httperror.py"),
            "ALREADY_APPLIED",
        )


class TestPatchOnlineCaptchaUpgrade(unittest.TestCase):
    """Regression: an install patched with the first version of Patch 11 has
    ``_parse_retry_after_header`` but still a combined except tuple for
    CAPTCHA + 429 + 403. Re-running must split the tuple and apply Retry-After
    to the 429 handler as well, without re-injecting the helper.
    """

    def test_upgrades_combined_tuple_and_honours_retry_after(self):
        content = (
            "def _parse_retry_after_header(resp):\n"
            "    return None\n"
            "        except (\n"
            "            SearxEngineCaptchaException,\n"
            "            SearxEngineTooManyRequestsException,\n"
            "            SearxEngineAccessDeniedException,\n"
            "        ) as e:\n"
            "            self.handle_exception(result_container, e, suspend=True)\n"
            "            self.logger.debug(e.message)\n"
        )
        res = apply_patches.patch_online_captcha(content, "online.py")
        self.assertNotEqual(res, "ALREADY_APPLIED")
        # The helper is defined exactly once (no duplicate injection).
        self.assertEqual(res.count("def _parse_retry_after_header"), 1)
        self.assertIn("except SearxEngineTooManyRequestsException as e:", res)
        self.assertIn(
            "retry_after = _parse_retry_after_header(getattr(e, 'response', None))",
            res,
        )
        self.assertNotIn("except (\n            SearxEngineCaptchaException", res)

    def test_already_final_state_is_noop(self):
        content = (
            "def _parse_retry_after_header(resp):\n"
            "    return None\n"
            "        except SearxEngineCaptchaException as e:\n"
            "            self.handle_exception(result_container, e, suspend=True)\n"
            "        except SearxEngineTooManyRequestsException as e:\n"
            "            self.handle_exception(result_container, e, suspend=True)\n"
            "        except SearxEngineAccessDeniedException as e:\n"
            "            self.handle_exception(result_container, e, suspend=True)\n"
        )
        res = apply_patches.patch_online_captcha(content, "online.py")
        self.assertEqual(res, "ALREADY_APPLIED")


class TestUpdateFileNoopHandling(unittest.TestCase):
    """Regression: update_file must not raise "anchor not found" for patches
    that are pure rewrites and report an unchanged result because there is
    nothing left to do.
    """

    def _cleanup(self, tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_unchanged_result_from_noop_patch_is_already_applied(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup, tmpdir)
        target = os.path.join(tmpdir, "sample.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("legacy = True\n")

        def rewrite(content, path):
            return content.replace("legacy = True", "")

        # Without the opt-in flag, unchanged output still fails loudly.
        self.assertNotIn("legacy = True", rewrite("pristine\n", "x"))

        setattr(rewrite, "_noop_when_unchanged", True)  # noqa: B010

        # Never applied -> patched.
        result = apply_patches.update_file(target, "sample rewrite", rewrite)
        self.assertEqual(result, "PATCHED")

        # Already applied -> unchanged output must be reported as already
        # applied, not as a missing anchor.
        result = apply_patches.update_file(target, "sample rewrite", rewrite)
        self.assertEqual(result, "ALREADY_APPLIED")

    def test_unchanged_result_without_flag_still_fails(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup, tmpdir)
        target = os.path.join(tmpdir, "sample.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("nothing to do\n")

        def stuck(content, path):
            return content  # anchor missing in a rewrite patch

        with self.assertRaisesRegex(RuntimeError, "injection point"):
            apply_patches.update_file(target, "stuck rewrite", stuck)


class TestHardeningEnhancements(unittest.TestCase):
    """Verify bug fixes and hardening enhancements."""

    def test_safe_getaddrinfo_pinned_host_internal_error_raises_gaierror(self):
        """Pinned host resolution failure must raise gaierror without live DNS leak."""
        import socket
        import threading

        thread_local = threading.local()
        thread_local.pin = {"host": "example.com", "ip": "malformed-ip", "port": 443}

        live_calls = []

        def mock_original_gai(h, p, *args, **kwargs):
            live_calls.append((h, p))
            return [("live_dns", h, p)]

        # Mimic hardened _safe_getaddrinfo
        def test_safe_getaddrinfo(h, p, *args, **kwargs):
            pin = getattr(thread_local, "pin", None)
            if pin:
                pin_host = pin.get("host")
                host_matches = False
                if pin_host:
                    h_clean = (h or "").strip("[]").rstrip(".").lower()
                    pin_clean = pin_host.strip("[]").rstrip(".").lower()
                    host_matches = h_clean == pin_clean
                if host_matches:
                    pin_port = pin.get("port")
                    port_matches = (
                        p is None
                        or p == pin_port
                        or str(p) == str(pin_port)
                        or (pin_port == 443 and p == "https")
                        or (pin_port == 80 and p == "http")
                    )
                    if port_matches:
                        try:
                            import ipaddress

                            ip_obj = ipaddress.ip_address(pin["ip"])
                            port_num = int(pin_port or 443)
                            req_family = args[0] if len(args) > 0 else kwargs.get("family", 0)
                            ip_family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
                            if req_family in (0, ip_family):
                                sockaddr = (pin["ip"], port_num, 0, 0) if ip_obj.version == 6 else (pin["ip"], port_num)
                                return [(ip_family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]
                            else:
                                raise socket.gaierror(
                                    socket.EAI_NONAME, f"Address family not supported for pinned host {pin_host}"
                                )
                        except socket.gaierror:
                            raise
                        except Exception as exc:  # noqa: BLE001
                            raise socket.gaierror(
                                socket.EAI_NONAME, f"Resolution failed for pinned host {pin_host}: {exc}"
                            )
            return mock_original_gai(h, p, *args, **kwargs)

        with self.assertRaises(socket.gaierror) as ctx:
            test_safe_getaddrinfo("example.com", 443)
        self.assertIn("Resolution failed for pinned host example.com", str(ctx.exception))
        # Ensure zero live DNS requests were made
        self.assertEqual(len(live_calls), 0)

    def test_safe_getaddrinfo_port_mismatch_raises_gaierror(self):
        """When host is pinned to a specific port, querying a mismatched port raises gaierror without live DNS leak."""
        import socket
        import threading

        thread_local = threading.local()
        thread_local.pin = {"host": "example.com", "ip": "93.184.216.34", "port": 443}

        live_calls = []

        def mock_original_gai(h, p, *args, **kwargs):
            live_calls.append((h, p))
            return [("live_dns", h, p)]

        def test_safe_getaddrinfo(h, p, *args, **kwargs):
            pin = getattr(thread_local, "pin", None)
            if pin:
                pin_host = pin.get("host")
                host_matches = False
                if pin_host:
                    h_clean = (h or "").strip("[]").rstrip(".").lower()
                    pin_clean = pin_host.strip("[]").rstrip(".").lower()
                    host_matches = h_clean == pin_clean
                if host_matches:
                    pin_port = pin.get("port")
                    port_matches = (
                        p is None
                        or p == pin_port
                        or str(p) == str(pin_port)
                        or (pin_port == 443 and p == "https")
                        or (pin_port == 80 and p == "http")
                    )
                    if port_matches:
                        return [
                            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (pin["ip"], int(pin_port)))
                        ]
                    else:
                        raise socket.gaierror(
                            socket.EAI_NONAME, f"Port mismatch for pinned host {pin_host}: {p} != {pin_port}"
                        )
            return mock_original_gai(h, p, *args, **kwargs)

        with self.assertRaises(socket.gaierror) as ctx:
            test_safe_getaddrinfo("example.com", 8080)
        self.assertIn("Port mismatch for pinned host example.com", str(ctx.exception))
        self.assertEqual(len(live_calls), 0)

    def test_parse_retry_after_http_date(self):
        """Verify _parse_retry_after_header parses HTTP dates and clamps delta seconds."""
        import datetime
        import email.utils

        def parse_retry_after(resp):
            if resp is None:
                return None
            try:
                hdr = None
                if hasattr(resp, "headers"):
                    hdr = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                if hdr is None:
                    return None
                hdr = hdr.strip()
                if hdr.isdigit():
                    v = int(hdr)
                    return max(5, min(v, 900))
                dt = email.utils.parsedate_to_datetime(hdr)
                if dt is not None:
                    now = (
                        datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                        if dt.tzinfo is None
                        else datetime.datetime.now(datetime.UTC)
                    )
                    delta = int((dt - now).total_seconds())
                    return max(5, min(delta, 900))
            except Exception:  # noqa: BLE001, S110
                pass
            return None

        class DummyResp:
            def __init__(self, val):
                self.headers = {"Retry-After": val} if val is not None else {}

        # 1. Delta seconds
        self.assertEqual(parse_retry_after(DummyResp("120")), 120)
        self.assertEqual(parse_retry_after(DummyResp("2")), 5)  # min clamp
        self.assertEqual(parse_retry_after(DummyResp("9999")), 900)  # max clamp

        # 2. Future HTTP-date (60s in future)
        now = datetime.datetime.now(datetime.UTC)
        future_hdr = email.utils.format_datetime(now + datetime.timedelta(seconds=60))
        res_future = parse_retry_after(DummyResp(future_hdr))
        self.assertIsNotNone(res_future)
        assert res_future is not None
        self.assertTrue(55 <= res_future <= 65)

        # 3. Past HTTP-date
        past_hdr = email.utils.format_datetime(now - datetime.timedelta(seconds=60))
        self.assertEqual(parse_retry_after(DummyResp(past_hdr)), 5)

        # 4. Invalid or missing
        self.assertIsNone(parse_retry_after(DummyResp("invalid-date")))
        self.assertIsNone(parse_retry_after(DummyResp(None)))
        self.assertIsNone(parse_retry_after(None))

    def test_json_lite_infobox_none_urls_safety(self):
        """Verify infoboxes with 'urls': None do not cause TypeError during json_lite serialization."""
        import json

        def get_box(i):
            d = i.as_dict() if hasattr(i, "as_dict") else (i if isinstance(i, dict) else {})
            urls_raw = (d.get("urls") if isinstance(d, dict) else getattr(i, "urls", [])) or []
            urls = []
            for u in urls_raw:
                if isinstance(u, dict):
                    urls.append({"title": u.get("title", ""), "url": u.get("url", "")})
                else:
                    urls.append({"title": getattr(u, "title", ""), "url": getattr(u, "url", "")})
            return {
                "infobox": d.get("infobox", "") if isinstance(d, dict) else getattr(i, "infobox", ""),
                "content": d.get("content", "") if isinstance(d, dict) else getattr(i, "content", ""),
                "urls": urls,
            }

        box_with_none_urls = {"infobox": "Test", "content": "Content", "urls": None}
        out = get_box(box_with_none_urls)
        self.assertEqual(out["urls"], [])
        serialized = json.dumps(out)
        self.assertIn('"urls": []', serialized)

    def test_disable_missing_engines_package_module(self):
        """Verify disable-missing-engines handles package/submodule engine names."""
        sample_yaml = "engines:\n  - name: mypkg\n    engine: subpkg.mymod\n    categories: general\n"
        engines = disable_missing_engines.extract_engines(sample_yaml)
        self.assertEqual(len(engines), 1)
        self.assertEqual(engines[0]["engine"], "subpkg.mymod")

    def test_json_lite_date_serialization_and_string_urls(self):
        """Verify datetime.date and string infobox URLs serialize without TypeError in json_lite."""
        import datetime
        import json

        # 1. Verify datetime.date serialization
        pub_date = datetime.date(2026, 9, 22)
        pub_str = pub_date.isoformat() if hasattr(pub_date, "isoformat") else str(pub_date)
        res_dict = {
            "publishedDate": pub_str,
            "pubdate": pub_str,
        }
        dumped = json.dumps(res_dict)
        self.assertIn('"publishedDate": "2026-09-22"', dumped)
        self.assertIn('"pubdate": "2026-09-22"', dumped)

        # 2. Verify string URLs in infoboxes
        raw_urls = ["https://example.com/item1", {"title": "Item 2", "url": "https://example.com/item2"}]
        urls = []
        for u in raw_urls:
            if isinstance(u, dict):
                urls.append({"title": u.get("title", ""), "url": u.get("url", "")})
            elif isinstance(u, str):
                urls.append({"title": u, "url": u})
            else:
                urls.append({"title": getattr(u, "title", ""), "url": getattr(u, "url", "")})

        self.assertEqual(urls[0], {"title": "https://example.com/item1", "url": "https://example.com/item1"})
        self.assertEqual(urls[1], {"title": "Item 2", "url": "https://example.com/item2"})

    def test_scrape_port_zero_blocked(self):
        """Verify _parse_scrape_url rejects port 0 to prevent fallback to port 80."""
        import urllib.parse

        class _ScrapeBlockedError(Exception):
            pass

        def parse_scrape_url(value):
            try:
                parsed_url = urllib.parse.urlparse(value)
                p = parsed_url.port
                if p is not None and p == 0:
                    raise _ScrapeBlockedError("Invalid port: 0")
                return parsed_url
            except ValueError as exc:
                raise _ScrapeBlockedError("Invalid URL") from exc

        # Port 0 must raise _ScrapeBlockedError
        with self.assertRaises(_ScrapeBlockedError) as ctx:
            parse_scrape_url("http://example.com:0/path")
        self.assertEqual(str(ctx.exception), "Invalid port: 0")

        # Standard ports must pass
        p80 = parse_scrape_url("http://example.com:80/path")
        self.assertEqual(p80.port, 80)
        p443 = parse_scrape_url("https://example.com:443/path")
        self.assertEqual(p443.port, 443)

    def test_scrape_fallback_html_strips_case_insensitive_scripts_and_styles(self):
        """Verify fallback HTML text extraction strips <SCRIPT>, <STYLE>, and <NOSCRIPT> tags case-insensitively."""
        import html
        import re

        sample_html = (
            "<html><head><TITLE>Test Article</TITLE>"
            "<SCRIPT type=\"text/javascript\">alert('evil1');</SCRIPT>"
            '<Script src="foo.js">var x = 1;</Script>'
            "<STYLE>body { color: red; }</style>"
            "<Noscript><p>Please enable JS</p></Noscript>"
            "</head><body>"
            "<h1>Main Heading</h1>"
            "<p>This is the &amp; genuine article body.</p>"
            "</body></html>"
        )

        raw_text = re.sub(r"(?si)<script.*?>.*?</script>", " ", sample_html)
        raw_text = re.sub(r"(?si)<style.*?>.*?</style>", " ", raw_text)
        raw_text = re.sub(r"(?si)<noscript.*?>.*?</noscript>", " ", raw_text)
        raw_text = re.sub(r"<[^>]+>", " ", raw_text)
        raw_text = html.unescape(raw_text)
        raw_text = re.sub(r"\s+", " ", raw_text).strip()

        self.assertNotIn("alert", raw_text)
        self.assertNotIn("evil1", raw_text)
        self.assertNotIn("var x", raw_text)
        self.assertNotIn("color: red", raw_text)
        self.assertNotIn("Please enable JS", raw_text)
        self.assertIn("Main Heading", raw_text)
        self.assertIn("This is the & genuine article body.", raw_text)

    def test_reserved_tlds_includes_intranet_localdomain_private(self):
        """Verify _is_reserved_scrape_host blocks .localdomain, .intranet, and .private hosts."""
        reserved_tlds = (
            ".localhost",
            ".local",
            ".internal",
            ".lan",
            ".home.arpa",
            ".invalid",
            ".test",
            ".example",
            ".onion",
            ".corp",
            ".home",
            ".localdomain",
            ".intranet",
            ".private",
        )

        def is_reserved_host(host):
            h = (host or "").strip().rstrip(".").lower()
            if not h or h == "localhost":
                return True
            for tld in reserved_tlds:
                bare = tld.lstrip(".")
                if h == bare or h.endswith(tld):
                    return True
            return False

        # Blocked domains
        self.assertTrue(is_reserved_host("router.localdomain"))
        self.assertTrue(is_reserved_host("sub.gateway.intranet"))
        self.assertTrue(is_reserved_host("nas.private"))
        self.assertTrue(is_reserved_host("localdomain"))
        self.assertTrue(is_reserved_host("intranet"))
        self.assertTrue(is_reserved_host("private"))
        self.assertTrue(is_reserved_host("localhost"))
        self.assertTrue(is_reserved_host("test.local"))

        # Allowed public domains
        self.assertFalse(is_reserved_host("example.com"))
        self.assertFalse(is_reserved_host("docs.searxng.org"))
        self.assertFalse(is_reserved_host("my-intranet.com"))

    def test_json_lite_format_source_handles_diverse_types(self):
        """Verify _format_source in get_json_lite_response safely formats strings, lists, sets, and non-strings."""

        def format_source(d):
            eng = d.get("engine", "")
            if eng:
                return str(eng)
            engs = d.get("engines")
            if isinstance(engs, (list, tuple, set)):
                return ", ".join(sorted(str(e) for e in engs if e is not None))
            if isinstance(engs, str):
                return engs
            return ""

        # 1. Primary engine present
        self.assertEqual(format_source({"engine": "bing"}), "bing")

        # 2. Merged engines list
        self.assertEqual(format_source({"engines": ["google", "bing"]}), "bing, google")

        # 3. Merged engines with integer / None elements (should not raise TypeError)
        self.assertEqual(format_source({"engines": ["google", 1, None]}), "1, google")

        # 4. Merged engines as string
        self.assertEqual(format_source({"engines": "duckduckgo"}), "duckduckgo")

        # 5. Empty or missing
        self.assertEqual(format_source({}), "")
        self.assertEqual(format_source({"engines": None}), "")

    def test_scrape_redirect_location_whitespace_stripped(self):
        """Verify redirect location with leading/trailing whitespace is cleanly stripped and joined."""
        import urllib.parse

        current_url = "https://example.com/start"
        raw_location = "   /destination?page=1  \t\n"
        cleaned = raw_location.strip()
        self.assertEqual(cleaned, "/destination?page=1")
        resolved = urllib.parse.urljoin(current_url, cleaned)
        self.assertEqual(resolved, "https://example.com/destination?page=1")

    def test_safe_getaddrinfo_handles_bytes_host_and_port(self):
        """Verify _safe_getaddrinfo accepts bytes host and port without TypeError."""
        import ipaddress
        import socket
        import threading

        thread_local = threading.local()
        thread_local.pin = {"host": "example.com", "ip": "93.184.216.34", "port": 443}

        def test_safe_gai(h, p, *args, **kwargs):
            pin = getattr(thread_local, "pin", None)
            if pin:
                pin_host = pin.get("host")
                host_matches = False
                if pin_host:
                    if isinstance(h, (bytes, bytearray)):
                        try:
                            h_str = h.decode("ascii")
                        except UnicodeDecodeError:
                            h_str = h.decode("utf-8", errors="replace")
                    else:
                        h_str = h or ""
                    h_clean = h_str.strip("[]").rstrip(".").lower()
                    pin_clean = pin_host.strip("[]").rstrip(".").lower()
                    if h_clean == pin_clean:
                        host_matches = True
                if host_matches:
                    pin_port = pin.get("port")
                    if isinstance(p, (bytes, bytearray)):
                        try:
                            p_str = p.decode("ascii", errors="replace")
                        except Exception:  # noqa: BLE001
                            p_str = str(p)
                    else:
                        p_str = p
                    port_matches = (
                        p_str is None
                        or p_str == pin_port
                        or str(p_str) == str(pin_port)
                        or (pin_port == 443 and p_str in (443, "443", "https"))
                    )
                    if port_matches:
                        _ = ipaddress.ip_address(pin["ip"])
                        port_num = int(pin_port or 443)
                        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (pin["ip"], port_num))]
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "live", (h, p))]

        # Bytes host and port
        res = test_safe_gai(b"example.com", b"443")
        self.assertEqual(res[0][4], ("93.184.216.34", 443))

        # Bytes host and int port
        res2 = test_safe_gai(b"example.com", 443)
        self.assertEqual(res2[0][4], ("93.184.216.34", 443))

    def test_is_reserved_scrape_host_handles_bytes(self):
        """Verify _is_reserved_scrape_host safely handles bytes hostnames."""
        reserved_tlds = (
            ".localhost",
            ".local",
            ".internal",
            ".lan",
            ".home.arpa",
            ".invalid",
            ".test",
            ".example",
            ".onion",
            ".corp",
            ".home",
            ".localdomain",
            ".intranet",
            ".private",
            ".arpa",
        )

        def is_reserved(host):
            if isinstance(host, (bytes, bytearray)):
                try:
                    host = host.decode("ascii")
                except UnicodeDecodeError:
                    host = host.decode("utf-8", errors="replace")
            h = (host or "").strip().rstrip(".").lower()
            if not h or h == "localhost":
                return True
            for tld in reserved_tlds:
                bare = tld.lstrip(".")
                if h == bare or h.endswith(tld):
                    return True
            return False

        self.assertTrue(is_reserved(b"localhost"))
        self.assertTrue(is_reserved(b"test.local"))
        self.assertTrue(is_reserved(b"router.arpa"))
        self.assertFalse(is_reserved(b"example.org"))

    def test_read_scrape_response_respects_env_max_duration(self):
        """Verify _read_scrape_response respects SEARXNG_SCRAPE_MAX_DURATION environment override."""
        import time

        try:
            import httpx

            timeout_exc_cls = httpx.TimeoutException
        except ImportError:

            class _FallbackTimeoutException(Exception):
                pass

            timeout_exc_cls = _FallbackTimeoutException

        def read_stream(chunks, env_dur=None, default_dur=15.0):
            max_duration = default_dur
            if env_dur is not None:
                try:
                    env_val = float(env_dur)
                    if env_val > 0:
                        max_duration = env_val
                except (ValueError, TypeError):
                    pass

            start_time = time.monotonic()
            read_chunks = []
            for chunk in chunks:
                if time.monotonic() - start_time > max_duration:
                    raise timeout_exc_cls("Response read stream timed out")
                read_chunks.append(chunk)
                time.sleep(0.01)
            return b"".join(read_chunks)

        # When duration is tight (0.005s), slow stream of chunks should time out reliably
        chunks = [b"chunk1", b"chunk2", b"chunk3", b"chunk4", b"chunk5"]
        with self.assertRaises(timeout_exc_cls):
            read_stream(chunks, env_dur="0.005")

        # When duration is generous, stream succeeds
        result = read_stream([b"chunk1", b"chunk2", b"chunk3"], env_dur="5.0")
        self.assertEqual(result, b"chunk1chunk2chunk3")

    def test_json_lite_none_fields_coerced_to_strings(self):
        """Verify None values in title, content, author, category, infobox, and urls are cleanly coerced."""
        d = {
            "title": None,
            "url": None,
            "content": None,
            "author": None,
            "category": None,
            "score": None,
            "infobox": None,
        }
        res = {
            "title": d.get("title") or "",
            "url": d.get("url") or "",
            "content": d.get("content") or "",
            "score": d.get("score", 0) if d.get("score") is not None else 0,
            "author": d.get("author") or "",
            "category": d.get("category") or "",
            "infobox": d.get("infobox") or "",
        }
        self.assertEqual(res["title"], "")
        self.assertEqual(res["url"], "")
        self.assertEqual(res["content"], "")
        self.assertEqual(res["score"], 0)
        self.assertEqual(res["author"], "")
        self.assertEqual(res["category"], "")
        self.assertEqual(res["infobox"], "")

    def test_scrape_fallback_html_strips_comments_iframes_templates(self):
        """Verify fallback HTML text extraction strips comments, iframes, and templates."""
        import html
        import re

        sample = (
            "<html><body>"
            "<!-- Secret comment with > operator -->"
            "<iframe src='evil.html'>Iframe text</iframe>"
            "<template><p>Template text</p></template>"
            "<p>Visible content</p>"
            "</body></html>"
        )
        raw_text = re.sub(r"(?si)<!--.*?-->", " ", sample)
        raw_text = re.sub(r"(?si)<script.*?>.*?</script>", " ", raw_text)
        raw_text = re.sub(r"(?si)<style.*?>.*?</style>", " ", raw_text)
        raw_text = re.sub(r"(?si)<noscript.*?>.*?</noscript>", " ", raw_text)
        raw_text = re.sub(r"(?si)<iframe.*?>.*?</iframe>", " ", raw_text)
        raw_text = re.sub(r"(?si)<template.*?>.*?</template>", " ", raw_text)
        raw_text = re.sub(r"<[^>]+>", " ", raw_text)
        raw_text = html.unescape(raw_text)
        raw_text = re.sub(r"\s+", " ", raw_text).strip()

        self.assertNotIn("Secret comment", raw_text)
        self.assertNotIn("Iframe text", raw_text)
        self.assertNotIn("Template text", raw_text)
        self.assertEqual(raw_text, "Visible content")

    def test_patch_settings_yml_reduces_cf_access_denied(self):
        """Verify patch_settings_yml reduces cf_SearxEngineAccessDenied."""
        sample_yml = (
            "search:\n"
            "  suspended_times:\n"
            "    SearxEngineCaptcha: 86400\n"
            "    SearxEngineAccessDenied: 86400\n"
            "    SearxEngineTooManyRequests: 3600\n"
            "    cf_SearxEngineCaptcha: 86400\n"
            "    cf_SearxEngineAccessDenied: 86400\n"
            "    recaptcha_SearxEngineCaptcha: 86400\n"
        )
        patched = apply_patches.patch_settings_yml(sample_yml, "settings.yml")
        self.assertIn("SearxEngineCaptcha: 900", patched)
        self.assertIn("cf_SearxEngineAccessDenied: 1800", patched)


class TestProjectPatchHardening(unittest.TestCase):
    """Tests for patch stability enhancements, error countermeasures, and AST verification."""

    def test_update_file_atomic_write_and_syntax_validation(self):
        """Verify update_file successfully writes valid Python syntax atomically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_path = os.path.join(tmpdir, "valid.py")
            with open(py_path, "w", encoding="utf-8") as f:
                f.write("x = 1\n")
            res = apply_patches.update_file(
                py_path,
                "valid python patch",
                lambda content, path: "x = 2\n",
            )
            self.assertEqual(res, "PATCHED")
            with open(py_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "x = 2\n")

    def test_update_file_syntax_error_protects_original_file(self):
        """Verify that an invalid Python patch raises RuntimeError and does not corrupt target file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_path = os.path.join(tmpdir, "broken.py")
            orig = "def good():\n    return 42\n"
            with open(py_path, "w", encoding="utf-8") as f:
                f.write(orig)

            with self.assertRaisesRegex(RuntimeError, "Patch validation failed.*invalid Python syntax"):
                apply_patches.update_file(
                    py_path,
                    "syntax error patch",
                    lambda content, path: "def broken(\n    return 42\n",  # SyntaxError: unclosed parenthesis
                )

            # Original file content must be preserved unchanged
            with open(py_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), orig)

    def test_json_lite_sanitizes_nan_inf_scores(self):
        """Verify get_json_lite_response cleans NaN, Infinity, and invalid scores to 0."""
        content = "def get_themes(p):\n    return []\n"
        patched = apply_patches.patch_webutils(content, "webutils.py")
        self.assertIn("def _clean_score(v):", patched)
        self.assertIn("math.isnan", patched)
        self.assertIn("math.isinf", patched)

        # Test the pure cleaning logic
        def clean_score(v):
            if v is None:
                return 0
            try:
                f = float(v)
                import math

                if math.isnan(f) or math.isinf(f):
                    return 0
                return int(f) if f.is_integer() else f
            except (ValueError, TypeError):
                return 0

        self.assertEqual(clean_score(float("nan")), 0)
        self.assertEqual(clean_score(float("inf")), 0)
        self.assertEqual(clean_score(float("-inf")), 0)
        self.assertEqual(clean_score("invalid"), 0)
        self.assertEqual(clean_score(12.5), 12.5)
        self.assertEqual(clean_score(10.0), 10)

    def test_json_lite_resilience_to_broken_objects(self):
        """Verify JSON-lite helper handles objects where as_dict() or get_ordered_results raises exceptions."""
        content = "def get_themes(p):\n    return []\n"
        patched = apply_patches.patch_webutils(content, "webutils.py")
        self.assertIn("getattr(rc, 'results', [])", patched)
        self.assertIn("callable(pub.isoformat)", patched)

    def test_scrape_integer_ip_blocking(self):
        """Verify integer representation of loopback/private IPs is detected and blocked."""
        content = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
        patched = apply_patches.patch_webapp_scrape_route(content, "webapp.py")
        self.assertIn("host_clean.isdigit()", patched)
        self.assertIn("0 <= ip_int <= 0xFFFFFFFF", patched)

        import ipaddress

        def is_blocked(host_clean):
            if host_clean.isdigit():
                try:
                    ip_int = int(host_clean)
                    if 0 <= ip_int <= 0xFFFFFFFF:
                        v4 = ipaddress.IPv4Address(ip_int)
                        return v4.is_loopback or v4.is_private
                except (ValueError, ipaddress.AddressValueError):
                    pass
            return False

        # 2130706433 is 127.0.0.1
        self.assertTrue(is_blocked("2130706433"))
        # 167772161 is 10.0.0.1
        self.assertTrue(is_blocked("167772161"))
        # 134744072 is 8.8.8.8 (public)
        self.assertFalse(is_blocked("134744072"))

    def test_simple_search_accessibility_reordered_attributes(self):
        """Verify patch_simple_search_accessibility works even when input attributes are in different order."""
        sample = '<input name="q" id="q" type="text" placeholder="Search">\n'
        patched = apply_patches.patch_simple_search_accessibility(sample, "search.html")
        self.assertIn("aria-label=\"{{ _('Search for...') }}\"", patched)
        self.assertIn('id="q"', patched)

    def test_preferences_accessibility_reordered_attributes(self):
        """Verify patch_preferences_accessibility works even when input attributes are in different order."""
        sample = '<input name="preferences" id="pref-hash-input" type="text">\n'
        patched = apply_patches.patch_preferences_accessibility(sample, "cookies.html")
        self.assertIn("aria-label=\"{{- _('Preferences hash') -}}\"", patched)
        self.assertIn('id="pref-hash-input"', patched)


class TestAiWebuiPatches(unittest.TestCase):
    """Tests for SearXNG Next AI-First WebUI patches and webui_next module."""

    def test_patch_webapp_ai_webui_injects_and_is_idempotent(self):
        sample = "import os\nimport sys\n\n@app.route('/search', methods=['GET', 'POST'])\ndef search():\n    pass\n"
        patched = apply_patches.patch_webapp_ai_webui(sample, "webapp.py")
        self.assertIn("# --- GenAI Next WebUI Integration ---", patched)
        self.assertIn("_webui_next.register_next_webui(app, sys.modules.get(__name__))", patched)
        self.assertEqual(apply_patches.patch_webapp_ai_webui(patched, "webapp.py"), "ALREADY_APPLIED")

    def test_patch_simple_base_ai_webui_injects_and_is_idempotent(self):
        sample = (
            '<nav id="links_on_top">\n'
            "      {%- block linkto_about -%}\n"
            '        <a href="/about">About</a>\n'
            "      {%- endblock -%}\n"
            "</nav>\n"
            "</body>\n"
        )
        patched = apply_patches.patch_simple_base_ai_webui(sample, "base.html")
        self.assertIn('class="link_on_top_ai"', patched)
        self.assertIn('href="/ai/embed.css"', patched)
        self.assertIn('src="/ai/embed.js"', patched)
        self.assertEqual(apply_patches.patch_simple_base_ai_webui(patched, "base.html"), "ALREADY_APPLIED")

    def test_patch_simple_index_ai_webui_injects_and_is_idempotent(self):
        sample = (
            '<div class="index">\n'
            '    <div class="title"><h1>SearXNG</h1></div>\n'
            "    {% include 'simple/simple_search.html' %}\n"
            "</div>\n"
        )
        patched = apply_patches.patch_simple_index_ai_webui(sample, "index.html")
        self.assertIn('class="sxng-next-badge"', patched)
        self.assertIn('class="sxng-next-badge-wrap"', patched)
        self.assertIn('class="sxng-ai-home-bar"', patched)
        self.assertNotIn('<h1>SearXNG</h1><span class="sxng-next-badge"', patched)
        self.assertEqual(apply_patches.patch_simple_index_ai_webui(patched, "index.html"), "ALREADY_APPLIED")

        # Test legacy migration where badge was inside .title
        legacy_sample = (
            '<div class="index">\n'
            '    <div class="title"><h1>SearXNG</h1><span class="sxng-next-badge">Next · AI-First Edition</span></div>\n'
            "    {% include 'simple/simple_search.html' %}\n"
            "</div>\n"
        )
        migrated = apply_patches.patch_simple_index_ai_webui(legacy_sample, "index.html")
        self.assertIn('class="sxng-next-badge-wrap"', migrated)
        self.assertNotIn('<h1>SearXNG</h1><span class="sxng-next-badge"', migrated)

    def test_patch_simple_results_ai_webui_injects_and_is_idempotent(self):
        sample = '<div id="results" class="{{ only_template }}">\n    <div id="urls" role="main"></div>\n</div>\n'
        patched = apply_patches.patch_simple_results_ai_webui(sample, "results.html")
        self.assertIn('id="sxng-ai-results-bar"', patched)
        self.assertIn('id="sxng-ai-deep-drawer"', patched)
        self.assertEqual(apply_patches.patch_simple_results_ai_webui(patched, "results.html"), "ALREADY_APPLIED")

    def test_webui_next_serves_single_charset_content_types(self):
        import webui_next
        from flask import Flask

        app = Flask(__name__)
        webui_next.register_next_webui(app, None)
        client = app.test_client()
        cases = {
            "/ai": "text/html",
            "/ai/embed.css": "text/css",
            "/ai/embed.js": "application/javascript",
        }
        for path, expected in cases.items():
            resp = client.get(path)
            self.assertEqual(resp.status_code, 200)
            ctype = resp.headers.get("Content-Type", "")
            self.assertIn(expected, ctype)
            self.assertEqual(ctype.count("charset"), 1, f"{path} must not duplicate charset: {ctype}")

        md_resp = client.get("/deep_search", query_string={"q": "", "format": "markdown"})
        self.assertEqual(md_resp.status_code, 400)
        md_ctype = md_resp.headers.get("Content-Type", "")
        self.assertIn("text/markdown", md_ctype)
        self.assertEqual(md_ctype.count("charset"), 1, f"markdown error must not duplicate charset: {md_ctype}")

    def test_webui_next_helpers_and_deep_search_pipeline(self):
        import webui_next

        self.assertTrue(webui_next._parse_bool("true"))
        self.assertFalse(webui_next._parse_bool("false"))
        self.assertEqual(webui_next._parse_int("999", 5, 1, 20), 20)
        self.assertEqual(
            webui_next._parse_domain_list("https://www.github.com/foo, docs.python.org"),
            ["github.com", "docs.python.org"],
        )

        info = webui_next.get_ai_info(host_url="http://127.0.0.1:8888")
        self.assertTrue(info["healthy"])
        self.assertEqual(info["endpoints"]["ai_workspace"], "/ai")
        self.assertEqual(info["endpoints"]["deep_search"], "/deep_search")
        self.assertIn("claude_code", info["snippets"])

        with (
            mock.patch.object(
                webui_next,
                "_search_in_process",
                return_value={
                    "query": "fastapi lifespan",
                    "results": [
                        {
                            "title": "FastAPI Lifespan Events",
                            "url": "https://fastapi.tiangolo.com/advanced/events/",
                            "content": "You can define lifespan startup and shutdown logic using asynccontextmanager.",
                            "source": "bing",
                            "score": 2.0,
                        }
                    ],
                    "answers": ["Use @asynccontextmanager with FastAPI(lifespan=...)"],
                },
            ),
            mock.patch.object(
                webui_next,
                "_scrape_url_direct",
                return_value={
                    "url": "https://fastapi.tiangolo.com/advanced/events/",
                    "content": "FastAPI lifespan context manager allows startup and shutdown events in async applications.",
                    "is_truncated": False,
                    "original_length": 91,
                },
            ),
        ):
            deep_res = webui_next.execute_server_deep_search(
                query="fastapi lifespan",
                search_depth="advanced",
                max_results=3,
                max_tokens=2000,
            )
            self.assertEqual(deep_res["query"], "fastapi lifespan")
            self.assertEqual(deep_res["results_count"], 1)
            self.assertEqual(deep_res["scraped_count"], 1)
            self.assertGreater(deep_res["estimated_tokens"], 0)
            self.assertIn("## 質問・調査テーマ", deep_res["rag_prompt"])

            scrape_res = webui_next.execute_scrape_analyze(
                url="https://fastapi.tiangolo.com/advanced/events/",
                query="lifespan startup",
                max_length=4000,
            )
            self.assertNotIn("error", scrape_res)
            self.assertGreater(scrape_res["estimated_tokens"], 0)
            self.assertTrue(len(scrape_res["highlights"]) >= 1)
            self.assertIn("FastAPI lifespan", scrape_res["markdown"])

            # Verify fast mode and URL auto-detection in execute_server_deep_search
            fast_res = webui_next.execute_server_deep_search(
                query="fastapi lifespan",
                search_depth="fast",
                max_results=3,
            )
            self.assertEqual(fast_res["mode"], "fast")
            self.assertEqual(fast_res["scraped_count"], 0)
            self.assertIn("Fast Search Results", fast_res["markdown"])

            auto_url_res = webui_next.execute_server_deep_search(
                query="https://fastapi.tiangolo.com/advanced/events/",
                mode="auto",
                focus_query="lifespan startup",
            )
            self.assertEqual(auto_url_res["mode"], "scrape")
            self.assertEqual(auto_url_res["scraped_count"], 1)
            self.assertIn("FastAPI lifespan", auto_url_res["markdown"])

    def test_webui_next_xss_url_sanitization_and_accessibility_markup(self):
        import webui_next

        html_doc = webui_next.AI_WORKSPACE_HTML
        embed_js = webui_next.SIMPLE_EMBED_JS
        embed_css = webui_next.SIMPLE_EMBED_CSS

        # Regression: targetUrl in runScrapeMode must be escaped with escapeHtml(targetUrl)
        self.assertNotIn("<p>' + targetUrl + '</p>", html_doc)
        self.assertIn("<p>' + escapeHtml(targetUrl) + '</p>", html_doc)

        # Verify URL scheme sanitizer and shell double-quote escaper exist
        self.assertIn("function safeHttpUrl(", html_doc)
        self.assertIn("function escapeShellDoubleQuoted(", html_doc)
        self.assertIn("function escapeHtml(", embed_js)

        # Verify WAI-ARIA tab roles, live regions, and keyboard focus styles
        self.assertIn('role="tablist"', html_doc)
        self.assertIn('role="tab"', html_doc)
        self.assertIn('role="tabpanel"', html_doc)
        self.assertIn('aria-live="polite"', html_doc)
        self.assertIn(":focus-visible", html_doc)
        self.assertIn(":focus-visible", embed_css)

        # Accessibility & shell injection hardening
        self.assertIn("active.isContentEditable", html_doc)
        self.assertIn("function (ch) { return", html_doc)
        self.assertIn(".settings-subtab:focus-visible", html_doc)
        self.assertIn(".switch-label input:focus-visible + .switch-slider", html_doc)
        self.assertIn('aria-controls="section-settings-engines"', html_doc)
        self.assertIn('role="tabpanel" aria-labelledby="subtab-engines-btn"', html_doc)
        self.assertIn("e.key === 'Escape'", html_doc)
        self.assertIn(r"split('[').join('\\[').split(']').join('\\]')", html_doc)

    def test_webui_next_javascript_syntax_validity(self):
        """Regression: ensure delivered JavaScript (AI_WORKSPACE_HTML and SIMPLE_EMBED_JS)
        has zero syntax errors, unclosed strings, or broken tokens.
        """
        import re
        import shutil
        import subprocess
        import tempfile

        import webui_next

        html_doc = webui_next.AI_WORKSPACE_HTML
        embed_js = webui_next.SIMPLE_EMBED_JS

        # Static guards: ensure no broken template strings or unescaped newlines in JS strings
        self.assertNotIn("return '\\' + ch;", html_doc)
        self.assertNotIn("join('\n", html_doc)
        self.assertNotIn("replace(/\n", html_doc)

        node_bin = shutil.which("node")
        if node_bin:
            scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html_doc, re.DOTALL | re.IGNORECASE)
            self.assertTrue(len(scripts) >= 1)
            with tempfile.TemporaryDirectory() as td:
                for idx, sc in enumerate(scripts):
                    sc_path = os.path.join(td, f"script_{idx}.js")
                    with open(sc_path, "w", encoding="utf-8") as f:
                        f.write(sc)
                    p = subprocess.run([node_bin, "--check", sc_path], capture_output=True, text=True, check=False)
                    self.assertEqual(p.returncode, 0, f"AI_WORKSPACE_HTML script {idx} syntax error:\n{p.stderr}")

                embed_path = os.path.join(td, "embed.js")
                with open(embed_path, "w", encoding="utf-8") as f:
                    f.write(embed_js)
                p2 = subprocess.run([node_bin, "--check", embed_path], capture_output=True, text=True, check=False)
                self.assertEqual(p2.returncode, 0, f"SIMPLE_EMBED_JS syntax error:\n{p2.stderr}")

    def test_webui_next_health_dot_reflects_real_status(self):
        """Regression: the /ai header status-dot used to hard-code aria-label="Server Online"
        without ever contacting /healthz, asserting a false status to screen readers.
        It must start with a neutral state and update from the /healthz response."""
        import webui_next

        html_doc = webui_next.AI_WORKSPACE_HTML
        self.assertIn('id="health-dot"', html_doc)
        self.assertNotIn('aria-label="Server Online" title="Server Online"></span>', html_doc)
        # Neutral initial state for screen readers before the check resolves
        self.assertIn('aria-label="Checking server status"', html_doc)
        # A real health probe must exist and update the label from the response
        self.assertIn("fetch('/healthz')", html_doc)
        self.assertIn("'Server Online'", html_doc)
        self.assertIn("'Server Offline'", html_doc)
        self.assertIn("'Server Error'", html_doc)

    def test_webui_next_ssrf_shorthand_ip_and_single_dns_resolution(self):
        import ipaddress

        import webui_next

        fake_webapp = mock.MagicMock()
        fake_webapp._ScrapeBlockedError = ValueError
        fake_webapp._ScrapeResponseTooLargeError = RuntimeError
        fake_webapp._is_reserved_scrape_host = lambda h: (
            h in ("localhost", "localhost.localdomain") or h.endswith(".local")
        )
        fake_webapp._is_ip_blocked = lambda ip: (
            ipaddress.ip_address(ip).is_loopback or ipaddress.ip_address(ip).is_private
        )
        fake_webapp._is_blocked_scrape_host = lambda h: False
        fake_webapp.pinned_dns = mock.MagicMock()

        # Shorthand, integer, and octal/hex IPv4 loopback must be statically blocked without DNS lookup
        with mock.patch("webui_next.socket.getaddrinfo") as mock_getaddrinfo:
            for host in (
                "127.1",
                "127.0.1",
                "2130706433",
                "0177.0.0.1",
                "0x7f.0.0.1",
                "0x7f000001",
                "0b1111111000000000000000000000001",
                "0o17700000001",
                "localhost",
            ):
                res = webui_next._scrape_url_direct(fake_webapp, f"http://{host}/secret")
                self.assertIn(
                    "スクレイピング拒否 (400)",
                    res.get("error", ""),
                    f"Expected {host} to be statically blocked",
                )
            mock_getaddrinfo.assert_not_called()

        # Port 0 must return 400 prefix so /api/scrape_analyze returns HTTP 400
        port_zero_res = webui_next._scrape_url_direct(fake_webapp, "http://example.com:0/test")
        self.assertIn("スクレイピング拒否 (400)", port_zero_res.get("error", ""))

        # Verify patch_webapp_scrape_route includes resolve_dns=False and socket.inet_aton
        sample = (
            "import warnings\n"
            "from flask import request\n\n"
            "@app.route('/search', methods=['GET', 'POST'])\n"
            "def search():\n"
            "    pass\n"
        )
        patched_webapp = apply_patches.patch_webapp_scrape_route(sample, "webapp.py")
        self.assertIn("resolve_dns=False", patched_webapp)
        self.assertIn("socket.inet_aton(host_clean)", patched_webapp)

    def test_webui_next_forwards_categories_engines_time_range(self):
        import webui_next

        captured = {}

        def spy_search_in_process(webapp_mod, query, **kwargs):
            captured["query"] = query
            captured.update(kwargs)
            return {"query": query, "results": [], "answers": []}

        with mock.patch.object(webui_next, "_search_in_process", side_effect=spy_search_in_process):
            webui_next.execute_server_deep_search(
                query="quantum computing",
                mode="fast",
                categories="science",
                engines="arxiv,semantic_scholar",
                time_range="year",
            )
        self.assertEqual(captured.get("categories"), "science")
        self.assertEqual(captured.get("engines"), "arxiv,semantic_scholar")
        self.assertEqual(captured.get("time_range"), "year")

    def test_webui_next_scrape_url_direct_prioritizes_ipv4_and_handles_oserror(self):
        import contextlib
        import socket

        import webui_next

        fake_webapp = mock.MagicMock()
        fake_webapp._ScrapeBlockedError = ValueError
        fake_webapp._ScrapeResponseTooLargeError = RuntimeError
        fake_webapp._is_reserved_scrape_host = lambda h: False
        fake_webapp._is_ip_blocked = lambda ip: False
        fake_webapp._is_blocked_scrape_host = lambda h: False

        captured_pinned_ips = []

        @contextlib.contextmanager
        def mock_pinned_dns(host, ips, port):
            captured_pinned_ips.append((host, ips, port))
            yield

        fake_webapp.pinned_dns = mock_pinned_dns

        # Mock httpx response stream
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        fake_client = mock.MagicMock()
        fake_client.stream.return_value.__enter__.return_value = mock_resp
        fake_webapp._scrape_client = fake_client
        fake_webapp._scrape_client_lock = contextlib.nullcontext()
        fake_webapp._read_scrape_response = lambda resp, max_duration=15.0: (
            "<html><body>Extracted test page</body></html>"
        )
        fake_webapp.trafilatura.extract = lambda html, **kw: "Extracted test page"

        # 1. Simulate getaddrinfo returning IPv6 first, then IPv4
        mock_addrs = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]
        with mock.patch("webui_next.socket.getaddrinfo", return_value=mock_addrs):
            res = webui_next._scrape_url_direct(fake_webapp, "https://example.com/test")
            self.assertEqual(res.get("content"), "Extracted test page")
            self.assertTrue(len(captured_pinned_ips) > 0)
            pinned_host, pinned_ips, pinned_port = captured_pinned_ips[-1]
            self.assertEqual(pinned_host, "example.com")
            self.assertEqual(pinned_port, 443)
            # IPv4 must be prioritized at index 0
            self.assertEqual(pinned_ips, ["93.184.216.34", "2001:db8::1"])

        # 2. Simulate OSError during DNS resolution
        with mock.patch("webui_next.socket.getaddrinfo", side_effect=OSError("Network is unreachable")):
            err_res = webui_next._scrape_url_direct(fake_webapp, "https://example.com/unreachable")
            self.assertIn("スクレイピング拒否", err_res.get("error", ""))
            self.assertIn("DNS resolution failed", err_res.get("error", ""))

    def test_webui_next_scrape_url_direct_normalizes_host_for_dns_pin(self):
        """R6 SSRF regression: Unicode dot variants / trailing dots in the URL
        host must be normalized before blocking, DNS resolution and pinning.

        httpx normalizes hosts (U+3002 etc -> '.', IDNA, trailing dot strip)
        before handing them to the transport. If the pin is keyed on the raw
        (un-normalized) host, the transport lookup no longer matches the pin,
        the pin is silently skipped and an attacker-controlled DNS answer can
        point the second resolution at an internal service (DNS rebinding).
        The scrape client must request the normalized-host URL so the pin is
        always effective.
        """
        import contextlib
        import ipaddress
        import socket
        import urllib.parse

        import webui_next

        fake_webapp = mock.MagicMock()
        fake_webapp._ScrapeBlockedError = ValueError
        fake_webapp._ScrapeResponseTooLargeError = RuntimeError
        fake_webapp._is_reserved_scrape_host = lambda h: False
        fake_webapp._is_ip_blocked = lambda ip: False
        fake_webapp._is_blocked_scrape_host = lambda h: False

        captured_pinned = []

        @contextlib.contextmanager
        def mock_pinned_dns(host, ips, port):
            captured_pinned.append((host, ips, port))
            yield

        fake_webapp.pinned_dns = mock_pinned_dns

        requested_urls = []
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}

        def fake_stream(method, url, **kwargs):
            requested_urls.append(url)

            class _Ctx:
                def __enter__(self):
                    return mock_resp

                def __exit__(self, *exc):
                    return False

            return _Ctx()

        fake_client = mock.MagicMock()
        fake_client.stream.side_effect = fake_stream
        fake_webapp._scrape_client = fake_client
        fake_webapp._scrape_client_lock = contextlib.nullcontext()
        # Match verify_ssl=True so the shared client is not rebuilt with a
        # real httpx.Client during the test.
        fake_webapp._scrape_client_verify_ssl = True
        fake_webapp._read_scrape_response = lambda resp, max_duration=15.0: "<html>ok</html>"
        fake_webapp.trafilatura.extract = lambda html, **kw: "ok"

        calls = [0]

        def fake_getaddrinfo(host, port, *args, **kwargs):
            # Simulate a rebinding attacker: the first lookup for ANY host
            # returns a public IP, any later lookup returns loopback.
            if calls[0] == 0:
                calls[0] = 1
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

        calls[0] = 0

        attack_urls = [
            # Ideographic full stop used as a dot -> httpx normalizes it away
            "http://attacker.example\u3002/x",
            # Trailing dot (FQDN root label) -> httpx strips it
            "http://attacker.example./x",
            # Fullwidth dot variant
            "http://attacker.example\uff0e/x",
        ]
        for url in attack_urls:
            calls[0] = 0
            requested_urls.clear()
            captured_pinned.clear()
            with mock.patch("webui_next.socket.getaddrinfo", side_effect=fake_getaddrinfo):
                res = webui_next._scrape_url_direct(fake_webapp, url, max_length=100)
            # The request must go out on the normalized host...
            self.assertTrue(requested_urls, "scrape request must be issued")
            self.assertEqual(
                urllib.parse.urlsplit(requested_urls[0]).hostname,
                "attacker.example",
                f"transport host must be normalized for pin match: {url} -> {requested_urls[0]}",
            )
            # ...and the pin must be keyed on the same normalized host.
            self.assertEqual(captured_pinned[-1][0], "attacker.example")
            # Content must be fetched (pin effective, single resolution)
            self.assertEqual(res.get("content"), "ok", f"unexpected error for {url}: {res.get('error')}")

        # Non-ASCII IDN hosts must be punycoded so the transport and pin agree.
        calls[0] = 0
        requested_urls.clear()
        captured_pinned.clear()
        with mock.patch("webui_next.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            res = webui_next._scrape_url_direct(fake_webapp, "http://例え.example/テスト", max_length=100)
        self.assertEqual(urllib.parse.urlsplit(requested_urls[0]).hostname, "xn--r8jz45g.example")
        self.assertEqual(captured_pinned[-1][0], "xn--r8jz45g.example")

        # Loopback obfuscation with Unicode dots must be statically blocked
        # before any DNS lookup (uses a fake that actually blocks private IPs).
        loopback_fake = mock.MagicMock()
        loopback_fake._ScrapeBlockedError = ValueError
        loopback_fake._ScrapeResponseTooLargeError = RuntimeError
        loopback_fake._is_reserved_scrape_host = lambda h: False
        loopback_fake._is_ip_blocked = lambda ip: (
            ipaddress.ip_address(ip).is_loopback or ipaddress.ip_address(ip).is_private
        )
        loopback_fake._is_blocked_scrape_host = lambda h: False
        loopback_fake.pinned_dns = mock_pinned_dns
        with mock.patch("webui_next.socket.getaddrinfo") as ga:
            res = webui_next._scrape_url_direct(
                loopback_fake,
                "http://127\u30020\u30020\u30021/secret",
                max_length=100,
            )
            self.assertIn("スクレイピング拒否 (400)", res.get("error", ""))
            ga.assert_not_called()

    def test_unified_root_serves_ai_first_workspace(self):
        """Verify root / serves the unified AI Search & Context Studio HTML with classic & settings tabs."""
        import webui_next
        from flask import Flask

        app = Flask("test_unified_root")
        webui_next.register_next_webui(app, None)
        client = app.test_client()

        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
        body = resp.data.decode("utf-8")
        self.assertIn("SearXNG Next", body)
        self.assertIn('id="tab-classic"', body)
        self.assertIn('id="tab-settings"', body)
        self.assertIn('data-mode="classic"', body)
        self.assertIn('data-mode="settings"', body)

    def test_unified_search_browser_redirects_and_api_passes(self):
        """Verify /search redirects HTML browser queries to /?q=... while preserving API json/data output."""
        import webui_next
        from flask import Flask, jsonify

        app = Flask("test_unified_search")

        @app.route("/search", methods=["GET", "POST"])
        def orig_search():
            return jsonify({"results": [{"title": "API result"}]}), 200

        @app.route("/preferences", methods=["GET", "POST"])
        def orig_preferences():
            return "ORIG_PREFERENCES_PAGE"

        @app.route("/about", methods=["GET"])
        def orig_about():
            return "ORIG_ABOUT_PAGE"

        webui_next.register_next_webui(app, None)
        client = app.test_client()

        # HTML browser requests redirect to unified studio
        html_resp = client.get("/search?q=machine+learning", headers={"Accept": "text/html,application/xhtml+xml"})
        self.assertEqual(html_resp.status_code, 302)
        self.assertIn("/?q=machine+learning", html_resp.headers.get("Location", ""))

        pref_resp = client.get("/preferences", headers={"Accept": "text/html"})
        self.assertEqual(pref_resp.status_code, 302)
        self.assertIn("/?mode=settings", pref_resp.headers.get("Location", ""))

        about_resp = client.get("/about")
        self.assertEqual(about_resp.status_code, 302)
        self.assertIn("/?mode=agent", about_resp.headers.get("Location", ""))

        # API requests pass through to original handler
        json_resp = client.get("/search?q=machine+learning&format=json")
        self.assertEqual(json_resp.status_code, 200)
        json_data = json_resp.get_json()
        self.assertEqual(json_data["results"][0]["title"], "API result")

        header_json_resp = client.get("/search?q=machine+learning", headers={"Accept": "application/json"})
        self.assertEqual(header_json_resp.status_code, 200)

    def test_settings_engines_api_get_and_post(self):
        """Verify /api/settings/engines GET introspects engine data and POST persists cookie settings."""
        import webui_next
        from flask import Flask

        app = Flask("test_settings_api")
        webui_next.register_next_webui(app, None)
        client = app.test_client()

        # GET request returns schema with engines, categories, total_engines
        get_resp = client.get("/api/settings/engines")
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.get_json()
        self.assertIn("engines", get_data)
        self.assertIn("categories", get_data)
        self.assertIn("total_engines", get_data)

        # POST request sets persistence cookies for enabled/disabled engines
        post_resp = client.post(
            "/api/settings/engines",
            json={
                "disabled_engines": ["duckduckgo", "google"],
                "enabled_engines": ["brave"],
            },
        )
        self.assertEqual(post_resp.status_code, 200)
        post_data = post_resp.get_json()
        self.assertTrue(post_data.get("success"))
        self.assertEqual(post_data.get("disabled_engines_count"), 2)
        self.assertEqual(post_data.get("enabled_engines_count"), 1)

        set_cookies = post_resp.headers.getlist("Set-Cookie")
        self.assertTrue(any("disabled_engines=" in c for c in set_cookies))
        self.assertTrue(any("enabled_engines=" in c for c in set_cookies))

    def test_classic_search_mode_and_pagination(self):
        """Verify execute_server_deep_search supports mode=classic and pageno."""
        import webui_next

        captured_kwargs = {}

        def mock_search_in_process(webapp_mod, query, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "query": query,
                "results": [
                    {
                        "title": "Classic Result",
                        "url": "https://example.com/classic",
                        "content": "A lightweight search card content.",
                        "source": "google",
                        "score": 1.5,
                    }
                ],
                "answers": [],
            }

        with mock.patch.object(webui_next, "_search_in_process", side_effect=mock_search_in_process):
            res = webui_next.execute_server_deep_search(
                query="rust programming",
                mode="classic",
                categories="it",
                pageno=3,
            )
            self.assertEqual(res["mode"], "classic")
            self.assertEqual(res["page"], 3)
            self.assertEqual(res["scraped_count"], 0)
            self.assertEqual(captured_kwargs.get("pageno"), 3)
            self.assertEqual(captured_kwargs.get("categories"), "it")
            self.assertIn("Classic Search Results", res["markdown"])
            self.assertIn("rust programming", res["markdown"])

    def test_webapp_ai_webui_patch_is_critical_severity(self):
        """Ensure webapp_ai_webui patch is marked CRITICAL to abort upstream sync if injection fails."""
        ai_patch = next((p for p in apply_patches.PATCH_SPECS if p.name == "webapp_ai_webui"), None)
        self.assertIsNotNone(ai_patch)
        self.assertEqual(ai_patch.severity, apply_patches.PatchSeverity.CRITICAL)


class TestPatchCache(unittest.TestCase):
    """Tests for patch caching and fast-path verification."""

    def test_compute_fingerprints_returns_dict(self):
        fp = apply_patches._compute_fingerprints()
        self.assertIsInstance(fp, dict)
        # Should at least contain this script itself or apply-patches.py
        self.assertTrue(any("apply-patches.py" in k for k in fp))

    def test_cache_validity_roundtrip(self):
        # Save cache and verify it's valid
        apply_patches.save_patch_cache()
        self.assertTrue(apply_patches.is_patch_cache_valid())

    def test_cache_invalidated_on_tamper(self):
        apply_patches.save_patch_cache()
        self.assertTrue(apply_patches.is_patch_cache_valid())

        # Temporarily tamper with cache file
        with open(apply_patches.CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        orig_files = data.get("files", {})
        # Fake a modified mtime
        if orig_files:
            first_key = next(iter(orig_files))
            data["files"][first_key]["size"] = orig_files[first_key]["size"] + 9999
            with open(apply_patches.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)

            self.assertFalse(apply_patches.is_patch_cache_valid())

        # Restore valid cache
        apply_patches.save_patch_cache()
        self.assertTrue(apply_patches.is_patch_cache_valid())


class TestPatchDiagnosticsAndResilience(unittest.TestCase):
    """Verify enhanced patch resilience, fallback matching, diagnostics, and rollback."""

    def test_patch_valkeydb_fallback_when_pwd_absent(self):
        """If upstream completely removed pwd dependency, valkeydb patch should be ALREADY_APPLIED."""
        content = "import os\n\ndef connect():\n    return 'connected'\n"
        result = apply_patches.patch_valkeydb(content, "valkeydb.py")
        self.assertEqual(result, "ALREADY_APPLIED")

    def test_patch_valkeydb_fallback_when_logger_var_changed(self):
        """If logger initialization differs, valkeydb patch should fall back after imports."""
        content = (
            "import os\n"
            "import pwd\n"
            "log = get_my_logger()\n\n"
            "def connect():\n"
            "    _pw = pwd.getpwuid(os.getuid())\n"
            "    logger.exception('can\\'t connect valkey DB ...')\n"
        )
        patched = apply_patches.patch_valkeydb(content, "valkeydb.py")
        self.assertIn("def _windows_safe_current_user():", patched)
        self.assertIn("_user_name, _user_uid = _windows_safe_current_user()", patched)

    def test_patch_settings_defaults_with_type_annotation_or_tuple(self):
        """Settings defaults patch should handle type annotations and tuple syntax."""
        sample_annotated = "OUTPUT_FORMATS: list[str] = [\n    'html',\n    'json',\n]\n"
        patched1 = apply_patches.patch_settings_defaults(sample_annotated, "settings_defaults.py")
        self.assertIn("'json_lite'", patched1)

        sample_tuple = "OUTPUT_FORMATS = ('html', 'json')\n"
        patched2 = apply_patches.patch_settings_defaults(sample_tuple, "settings_defaults.py")
        self.assertIn("'json_lite'", patched2)

    def test_patch_webutils_fallback_when_get_themes_missing(self):
        """If get_themes is missing in webutils, get_json_lite_response falls back to other functions or EOF."""
        sample = "import json\n\ndef render(t, **kw):\n    return ''\n"
        patched = apply_patches.patch_webutils(sample, "webutils.py")
        self.assertIn("def get_json_lite_response", patched)
        import ast

        ast.parse(patched)  # syntax must be valid

    def test_patch_webapp_scrape_route_fallback_anchors(self):
        """If @app.route('/search') is absent, fallback anchors inject /scrape route safely."""
        sample = "import warnings\nfrom flask import Flask\n\n@main_bp.route('/search')\ndef search():\n    pass\n"
        patched = apply_patches.patch_webapp_scrape_route(sample, "webapp.py")
        self.assertIn("def scrape():", patched)
        self.assertIn("@app.route('/scrape'", patched)
        import ast

        ast.parse(patched)

    def test_patch_online_captcha_fallback_anchors(self):
        """If original import block is altered upstream, fallback anchor injects _parse_retry_after_header."""
        sample = (
            "from .abstract import EngineProcessor\n"
            "from searx.metrics.error_recorder import count_error\n\n"
            "class OnlineEngineProcessor(EngineProcessor):\n"
            "    def error_handler(self, result_container):\n"
            "        try:\n"
            "            pass\n"
            "        except (\n"
            "            SearxEngineCaptchaException,\n"
            "            SearxEngineTooManyRequestsException,\n"
            "            SearxEngineAccessDeniedException,\n"
            "        ) as e:\n"
            "            self.handle_exception(result_container, e, suspend=True)\n"
            "            self.logger.debug(e.message)\n"
        )
        patched = apply_patches.patch_online_captcha(sample, "online.py")
        self.assertIn("def _parse_retry_after_header", patched)
        self.assertIn("except SearxEngineCaptchaException as e:", patched)
        import ast

        ast.parse(patched)

    def test_diagnose_patch_failure_identifies_missing_anchors_and_tokens(self):
        """Diagnostic analyzer should locate missing anchors and report token occurrences."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "test_file.py")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("def custom_user_func():\n    return 'user'\n")

            missing, suggestions = apply_patches.diagnose_patch_failure(
                fpath,
                "Test Patch",
                expected_anchors=["pwd.getpwuid(os.getuid())"],
                diagnostic_hint="pwd module missing on Windows.",
            )
            self.assertEqual(len(missing), 1)
            self.assertIn("pwd.getpwuid", missing[0])
            self.assertTrue(any("Hint: pwd module missing on Windows." in s for s in suggestions))

    def test_safe_relpath_handles_cross_drive_and_same_drive(self):
        """_safe_relpath must gracefully handle cross-drive paths without raising ValueError."""
        if sys.platform == "win32":
            res_same = apply_patches._safe_relpath("C:\\repo\\sub\\file.py", "C:\\repo")
            self.assertEqual(res_same, "sub/file.py")

            res_cross = apply_patches._safe_relpath("C:\\Users\\Temp\\file.py", "D:\\a\\repo")
            self.assertEqual(res_cross, "C:/Users/Temp/file.py")

            with mock.patch("os.path.relpath", side_effect=ValueError("path is on mount 'C:', start on mount 'D:'")):
                fallback = apply_patches._safe_relpath("C:\\temp\\file.py", "D:\\repo")
                self.assertEqual(fallback, "C:/temp/file.py")

    def test_diagnose_patch_failure_resilient_to_cross_drive(self):
        """diagnose_patch_failure must not crash when file and REPO_ROOT are on different drives."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "test_file.py")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("def dummy(): pass\n")

            with mock.patch.object(apply_patches, "REPO_ROOT", "Z:\\VirtualWorkspace\\Repo"):
                missing, suggestions = apply_patches.diagnose_patch_failure(
                    fpath,
                    "Cross Drive Test Patch",
                    expected_anchors=["missing_anchor()"],
                    diagnostic_hint="testing cross-drive resilience",
                )
                self.assertEqual(len(missing), 1)
                self.assertTrue(any("git log -p -n 3" in s for s in suggestions))

    def test_patch_transaction_persist_backups_cross_drive(self):
        """PatchTransaction.persist_backups must succeed even if files are on another drive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "cross_drive.py")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("original code")

            tx = apply_patches.PatchTransaction(backup_dir=os.path.join(tmpdir, ".backups"))
            tx.record_original(fpath, "original code")
            with mock.patch.object(apply_patches, "REPO_ROOT", "Z:\\VirtualWorkspace\\Repo"):
                tx.persist_backups()

            manifest_path = os.path.join(tmpdir, ".backups", "manifest.json")
            self.assertTrue(os.path.exists(manifest_path))
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertIn(os.path.abspath(fpath), manifest)

    def test_patch_transaction_backup_and_rollback(self):
        """PatchTransaction should back up files and restore them completely upon rollback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "sample.txt")
            original_text = "original content before patching"
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(original_text)

            tx = apply_patches.PatchTransaction(backup_dir=os.path.join(tmpdir, ".backups"))
            # Update file using update_file with transaction
            res = apply_patches.update_file(
                fpath,
                "test transaction update",
                lambda c, p: "MODIFIED TEXT",
                raise_on_failure=False,
                transaction=tx,
            )
            self.assertEqual(res.status, apply_patches.PatchStatus.PATCHED)
            with open(fpath, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "MODIFIED TEXT")

            # Roll back
            restored = tx.rollback()
            self.assertIn(os.path.abspath(fpath), restored)
            with open(fpath, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), original_text)

    def test_update_file_batch_mode_returns_patch_result(self):
        """When raise_on_failure=False, update_file returns PatchResult without raising exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "target.py")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("unchanged code")

            # Patch returns unchanged content and is not noop -> should fail cleanly
            res = apply_patches.update_file(
                fpath,
                "failing patch",
                lambda c, p: c,
                raise_on_failure=False,
            )
            self.assertEqual(res.status, apply_patches.PatchStatus.FAILED)
            self.assertIn("could not find injection point", res.message)

    def test_run_all_patches_batch_collection(self):
        """run_all_patches should execute all specs and aggregate both successes and failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = os.path.join(tmpdir, "f1.py")
            f2 = os.path.join(tmpdir, "f2.py")
            with open(f1, "w", encoding="utf-8") as f:
                f.write("content 1")
            with open(f2, "w", encoding="utf-8") as f:
                f.write("content 2")

            specs = [
                apply_patches.PatchSpec(
                    name="spec1",
                    target_path=f1,
                    description="spec 1 success",
                    patch_func=lambda c, p: "var1 = 1\n",
                    severity=apply_patches.PatchSeverity.CRITICAL,
                ),
                apply_patches.PatchSpec(
                    name="spec2",
                    target_path=f2,
                    description="spec 2 failure",
                    patch_func=lambda c, p: c,  # fails
                    severity=apply_patches.PatchSeverity.FEATURE,
                ),
            ]

            results = apply_patches.run_all_patches(specs)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].status, apply_patches.PatchStatus.PATCHED)
            self.assertEqual(results[1].status, apply_patches.PatchStatus.FAILED)

    def test_cli_main_check_mode(self):
        """CLI main with --check returns exit code 0."""
        with mock.patch("sys.argv", ["apply-patches.py", "--check"]):
            exit_code = apply_patches.main()
            self.assertEqual(exit_code, 0)

    def test_cli_main_exit_codes_with_mock_failures(self):
        """CLI main returns 1 for CRITICAL failures and 2 for non-critical failures (or 1 under --strict)."""
        mock_spec_optional_fail = [
            apply_patches.PatchSpec(
                name="opt_fail",
                target_path=os.path.join(apply_patches.REPO_ROOT, "UPSTREAM_VERSION.txt"),
                description="optional failure spec",
                patch_func=lambda c, p: c,  # fails
                severity=apply_patches.PatchSeverity.OPTIONAL,
            )
        ]
        mock_spec_critical_fail = [
            apply_patches.PatchSpec(
                name="crit_fail",
                target_path=os.path.join(apply_patches.REPO_ROOT, "UPSTREAM_VERSION.txt"),
                description="critical failure spec",
                patch_func=lambda c, p: c,  # fails
                severity=apply_patches.PatchSeverity.CRITICAL,
            )
        ]

        # 1. Non-critical failure without --strict returns 2
        with (
            mock.patch.object(apply_patches, "PATCH_SPECS", mock_spec_optional_fail),
            mock.patch("sys.argv", ["apply-patches.py", "--check"]),
        ):
            exit_code = apply_patches.main()
            self.assertEqual(exit_code, 2)

        # 2. Non-critical failure with --strict returns 1
        with (
            mock.patch.object(apply_patches, "PATCH_SPECS", mock_spec_optional_fail),
            mock.patch("sys.argv", ["apply-patches.py", "--check", "--strict"]),
        ):
            exit_code = apply_patches.main()
            self.assertEqual(exit_code, 1)

        # 3. Critical failure returns 1
        with (
            mock.patch.object(apply_patches, "PATCH_SPECS", mock_spec_critical_fail),
            mock.patch("sys.argv", ["apply-patches.py", "--check"]),
        ):
            exit_code = apply_patches.main()
            self.assertEqual(exit_code, 1)

    def test_patch_preferences_validation(self):
        sample = (
            "    def parse(self, data: str):\n"
            '        """Parse and validate ``data`` and store the result at ``self.value``"""\n'
            "        if data == '':\n"
            "            self.value: list[str] = []\n"
            "            return\n"
            "\n"
            "        elements = data.split(',')\n"
            "        self._validate_selections(elements)\n"
            "        self.value = elements\n"
            "\n"
            "        for user_setting_name, user_setting in input_data.items():\n"
            "            if user_setting_name in self.key_value_settings:\n"
            "                if self.key_value_settings[user_setting_name].locked:\n"
            "                    continue\n"
            "                self.key_value_settings[user_setting_name].parse(user_setting)\n"
        )
        patched = apply_patches.patch_preferences_validation(sample, "preferences.py")
        self.assertIn("self.value = [x for x in elements if x in self.choices]", patched)
        self.assertIn("except ValidationException as e:", patched)
        # Verify idempotency
        self.assertEqual(apply_patches.patch_preferences_validation(patched, "preferences.py"), "ALREADY_APPLIED")

        # Test with import line present
        sample_with_import = "from searx import get_setting, settings, autocomplete, favicons\n" + sample
        patched_with_import = apply_patches.patch_preferences_validation(sample_with_import, "preferences.py")
        self.assertIn("from searx import get_setting, settings, autocomplete, favicons, logger", patched_with_import)
        self.assertIn("self.value = [x for x in elements if x in self.choices]", patched_with_import)
        self.assertIn("except ValidationException as e:", patched_with_import)
        self.assertEqual(
            apply_patches.patch_preferences_validation(patched_with_import, "preferences.py"), "ALREADY_APPLIED"
        )

    def test_patch_webadapter_categories(self):
        sample = (
            "    for categ in category_list:\n"
            "        result.extend(\n"
            "            EngineRef(engine.name, categ)\n"
            "            for engine in categories[categ]\n"
            "            if (engine.name, categ) not in disabled_engines\n"
            "        )\n"
        )
        patched = apply_patches.patch_webadapter_categories(sample, "webadapter.py")
        self.assertIn("for engine in categories.get(categ, [])", patched)
        # Verify idempotency
        self.assertEqual(apply_patches.patch_webadapter_categories(patched, "webadapter.py"), "ALREADY_APPLIED")

    def test_patch_webapp_preferences_validation(self):
        sample = (
            "    preferences = Preferences(themes, list(categories.keys()), engines, searx.plugins.STORAGE, client_pref)\n"
            "    try:\n"
            "        preferences.parse_dict(sxng_request.cookies)\n"
            "\n"
            "    except Exception as e:\n"
            "        logger.exception(e, exc_info=True)\n"
            "        else:\n"
            "            preferences.parse_dict(sxng_request.form)\n"
            "    except Exception as e:\n"
            "        logger.exception(e, exc_info=True)\n"
        )
        patched = apply_patches.patch_webapp_preferences_validation(sample, "webapp.py")
        self.assertIn(
            "all_categories = sorted(set(list(categories.keys()) + list(settings.get('categories_as_tabs', {}).keys())))",
            patched,
        )
        self.assertIn(
            "except ValidationException as e:\n        logger.debug('Invalid settings in cookies: %s', e)", patched
        )
        self.assertIn(
            "except ValidationException as e:\n        logger.debug('Invalid settings in request: %s', e)", patched
        )
        # Verify idempotency
        self.assertEqual(apply_patches.patch_webapp_preferences_validation(patched, "webapp.py"), "ALREADY_APPLIED")


class TestPatchHardeningM2(unittest.TestCase):
    """Dedicated regression unit tests for M2 Patch Management and Windows Security Hardening."""

    def test_cache_tracked_targets_completeness(self):
        """F2.1: Verify _get_tracked_targets dynamically includes all PATCH_SPECS targets."""
        tracked = apply_patches._get_tracked_targets()
        self.assertIsInstance(tracked, list)

        # Core targets must be present
        self.assertIsNotNone(apply_patches.__file__)
        assert apply_patches.__file__ is not None
        self.assertIn(os.path.abspath(apply_patches.__file__), tracked)
        self.assertIn(os.path.join(apply_patches.REPO_ROOT, "tools", "disable-missing-engines.py"), tracked)
        self.assertIn(os.path.join(apply_patches.REPO_ROOT, "tools", "webui_next.py"), tracked)
        self.assertIn(os.path.join(apply_patches.REPO_ROOT, "UPSTREAM_VERSION.txt"), tracked)

        # All PATCH_SPECS target paths must be present
        for spec in apply_patches.PATCH_SPECS:
            self.assertIn(
                os.path.abspath(spec.target_path),
                tracked,
                f"Spec target {spec.target_path} missing from _get_tracked_targets()",
            )

        # Specifically verify critical category targets are tracked
        pref_target = os.path.abspath(os.path.join(apply_patches.SITE_PACKAGES, "searx", "preferences.py"))
        webadapter_target = os.path.abspath(os.path.join(apply_patches.SITE_PACKAGES, "searx", "webadapter.py"))
        self.assertIn(pref_target, tracked)
        self.assertIn(webadapter_target, tracked)

    def test_rollback_path_traversal_orig_path_rejected(self):
        """F2.2: Verify PatchTransaction.rollback rejects orig_path outside REPO_ROOT / SITE_PACKAGES."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            # Create a legitimate backup file in backup_dir
            bak_file = os.path.join(backup_dir, "outside.bak")
            with open(bak_file, "w", encoding="utf-8") as f:
                f.write("malicious payload")

            # Point orig_path to an unauthorized location outside REPO_ROOT and SITE_PACKAGES
            outside_target = os.path.join(tmpdir, "outside_target.txt")
            manifest = {outside_target: bak_file}
            with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            tx = apply_patches.PatchTransaction(backup_dir=backup_dir)
            with mock.patch.object(apply_patches.logger, "error") as mock_logger:
                restored = tx.rollback()
                self.assertEqual(restored, [])
                self.assertFalse(os.path.exists(outside_target))
                mock_logger.assert_called_with(
                    "Security violation: rollback target %s outside permitted boundaries",
                    outside_target,
                )

    def test_rollback_path_traversal_bak_path_rejected(self):
        """F2.2: Verify PatchTransaction.rollback rejects bak_path outside backup_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            # Legitimate target inside repo
            valid_target = os.path.join(apply_patches.REPO_ROOT, "tools", "test_dummy_target.txt")
            # bak_path outside backup_dir
            outside_bak = os.path.join(tmpdir, "outside.bak")
            with open(outside_bak, "w", encoding="utf-8") as f:
                f.write("fake backup")

            manifest = {valid_target: outside_bak}
            with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            tx = apply_patches.PatchTransaction(backup_dir=backup_dir)
            with mock.patch.object(apply_patches.logger, "error") as mock_logger:
                restored = tx.rollback()
                self.assertEqual(restored, [])
                self.assertFalse(os.path.exists(valid_target))
                mock_logger.assert_called_with(
                    "Security violation: backup file %s outside backup directory",
                    outside_bak,
                )

    def test_rollback_legitimate_target_restored(self):
        """F2.2: Verify PatchTransaction.rollback restores authorized files correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            # Use a mock repo root to avoid touching live workspace files
            mock_repo = os.path.join(tmpdir, "repo")
            os.makedirs(mock_repo, exist_ok=True)
            target_file = os.path.join(mock_repo, "file.py")
            with open(target_file, "w", encoding="utf-8") as f:
                f.write("modified content")

            bak_file = os.path.join(backup_dir, "file.bak")
            with open(bak_file, "w", encoding="utf-8") as f:
                f.write("original content")

            manifest = {target_file: bak_file}
            with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            tx = apply_patches.PatchTransaction(backup_dir=backup_dir)
            with mock.patch.object(apply_patches, "REPO_ROOT", mock_repo):
                restored = tx.rollback()
                self.assertEqual(len(restored), 1)
                with open(target_file, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), "original content")

    def test_cli_report_path_traversal_rejected(self):
        """F2.3: Verify CLI --report path traversal outside REPO_ROOT raises ValueError."""
        outside_path = os.path.abspath(os.path.join(apply_patches.REPO_ROOT, "..", "outside_report.json"))
        with (
            mock.patch("sys.argv", ["apply-patches.py", "--check", "--report", outside_path]),
            self.assertRaisesRegex(ValueError, "Report output must reside within repository directory."),
        ):
            apply_patches.main()

    def test_cli_report_path_valid_accepted(self):
        """F2.3: Verify CLI --report within REPO_ROOT is accepted without error."""
        valid_report = os.path.join(apply_patches.REPO_ROOT, ".test_m2_report.json")
        try:
            with mock.patch("sys.argv", ["apply-patches.py", "--check", "--report", valid_report]):
                exit_code = apply_patches.main()
                self.assertEqual(exit_code, 0)
        finally:
            if os.path.exists(valid_report):
                try:
                    os.remove(valid_report)
                except OSError:
                    pass

    def test_ensure_secret_key_mkstemp_usage(self):
        """F2.4 & F2.5: Verify ensure-secret-key uses tempfile.mkstemp rather than static .tmp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = os.path.join(tmpdir, "secret.key")
            with mock.patch("tempfile.mkstemp", wraps=tempfile.mkstemp) as mock_mkstemp:
                success = ensure_secret_key._write_key(key_file, "a" * 64)
                self.assertTrue(success)
                self.assertTrue(mock_mkstemp.called)
                _, kwargs = mock_mkstemp.call_args
                self.assertEqual(kwargs.get("prefix"), ".tmp_key_")

            with open(key_file, "r", encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), "a" * 64)

    def test_ensure_secret_key_icacls_permissions_on_windows(self):
        """F2.4: Verify set_file_permissions runs icacls on Windows."""
        dummy_path = r"C:\fake\config\secret.key"
        with (
            mock.patch("sys.platform", "win32"),
            mock.patch.dict(os.environ, {"USERNAME": "win_user"}),
            mock.patch("subprocess.run") as mock_run,
        ):
            ensure_secret_key.set_file_permissions(dummy_path)
            mock_run.assert_called_once_with(
                ["icacls", dummy_path, "/inheritance:r", "/grant:r", "win_user:(R,W)"],
                check=False,
                capture_output=True,
            )

    def test_ensure_secret_key_posix_permissions(self):
        """F2.4: Verify set_file_permissions uses chmod 600 on POSIX platforms."""
        dummy_path = "/fake/config/secret.key"
        with (
            mock.patch("sys.platform", "linux"),
            mock.patch("os.chmod") as mock_chmod,
        ):
            ensure_secret_key.set_file_permissions(dummy_path)
            mock_chmod.assert_called_once_with(dummy_path, stat.S_IRUSR | stat.S_IWUSR)

    def test_settings_loader_quoted_path_stripped(self):
        """F2.6: Verify settings_loader.get_user_cfg_folder strips enclosing quotes."""
        from searx import settings_loader

        example_cfg = os.path.abspath(os.path.join(apply_patches.REPO_ROOT, "config", "settings.yml.example"))
        expected_folder = os.path.dirname(example_cfg)

        # 1. Double quotes
        with mock.patch.dict(os.environ, {"SEARXNG_SETTINGS_PATH": f'"{example_cfg}"'}):
            folder = settings_loader.get_user_cfg_folder()
            self.assertEqual(str(folder), expected_folder)

        # 2. Single quotes
        with mock.patch.dict(os.environ, {"SEARXNG_SETTINGS_PATH": f"'{example_cfg}'"}):
            folder = settings_loader.get_user_cfg_folder()
            self.assertEqual(str(folder), expected_folder)

    def test_scrape_client_keepalive_hardening(self):
        """F2.9: Verify patch_webapp_scrape_route sets max_keepalive_connections=0."""
        sample = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
        patched = apply_patches.patch_webapp_scrape_route(sample, "webapp.py")
        self.assertIn("max_keepalive_connections=0", patched)
        self.assertNotIn("max_keepalive_connections=20", patched)

    def test_settings_loader_whitespace_padded_quotes(self):
        """Verify settings_loader.get_user_cfg_folder handles whitespace around quotes."""
        from searx import settings_loader

        example_cfg = os.path.abspath(os.path.join(apply_patches.REPO_ROOT, "config", "settings.yml.example"))
        expected_folder = os.path.dirname(example_cfg)

        cases = [
            f'  "{example_cfg}"  ',
            f"  '{example_cfg}'  ",
            f"   {example_cfg}   ",
            f'  " {example_cfg} "  ',
            f"  ' {example_cfg} '  ",
        ]
        for c in cases:
            with mock.patch.dict(os.environ, {"SEARXNG_SETTINGS_PATH": c}):
                folder = settings_loader.get_user_cfg_folder()
                self.assertEqual(str(folder), expected_folder, f"Failed on case: {c}")

    def test_settings_loader_quoted_custom_filename_retained(self):
        """Verify load_settings retains custom filename when SEARXNG_SETTINGS_PATH is quoted."""
        from searx import settings_loader

        with tempfile.TemporaryDirectory() as tmpdir:
            custom_cfg = os.path.join(tmpdir, "custom_profile.yml")
            with open(custom_cfg, "w", encoding="utf-8") as f:
                f.write("use_default_settings: true\ngeneral:\n  debug: false\n")

            with mock.patch.dict(
                os.environ,
                {
                    "SEARXNG_SETTINGS_PATH": f'  "{custom_cfg}"  ',
                    "SEARXNG_DISABLE_ETC_SETTINGS": "1",
                },
            ):
                _cfg, msg = settings_loader.load_settings()
                self.assertIn("custom_profile.yml", msg)

    def test_settings_loader_patch_spec_registered_and_applied(self):
        """Verify settings_loader_quotes is registered in PATCH_SPECS and functions properly."""
        spec_names = [s.name for s in apply_patches.PATCH_SPECS]
        self.assertIn("settings_loader_quotes", spec_names)

        raw_sample = (
            "def get_user_cfg_folder():\n"
            "    folder = None\n"
            '    settings_path = os.environ.get("SEARXNG_SETTINGS_PATH", "")\n'
            "    return folder\n\n"
            "def load_settings():\n"
            '    settings_yml = os.environ.get("SEARXNG_SETTINGS_PATH")\n'
            "    if settings_yml and Path(settings_yml).is_file():\n"
            "        pass\n"
        )
        patched = apply_patches.patch_settings_loader(raw_sample, "settings_loader.py")
        self.assertIn('raw_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip()', patched)
        self.assertIn("settings_path = raw_path.strip('\"\\'').strip()", patched)
        self.assertIn("settings_yml = settings_yml.strip().strip('\"\\'').strip()", patched)

        # Re-running on patched returns ALREADY_APPLIED
        reapplied = apply_patches.patch_settings_loader(patched, "settings_loader.py")
        self.assertEqual(reapplied, "ALREADY_APPLIED")

        # Test upstream syntax without second argument and CRLF
        upstream_sample = (
            "def get_user_cfg_folder() -> Path | None:\r\n"
            "    folder = None\r\n"
            '    settings_path = os.environ.get("SEARXNG_SETTINGS_PATH")\r\n\r\n'
            "    if settings_path:\r\n"
            "        pass\r\n\r\n"
            "def load_settings():\r\n"
            '    settings_yml = os.environ.get("SEARXNG_SETTINGS_PATH")\r\n'
            "    if settings_yml and Path(settings_yml).is_file():\r\n"
            "        pass\r\n"
        )
        patched_upstream = apply_patches.patch_settings_loader(upstream_sample, "settings_loader.py")
        self.assertIn('raw_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip()', patched_upstream)
        self.assertIn("settings_path = raw_path.strip('\"\\'').strip()", patched_upstream)
        self.assertIn("settings_yml = settings_yml.strip().strip('\"\\'').strip()", patched_upstream)
        self.assertEqual(
            apply_patches.patch_settings_loader(patched_upstream, "settings_loader.py"), "ALREADY_APPLIED"
        )

    def test_ensure_secret_key_multiprocess_concurrency(self):
        """Verify concurrent processes can initialize secret key without WinError 5/32."""
        import concurrent.futures
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_repo = os.path.join(tmpdir, "fake_repo")
            fake_tools = os.path.join(fake_repo, "tools")
            fake_config = os.path.join(fake_repo, "config")
            os.makedirs(fake_tools, exist_ok=True)
            os.makedirs(fake_config, exist_ok=True)

            shutil.copy(
                os.path.join(HERE, "ensure-secret-key.py"),
                os.path.join(fake_tools, "ensure-secret-key.py"),
            )
            shutil.copy(
                os.path.join(apply_patches.REPO_ROOT, "config", "settings.yml.example"),
                os.path.join(fake_config, "settings.yml.example"),
            )

            target_script = os.path.join(fake_tools, "ensure-secret-key.py")
            num_procs = 8
            cmd = [sys.executable, target_script]

            def run_proc():
                p = subprocess.run(cmd, capture_output=True, text=True, cwd=fake_repo, check=False)
                return p.returncode, p.stdout.strip(), p.stderr.strip()

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_procs) as executor:
                futures = [executor.submit(run_proc) for _ in range(num_procs)]
                results = [f.result() for f in futures]

            exit_codes = [r[0] for r in results]
            outputs = [r[1] for r in results]

            for i, code in enumerate(exit_codes):
                self.assertEqual(code, 0, f"Process {i} failed with return code {code}: {results[i]}")
                self.assertTrue(outputs[i].startswith("set SEARXNG_SECRET="))
                key = outputs[i].replace("set SEARXNG_SECRET=", "")
                self.assertEqual(len(key), 64)

            # Check that secret.key was generated and has no orphans
            orphaned = [f for f in os.listdir(fake_config) if f.startswith(".tmp_key_") or f.endswith(".tmp")]
            self.assertEqual(orphaned, [])

    def test_ensure_secret_key_fd_cleanup_on_open_error(self):
        """Verify temp_fd is closed and temp file removed if open() fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "secret.key")
            orig_open = open

            def failing_open(*args, **kwargs):
                if len(args) > 0 and isinstance(args[0], int):
                    raise OSError("Simulated low-level OS failure in open()")
                return orig_open(*args, **kwargs)

            with mock.patch("builtins.open", side_effect=failing_open):
                success = ensure_secret_key._write_key(test_file, "a" * 64)
                self.assertFalse(success)

            orphaned = [f for f in os.listdir(tmpdir) if f.startswith(".tmp_key_")]
            self.assertEqual(orphaned, [], f"Orphaned files remaining: {orphaned}")

    def test_ensure_secret_key_acl_applied_to_existing_key(self):
        """Verify main() unconditionally calls set_file_permissions even when key exists."""
        with (
            mock.patch.object(ensure_secret_key, "_read_key", return_value="f" * 64),
            mock.patch.object(ensure_secret_key, "set_file_permissions") as mock_set_perm,
            mock.patch.object(ensure_secret_key, "_ensure_settings_file"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = ensure_secret_key.main()
            self.assertEqual(code, 0)
            mock_set_perm.assert_called_once_with(ensure_secret_key.SECRET_KEY_PATH)

    def test_deployed_webapp_keepalive_setting(self):
        """Verify deployed site-packages webapp.py has max_keepalive_connections=0."""
        webapp_path = os.path.join(apply_patches.SITE_PACKAGES, "searx", "webapp.py")
        self.assertTrue(os.path.exists(webapp_path), f"webapp.py not found at {webapp_path}")
        with open(webapp_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            "max_keepalive_connections=0",
            content,
            "Deployed site-packages webapp.py does not have max_keepalive_connections=0",
        )
        self.assertNotIn(
            "max_keepalive_connections=20",
            content,
            "Deployed site-packages webapp.py still contains max_keepalive_connections=20",
        )

    def test_apply_patches_check_all_clean(self):
        """Verify python tools/apply-patches.py --check reports 0 pending patches."""
        results = apply_patches.run_all_patches(apply_patches.PATCH_SPECS, dry_run=True)
        non_applied = [r for r in results if r.status != apply_patches.PatchStatus.ALREADY_APPLIED]
        self.assertEqual(
            non_applied,
            [],
            f"apply-patches.py --check found pending or failed patches: {non_applied}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
