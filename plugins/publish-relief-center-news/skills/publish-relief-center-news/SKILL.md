---
name: publish-relief-center-news
description: Use when the user wants to publish news articles from a Relief Center bilingual news .docx file (the ones under examples/content/news/) into the Odoo Latest News blog. Also triggers on slash command invocations of /publish-relief-center-news, on requests to sync the news docx to the CMS, on "publish the unpublished articles", and on any ask to turn white-filled cells in the news docx into live blog posts. Prefer this skill for Relief Center news publishing even if the user doesn't name it — it's the only path in this project that handles the bilingual EN/AR title + body mapping and the docx status recolor together.
---

# publish-relief-center-news

## Overview

Publish the unpublished articles from a Relief Center news `.docx` into the Odoo "Latest News" blog, then mark them published in the docx by recoloring their cells. One invocation handles every unpublished article in the file.

The skill runs as a **multi-agent orchestration** — the main session is the orchestrator; subagents handle docx inspection, per-article field extraction, and fuzzy resolution of author + countries. This keeps each agent's context minimal and lets per-article work happen in parallel.

All Odoo access goes through XML-RPC via this skill's own scripts (`scripts/odoo_client.py`, `scripts/odoo_search.py`, `scripts/publish_blog_post.py`). The skill does **not** use the `odoo-mcp-nextjs` MCP — its `createRecords` is broken, and its `smartSearch` silently drops the language context needed for Arabic title translations. Stick to the XML-RPC scripts.

## When to use

- User runs `/publish-relief-center-news <docx-path>`
- User asks to publish / push / sync unpublished articles from a Relief Center news docx into Odoo
- User asks "why hasn't this article been published yet?" about a docx with white cells — run the skill to publish the white ones

## When NOT to use

- User wants to publish to the **Relief Coordination** blog (id 17) or any blog other than Latest News (id 14). This skill is locked to Latest News.
- User wants to modify an existing blog post's content. This skill only creates new posts.
- User wants to publish to **production** Odoo. The plugin's userConfig is set per install; point it at a staging instance only. Production is out of scope for this plugin version.

## Invocation

```
/publish-relief-center-news <path-to-docx>
```

Example:
```
/publish-relief-center-news "examples/content/news/April 2026.docx"
```

## Credentials

`scripts/odoo_client.py` looks up Odoo connection info in this order, first match wins:

1. **Individual environment variables**: `ODOO_URL`, `ODOO_DB`, `ODOO_UID`, `ODOO_PASSWORD`. These map 1:1 to the plugin's userConfig fields — when the user configured the plugin at install time, the values live there and are surfaced to scripts as env vars. Users can also export them in their shell for ad-hoc overrides. This is the primary and recommended path.
2. **`odoo-credentials.json` file**: auto-discovered by `ODOO_CREDENTIALS_PATH` env var override, or by walking up from `cwd` to the first directory containing a file named `odoo-credentials.json`. Used as a dev-time fallback. The file's `staging` key must contain an object with `url`, `db`, `uid`, `credential`.

If neither resolves, scripts raise `CredentialsNotFound` with a message listing what was checked. Prefer userConfig for production installs; the file path is a convenience for the skill's original development workflow.

## Orchestration flow

The skill ships with its scripts under `scripts/` and reference docs under `references/`, relative to the skill's base directory. Claude Code shows the absolute base directory at the top of this SKILL.md when the skill loads (look for **"Base directory for this skill: …"**). In every command below, replace `<SKILL_DIR>` with that absolute path.

Work from the user's project directory (where the docx lives) so the orchestrator's cwd matches the docx path argument. Credentials are supplied via plugin userConfig — see the README and the `Credentials` section below.

### Step 1 — Dispatch Agent A (docx inspector)

Use the `Agent` tool with `subagent_type: general-purpose`. Its job: find the unpublished article rows. Each article in the docx is **one row with two cells** (EN on the left, AR on the right). Pass this prompt verbatim (substitute `<docx-path>`):

> Your task: identify unpublished articles in a Relief Center news .docx file.
>
> 1. Run: `python <SKILL_DIR>/scripts/inspect_docx.py "<docx-path>"`
> 2. Parse the JSON output (list of row records, each with `row_index`, `en_cell_index`, `ar_cell_index`, `fill`, `en_text`, `ar_text`, `is_article`).
> 3. Filter to entries where `is_article == true` AND the cell is unpublished. A cell counts as unpublished if `fill` is either `null` (no fill set, which Word renders as white) OR case-insensitively `"FFFFFF"` (explicit white). Any other value (green shades, purple, etc.) means already published.
> 4. Return a JSON list: `[{"row_index": <int>, "en_cell_index": <int>, "ar_cell_index": <int>, "en_text": <str>, "ar_text": <str>}, ...]`. Preserve `en_text` and `ar_text` verbatim — Agent B needs them. Do NOT publish anything; your only job is discovery. If no rows match, return `[]`.

