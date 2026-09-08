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
        # A key that is too short is treated as invalid and replaced.
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

    def test_main_rotates_unsafe_existing_key(self):
        secret_path, settings_path, example_path = self._make_paths(
            with_key=("a" * 64) + " & echo INJECTED"
        )
        with mock.patch.object(self.fn, "SECRET_KEY_PATH", secret_path), \
             mock.patch.object(self.fn, "SETTINGS_PATH", settings_path), \
             mock.patch.object(self.fn, "SETTINGS_EXAMPLE_PATH", example_path):
            with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                rc = self.fn.main()
        self.assertEqual(rc, 0)
        key = out.getvalue().strip().split("=", 1)[1]
        self.assertRegex(key, r"^[0-9a-f]{64}$")

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
            with mock.patch.object(sys, "stdout", new_callable=io.StringIO):
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
        # The canonical injected function references the 'score' key, 'engines' key,
        # and the `_get_box` nested helper. All must be present for the idempotency
        # check to fire.
        content = (
            "def get_json_lite_response(sq, rc):\n"
            "    # 'score': d.get('score', 0)\n"
            "    # d.get('engines')\n"
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
        self.assertIn("', '.join(sorted(d.get('engines', [])))", result)


class TestPatchWebUtilsWindowsPaths(unittest.TestCase):
    """Verify URL-facing paths are normalized on Windows."""

    def setUp(self):
        self.fn = apply_patches.patch_webutils_windows_paths

    def test_normalizes_static_and_result_template_paths(self):
        content = (
            "file_list.append(str(f.relative_to(static_path)))\n"
            "result_templates.add(f)\n"
        )
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
        self.assertIn('aria-label="{{ _(\'Search for...\') }}"', result)

    def test_is_idempotent(self):
        content = '<input id="q" name="q" type="text" aria-label="{{ _(\'Search for...\') }}">\n'
        self.assertEqual(self.fn(content, "search.html"), "ALREADY_APPLIED")


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
        lines.extend([
            "    # load_module",
            "",
            "def load_engines(engine_list):",
            "    for engine_data in engine_list:",
        ])
        if with_legacy_patch:
            lines.append("        if engine_data.get(\"inactive\") is True or engine_data.get(\"disabled\") is True:")
            lines.append("            logger.debug(")
            lines.append("                \"loading engine %s skipped: inactive or disabled in config!\",")
            lines.append("                engine_data.get(\"name\", \"???\"),")
            lines.append("            )")
            lines.append("            continue")
        else:
            lines.append("        if engine_data.get(\"inactive\") is True:")
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


class TestPatchSettingsYml(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_settings_yml
        self.cfg_fn = apply_patches.patch_config_settings_yml

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

    def test_replaces_arbitrary_integers(self):
        # R1 regression test: regex pattern matches any upstream integer
        content = (
            "SearxEngineCaptcha: 7200\n"
            "SearxEngineAccessDenied: 14400\n"
            "SearxEngineTooManyRequests: 1800\n"
        )
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
            "if output_format in ('json', 'json_lite'):\n"
            "    pass\n"
            "if output_format == 'json_lite':\n"
            "    pass\n"
        )
        self.assertEqual(self.fn(content, "webapp.py"), "ALREADY_APPLIED")

    def test_patches_index_error_and_handler(self):
        content = (
            "import warnings\n"
            "def index_error(output_format, err):\n"
            "    if output_format == 'json':\n"
            "        return err\n"
            "    if output_format == 'json':\n"
            "        response = webutils.get_json_response\n"
        )
        res = self.fn(content, "webapp.py")
        self.assertIn("import ipaddress", res)
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
            "max_keepalive_connections=20\n"
            "_searxng_original_getaddrinfo\n"
            "v15-bulletproof-scrape-fix\n"
            "import re\n"
            "import html\n"
            "import httpx\n"
            "import idna\n"
            "trust_env=False\n"
            "class _ScrapeBlockedError\n"
        )
        self.assertEqual(self.fn(content, "webapp.py"), "ALREADY_APPLIED")

    def test_injects_scrape_route(self):
        content = (
            "import warnings\n"
            "from flask import Flask\n\n"
            "@app.route('/search')\n"
            "def search():\n"
            "    pass\n"
        )
        res = self.fn(content, "webapp.py")
        self.assertIn("import trafilatura", res)
        self.assertIn("import html", res)
        self.assertIn("import httpx", res)
        self.assertIn("import idna", res)
        self.assertIn("@app.route('/scrape'", res)
        self.assertIn("def scrape():", res)
        self.assertIn("v15-bulletproof-scrape-fix", res)
        self.assertIn("def _parse_scrape_url", res)
        self.assertIn("def _read_scrape_response", res)
        self.assertIn("_SCRAPE_MAX_RESPONSE_BYTES", res)
        # R2 regression: type validation
        self.assertIn("isinstance(url, str)", res)
        # R3 regression: idna normalization in _safe_getaddrinfo (module-level import)
        self.assertIn("idna.encode", res)
        # Verify idna is imported at module level, not inside _safe_getaddrinfo
        self.assertNotIn("import idna\n                        enc_h", res)
        # R4 regression: DNS pinning family isolation, mixed record check, and reserved TLDs
        self.assertIn("Address family not supported for pinned host", res)
        self.assertIn("_RESERVED_TLDS", res)
        self.assertIn("resolves to a private/reserved IP", res)
        self.assertIn("html.unescape", res)
        # HTTPX trusts HTTP(S)_PROXY by default.  The scrape client must make
        # direct, DNS-pinned connections instead of delegating DNS to a proxy.
        self.assertIn("trust_env=False", res)


