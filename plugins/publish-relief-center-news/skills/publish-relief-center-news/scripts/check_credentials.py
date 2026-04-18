"""
Verify Odoo credentials are configured and accepted by the server.

Used as the skill's Step 0 (before any docx or publish work) so the
orchestrator can tell the user exactly how to fix a missing or wrong
configuration before anything else runs. This matters on Claude Desktop
in particular, where the plugin's userConfig UI doesn't always surface
at install time — without this check, the first downstream script fails
with a scary `CredentialsNotFound` traceback that leaves the user stuck.

Always exits with one line of JSON on stdout.

Success:     {"ok": true, "user": "Name", "uid": 67}              (exit 0)
Missing:     {"ok": false, "error": "missing", "message": "..."}  (exit 1)
Auth failed: {"ok": false, "error": "auth_failed", "message": "..."}  (exit 1)
"""
from __future__ import annotations

import io
import json
import sys

from odoo_client import (
    CredentialsNotFound,
    OdooClient,
    load_credentials,
)


def _print(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    try:
        creds = load_credentials()
    except CredentialsNotFound as exc:
        _print({"ok": False, "error": "missing", "message": str(exc)})
        return 1
    except Exception as exc:
        # Malformed file, bad JSON, ValueError from ODOO_UID-not-numeric, etc.
        _print({
            "ok": False,
            "error": "missing",
            "message": f"Credential loader raised {type(exc).__name__}: {exc}",
        })
        return 1

    try:
        client = OdooClient.from_credentials(creds)
        rows = client.call(
            "res.users", "read", [[creds["uid"]], ["name", "login"]]
        )
    except Exception as exc:
        # Server-side auth failure, network issues, or any Odoo-side rejection.
        _print({
            "ok": False,
            "error": "auth_failed",
            "message": f"{type(exc).__name__}: {str(exc)[:300]}",
        })
        return 1

    if not rows:
        _print({
            "ok": False,
            "error": "auth_failed",
            "message": f"res.users.read returned no row for uid {creds['uid']}.",
        })
        return 1

    user = rows[0]
    _print({"ok": True, "user": user.get("name", ""), "uid": creds["uid"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