Parse the returned list. If it's empty, tell the user "No unpublished articles in `<docx-path>`." and stop — don't dispatch any more agents.

### Step 2 — Dispatch Agent B (field extractor) per article, **in parallel**

Launch one `Agent` tool call per unpublished article **in the same message** so they run concurrently. Each gets `subagent_type: general-purpose`. For each article, pass this prompt (substitute `<row_index>`, `<en_text>`, `<ar_text>`):

> Your task: extract structured fields from one Relief Center news article. The article lives in a single table row of a bilingual docx; you receive the English and Arabic halves as separate strings.
>
> Article row_index: `<row_index>`
>
> English cell text:
> ```
> <en_text>
> ```
>
> Arabic cell text:
> ```
> <ar_text>
> ```
>
> **Before generating any HTML, read `<SKILL_DIR>/references/body_html_template.md` in full.** That file is the source of truth for body structure (byline format, paragraph shape, lists, alignment, emphasis, special characters). Do not improvise — match the template exactly.
>
> Extract these fields:
> - `title_en`: English title (from the `Title:` line in the English cell)
> - `title_ar`: Arabic title (from the `العنوان:` line in the Arabic cell)
> - `body_en_html`: the English body converted to HTML following the template. The body starts after `News Text:` or `News details:`. Critical rule from the template: the byline (`{Author} |`) goes inside `<strong>…</strong>` with `&nbsp;` after the `|` and a `<br>` immediately after the closing `</strong>` so the first body sentence renders on a new line. The first `<p>` also carries `data-oe-version="2.0"`.
> - `body_ar_html`: same transformation for the Arabic body (starts after `نص الخبر:`). Same byline + `<br>` pattern. No `dir="rtl"`.
> - `post_date_iso`: the article's date in `"YYYY-MM-DD HH:MM:SS"` format. Source: the `Date:` / `التاريخ:` line (e.g., "5 April 2026" → "2026-04-05 00:00:00"). Try the English cell first; fall back to the Arabic cell.
> - `author_name_string`: the English byline text before the `|` in the first body paragraph of the English cell (e.g., "Dr. Ola Al Kahlout"). Trim whitespace.
> - `country_string`: the `Country / Countries:` value from the English cell, verbatim (e.g., "International", "Gaza, Lebanon", "Yemen").
>
> Then dispatch two subagents **in parallel** (single message, two Agent tool calls):
>
> **Author resolver** (subagent_type: general-purpose):
> > Given the author name string `<author_name_string>`, resolve it to an Odoo `res.partner` id.
> >
> > 1. Run: `python <SKILL_DIR>/scripts/odoo_search.py res.partner "<author_name_string>"`
> > 2. Parse JSON. If the top candidate's `similarity >= 0.60`, return `{"author_id": <top.id>, "matched_name": <top.name>, "confidence": <top.similarity>}`.
> > 3. Otherwise return `{"author_id": 79, "matched_name": "Shafiq Belaroussi (fallback)", "confidence": 0}`. Partner 79 is the current authenticated user's partner — the safe default.
>
> **Country resolver** (subagent_type: general-purpose):
> > Given the country string `<country_string>`, resolve it to a list of Odoo `res.country` ids.
> >
> > 1. Normalize and check for non-specific values: if the trimmed string (case-insensitive) is one of `International`, `Global`, `Worldwide`, `دولي`, `عالمي`, return `{"country_ids": []}` and stop.
> > 2. Otherwise split on commas and `/`. For each token, run: `python <SKILL_DIR>/scripts/odoo_search.py res.country "<token>"`
> > 3. For each search, if the top candidate has `similarity >= 0.60`, include its id. Drop tokens with no confident match.
> > 4. Return `{"country_ids": [id1, id2, ...], "skipped": [unmatched_tokens]}`.
>
> Merge the two resolver results into the final JSON field dict:
> ```json
> {
>   "row_index": <int>,
>   "title_en": "...",
>   "title_ar": "...",
>   "body_en_html": "...",
>   "body_ar_html": "...",
>   "post_date_iso": "YYYY-MM-DD HH:MM:SS",
>   "author_id": <int>,
>   "country_ids": [<int>, ...]
> }
> ```
> Return this dict. Do not invoke any publish scripts yourself — the orchestrator will.

### Step 3 — Publish each article via XML-RPC

For each Agent B result, you already hold that article's `row_index`, `en_cell_index`, and `ar_cell_index` from Step 1. Strip `row_index` from the field dict before sending (publish_blog_post.py doesn't expect it), and pipe the rest to the publisher:

