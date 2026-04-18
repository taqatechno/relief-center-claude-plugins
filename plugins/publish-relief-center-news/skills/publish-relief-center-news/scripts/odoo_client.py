"""
Shared Odoo JSON-RPC client for the publish-relief-center-news plugin.

Credentials are resolved in this order, first match wins:

1. **Individual environment variables** — `ODOO_URL`, `ODOO_DB`, `ODOO_UID`,
   `ODOO_PASSWORD`. These map 1:1 to the plugin's userConfig fields. Set
   all four for this path to win; partial sets fall through to step 2.
2. **`odoo-credentials.json` file** — auto-discovered via
   `ODOO_CREDENTIALS_PATH` env var override, or by walking up from `cwd`.
   The file's `staging` key (or whatever `ODOO_ENVIRONMENT` names) must
   contain `{url, db, uid, credential}`. Dev-time fallback.

JSON-RPC is used instead of XML-RPC because the Odoo staging edge layer
intermittently corrupts bytes inside the XML envelope, tripping the
server's `xml.parsers.expat` parser with a "reference to invalid character
number" fault before any ORM logic runs. The fault is often session-
persistent — every retry against the same keep-alive connection re-hits
the same parser. JSON-RPC has no XML parser in the pipeline, so that
entire failure class disappears.

This module is imported by the other scripts in this folder — it is not a
CLI.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


CREDENTIALS_FILENAME = "odoo-credentials.json"
DEFAULT_ENVIRONMENT_KEY = "staging"
DEFAULT_TIMEOUT_SECONDS = 60.0
ENV_VAR_NAMES = ("ODOO_URL", "ODOO_DB", "ODOO_UID", "ODOO_PASSWORD")


class CredentialsNotFound(FileNotFoundError):
    pass


class OdooRpcError(Exception):
    """Raised when Odoo's JSON-RPC endpoint returns an error object.

    Exposes `.faultCode` and `.faultString` attributes so existing retry
    matchers written against `xmlrpc.client.Fault` continue to work
    (they grep substrings from `faultString`).
    """

    def __init__(self, code, message, data=None):
        self.faultCode = code
        data = data or {}
        self.faultString = (
            data.get("debug") or data.get("message") or message or ""
        )
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"<OdooRpcError {code}: {self.faultString[:200]}>")


def _credentials_from_env() -> dict | None:
    """Return a credential dict if all four env vars are set, else None."""
    values = {name: os.environ.get(name) for name in ENV_VAR_NAMES}
    if any(v is None or v == "" for v in values.values()):
        return None
    try:
        uid_int = int(values["ODOO_UID"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"ODOO_UID must be a numeric string, got {values['ODOO_UID']!r}"
        ) from exc
    return {
        "url": values["ODOO_URL"],
        "db": values["ODOO_DB"],
        "uid": uid_int,
        "credential": values["ODOO_PASSWORD"],
    }


def _discover_credentials_path() -> Path:
    env_path = os.environ.get("ODOO_CREDENTIALS_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p
        raise CredentialsNotFound(
            f"ODOO_CREDENTIALS_PATH={env_path!r} does not point to a file."
        )

    checked: list[Path] = []

    # 1) The file the skill's interactive Step 0 writes to. This is the
    #    canonical location for credentials collected in chat, reachable
    #    regardless of where the user invokes the skill from.
    home_path = Path.home() / ".claude" / CREDENTIALS_FILENAME
    checked.append(home_path)
    if home_path.is_file():
        return home_path

    # 2) Walk up from cwd to catch project-local credential files (the
    #    original dev-mode discovery path, still supported).
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / CREDENTIALS_FILENAME
        checked.append(candidate)
        if candidate.is_file():
            return candidate

    raise CredentialsNotFound(
        "No Odoo credentials found. Set the plugin userConfig (ODOO_URL, "
        "ODOO_DB, ODOO_UID, ODOO_PASSWORD) via `/plugin config`, export "
        "those env vars, or let the skill's Step 0 prompt you to enter "
        "them interactively (they'll be saved to ~/.claude/"
        "odoo-credentials.json). Paths checked for the file:\n  "
        + "\n  ".join(str(p) for p in checked)
    )


def load_credentials(
    path: str | os.PathLike | None = None,
    environment: str = DEFAULT_ENVIRONMENT_KEY,
) -> dict:
    """Return the credential dict. Env vars win over the file; pass
    `path` explicitly to force the file path and skip env-var lookup."""
    if path is None:
        creds = _credentials_from_env()
        if creds is not None:
            return creds

    resolved = Path(path) if path else _discover_credentials_path()
    data = json.loads(resolved.read_text(encoding="utf-8"))
    env_key = os.environ.get("ODOO_ENVIRONMENT", environment)
    if env_key not in data:
        raise KeyError(
            f"Environment key {env_key!r} missing from {resolved}. "
            f"Available: {sorted(data.keys())}"
        )
    return data[env_key]


class OdooClient:
    """Minimal wrapper around Odoo's /jsonrpc endpoint for execute_kw calls."""

    def __init__(self, url: str, db: str, uid: int, password: str,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.url = url.rstrip("/")
        self.db = db
        self.uid = uid
        self.password = password
        self.timeout = timeout
        self._endpoint = f"{self.url}/jsonrpc"

    @classmethod
    def from_credentials(cls, creds: dict | None = None) -> "OdooClient":
        if creds is None:
            creds = load_credentials()
        return cls(
            url=creds["url"],
            db=creds["db"],
            uid=int(creds["uid"]),
            password=creds["credential"],
        )

    def call(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
    ):
        """POST an `execute_kw(db, uid, password, model, method, args, kwargs)`
        JSON-RPC envelope to Odoo and return the unwrapped `.result`.

        Raises `OdooRpcError` when Odoo returns an `error` object.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db,
                    self.uid,
                    self.password,
                    model,
                    method,
                    args,
                    kwargs or {},
                ],
            },
        }
        # ensure_ascii=True escapes non-ASCII (e.g. Arabic) as \uXXXX, producing
        # a pure-ASCII string. This avoids a Windows-specific UnicodeEncodeError
        # that fires when upstream stdin decoding leaves unpaired surrogates in
        # the payload: with ensure_ascii=False + .encode('utf-8'), surrogates
        # crash the encode step. With ensure_ascii=True the encode is a no-op
        # on the ASCII output. Odoo's JSON parser decodes the \uXXXX escapes
        # back to the original codepoints server-side, so this is lossless.
        body = json.dumps(payload, ensure_ascii=True).encode("ascii")
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            response = json.loads(resp.read().decode("utf-8"))

        if "error" in response:
            err = response["error"]
            raise OdooRpcError(
                code=err.get("code", -1),
                message=err.get("message", ""),
                data=err.get("data"),
            )
        return response.get("result")
