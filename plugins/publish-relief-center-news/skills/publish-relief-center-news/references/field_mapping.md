# blog.post field mapping

Reference for the orchestration agent and Agent B (field extractor). Kept out of `SKILL.md` so that file stays scannable.

## Target blog: "Latest News"

- Model: `blog.post`
- `blog_id` = **14** (the `blog.blog` record whose name is "Latest News")

## Fields the skill sets on create

| `blog.post` field | Source | Notes |
|---|---|---|
| `name` | docx English title | Translatable; the Arabic title is written in a follow-up `write` call under `context={"lang": "ar_001"}`. |
| `content` | docx English body, HTML | Wrap each paragraph in `<p style="text-align: justify;">…</p>`. The byline (`Author Name |`) goes inside a `<strong>` at the start of the first paragraph, mirroring the house style on existing posts. |
| `website_content_ar` | docx Arabic body, HTML | Custom non-translatable field. Same HTML structure as `content`, with the Arabic title usually appearing as part of the content (no separate AR title field — the title goes on `name`). |
| `author_id` | Agent C resolver | Int. Falls back to partner id **79** (Shafiq Belaroussi, `res.users` uid 67's partner) when fuzzy match < 60%. |
| `country_ids` | Agent D resolver | `[(6, 0, [id1, id2, ...])]` many2many replace. Empty list (`[]`) for International / Global / عالمي / دولي. |
| `post_date` | docx date (e.g., "5 April 2026") | ISO format: `"YYYY-MM-DD HH:MM:SS"`. Time can be 00:00:00. |
| `published_date` | same as `post_date` | Existing posts set both equal. |
| `blog_id` | constant | **14** |
| `is_published` | constant | `true` |
| `website_published` | constant | `true` |
| `is_homepage` | constant | `true` (drives the homepage Latest News section) |
| `is_relief_coordination` | constant | `false` (this is Latest News, not Relief Coordination) |

## Fields the skill does NOT set

Leave unset / default, per locked decisions:

- `subtitle`, `seo_name`, `website_meta_title`, `website_meta_description`, `website_meta_keywords`, `website_meta_og_img` — SEO handled manually if at all.
- `teaser`, `teaser_manual` — `teaser` auto-derives from `content`; `teaser_manual` is a manual override the user doesn't use in this workflow. **However** see the "teaser refresh workaround" note below — the skill does a no-op `write` of `content` after create specifically to re-trigger the teaser compute cleanly.
- `cover_properties`, `copyright` — cover image and photo credit are set manually in the Odoo UI after publish; each article has a different image + credit that isn't in the docx.
- `tag_ids`, `emergency_id`, `website_id` — unused on existing Latest News posts (id 110, 112, 118, 121 all leave these empty/default).
- `author_avatar` — empty on existing posts.
- `active` — defaults to `true`; no need to set explicitly.

## Teaser refresh workaround

Odoo's `teaser` compute runs during `create` with an HTML-to-plaintext pass that renders inline `<strong>…</strong>` as `*…*` (markdown-style asterisks). A freshly-created post shows a teaser like `*Dr. Ola Alkahlout |*` even though the byline is wrapped in `<strong>`, not surrounded by literal asterisks.

On any **subsequent** `write` of `content`, Odoo re-runs the compute with a cleaner pass that strips the tags without substituting asterisks, producing `Dr. Ola Alkahlout |` — matching post 121 (which looked clean because a human edited it after creation).

To match existing posts, `publish_blog_post.py` does a no-op `write` of `content` (to the same HTML value) immediately after the AR title translation write. This triggers the clean recompute without changing any data. The extra XML-RPC round trip is cheap and invisible to the user.

Verify by reading `teaser` after publish — it should NOT contain asterisks.

## AR title: how Odoo stores it

`name` is a **translatable** char field (`translate: true`). Odoo stores its value per language. The skill's two-step pattern:

1. `create` with `{"name": "<English title>", …}` — sets the `en_US` value.
2. `write` with `{"name": "<Arabic title>"}` and `context={"lang": "ar_001"}` — sets the `ar_001` value.

Verified working via `scripts/publish_blog_post.py` (which reuses the pattern from the project's probe script).

**Important read-back caveat (for verification):** the `odoo-mcp-nextjs` MCP's `smartSearch` does NOT forward `context.lang` — it always returns the default-language value. To read the Arabic title for verification, use the skill's own `odoo_client.py` XML-RPC helper with `{"context": {"lang": "ar_001"}}`.

## Body parsing hints for Agent B

Each article cell in the docx contains both language versions, in this typical order:

```
News No.: 1
Title: <English title line>
Country / Countries: <International | Global | country names>
News details:                   ← or "News Text:" — both appear
<Author Name> |<English body paragraph 1>
<English body paragraph 2>
…
خبر رقم: 1
العنوان: <Arabic title line>
الدولة / الدول: <دولي | عالمي | country names in Arabic>
نص الخبر:
<Arabic Author Name> |<Arabic body paragraph 1>
<Arabic body paragraph 2>
…
```

- The **byline** is the author name string, directly followed by ` |` (space + pipe) at the start of the first body paragraph. Spacing/casing varies across articles ("Al Kahlout" / "AlKahlout" / "Alkahlout") which is why author resolution is fuzzy.
- The **date** appears either as its own `Date: …` / `التاريخ: …` line OR in a preceding blue-fill separator row (`5/ابريل/2026`) — prefer the in-cell `Date:` line if present, else parse the preceding separator.
- The **country** line is labeled `Country / Countries:` (EN) or `الدولة / الدول:` / `الدولة:` (AR). Use either or both to cross-check; prefer English form for the res.country fuzzy match but fall back to Arabic if EN is absent.
- **HTML conversion**: split body on blank lines (double newline). For each paragraph, wrap as `<p style="text-align: justify;">…</p>`. For the first paragraph, wrap the byline portion (author name + ` |`) in `<strong>…</strong>` so it renders bold like existing posts (see id 110's stored HTML for the exact shape).

## Country string → country_ids special cases

These values mean "no specific country" and should produce an empty `country_ids`:

- English: `International`, `Global`, `Worldwide`
- Arabic: `دولي` (dawly = international), `عالمي` (3ālamy = global)

Any other string is tokenized on commas and forward-slashes, and each token goes through `odoo_search.py res.country <token>`. Accept the top candidate if its `similarity >= 0.60`.

## Reference: an existing Latest News post

Post id **110** (`Increasing Complexity in Aid Delivery Across Conflict Settings Reshapes Humanitarian Priorities`, 2026-04-05) is a good template to mirror:

- `name`: English title only
- `content`: paragraphs wrapped in `<p style="text-align: justify;">`, byline in `<strong>`
- `website_content_ar`: same structure, Arabic content
- `author_id`: 42 (Islam Jamal AlNajjar — the creator at the time)
- `country_ids`: `[]` (empty despite mentioning Gaza/Lebanon/Syria/Yemen — "International" scope)
- `is_homepage`: true; `is_relief_coordination`: false
- `copyright`: set manually after (`"Daily challenges in collecting water. ©AL WATAN"`)