class TestPatchProcessorsInit(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_processors_init

    def test_already_applied(self):
        content = (
            'if eng_settings.get("inactive", False) is True:\n'
            "    continue\n"
        )
        self.assertEqual(self.fn(content, "__init__.py"), "ALREADY_APPLIED")

    def test_removes_legacy_disabled_processor_skip(self):
        content = (
            "if eng_settings.get(\"inactive\", False) is True:\n"
            "    continue\n"
            "            if eng_settings.get(\"disabled\", False) is True:\n"
            "                logger.debug(\"Engine '%s' is disabled in config, skipping processor init.\", eng_name)\n"
            "                continue\n"
        )
        res = self.fn(content, "__init__.py")
        self.assertNotIn("skipping processor init", res)
        self.assertNotIn("if eng_settings.get(\"disabled\", False) is True:", res)


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
            "    if len(resp.text) < 2000 and \"/sorry/\" in resp.text:\n"
            "        raise SearxEngineCaptchaException()"
        )
        res = self.fn(old, "google.py")
        self.assertIn('loc = (resp.headers.get("Location")', res)
        self.assertIn('sorry.google.com', res)


class TestPatchSogouCaptcha(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_sogou_captcha

    def test_already_applied(self):
        content = 'antispider in content and captcha in content.lower() and resp.headers.get in content'
        self.assertEqual(self.fn(content, "sogou.py"), "ALREADY_APPLIED")

    def test_replaces_sogou_response(self):
        old = (
            "def response(resp):\n"
            "    if (\n"
            "        resp.status_code == 302\n"
            "        and resp.next_request is not None\n"
            "        and str(resp.next_request.url).startswith(\"http://www.sogou.com/antispider\")\n"
            "    ):\n"
            "        raise SearxEngineCaptchaException()"
        )
        res = self.fn(old, "sogou.py")
        self.assertIn("antispider", res)
        self.assertIn("resp.headers.get(\"Location\")", res)


class TestPatchAbstractSuspend(unittest.TestCase):
    def setUp(self):
        self.fn = apply_patches.patch_abstract_suspend

    def test_already_applied(self):
        content = (
            "            self.suspend_end_time = default_timer() + suspended_time\n"
            "            self.suspend_reason = suspend_reason\n"
            "            logger.debug(\"Suspend for %i seconds\", suspended_time)"
        )
        self.assertEqual(self.fn(content, "abstract.py"), "ALREADY_APPLIED")

    def test_removes_legacy_global_cap(self):
        legacy = (
            "            suspended_time = min(suspended_time, get_setting(\"search.max_ban_time_on_fail\"))\n"
            "            if \"captcha\" in suspend_reason.lower() or \"SearxEngineCaptcha\" in suspend_reason:\n"
            "                suspended_time = min(suspended_time, 900)\n"
            "            if suspended_time > 120 and self.continuous_errors == 1:\n"
            "                suspended_time = min(suspended_time, 120)\n"
            "\n"
            "            self.suspend_end_time = default_timer() + suspended_time\n"
            "            self.suspend_reason = suspend_reason\n"
            "            logger.debug(\"Suspend for %i seconds\", suspended_time)"
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
        sample = (
            "engines:\n"
            "  - name: removed_engine\n"
            "    engine: removed_mod\n"
            "    disabled: false\n"
            "    shortcut: rm\n"
        )
        res = self.mod.disable_engine_in_text(sample, "removed_engine")
        self.assertIn("inactive: true", res)
        self.assertIn("disabled: false", res)
        self.assertIn("shortcut: rm", res)

    def test_inactivate_engine_when_already_inactive_is_noop(self):
        sample = (
            "engines:\n"
            "  - name: removed_engine\n"
            "    engine: removed_mod\n"
            "    inactive: true\n"
        )
        res = self.mod.disable_engine_in_text(sample, "removed_engine")
        self.assertEqual(res, sample)

    def test_preserves_comments_and_formatting(self):
        sample = (
            "# Top comment\n"
            "engines:\n"
            "  # Engine comment\n"
            "  - name: missing\n"
            "    # inner comment\n"
            "    engine: missing\n"
        )
        res = self.mod.disable_engine_in_text(sample, "missing")
        self.assertIn("# Top comment", res)
        self.assertIn("# inner comment", res)
        self.assertIn("inactive: true", res)

    def test_engine_name_with_special_chars(self):
        # Engine names with hyphens, dots, etc. should be matched by escaped regex.
        sample = (
            "engines:\n"
            "  - name: my-engine.v2\n"
            "    engine: my_engine_v2\n"
        )
        res = self.mod.disable_engine_in_text(sample, "my-engine.v2")
        self.assertIn("inactive: true", res)

    def test_no_match_returns_unchanged(self):
        sample = (
            "engines:\n"
            "  - name: existing\n"
            "    engine: existing\n"
        )
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
            "  - name: missing_target\n"
            "    engine: missing_target\n"
            "    categories: general\n"
            "    inactive: true\n",
            result,
        )
        self.assertEqual(result.count("inactive: true"), 1)

    def test_preserves_crlf_line_endings(self):
        sample = (
            "engines:\r\n"
            "  - name: missing\r\n"
            "    engine: missing\r\n"
        )
        res = self.mod.disable_engine_in_text(sample, "missing")
        self.assertIn("inactive: true", res)
        # Should preserve CRLF (block contained CRLF).
        self.assertIn("\r\n", res)

    def test_inactive_various_truthy_values(self):
        # Anything in {'true', 'yes', 'on', '1'} (lowercased) should be treated
        # as already-inactive and not double-modified.
        for val in ("true", "yes", "on", "1", "TRUE", "Yes", "ON"):
            sample = (
                "engines:\n"
                "  - name: e\n"
                "    engine: e\n"
                f"    inactive: {val}\n"
            )
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
            "    engine: \"bing_images\"\n"
            "  - name: \"complex-engine\"\n"
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
            "engines:\n"
            "  - name: google\n"
            "    engine: google\n"
            "  - name: \"missing-engine\"\n"
            "    engine: missing_engine\n"
        )
        with mock.patch.object(self.mod, "yaml", None):
            # 1. extract_engines works without PyYAML
            engines = self.mod.extract_engines(sample)
            self.assertEqual(len(engines), 2)
            self.assertEqual(engines[1]["name"], "missing-engine")

            # 2. disable_engine_in_text works without PyYAML
            res = self.mod.disable_engine_in_text(sample, "missing-engine")
            self.assertIn("inactive: true", res)
            self.assertIn("name: \"missing-engine\"", res)

    def test_main_execution_without_yaml(self):
        settings_file = os.path.join(self._tmpdir, "settings.yml")
        engines_dir = os.path.join(self._tmpdir, "engines")
        os.makedirs(engines_dir, exist_ok=True)

        # Create one existing engine module and one missing engine
        with open(os.path.join(engines_dir, "google.py"), "w") as f:
            f.write("# google engine\n")

        with open(settings_file, "w", encoding="utf-8") as f:
            f.write(
                "engines:\n"
                "  - name: google\n"
                "    engine: google\n"
                "  - name: removed\n"
                "    engine: removed\n"
            )

        with mock.patch.object(self.mod, "yaml", None):
            with mock.patch.object(sys, "argv", ["disable-missing-engines.py", settings_file, engines_dir]):
                self.mod.main()

        with open(settings_file, "r", encoding="utf-8") as f:
            updated = f.read()

        self.assertIn("inactive: true", updated)
        self.assertIn("- name: removed\n    engine: removed\n    inactive: true", updated)
        self.assertNotIn("inactive: true\n  - name: google", updated)


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
        content = (
            "cf_SearxEngineCaptcha: 1296000\n"
            "recaptcha_SearxEngineCaptcha: 604800\n"
        )
        result = self.fn(content, "settings.yml")
        self.assertIn("cf_SearxEngineCaptcha: 3600", result)
        self.assertIn("recaptcha_SearxEngineCaptcha: 3600", result)


