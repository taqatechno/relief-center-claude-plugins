"""
Create one blog.post in Odoo Latest News from a JSON field dict.

Used by the main orchestrator of the publish-relief-center-news skill.
Reads credentials via odoo_client.load_credentials (auto-discovered) and
talks to /xmlrpc/2/object directly — no MCP.

Input (file path argument or stdin, JSON):
    {
        "title_en":       "English title",
        "title_ar":       "العنوان العربي",
        "body_en_html":   "<p>English body...</p>",
        "body_ar_html":   "<p>Arabic body...</p>",
        "post_date_iso":  "2026-04-15 00:00:00",   # or "YYYY-MM-DD"
        "author_id":      42,                      # int (res.partner id)
        "country_ids":    [110, 221]               # list of res.country ids; may be []
    }

Usage:
    python publish_blog_post.py /path/to/article.json    # Read from file
    python publish_blog_post.py < /path/to/article.json  # Read from stdin

Output (stdout, JSON):
    {"status": "created",  "id": 123, "url": "https://.../blog/latest-news-14/...-123"}
    {"status": "existing", "id": 123, "url": "..."}         # duplicate title pre-flight hit
    {"status": "partial",  "id": 123, "url": "...",         # EN created, AR translation failed
     "warning": "..."}

On unrecoverable failure: prints error JSON to stdout, exits non-zero.

Constants (locked per plan):
    blog_id                = 14   (Latest News)
    is_published           = true
    website_published      = true
    is_homepage            = true
    is_relief_coordination = false
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback

from odoo_client import OdooClient, OdooRpcError, load_credentials


LATEST_NEWS_BLOG_ID = 14
AR_LANG_CODE = "ar_001"
REQUIRED_FIELDS = [
    "title_en",
    "title_ar",
    "body_en_html",
    "body_ar_html",
    "post_date_iso",
    "author_id",
    "country_ids",
]

# Defensive retry loop. Under XML-RPC we hit a reproducible server-side expat
# fault ("reference to invalid character number") on bilingual writes — that
# failure class is gone now that we POST JSON instead, but we keep the
# matchers and the retry as defense in depth against any similar transient
# that might show up at the JSON-RPC endpoint later. Match narrowly so we
# don't mask real errors (invalid field values, access denials, etc.).
_TRANSIENT_FAULT_MARKERS = (
    "reference to invalid character number",  # legacy XML-parser symptom
)
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.0


def _is_transient_fault(fault: OdooRpcError) -> bool:
    msg = str(getattr(fault, "faultString", "") or "")
    return any(marker in msg for marker in _TRANSIENT_FAULT_MARKERS)


def _call_with_retry(client: OdooClient, model: str, method: str,
                     args: list, kwargs: dict | None = None):
    """Call client.call() with a small retry loop scoped to known transients.
    All other faults propagate immediately."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return client.call(model, method, args, kwargs)
        except OdooRpcError as exc:
            if not _is_transient_fault(exc) or attempt == _MAX_ATTEMPTS:
                raise
            sys.stderr.write(
                f"[retry] {model}.{method} attempt {attempt}/{_MAX_ATTEMPTS} "
                f"hit transient fault; sleeping {_RETRY_DELAY_SECONDS:g}s\n"
            )
            sys.stderr.flush()
            time.sleep(_RETRY_DELAY_SECONDS)


