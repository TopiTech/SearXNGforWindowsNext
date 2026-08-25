"""Ensure secret_key in settings.yml is not the default value.

If the secret_key matches the known default, generate a new random key.
This script is called by the launcher batch file before starting the server.
"""
import secrets
import os
import re

DEFAULT_KEY = "SearXNG for Windows-mbaozi"
# Known committed keys in config/settings.yml that must be rotated on first run.
# These values were committed to the repository and are shared by all clones.
KNOWN_COMMITTED_KEYS = [
    DEFAULT_KEY,
    "654eba279ae3354410f8c36f11535af7b1d6f893482cccad86268bdd50a047c1",
    "4d7e7376e13c5de05bd915d4e270928abf72686db55a58b27ae3d5c14cf387d4",
    "c131e23ee31e69e1f16c712e6e1b3e1a7b20b976bf75f10d2a45da807201ba70",
    "CHANGE_ME__generate_with_tools_ensure_secret_key_py__or_set_SEARXNG_SECRET",
]
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yml")


def main():
    path = os.path.normpath(SETTINGS_PATH)
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    for known_key in KNOWN_COMMITTED_KEYS:
        default_pattern = rf'secret_key:\s*["\']?{re.escape(known_key)}["\']?'
        if re.search(default_pattern, content):
            print("[INFO] Known committed secret_key detected. Generating a secure random key...")
            new_key = secrets.token_hex(32)
            content = re.sub(
                default_pattern,
                f'secret_key: "{new_key}"',
                content,
                count=1,
            )
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            print(f"[INFO] Rotated secret_key in {path}")
            return
    if re.search(r'secret_key:\s*["\']?CHANGE_ME', content):
        print("[INFO] Placeholder secret_key detected. Generating a secure random key...")
        new_key = secrets.token_hex(32)
        content = re.sub(
            r'secret_key:\s*["\']?CHANGE_ME[^"\']*["\']?',
            f'secret_key: "{new_key}"',
            content,
            count=1,
        )
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        print(f"[INFO] Rotated placeholder secret_key in {path}")
        return


if __name__ == "__main__":
    main()
