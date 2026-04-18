"""
Fuzzy-search an Odoo model by its `name` field and return ranked candidates.

Used by the author resolver (res.partner) and country resolver (res.country)
subagents in the publish-relief-center-news skill. Generic by design: same
code path for any model that exposes a `name` field.

Usage:
    python odoo_search.py <model> <query> [--limit N] [--environment KEY]

Example:
    python odoo_search.py res.partner "Dr. Ola Al Kahlout"
    python odoo_search.py res.country "Yemen" --limit 5

Output: a JSON list sorted by similarity descending, each element shaped:
    {"id": int, "name": str, "similarity": float}   # similarity in [0.0, 1.0]

The 60%-threshold rule is enforced by the caller (the agent reading the JSON),
not by this script. This script stays agnostic so thresholds can be tuned
per caller without rebuilding.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from difflib import SequenceMatcher

from odoo_client import OdooClient, load_credentials


# Words too generic to drive a search on their own. Kept small on purpose —
# the script still searches the full query too, so this only affects
# per-token candidate gathering.
STOPWORDS = {
    "dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "prof", "prof.",
    "the", "of", "and", "&",
}


def _tokenize(query: str) -> list[str]:
    raw = re.split(r"[\s,/\-]+", query.strip())
    seen: set[str] = set()
    tokens: list[str] = []
    for word in raw:
        clean = word.strip().strip(".,;:").lower()
        if not clean or clean in STOPWORDS or len(clean) < 2:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        tokens.append(word.strip().strip(".,;:"))
    return tokens


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def search(client: OdooClient, model: str, query: str, limit: int) -> list[dict]:
    """Collect candidates matching the query, score them, return top N."""
    candidates: dict[int, dict] = {}

    def _collect(domain: list):
        rows = client.call(
            model,
            "search_read",
            [domain],
            {"fields": ["id", "name"], "limit": 25},
        )
        for row in rows:
            if row["id"] in candidates:
                continue
            candidates[row["id"]] = {"id": row["id"], "name": row["name"] or ""}

    # Full-query ilike first (best signal when it matches)
    _collect([["name", "ilike", query]])

    # Per-token ilike to catch partial matches
    for token in _tokenize(query):
        _collect([["name", "ilike", token]])

    scored = [
        {**c, "similarity": round(_similarity(query, c["name"]), 4)}
        for c in candidates.values()
        if c["name"]
    ]
    scored.sort(key=lambda r: r["similarity"], reverse=True)
    return scored[:limit]


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("model", help="Odoo model name, e.g. res.partner or res.country")
    ap.add_argument("query", help="The name/string to fuzzy-match against")
    ap.add_argument("--limit", type=int, default=10, help="Max candidates to return (default 10)")
    ap.add_argument(
        "--environment",
        default="staging",
        help="Credentials key in odoo-credentials.json (default: staging)",
    )
    args = ap.parse_args()

    creds = load_credentials(environment=args.environment)
    client = OdooClient.from_credentials(creds)

    results = search(client, args.model, args.query, args.limit)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
