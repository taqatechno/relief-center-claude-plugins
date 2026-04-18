"""
Persist Odoo credentials collected interactively during the skill's Step 0.

Reads a small JSON object from stdin with the four fields the user gave us
and writes them to ~/.claude/odoo-credentials.json in the nested shape that
odoo_client.load_credentials() already recognizes (the `staging` key holding
`url/db/uid/credential`). This is the path taken when the plugin's userConfig
isn't reaching scripts as env vars — mostly Claude Desktop today, since
Claude Code's `/plugin config` tends to flow through differently — so the
skill collects the values once in chat and saves them here for every future
invocation to find.

Input (stdin, JSON):
    {"url": "https://...", "db": "...", "uid": "67", "password": "..."}
    # uid may be string or int; passwords accepted verbatim

Output (stdout, JSON): {"saved": "<absolute-path>"} on success.
Exit 0 on success; non-zero with error JSON on validation failure.

Sensitive values (the password) end up in a plaintext JSON file in the
user's home. This is a pragmatic tradeoff: the alternative (OS keyring
APIs, per-platform code) is heavier and this skill is already OK with
the same shape when credentials live inside a project tree. If you care
about at-rest protection, use a disk-encrypted home directory or the
env-var path instead.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path


REQUIRED_FIELDS = ("url", "db", "uid", "password")
TARGET_PATH = Path.home() / ".claude" / "odoo-credentials.json"


def _print(obj: dict, stream=None) -> None:
    (stream or sys.stdout).write(json.dumps(obj, ensure_ascii=False))
    (stream or sys.stdout).write("\n")
    (stream or sys.stdout).flush()


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    raw_bytes = sys.stdin.buffer.read()
    if not raw_bytes.strip():
        _print({"error": "no JSON payload on stdin"}, sys.stderr)
        return 2

    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        _print({"error": "stdin not valid UTF-8", "detail": str(exc)}, sys.stderr)
        return 2

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _print({"error": "invalid JSON on stdin", "detail": str(exc)}, sys.stderr)
        return 2

    missing = [f for f in REQUIRED_FIELDS if not payload.get(f)]
    if missing:
        _print({"error": f"missing required field(s): {missing}"}, sys.stderr)
        return 2

    try:
        uid_int = int(payload["uid"])
    except (TypeError, ValueError):
        _print({"error": f"uid must be numeric, got {payload['uid']!r}"}, sys.stderr)
        return 2

    record = {
        "staging": {
            "url": payload["url"].rstrip(),
            "db": payload["db"].rstrip(),
            "uid": uid_int,
            "credential": payload["password"],
        }
    }

    # Merge with any existing file so we don't blow away other environments.
    existing: dict = {}
    if TARGET_PATH.is_file():
        try:
            existing = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except json.JSONDecodeError:
            existing = {}
    existing["staging"] = record["staging"]

    TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    TARGET_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _print({"saved": str(TARGET_PATH)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
