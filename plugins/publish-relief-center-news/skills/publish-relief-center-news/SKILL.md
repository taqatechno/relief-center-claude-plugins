---
name: publish-relief-center-news
description: Use when the user wants to publish news articles from a Relief Center bilingual news .docx file (the ones under examples/content/news/) into the Odoo Latest News blog. Also triggers on slash command invocations of /publish-relief-center-news, on requests to sync the news docx to the CMS, on "publish the unpublished articles", and on any ask to turn white-filled cells in the news docx into live blog posts. Prefer this skill for Relief Center news publishing even if the user doesn't name it — it's the only path in this project that handles the bilingual EN/AR title + body mapping and the docx status recolor together.
---

# publish-relief-center-news

## Overview

Publish the unpublished articles from a Relief Center news `.docx` into the Odoo "Latest News" blog, then mark them published in the docx by recoloring their cells. One invocation handles every unpublished article in the file.

The skill runs as a **multi-agent orchestration** — the main session is the orchestrator; subagents handle docx inspection, per-article HTML formatting, and fuzzy resolution of author + countries against Odoo. This keeps each agent's context minimal and lets per-article work happen in parallel.

All Odoo access goes through XML-RPC via this skill's own scripts (`scripts/odoo_client.py`, `scripts/odoo_search.py`, `scripts/publish_blog_post.py`). The skill does **not** use the `odoo-mcp-nextjs` MCP — its `createRecords` is broken, and its `smartSearch` silently drops the language context needed for Arabic title translations. Stick to the XML-RPC scripts.

**Cross-platform support:** The skill includes OS detection (`orchestrate_publish.py` helper script) for safe temp file handling on Windows, Linux, and macOS. This avoids shell quoting issues that break on apostrophes in article body text.

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

### Step 0 — Credential check

Before dispatching any agents or touching the docx, verify Odoo credentials are configured and accepted by the server:

```bash
python <SKILL_DIR>/scripts/check_credentials.py
```

The script prints a single line of JSON and exits 0 on success, 1 on failure. Handle the three cases below.

#### Case A: `{"ok": true, "user": "...", "uid": N}`

Credentials work. Proceed to Step 1 silently — no need to mention the check to the user.

#### Case B: `{"ok": false, "error": "missing", ...}` — collect interactively

The plugin has no credentials configured. Collect them from the user **one at a time in chat**, then save them for this and future runs. Do not dump the whole list in a single message — the user should answer each question before the next is asked.

1. Tell the user: *"I need to set up Odoo credentials for this plugin — I'll ask for four values, save them locally, and then publish."*
2. Ask: *"**1 of 4 — What's your Odoo URL?** (e.g. `https://your-instance.odoo.com/`)"* — wait for the user's reply.
3. Ask: *"**2 of 4 — What's your Odoo database name?**"* — wait for reply.
4. Ask: *"**3 of 4 — What's your numeric Odoo user ID?** (the integer `uid` from your Odoo profile, e.g. `67`)"* — wait for reply.
5. Ask: *"**4 of 4 — What's your Odoo password?**"* — wait for reply.
6. Once all four are collected, save them. Because the password may contain shell metacharacters, **do not use inline `echo '...' | python save_credentials.py`** — instead:
    a. Use the `Write` tool to create a temp file `~/.claude-cred-tmp.json` with this exact content (fill in the four values verbatim):
        ```json
        {"url": "<URL>", "db": "<DB>", "uid": "<UID>", "password": "<PASSWORD>"}
        ```
    b. Pipe that file into the saver and remove it:
        ```bash
        python <SKILL_DIR>/scripts/save_credentials.py < ~/.claude-cred-tmp.json && rm ~/.claude-cred-tmp.json
        ```
    The saver writes the values into `~/.claude/odoo-credentials.json` in the nested shape `odoo_client` expects. The temp file is removed immediately so the password doesn't linger on disk in a second location.
7. Re-run `python <SKILL_DIR>/scripts/check_credentials.py`. If the second check returns `{"ok": true}`, tell the user: *"Credentials saved. Authenticated as `<user>`. Proceeding to publish."* — and go to Step 1. If it returns `{"ok": false}` again, show the error message and ask the user which field to re-enter (repeat the flow for only the affected field, then call `save_credentials.py` again).

**Do not echo the password back to the user in your response text.** Acknowledge that it was collected and saved — do not include the value in confirmations, summaries, or any other output.

