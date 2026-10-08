#!/usr/bin/env python3
"""Bundle tools/webui/ components into tools/webui_next.py.

Unifies HTML, CSS, and JavaScript into AI_WORKSPACE_HTML with syntax checking.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
WEBUI_DIR = TOOLS_DIR / "webui"
WEBUI_NEXT_PY = TOOLS_DIR / "webui_next.py"


def build_ai_workspace_html() -> str:
    """Read styles.css, body.html, app.js, and template.html and return combined HTML."""
    css = (WEBUI_DIR / "styles.css").read_text(encoding="utf-8")
    body = (WEBUI_DIR / "body.html").read_text(encoding="utf-8")
    js = (WEBUI_DIR / "app.js").read_text(encoding="utf-8")
    tmpl = (WEBUI_DIR / "template.html").read_text(encoding="utf-8")

    html = tmpl.replace("{{ CSS }}", css).replace("{{ BODY }}", body).replace("{{ JS }}", js)
    validate_assets(css, body, js)
    return html


def validate_assets(css: str, body: str, js: str) -> None:
    """Reject assets that would corrupt the r-string embedding in webui_next.py.

    The compiled HTML is pasted verbatim into ``_EMBEDDED_AI_WORKSPACE_HTML = r\"\"\"...\"\"\"``:
    a ``\"\"\"`` sequence would terminate the literal early, and a trailing
    quote right before the closer would break it too. Failing loudly here
    beats writing a syntactically invalid webui_next.py that kills server
    startup.
    """
    for name, content in (("styles.css", css), ("body.html", body), ("app.js", js)):
        if '"""' in content:
            raise ValueError(f'{name} contains \'"""\' which would break the r-string embedding in webui_next.py')
        if content.endswith('"'):
            raise ValueError(f"{name} ends with a double quote which would break the r-string embedding")
        if "</script" in content.lower():
            raise ValueError(f"{name} contains '</script' which would break the inline <script> block in the HTML")


def verify_webui_next_py(py_text: str) -> None:
    """Compile-check webui_next.py after rewriting; raise on syntax errors."""
    try:
        ast.parse(py_text)
    except SyntaxError as exc:
        raise ValueError(f"webui_next.py is syntactically invalid after bundling: {exc}") from exc


def update_webui_next_py() -> None:
    """Inject the compiled AI_WORKSPACE_HTML into tools/webui_next.py safely."""
    html_content = build_ai_workspace_html()
    py_text = WEBUI_NEXT_PY.read_text(encoding="utf-8")

    # Locate _EMBEDDED_AI_WORKSPACE_HTML = r""" ... """ block
    start_marker = '_EMBEDDED_AI_WORKSPACE_HTML = r"""'
    end_marker = '"""\n\nAI_WORKSPACE_HTML = _load_ai_workspace_html()'

    start_idx = py_text.find(start_marker)
    if start_idx != -1:
        end_idx = py_text.find(end_marker, start_idx)
        if end_idx != -1:
            prefix = py_text[:start_idx]
            suffix = py_text[end_idx:]
            new_py_text = f'{prefix}_EMBEDDED_AI_WORKSPACE_HTML = r"""{html_content}{suffix}'
            verify_webui_next_py(new_py_text)
            WEBUI_NEXT_PY.write_text(new_py_text, encoding="utf-8")
            print(
                f"Successfully compiled {len(html_content)} bytes into _EMBEDDED_AI_WORKSPACE_HTML in {WEBUI_NEXT_PY}"
            )
            return

    # Fallback to direct AI_WORKSPACE_HTML = """
    start_marker_legacy = 'AI_WORKSPACE_HTML = """'
    end_marker_legacy = '\n"""\n\n\ndef register_next_webui'
    start_idx = py_text.find(start_marker_legacy)
    if start_idx != -1:
        end_idx = py_text.find(end_marker_legacy, start_idx)
        if end_idx != -1:
            prefix = py_text[:start_idx]
            suffix = py_text[end_idx:]
            new_py_text = f'{prefix}AI_WORKSPACE_HTML = """{html_content}{suffix}'
            verify_webui_next_py(new_py_text)
            WEBUI_NEXT_PY.write_text(new_py_text, encoding="utf-8")
            print(f"Successfully compiled {len(html_content)} bytes into AI_WORKSPACE_HTML in {WEBUI_NEXT_PY}")
            return

    raise ValueError("Could not find embedding markers in webui_next.py")


if __name__ == "__main__":
    try:
        update_webui_next_py()
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
