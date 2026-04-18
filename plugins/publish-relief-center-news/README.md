# publish-relief-center-news

Claude Code plugin that publishes unpublished bilingual (English + Arabic) news articles from a Relief Center news `.docx` into the Odoo **Latest News** blog (`blog_id = 14`), then recolors the published cells purple so the docx stays in sync with reality.

## What it does

Given a monthly news docx where each article sits in a two-cell table row (left: English, right: Arabic) and the row's fill color encodes publication state (white = unpublished, green = manually published, purple = published by this plugin), the plugin:

1. Inspects the docx and lists unpublished (white-filled) article rows.
2. Extracts per-article fields: title EN/AR, body EN/AR, date, author name, country string.
3. Fuzzy-resolves the author name to an Odoo `res.partner` id, and the country string to `res.country` ids.
4. Creates a `blog.post` under Latest News with the English title + HTML body, then writes `website_content_ar` (Arabic body) and the Arabic `name` translation in follow-up calls.
5. Recolors the published cells from white to `#B4A7D6` (light purple) in place so next run skips them.

All Odoo I/O goes through the JSON-RPC endpoint (`/jsonrpc`). An XML-RPC path was tried first; Odoo's server-side XML parser intermittently — and sometimes session-persistently — fails on bilingual writes with a `reference to invalid character number` error. JSON-RPC has no XML parser in the request path, which eliminates that failure class.

## Install

See the [repo-level README](../../README.md#install-the-marketplace) for how to register this marketplace and enable plugins from it.

Once the marketplace is registered and `publish-relief-center-news@relief-center-claude-plugins` is enabled, configure it:

```
/plugin config publish-relief-center-news
```

## userConfig fields

| Field | What | Example |
|---|---|---|
| `ODOO_URL` | Odoo instance URL | `https://relief-center-staging-30897768.dev.odoo.com/` |
| `ODOO_DB` | Database name | `relief-center-staging-30897768` |
| `ODOO_UID` | Numeric user ID | `67` |
| `ODOO_PASSWORD` | Password (sensitive; goes to the OS secure store, not `settings.json`) | `…` |

### Overriding at runtime

`scripts/odoo_client.py` reads these values as environment variables first. Export them in your shell, or set them in `.claude/settings.json`'s `env` block, to override the userConfig for a single session:

```json
{ "env": { "ODOO_URL": "...", "ODOO_DB": "...", "ODOO_UID": "12", "ODOO_PASSWORD": "..." } }
```

### Dev-only file fallback

If none of the env vars are set, the scripts walk up from `cwd` looking for a file named `odoo-credentials.json` (or whatever `ODOO_CREDENTIALS_PATH` points to). The file's `staging` key (or whatever `ODOO_ENVIRONMENT` names) must contain `{url, db, uid, credential}`. This is a convenience for development only; prefer userConfig for any real install.

## Use

```
/publish-relief-center-news "path/to/April 2026.docx"
```

Claude Code will dispatch subagents to inspect the docx, extract fields per unpublished article, fuzzy-resolve author + countries, publish to Odoo, and recolor the docx. A final summary lists new post IDs + URLs, any skipped (already-existing) titles, and any partial publishes.

## Plugin layout

```
publish-relief-center-news/
├── .claude-plugin/
│   └── plugin.json                  # manifest + userConfig declaration
└── skills/
    └── publish-relief-center-news/
        ├── SKILL.md                 # orchestration instructions for the main agent
        ├── references/
        │   ├── field_mapping.md     # blog.post field reference
        │   └── body_html_template.md # bilingual body HTML conventions
        └── scripts/
            ├── odoo_client.py       # JSON-RPC client, env-var + file credentials
            ├── odoo_search.py       # fuzzy model-name search CLI
            ├── inspect_docx.py      # list article rows with fill colors
            ├── recolor_docx_cells.py # white → purple, byte-surgical
            └── publish_blog_post.py  # create + AR writes + teaser refresh
```

## License

See [`../../LICENSE`](../../LICENSE) at the repo root.