#### Case C: `{"ok": false, "error": "auth_failed", ...}` — server rejected the login

Credentials exist but Odoo rejected them. Tell the user, include the `message` from the JSON, and offer to re-collect:

> Odoo rejected the login. Server message: `<message>`. The credentials on file may be out of date — if you want, I can walk through the four prompts again to replace them.

If the user agrees, run the interactive collection flow from Case B. The saver will overwrite the stale values.

### Step 1 — Dispatch Agent A (docx inspector)

Use the `Agent` tool with `subagent_type: general-purpose`. Its job: find unpublished articles in the docx. Each article is its own **table** with six labeled field rows (Title, Author, Date, Country, Body, Status). Publication state is encoded in the Status row text: "Unpublished" means the article needs publishing. Pass this prompt verbatim (substitute `<docx-path>`):

> Your task: identify unpublished articles in a Relief Center news .docx file.
>
> 1. Run: `python <SKILL_DIR>/scripts/inspect_docx.py "<docx-path>"`
> 2. Parse the JSON output — a list of article dicts, each with pre-extracted fields: `article_index`, `title_en`, `title_ar`, `author_en`, `date_en`, `country_en`, `body_en`, `body_ar`, `status_en`, `status_en_cell_index`, `status_ar_cell_index`, `article_cell_indices` (list of every `<w:tc>` index inside the article's table, in document order — used by the recolor step to tint the whole article).
> 3. Filter to entries where `status_en` equals "Unpublished" (the article has not yet been published).
> 4. Return the filtered list **as-is** — don't strip or rename any fields, downstream steps need them. If no articles match, return `[]`.
>
> Do NOT publish anything; your only job is discovery.

Parse the returned list. If it's empty, tell the user "No unpublished articles in `<docx-path>`." and stop — don't dispatch any more agents.

### Step 2 — Dispatch Agent B (field formatter) per article, **in parallel**

With structured output from Agent A, Agent B's job is much lighter than before: fields are already extracted, so Agent B only formats body HTML, parses the date string, and resolves author + country against Odoo. Launch one `Agent` tool call per unpublished article **in the same message** so they run concurrently. Each gets `subagent_type: general-purpose`. For each article, pass this prompt (substitute the per-article values from Agent A's output):

> Your task: format one pre-extracted Relief Center news article for Odoo publishing. Fields are already structured — you just need to build bilingual body HTML, parse the date, and resolve author + country against Odoo.
>
> Pre-extracted fields:
> - `article_index`: `<article_index>`
> - `title_en`: `<title_en>`
> - `title_ar`: `<title_ar>`
> - `author_en`: `<author_en>`  (e.g. "Dr. Ola Alkahlout")
> - `date_en`: `<date_en>`  (e.g. "15 April 2026")
> - `country_en`: `<country_en>`  (e.g. "International" or "Yemen")
> - `body_en`: `<body_en>`  (plain text, paragraphs separated by `\n`)
> - `body_ar`: `<body_ar>`  (plain text, paragraphs separated by `\n`)
>
> **Before generating any HTML, read `<SKILL_DIR>/references/body_html_template.md` in full.** That file is the source of truth for body structure (byline format, paragraph shape, lists, alignment, emphasis, special characters). Match it exactly.
>
> Produce these derived fields:
> - `body_en_html`: wrap each body_en paragraph in `<p style="text-align: justify;">…</p>`. The first `<p>` also carries `data-oe-version="2.0"`, and its content begins with `<strong>{author_en} |&nbsp;</strong><br>` followed immediately by the first paragraph's text (the byline renders on its own line, then the body). Example:
>   `<p style="text-align: justify;" data-oe-version="2.0"><strong>Dr. Ola Alkahlout |&nbsp;</strong><br>{first body paragraph}</p><p style="text-align: justify;">{second body paragraph}</p>…`
> - `body_ar_html`: same pattern using `author_ar` and `body_ar`. Do NOT add `dir="rtl"` — Odoo's theme handles direction.
> - `post_date_iso`: the article's date in `"YYYY-MM-DD HH:MM:SS"` format. Parse `date_en` (e.g. "15 April 2026" → "2026-04-15 00:00:00"). Time can be 00:00:00. If `date_en` is unparseable, fall back to `date_ar` and infer from Arabic month names.
>
> Then dispatch one subagent to resolve both author and country against Odoo (subagent_type: general-purpose):
>
> **Odoo Resolver** (resolves author + country together):
> > Given author_en = `<author_en>` and country_en = `<country_en>`, resolve both to Odoo record IDs.
> >
> > **Author resolution:**
> > 1. Run: `python <SKILL_DIR>/scripts/odoo_search.py res.partner "<author_en>"`
> > 2. Parse JSON. If the top candidate's `similarity >= 0.60`, use its id and name.
> > 3. Otherwise use author_id: 79 (Shafiq Belaroussi, fallback).
> >
> > **Country resolution:**
> > 1. Normalize: if the trimmed string (case-insensitive) is `International`, `Global`, `Worldwide`, `دولي`, or `عالمي`, set country_ids to `[]` and stop.
> > 2. Otherwise split on commas and `/`. For each token:
> >    - Run: `python <SKILL_DIR>/scripts/odoo_search.py res.country "<token>"`
> >    - If the top candidate has `similarity >= 0.60`, include its id.
> > 3. Return country_ids as a list of matched ids (empty for global).
> >
> > Return both results in one dict and merge into the final article dict:
>
> ```json
> {
>   "article_index": <int>,
>   "title_en": "...",
>   "title_ar": "...",
>   "body_en_html": "...",
>   "body_ar_html": "...",
>   "post_date_iso": "YYYY-MM-DD HH:MM:SS",
>   "author_id": <int>,
>   "country_ids": [<int>, ...]
> }
> ```
> Do not invoke any publish scripts yourself — the orchestrator will.