def _print_json(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _print_err(obj: dict) -> None:
    sys.stderr.write(json.dumps(obj, ensure_ascii=False))
    sys.stderr.write("\n")
    sys.stderr.flush()


def _validate(payload: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    if not isinstance(payload["country_ids"], list):
        raise ValueError("country_ids must be a list (may be empty)")
    if not isinstance(payload["author_id"], int):
        raise ValueError("author_id must be an integer")


def _find_existing(client: OdooClient, title_en: str) -> int | None:
    hits = _call_with_retry(
        client,
        "blog.post",
        "search",
        [[["blog_id", "=", LATEST_NEWS_BLOG_ID], ["name", "=", title_en]]],
        {"limit": 1},
    )
    return hits[0] if hits else None


def _build_url(client: OdooClient, record_id: int, title_en: str) -> str:
    # Best-effort: read website_absolute_url so the caller gets a real link.
    try:
        rows = _call_with_retry(
            client,
            "blog.post",
            "read",
            [[record_id], ["website_absolute_url", "website_url"]],
        )
        if rows:
            return rows[0].get("website_absolute_url") or rows[0].get("website_url") or ""
    except Exception:
        pass
    return ""


def publish(payload: dict) -> dict:
    _validate(payload)
    client = OdooClient.from_credentials(load_credentials())

    existing = _find_existing(client, payload["title_en"])
    if existing:
        url = _build_url(client, existing, payload["title_en"])
        return {"status": "existing", "id": existing, "url": url}

    # Create payload deliberately OMITS `website_content_ar` — see the block
    # comment below the create call. The Arabic body is set in step 2 via a
    # separate write. Do not add it back here.
    vals = {
        "name": payload["title_en"],
        "blog_id": LATEST_NEWS_BLOG_ID,
        "content": payload["body_en_html"],
        "author_id": payload["author_id"],
        "country_ids": [(6, 0, payload["country_ids"])],  # many2many replace-all
        "post_date": payload["post_date_iso"],
        "published_date": payload["post_date_iso"],
        "is_published": True,
        "website_published": True,
        "is_homepage": True,
        "is_relief_coordination": False,
    }

    # Step 1 — create. Must not include `website_content_ar`. Adding the full
    # bilingual payload to create reliably triggers a server-side XML-RPC
    # envelope parse fault on this Odoo staging instance (see
    # reports/error-report.md and the plan's "Known issue: large bilingual
    # create payload" section). Splitting the Arabic body into its own write
    # (step 2) keeps the create small enough to go through. Do NOT merge this
    # field back into `vals` as a "simplification".
    record_id = _call_with_retry(client, "blog.post", "create", [vals])

    warning: str | None = None

    # Step 2 — Arabic body (`website_content_ar`). Separate write.
    try:
        _call_with_retry(
            client,
            "blog.post",
            "write",
            [[record_id], {"website_content_ar": payload["body_ar_html"]}],
        )
    except Exception as exc:
        warning = f"AR body write failed: {exc!r}"

    # Step 3 — Arabic title translation. Uses lang context because `name` is a
    # translatable field; setting it here stores the ar_001 translation
    # alongside the en_US value set during create.
    try:
        _call_with_retry(
            client,
            "blog.post",
            "write",
            [[record_id], {"name": payload["title_ar"]}],
            {"context": {"lang": AR_LANG_CODE}},
        )
    except Exception as exc:
        title_warn = f"AR title translation failed: {exc!r}"
        warning = f"{warning}; {title_warn}" if warning else title_warn

    # Step 4 — refresh teaser. Odoo's first-pass teaser compute (run during
    # create) renders inline <strong> tags as *asterisks* in the plaintext
    # snippet — e.g., "*Dr. Name |*" instead of "Dr. Name |". Any subsequent
    # write of `content` re-runs the compute with a cleaner HTML-to-text pass,
    # so a no-op rewrite of the same content value produces the clean teaser
    # that matches manually-edited posts (verified against post 121). Failure
    # here is cosmetic only.
    try:
        _call_with_retry(
            client,
            "blog.post",
            "write",
            [[record_id], {"content": vals["content"]}],
        )
    except Exception as exc:
        teaser_warn = f"teaser refresh failed: {exc!r}"
        warning = f"{warning}; {teaser_warn}" if warning else teaser_warn

    url = _build_url(client, record_id, payload["title_en"])
    result: dict = {"status": "partial" if warning else "created", "id": record_id, "url": url}
    if warning:
        result["warning"] = warning
    return result


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    # Read JSON from file argument or stdin
    if len(sys.argv) > 1:
        # File path provided as argument
        file_path = sys.argv[1]
        try:
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
        except FileNotFoundError:
            _print_err({"error": "file not found", "path": file_path})
            return 2
        except Exception as exc:
            _print_err({"error": f"failed to read file: {exc}", "path": file_path})
            return 2
    else:
        # Read from stdin (backward compatible)
        # On Windows, the default sys.stdin.read() uses the locale codec
        # (often cp1252) and can inject surrogates for undecodable bytes,
        # which crashes the JSON-RPC encoder. Going through stdin.buffer
        # sidesteps this and uses UTF-8 directly.
        raw_bytes = sys.stdin.buffer.read()

    if not raw_bytes.strip():
        _print_err({"error": "no JSON payload provided"})
        return 2

    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        _print_err({"error": "payload not valid UTF-8", "detail": str(exc)})
        return 2

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _print_err({"error": "invalid JSON", "detail": str(exc)})
        return 2

    try:
        result = publish(payload)
    except Exception as exc:
        _print_err({
            "error": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        })
        return 1

    _print_json(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
