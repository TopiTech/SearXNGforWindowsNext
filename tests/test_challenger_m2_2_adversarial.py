"""Comprehensive Adversarial Verification Suite for Milestone M2.

Challenger M2-2: Windows ACL & Concurrency Stress Challenger
Tests:
1. tools/ensure-secret-key.py:
   - ACL verification & icacls lockdown
   - Concurrency stress & mkstemp collision avoidance
   - Subprocess multi-process concurrent generation race conditions
   - Error handling & orphaned temp file cleanup
2. settings_loader.py:
   - Quoted path handling (double, single, whitespace-padded, custom filenames)
3. Scrape route keepalive:
   - Socket closure verification with max_keepalive_connections=0
   - Check actual deployed code in site-packages and repository
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_PACKAGES = os.path.join(REPO_ROOT, "python", "Lib", "site-packages")
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")

if SITE_PACKAGES not in sys.path:
    sys.path.insert(0, SITE_PACKAGES)
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


# =========================================================================
# SUITE 1: Secret Key ACL, Concurrency, and Error Handling
# =========================================================================
class TestSecretKeyAdversarial(unittest.TestCase):
    """Stress-test tools/ensure-secret-key.py."""

    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "ensure_secret_key", os.path.join(TOOLS_DIR, "ensure-secret-key.py")
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Failed to load spec for ensure-secret-key.py")
        self.esk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.esk)
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        with contextlib.suppress(OSError):
            self.temp_dir.cleanup()

    def test_acl_lockdown_icacls(self):
        """Verify that set_file_permissions applies icacls /inheritance:r /grant:r on Windows."""
        test_file = os.path.join(self.temp_dir.name, "secret.key")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("a" * 64 + "\n")

        self.esk.set_file_permissions(test_file)

        if sys.platform == "win32":
            res = subprocess.run(["icacls", test_file], capture_output=True, text=True, check=True)
            output = res.stdout
            username = os.environ.get("USERNAME", "")
            self.assertTrue(username, "USERNAME env var should be present on Windows")
            self.assertIn(username, output)
            self.assertIn("(R,W)", output)

            # Ensure inheritance is stripped: '(I)' indicates inherited permission
            lines = [l for l in output.splitlines() if test_file in l or username in l]
            for line in lines:
                self.assertNotIn("(I)", line, f"Found inherited permission in icacls output: {line}")

    def test_acl_missing_username_fallback(self):
        """Verify behavior when USERNAME is unset: should not crash."""
        test_file = os.path.join(self.temp_dir.name, "secret_no_user.key")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("b" * 64 + "\n")

        with patch.dict(os.environ, {}, clear=True):
            try:
                self.esk.set_file_permissions(test_file)
            except (OSError, KeyError, subprocess.SubprocessError) as exc:
                self.fail(f"set_file_permissions crashed when USERNAME was missing: {exc}")

    def test_mkstemp_concurrency_threads(self):
        """Simulate 30 concurrent threads calling _write_key on the same file path."""
        test_file = os.path.join(self.temp_dir.name, "concurrent_secret.key")
        num_threads = 30
        keys = [f"{i:02x}" * 32 for i in range(num_threads)]
        results = []
        errors = []

        def worker(idx):
            try:
                success = self.esk._write_key(test_file, keys[idx])
                results.append((idx, success))
            except Exception as exc:  # noqa: BLE001
                errors.append((idx, exc))

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        self.assertEqual(errors, [], f"Unexpected exceptions during concurrent _write_key: {errors}")
        self.assertTrue(os.path.exists(test_file), "Target key file does not exist after concurrent writes")
        final_key = self.esk._read_key(test_file)
        self.assertIsNotNone(final_key)
        self.assertEqual(len(final_key), 64)

        orphaned = [f for f in os.listdir(self.temp_dir.name) if f.startswith(".tmp_key_") or f.endswith(".tmp")]
        self.assertEqual(orphaned, [], f"Orphaned temporary files found in directory: {orphaned}")

    def test_multiprocess_concurrent_key_generation(self):
        """Simulate 10 concurrent processes launching ensure-secret-key from scratch."""
        fake_repo = os.path.join(self.temp_dir.name, "fake_repo")
        fake_tools = os.path.join(fake_repo, "tools")
        fake_config = os.path.join(fake_repo, "config")
        os.makedirs(fake_tools, exist_ok=True)
        os.makedirs(fake_config, exist_ok=True)

        shutil.copy(os.path.join(TOOLS_DIR, "ensure-secret-key.py"), os.path.join(fake_tools, "ensure-secret-key.py"))
        shutil.copy(
            os.path.join(REPO_ROOT, "config", "settings.yml.example"), os.path.join(fake_config, "settings.yml.example")
        )

        target_script = os.path.join(fake_tools, "ensure-secret-key.py")
        num_procs = 10
        cmd = [sys.executable, target_script]

        def run_proc():
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=fake_repo, check=False)
            return p.returncode, p.stdout.strip(), p.stderr.strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_procs) as executor:
            futures = [executor.submit(run_proc) for _ in range(num_procs)]
            results = [f.result() for f in futures]

        exit_codes = [r[0] for r in results]
        outputs = [r[1] for r in results]
        stderrs = [r[2] for r in results]

        print(f"\n[DEBUG] Multiprocess results: exit codes={exit_codes}")
        for i, code in enumerate(exit_codes):
            self.assertEqual(
                code, 0, f"Process {i} failed with return code {code}. stdout: {outputs[i]}, stderr: {stderrs[i]}"
            )
            self.assertTrue(outputs[i].startswith("set SEARXNG_SECRET="))
            key_val = outputs[i].replace("set SEARXNG_SECRET=", "")
            self.assertEqual(len(key_val), 64)

        # Check secret.key exists and has no orphans
        orphaned = [f for f in os.listdir(fake_config) if f.startswith(".tmp_key_") or f.endswith(".tmp")]
        self.assertEqual(orphaned, [], f"Orphaned temporary files in fake_config: {orphaned}")

    def test_error_handling_orphaned_file_cleanup_on_write_error(self):
        """Verify cleanup when an error occurs during f.write()."""
        test_file = os.path.join(self.temp_dir.name, "failed_secret.key")
        orig_open = open

        class MockFile:
            def __init__(self, real_f):
                self.real_f = real_f

            def write(self, s):
                raise OSError("Disk full error")

            def flush(self):
                pass

            def fileno(self):
                return self.real_f.fileno()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return self.real_f.__exit__(exc_type, exc_val, exc_tb)

        def mock_open(*args, **kwargs):
            real_f = orig_open(*args, **kwargs)
            if len(args) > 0 and isinstance(args[0], int):
                return MockFile(real_f)
            return real_f

        with patch("builtins.open", side_effect=mock_open):
            success = self.esk._write_key(test_file, "c" * 64)
            self.assertFalse(success, "_write_key should return False when write fails")

        # Check that no .tmp_key_* file was left behind
        orphaned = [f for f in os.listdir(self.temp_dir.name) if f.startswith(".tmp_key_")]
        self.assertEqual(orphaned, [], f"Orphaned temporary file remained after failure: {orphaned}")

    def test_fd_leak_on_open_failure_adversarial(self):
        """Empirically test vulnerability: If open(temp_fd) fails, temp_fd is leaked,
        causing os.remove(tmp_path) to fail with WinError 32 on Windows.
        """
        test_file = os.path.join(self.temp_dir.name, "fd_leak_secret.key")
        orig_open = open
        leaked_fds = []

        def failing_open(*args, **kwargs):
            if len(args) > 0 and isinstance(args[0], int):
                leaked_fds.append(args[0])
                raise OSError("Low-level OS failure opening file descriptor")
            return orig_open(*args, **kwargs)

        try:
            with patch("builtins.open", side_effect=failing_open):
                success = self.esk._write_key(test_file, "d" * 64)
                self.assertFalse(success)

            orphaned = [f for f in os.listdir(self.temp_dir.name) if f.startswith(".tmp_key_")]
            print(f"\n[DEBUG] Orphaned files after open failure: {orphaned}")
            self.assertEqual(
                orphaned, [], f"Bug in ensure-secret-key.py: temp_fd leaked and orphaned file remaining: {orphaned}"
            )
        finally:
            # Clean up leaked fds so Windows temp directory can be removed in tearDown
            for fd in leaked_fds:
                try:
                    os.close(fd)
                except OSError:
                    pass


# =========================================================================
# SUITE 2: Settings Loader Quote Handling
# =========================================================================
class TestSettingsLoaderAdversarial(unittest.TestCase):
    """Stress-test settings_loader.py quote handling."""

    def setUp(self):
        self.orig_env = os.environ.get("SEARXNG_SETTINGS_PATH")
        self.orig_disable = os.environ.get("SEARXNG_DISABLE_ETC_SETTINGS")
        os.environ["SEARXNG_DISABLE_ETC_SETTINGS"] = "1"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.temp_dir.name) / "settings.yml"
        self.custom_file = Path(self.temp_dir.name) / "custom_profile.yml"

        # Write valid minimal settings
        minimal_yaml = "use_default_settings: true\ngeneral:\n  debug: false\n"
        self.settings_file.write_text(minimal_yaml, encoding="utf-8")
        self.custom_file.write_text(minimal_yaml, encoding="utf-8")

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["SEARXNG_SETTINGS_PATH"] = self.orig_env
        else:
            os.environ.pop("SEARXNG_SETTINGS_PATH", None)
        if self.orig_disable is not None:
            os.environ["SEARXNG_DISABLE_ETC_SETTINGS"] = self.orig_disable
        else:
            os.environ.pop("SEARXNG_DISABLE_ETC_SETTINGS", None)
        with contextlib.suppress(OSError):
            self.temp_dir.cleanup()

    def test_surrounding_double_quotes(self):
        """Test SEARXNG_SETTINGS_PATH with surrounding double quotes: '\"path\"'."""
        from searx import settings_loader

        os.environ["SEARXNG_SETTINGS_PATH"] = f'"{self.settings_file}"'
        folder = settings_loader.get_user_cfg_folder()
        self.assertEqual(folder, Path(self.temp_dir.name))
        _cfg, msg = settings_loader.load_settings()
        self.assertIn("settings.yml", msg)

    def test_surrounding_single_quotes(self):
        """Test SEARXNG_SETTINGS_PATH with surrounding single quotes: ''path''."""
        from searx import settings_loader

        os.environ["SEARXNG_SETTINGS_PATH"] = f"'{self.settings_file}'"
        folder = settings_loader.get_user_cfg_folder()
        self.assertEqual(folder, Path(self.temp_dir.name))
        _cfg, msg = settings_loader.load_settings()
        self.assertIn("settings.yml", msg)

    def test_whitespace_padded_double_quotes(self):
        """Test SEARXNG_SETTINGS_PATH with whitespace-padded double quotes: ' \"...\" '."""
        from searx import settings_loader

        os.environ["SEARXNG_SETTINGS_PATH"] = f'  "{self.settings_file}"  '
        folder = settings_loader.get_user_cfg_folder()
        self.assertEqual(folder, Path(self.temp_dir.name))
        _cfg, msg = settings_loader.load_settings()
        self.assertIn("settings.yml", msg)

    def test_whitespace_padded_single_quotes(self):
        """Test SEARXNG_SETTINGS_PATH with whitespace-padded single quotes: ' '...' '."""
        from searx import settings_loader

        os.environ["SEARXNG_SETTINGS_PATH"] = f"  '{self.settings_file}'  "
        folder = settings_loader.get_user_cfg_folder()
        self.assertEqual(folder, Path(self.temp_dir.name))
        _cfg, msg = settings_loader.load_settings()
        self.assertIn("settings.yml", msg)

    def test_custom_filename_with_quotes(self):
        """Test SEARXNG_SETTINGS_PATH with custom filename like 'custom_profile.yml' in quotes."""
        from searx import settings_loader

        os.environ["SEARXNG_SETTINGS_PATH"] = f'"{self.custom_file}"'
        folder = settings_loader.get_user_cfg_folder()
        self.assertEqual(folder, Path(self.temp_dir.name))
        _cfg, msg = settings_loader.load_settings()
        self.assertIn("custom_profile.yml", msg)


# =========================================================================
# SUITE 3: Scrape Route Keepalive & Socket Closure
# =========================================================================
class KeepaliveTrackingHandler(http.server.BaseHTTPRequestHandler):
    """Local HTTP handler supporting HTTP/1.1 keep-alive and recording client ports."""

    protocol_version = "HTTP/1.1"
    requests_received: ClassVar[list] = []

    def do_GET(self):
        KeepaliveTrackingHandler.requests_received.append(self.client_address)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "13")
        self.end_headers()
        self.wfile.write(b"Hello, world!")

    def log_message(self, format, *args):
        pass


class TestScrapeKeepaliveAdversarial(unittest.TestCase):
    """Stress-test keepalive socket closure vs reuse."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), KeepaliveTrackingHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        KeepaliveTrackingHandler.requests_received.clear()

    def test_empirical_keepalive_zero_closes_socket(self):
        """Empirically prove that max_keepalive_connections=0 forces new socket per request,
        while max_keepalive_connections=20 reuses the same socket.
        """
        import httpx

        url = f"http://127.0.0.1:{self.port}/"

        # Case 1: max_keepalive_connections=20 (pooling allowed)
        KeepaliveTrackingHandler.requests_received.clear()
        client_reuse = httpx.Client(
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            timeout=5.0,
        )
        try:
            r1 = client_reuse.get(url)
            r2 = client_reuse.get(url)
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
        finally:
            client_reuse.close()

        ports_reuse = [addr[1] for addr in KeepaliveTrackingHandler.requests_received]
        print(f"\n[DEBUG] max_keepalive_connections=20 client ports: {ports_reuse}")
        self.assertEqual(len(ports_reuse), 2)
        self.assertEqual(ports_reuse[0], ports_reuse[1], "max_keepalive_connections=20 should reuse TCP socket")

        # Case 2: max_keepalive_connections=0 (pooling prohibited)
        KeepaliveTrackingHandler.requests_received.clear()
        client_no_reuse = httpx.Client(
            limits=httpx.Limits(max_keepalive_connections=0, max_connections=50),
            timeout=5.0,
        )
        try:
            r1 = client_no_reuse.get(url)
            r2 = client_no_reuse.get(url)
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
        finally:
            client_no_reuse.close()

        ports_no_reuse = [addr[1] for addr in KeepaliveTrackingHandler.requests_received]
        print(f"[DEBUG] max_keepalive_connections=0 client ports: {ports_no_reuse}")
        self.assertEqual(len(ports_no_reuse), 2)
        self.assertNotEqual(
            ports_no_reuse[0], ports_no_reuse[1], "max_keepalive_connections=0 must NOT reuse TCP socket"
        )

    def test_deployed_site_packages_webapp_keepalive_setting(self):
        """Check if python/Lib/site-packages/searx/webapp.py actually has max_keepalive_connections=0."""
        webapp_path = os.path.join(SITE_PACKAGES, "searx", "webapp.py")
        self.assertTrue(os.path.exists(webapp_path), f"webapp.py not found at {webapp_path}")
        content = Path(webapp_path).read_text(encoding="utf-8")

        match = re.search(r"scrape_limits\s*=\s*httpx\.Limits\((.*?)\)", content)
        self.assertIsNotNone(match, "Could not find scrape_limits in site-packages searx/webapp.py")
        limits_str = match.group(1)
        print(f"\n[DEBUG] Site-packages webapp.py scrape_limits: {limits_str}")
        self.assertIn(
            "max_keepalive_connections=0",
            limits_str,
            f"DEPLOYMENT BUG: site-packages/searx/webapp.py has '{limits_str}', NOT max_keepalive_connections=0!",
        )

    def test_webui_next_keepalive_setting(self):
        """Check if tools/webui_next.py fetch_url has max_keepalive_connections=0 or 20."""
        webui_path = os.path.join(TOOLS_DIR, "webui_next.py")
        content = Path(webui_path).read_text(encoding="utf-8")
        match = re.search(r"scrape_limits\s*=\s*httpx_mod\.Limits\((.*?)\)", content)
        if match:
            limits_str = match.group(1)
            print(f"\n[DEBUG] tools/webui_next.py scrape_limits: {limits_str}")
            self.assertIn("max_keepalive_connections=0", limits_str, f"tools/webui_next.py still has '{limits_str}'")


if __name__ == "__main__":
    unittest.main()