### Step 3 — Publish each article via XML-RPC

For each Agent B result, you hold the article's `article_index`, `status_en_cell_index`, `status_ar_cell_index`, and `article_cell_indices` from Agent A's output in Step 1. Strip `article_index` from the Agent B dict (publish_blog_post.py doesn't expect it), then publish via file redirection (never via `echo` pipe, which breaks on apostrophes in body text).

**CRITICAL: Detect OS and use appropriate temp directory:**

#### On Windows (or when running bash/WSL on Windows):
```python
import tempfile
import json
import subprocess
import os

# Get OS-appropriate temp directory
temp_dir = tempfile.gettempdir()  # e.g., C:\Users\...\AppData\Local\Temp on Windows
temp_file = os.path.join(temp_dir, f'rc_article_{article_index}.json')

# Write JSON to temp file using Python (handles encoding properly)
with open(temp_file, 'w', encoding='utf-8') as f:
    json.dump(field_dict, f)

# Pipe from file (works on all platforms)
with open(temp_file, 'r', encoding='utf-8') as f:
    result = subprocess.run(
        [sys.executable, '<SKILL_DIR>/scripts/publish_blog_post.py'],
        stdin=f,
        capture_output=True,
        text=True
    )

# Clean up
os.remove(temp_file)
publish_result = json.loads(result.stdout)
```

#### On Linux/macOS (or in a pure POSIX environment):
```bash
# Still use temp file approach — it's safer and more portable
python -c "import json; json.dump({...}, open('/tmp/rc_article_<idx>.json', 'w'))" && \
python <SKILL_DIR>/scripts/publish_blog_post.py < /tmp/rc_article_<idx>.json && \
rm /tmp/rc_article_<idx>.json
```

**Why the temp file approach:**
- Shell `echo '...' | python` breaks on apostrophes in article body text (e.g., "donors' awareness", "system's ability")
- `tempfile.gettempdir()` returns the OS-appropriate temp directory (Windows or POSIX)
- File redirection via `<` works identically on Windows bash (Git Bash, WSL) and POSIX
- `publish_blog_post.py` already reads `sys.stdin.buffer` as UTF-8 — file redirection works perfectly

Parse the JSON on stdout:
- `status: "created"` or `status: "partial"` (AR translation warning) → success; queue every index in `article_cell_indices` for recoloring, and queue `status_en_cell_index` for the `Unpublished → Published` text rewrite
- `status: "existing"` → the post already exists under this title; still queue `article_cell_indices` for recolor and `status_en_cell_index` for the text rewrite (the docx should reflect reality even for duplicates)
- Non-zero exit → log the error JSON (from stderr), do NOT queue that article's cells, continue with the rest

### Step 4 — Recolor the article table and switch its Status to "Published"

After all publishes complete, call `recolor_docx_cells.py` once with every queued cell index. The v6 convention for "article published" is that the **entire article table** is tinted purple — not just the Status row — so the whole article reads as done at a glance. In the same call, use `--set-text` to flip the Status cell's text from `Unpublished` to `Published`:

```bash
python <SKILL_DIR>/scripts/recolor_docx_cells.py "<docx-path>" \
    --set-text <status_en_idx_1>=Published \
    --set-text <status_en_idx_2>=Published \
    <article_cell_idx_1> <article_cell_idx_2> <article_cell_idx_3> ...
```

Each positional cell index gets its white fill flipped to `#B4A7D6` (light purple). Each `--set-text <idx>=<text>` entry rewrites the first `<w:t>` inside that cell (any sibling `<w:t>` runs in the same cell are blanked so the text reads cleanly). If the docx is open in Word, the script will fail to overwrite — warn the user to close Word and rerun; the duplicate-title pre-flight in `publish_blog_post.py` keeps reruns safe.

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
| Agent A returns `[]` (no articles with unpublished Status) | Orchestrator reports and exits. No other agents spawned. |
| `publish_blog_post.py` returns `status: "existing"` for a title already in Latest News | Skill still queues that article's Status cells for recoloring — the docx should match reality. |
| AR title translation write fails (EN post created OK) | `publish_blog_post.py` returns `status: "partial"` with a `warning` string. Skill treats it as published and continues. User can fix the AR title in Odoo UI. |
| Agent C (Odoo resolver) finds no author match ≥60% | Returns `author_id: 79` (current user's partner); proceeds normally. |
| Agent C (Odoo resolver) finds no confident country matches | Returns `country_ids: []`; matches the existing convention on most posts. |
| `recolor_docx_cells.py` fails (e.g., file locked by Word) | Posts exist in Odoo but docx unchanged. Warn user to close Word and rerun — the duplicate-title pre-flight keeps a rerun idempotent. |
| Step 3 publish fails: shell quoting error (exit 2, "unexpected EOF while looking for matching `'`") | **Use `orchestrate_publish.py` helper script** (handles OS detection + temp file management automatically) or manually write JSON to `tempfile.gettempdir()/rc_article_<idx>.json`, then pipe: `python publish_blog_post.py < <temp_file>`. Never use `echo '...' \| python ...` — shell single-quotes break on apostrophes in body text. See Step 3 for details. |
| Credentials not found | Scripts raise `CredentialsNotFound`. Tell the user to set the plugin's userConfig (ODOO_URL, ODOO_DB, ODOO_UID, ODOO_PASSWORD) via `/plugin config`, or export those env vars in their shell. |

## Examples

### Example 1 — Happy path

User: `/publish-relief-center-news "examples/content/news/May 2026.docx"`

Skill:
1. Agent A runs `inspect_docx.py`, returns 3 articles with status_en = "Unpublished" and all fields pre-extracted (title/author/date/country/body for EN & AR, plus Status cell indices)
2. Dispatches 3 Agent B subagents in parallel; each formats body HTML, parses date, and dispatches one Odoo Resolver (Agent C) for author/country resolution
3. All 3 return complete field dicts
4. Orchestrator publishes each via `publish_blog_post.py` → ids 130, 131, 132 created
5. Orchestrator calls `recolor_docx_cells.py "May 2026.docx" --set-text 21=Published --set-text 44=Published --set-text 67=Published <every index in each article's article_cell_indices>` → all three article tables turn purple end-to-end and their Status rows read "Published"
6. Reports: "3 articles published; 3 article tables recolored purple and marked Published" with URLs

### Example 2 — No unpublished articles

User: `/publish-relief-center-news "examples/content/news/April 2026.docx"` (every article's Status row is already green or purple)

Skill:
1. Agent A returns `[]` (no articles where status_en = "Unpublished")
2. Skill reports: "No unpublished articles in April 2026.docx — every Status row is already green (manual) or purple (AI)."
3. No subagents spawned. No Odoo calls made.

### Example 3 — Partial failure

User: `/publish-relief-center-news ...docx` with 2 unpublished articles; one article's Date field in the docx is an unparseable placeholder.

Skill:
1. Agent A finds 2 unpublished articles
2. One Agent B returns a valid field dict; the other can't parse its `date_en` and returns a dict missing `post_date_iso`
3. `publish_blog_post.py` succeeds on article 1, fails on article 2 with "Missing required fields: ['post_date_iso']"
4. Orchestrator recolors article 1's entire table to purple and flips its Status cell to "Published"; leaves article 2's table untouched
5. Reports: "1 published, 1 failed (couldn't parse the Date field — check the docx for that article)"
