#!/usr/bin/env python3
"""Unified Opaque-Box Test Client and CLI Runner for SearXNGforWindowsNext E2E Tests.

Supports automatic test server management:
1. If a running SearXNG server is detected on SEARXNG_BASE_URL (or http://127.0.0.1:8888),
   tests communicate with it over real HTTP.
2. If no server is running, an in-process WSGI server is spun up on an ephemeral localhost port
   (e.g., http://127.0.0.1:0), providing an authentic live HTTP runtime for both API endpoints
   and CLI tools (tools/searxng_cli.py) without requiring separate process orchestration.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Determine workspace root
TESTS_E2E_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TESTS_E2E_DIR, "..", ".."))
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
CONFIG_DIR = os.path.join(REPO_ROOT, "config")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.yml")
PYTHON_EXE = os.path.join(REPO_ROOT, "python", "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

# Shared global background test server
_SERVER_LOCK = threading.Lock()
_EPHEMERAL_SERVER: Any = None
_EPHEMERAL_SERVER_THREAD: threading.Thread | None = None
_RESOLVED_BASE_URL: str | None = None


class E2EResponse:
    """Standardized response container for opaque-box HTTP responses."""

    def __init__(self, status_code: int, headers: dict[str, str], text: str, data: bytes) -> None:
        self.status_code = status_code
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.text = text
        self.data = data

    def json(self) -> Any:
        """Parse response text as JSON."""
        return json.loads(self.text)

    def header(self, name: str, default: str = "") -> str:
        """Get header value case-insensitively."""
        return self.headers.get(name.lower(), default)

    def __repr__(self) -> str:
        return f"<E2EResponse [{self.status_code}] length={len(self.data)}>"


def _is_url_healthy(url: str, timeout: float = 1.0) -> bool:
    """Check if a SearXNG instance responds at url/healthz."""
    health_url = f"{url.rstrip('/')}/healthz"
    try:
        req = urllib.request.Request(
            health_url,
            headers={
                "User-Agent": "SearXNG-E2E-Probe/1.0",
                "X-Forwarded-For": "127.0.0.1",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def start_test_server() -> str:
    """Start an ephemeral in-process WSGI server if no live server is already active."""
    global _EPHEMERAL_SERVER, _EPHEMERAL_SERVER_THREAD, _RESOLVED_BASE_URL

    with _SERVER_LOCK:
        if _RESOLVED_BASE_URL and _is_url_healthy(_RESOLVED_BASE_URL):
            return _RESOLVED_BASE_URL

        # 1. Check if configured SEARXNG_BASE_URL or default 8888 is active
        configured_url = os.environ.get("SEARXNG_BASE_URL", "http://127.0.0.1:8888").rstrip("/")
        if _is_url_healthy(configured_url):
            _RESOLVED_BASE_URL = configured_url
            return _RESOLVED_BASE_URL

        # 2. Setup environment variables for local SearXNG
        if not os.environ.get("SEARXNG_SECRET"):
            os.environ["SEARXNG_SECRET"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        if not os.environ.get("SEARXNG_SETTINGS_PATH") and os.path.exists(SETTINGS_PATH):
            os.environ["SEARXNG_SETTINGS_PATH"] = SETTINGS_PATH
        os.environ["SEARXNG_LIMITER"] = "false"

        # Suppress noisy logging during tests
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        from searx.webapp import app
        from werkzeug.serving import make_server

        srv = make_server("127.0.0.1", 0, app, threaded=True)
        port = srv.port
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()

        _EPHEMERAL_SERVER = srv
        _EPHEMERAL_SERVER_THREAD = t
        _RESOLVED_BASE_URL = f"http://127.0.0.1:{port}"
        os.environ["SEARXNG_BASE_URL"] = _RESOLVED_BASE_URL
        return _RESOLVED_BASE_URL


def stop_test_server() -> None:
    """Shut down the ephemeral background test server if started."""
    global _EPHEMERAL_SERVER, _EPHEMERAL_SERVER_THREAD, _RESOLVED_BASE_URL

    with _SERVER_LOCK:
        if _EPHEMERAL_SERVER:
            with contextlib.suppress(Exception):
                _EPHEMERAL_SERVER.shutdown()
            _EPHEMERAL_SERVER = None
            _EPHEMERAL_SERVER_THREAD = None
            _RESOLVED_BASE_URL = None


class E2EClient:
    """Opaque-box client executing API requests via live HTTP."""

    def __init__(self, base_url: str | None = None) -> None:
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = start_test_server()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
    ) -> E2EResponse:
        """Execute HTTP GET request."""
        query_str = f"?{urllib.parse.urlencode(params)}" if params else ""
        full_url = f"{self.base_url}{path}{query_str}"
        req_headers = {
            "User-Agent": "SearXNG-E2E-Test/1.0",
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(full_url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                text = data.decode("utf-8", errors="replace")
                resp_headers = dict(resp.headers)
                return E2EResponse(resp.status, resp_headers, text, data)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            text = data.decode("utf-8", errors="replace")
            resp_headers = dict(exc.headers)
            return E2EResponse(exc.code, resp_headers, text, data)

    def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        json_data: Any | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
    ) -> E2EResponse:
        """Execute HTTP POST request."""
        full_url = f"{self.base_url}{path}"
        req_headers = {
            "User-Agent": "SearXNG-E2E-Test/1.0",
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
        }
        if headers:
            req_headers.update(headers)

        body_bytes = b""
        if json_data is not None:
            body_bytes = json.dumps(json_data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif data is not None:
            body_bytes = urllib.parse.urlencode(data).encode("utf-8")
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(full_url, data=body_bytes, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_data = resp.read()
                text = resp_data.decode("utf-8", errors="replace")
                resp_headers = dict(resp.headers)
                return E2EResponse(resp.status, resp_headers, text, resp_data)
        except urllib.error.HTTPError as exc:
            resp_data = exc.read()
            text = resp_data.decode("utf-8", errors="replace")
            resp_headers = dict(exc.headers)
            return E2EResponse(exc.code, resp_headers, text, resp_data)


class E2ECLIRunner:
    """Helper for executing workspace CLI tools in subprocesses."""

    @staticmethod
    def run_cmd(
        args: list[str],
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> subprocess.CompletedProcess:
        """Run an arbitrary command with python executable."""
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)

        return subprocess.run(
            args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=cmd_env,
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def run_searxng_cli(subcommand_args: list[str], base_url: str | None = None) -> subprocess.CompletedProcess:
        """Execute tools/searxng_cli.py with optional base_url."""
        cli_py = os.path.join(TOOLS_DIR, "searxng_cli.py")
        url = base_url or os.environ.get("SEARXNG_BASE_URL") or start_test_server()
        args = [PYTHON_EXE, cli_py, "--base-url", url] + subcommand_args
        return E2ECLIRunner.run_cmd(args)

    @staticmethod
    def run_apply_patches(patch_args: list[str]) -> subprocess.CompletedProcess:
        """Execute tools/apply-patches.py."""
        script_py = os.path.join(TOOLS_DIR, "apply-patches.py")
        args = [PYTHON_EXE, script_py] + patch_args
        return E2ECLIRunner.run_cmd(args)

    @staticmethod
    def run_ensure_secret_key(key_args: list[str] | None = None) -> subprocess.CompletedProcess:
        """Execute tools/ensure-secret-key.py."""
        script_py = os.path.join(TOOLS_DIR, "ensure-secret-key.py")
        args = [PYTHON_EXE, script_py] + (key_args or [])
        return E2ECLIRunner.run_cmd(args)