```bash
echo '<field_dict_json_without_row_index>' | python <SKILL_DIR>/scripts/publish_blog_post.py
```

Parse the JSON on stdout:
- `status: "created"` or `status: "partial"` (AR translation warning) → success; queue **both** `en_cell_index` and `ar_cell_index` for recoloring
- `status: "existing"` → the post already exists under this title; still queue both cell indices for recoloring (the docx should reflect reality even for duplicates)
- Non-zero exit → log the error JSON (from stderr), do NOT queue those cells for recolor, continue with the rest

### Step 4 — Recolor successfully-published cells to purple

After all publishes complete, call `recolor_docx_cells.py` once with every queued cell index (both EN and AR cells of each published article):

```bash
python <SKILL_DIR>/scripts/recolor_docx_cells.py "<docx-path>" <idx1> <idx2> <idx3> <idx4> ...
```

This flips each target cell's white fill to `#B4A7D6` (light purple) in place. If the docx is open in Word, the script will fail to overwrite — warn the user to close Word and rerun; the duplicate-title pre-flight in `publish_blog_post.py` keeps reruns safe.

### Step 5 — Report summary to the user

Print a concise summary:

- `N articles published, K failed, M recolored.`
- Bulleted list of new posts: `- <title_en>: <url>`
- Any failures, each with a short error reason
- Any resolver fallbacks (e.g., "Author fell back to current user for article `<cell_index>`")

## Field mapping reference

Read `references/field_mapping.md` for:
- The full list of `blog.post` fields set (vs. skipped)
- The `blog_id=14` (Latest News) and related constants
- The EN/AR title translation mechanism details
- Body-parsing hints (byline, date, country variations)
- A reference existing post (id 110) to mirror style

## Error handling

| Condition | What happens |
|---|---|
| Agent A returns `[]` (no white cells) | Orchestrator reports and exits. No other agents spawned. |
| `publish_blog_post.py` returns `status: "existing"` for a title already in Latest News | Skill still includes that cell in the recolor list — the docx should match reality. |
| AR title translation write fails (EN post created OK) | `publish_blog_post.py` returns `status: "partial"` with a `warning` string. Skill treats it as published and continues. User can fix the AR title in Odoo UI. |
| Agent C (author resolver) finds no match ≥60% | Returns `author_id: 79` (current user's partner); orchestrator proceeds normally. |
| Agent D (country resolver) finds no confident matches | Returns `country_ids: []`; matches the existing convention on most posts. |
| `recolor_docx_cells.py` fails (e.g., file locked by Word) | Posts exist in Odoo but docx unchanged. Warn user to close Word and rerun — the duplicate-title pre-flight keeps a rerun idempotent. |
| Credentials not found | Scripts raise `CredentialsNotFound`. Tell the user to set the plugin's userConfig (ODOO_URL, ODOO_DB, ODOO_UID, ODOO_PASSWORD) via `/plugin config`, or export those env vars in their shell. |

## Examples

### Example 1 — Happy path

User: `/publish-relief-center-news "examples/content/news/May 2026.docx"`

Skill:
1. Agent A finds 3 unpublished (white-filled) article rows → `[{row_index: 5, en_cell_index: 11, ar_cell_index: 12, …}, …]`
2. Dispatches 3 Agent B subagents in parallel; each dispatches its own C + D
3. All 3 return complete field dicts
4. Orchestrator publishes each via `publish_blog_post.py` → ids 130, 131, 132 created
5. Orchestrator calls `recolor_docx_cells.py "May 2026.docx" 11 12 15 16 19 20` → all 6 cells (EN + AR of each article) turned purple
6. Reports: "3 articles published, 6 cells recolored purple" with URLs

### Example 2 — No unpublished articles

User: `/publish-relief-center-news "examples/content/news/April 2026.docx"` (all cells already green or purple)

Skill:
1. Agent A returns `[]`
2. Skill reports: "No unpublished articles in April 2026.docx — all cells are already green (manual) or purple (AI)."
3. No subagents spawned. No Odoo calls made.

### Example 3 — Partial failure

User: `/publish-relief-center-news ...docx` with 2 unpublished articles; one article's date parsing fails.

Skill:
1. Agent A finds 2 cells
2. One Agent B returns a valid field dict; the other returns an incomplete dict (missing `post_date_iso`)
3. `publish_blog_post.py` succeeds on article 1, fails on article 2 with "Missing required fields: ['post_date_iso']"
4. Orchestrator recolors article 1's cell, leaves article 2's cell white
5. Reports: "1 published, 1 failed (missing post_date_iso — check the docx Date: line for that article)"