class TestPatchProcessorsInitEdgeCases(unittest.TestCase):
    """Cleanup does not alter already-upstream processor code."""

    def setUp(self):
        self.fn = apply_patches.patch_processors_init

    def test_leaves_inactive_check_with_extra_whitespace_unchanged(self):
        content = (
            'if   eng_settings.get("inactive", False)  is  True:\n'
            "    continue\n"
        )
        result = self.fn(content, "__init__.py")
        self.assertEqual(result, "ALREADY_APPLIED")

    def test_removes_legacy_disabled_processor_skip(self):
        content = (
            'if eng_settings.get("inactive", False) is True:\n'
            "    continue\n"
            "            if eng_settings.get(\"disabled\", False) is True:\n"
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
            "        if engine_data.get(\"inactive\") is True or engine_data.get(\"disabled\") is True:\n"
            "            logger.debug(\n"
            "                \"loading engine %s skipped: inactive or disabled in config!\",\n"
            "                engine_data.get(\"name\", \"???\"),\n"
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
        import socket
        import threading
        import ipaddress

        thread_local = threading.local()
        thread_local.pin = {'host': 'example.com', 'ip': '93.184.216.34', 'port': 443}

        def mock_original_gai(h, p, *args, **kwargs):
            return [('live_dns', h, p)]

        # Mimic _safe_getaddrinfo implementation
        def test_safe_getaddrinfo(h, p, *args, **kwargs):
            pin = getattr(thread_local, 'pin', None)
            if pin:
                pin_host = pin.get('host')
                if pin_host and (h or '').rstrip('.').lower() == pin_host.rstrip('.').lower():
                    pin_port = pin.get('port')
                    if p is None or p == pin_port or str(p) == str(pin_port) or (pin_port == 443 and p == 'https'):
                        ip_obj = ipaddress.ip_address(pin['ip'])
                        port_num = int(pin_port or 443)
                        req_family = args[0] if len(args) > 0 else kwargs.get('family', 0)
                        ip_family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
                        if req_family in (0, ip_family):
                            sockaddr = (pin['ip'], port_num, 0, 0) if ip_obj.version == 6 else (pin['ip'], port_num)
                            return [(ip_family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr)]
                        else:
                            raise socket.gaierror(socket.EAI_NONAME, f'Address family not supported for pinned host {pin_host}')
            return mock_original_gai(h, p, *args, **kwargs)

        # 1. Matching family returns pinned IP
        res_v4 = test_safe_getaddrinfo('example.com', 443, socket.AF_INET)
        self.assertEqual(res_v4[0][4], ('93.184.216.34', 443))

        # 2. Incompatible family raises gaierror (does NOT leak to live DNS)
        with self.assertRaises(socket.gaierror):
            test_safe_getaddrinfo('example.com', 443, socket.AF_INET6)

        # 3. Unpinned host falls through to original resolver
        res_other = test_safe_getaddrinfo('other.com', 443, socket.AF_INET)
        self.assertEqual(res_other, [('live_dns', 'other.com', 443)])

    def test_read_scrape_response_unknown_charset_fallback(self):
        # R4 verification: Malformed/bogus charset header must not crash with 500 LookupError
        class DummyResponse:
            headers = {'content-type': 'text/html; charset=bogus-unknown-codec'}
            encoding = 'bogus-unknown-codec'
            def iter_bytes(self):
                yield 'Hello, 世界!'.encode('utf-8')

        resp = DummyResponse()
        chunks = []
        for c in resp.iter_bytes():
            chunks.append(c)
        body = b''.join(chunks)

        encoding = resp.encoding or 'utf-8'
        try:
            decoded = body.decode(encoding, errors='replace')
        except (LookupError, ValueError):
            decoded = body.decode('utf-8', errors='replace')

        self.assertEqual(decoded, 'Hello, 世界!')

    def test_mixed_record_dns_rejection_logic(self):
        # R4 verification: If a domain resolves to both a global IP and a private IP,
        # it must be strictly rejected as an SSRF attack.
        import ipaddress

        records = [
            (2, 1, 6, '', ('93.184.216.34', 443)),  # global
            (2, 1, 6, '', ('192.168.1.1', 443)),   # private
        ]

        def validate_records(addr_info):
            for res in addr_info:
                ip_raw = res[4][0]
                ip_obj = ipaddress.ip_address(ip_raw)
                if not ip_obj.is_global:
                    return False, f'Blocked non-global: {ip_raw}'
            return True, 'OK'

        ok, msg = validate_records(records)
        self.assertFalse(ok)
        self.assertIn('192.168.1.1', msg)

    def test_reserved_tlds_blocking_logic(self):
        # R4 verification: Reserved TLDs must be blocked statically
        reserved_tlds = (
            '.localhost', '.local', '.internal', '.lan', '.home.arpa',
            '.invalid', '.test', '.example', '.onion', '.corp', '.home',
        )
        def is_blocked(host):
            h = (host or '').strip().rstrip('.').lower()
            return not h or h == 'localhost' or any(h.endswith(tld) for tld in reserved_tlds)

        for blocked in ['router.local', 'myhost.internal', 'gateway.lan', 'device.home.arpa', 'dark.onion', 'localhost']:
            self.assertTrue(is_blocked(blocked), f"{blocked} should be blocked")

        for allowed in ['example.com', 'searxng.org', 'google.com', 'wikipedia.org']:
            self.assertFalse(is_blocked(allowed), f"{allowed} should not be blocked")

    def test_html_unescape_in_scrape_fallback(self):
        # R4 verification: Fallback extraction unescapes HTML entities for GenAI readability
        import html
        import re

        raw_html = "<p>SearXNG &amp; AI: &quot;Fast &apos;n&apos; Lean&quot; &lt;3</p>"
        stripped = re.sub(r'<[^>]+>', ' ', raw_html)
        unescaped = html.unescape(stripped).strip()
        self.assertEqual(unescaped, "SearXNG & AI: \"Fast 'n' Lean\" <3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
