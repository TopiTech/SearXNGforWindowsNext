"""Ensure secret_key in settings.yml is not the default value.

If the secret_key matches the known default, generate a new random key.
This script is called by the launcher batch file before starting the server.
"""
import secrets
import os
import re
import sys

DEFAULT_KEY = "SearXNG for Windows-mbaozi"
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yml")


def main():
    path = os.path.normpath(SETTINGS_PATH)
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    default_pattern = rf'secret_key:\s*["\']?{re.escape(DEFAULT_KEY)}["\']?'
    if not re.search(default_pattern, content):
        return

    print("[INFO] Default secret_key detected. Generating a secure random key...")
    new_key = secrets.token_hex(32)
    content = re.sub(
        default_pattern,
        f'secret_key: "{new_key}"',
        content,
        count=1,
    )
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


if __name__ == "__main__":
    main()
