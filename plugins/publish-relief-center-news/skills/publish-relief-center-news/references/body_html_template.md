# Body HTML template

House style for the `content` (English) and `website_content_ar` (Arabic) fields on Latest News `blog.post` records. Follow this reference when generating body HTML so the new post renders identically to existing manually-published posts (canonical example: post id 119, "Humanitarian Assistance and Funding: A Widening Gap Threatening the Response to the Sudanese Refugee Crisis in Chad").

Both language bodies share the same structural rules unless called out otherwise.

## Paragraph shape

Every paragraph is a single `<p>` element with `text-align: justify;`:

```html
<p style="text-align: justify;">Body paragraph text goes here.</p>
```

The **first paragraph only** additionally carries Odoo's editor metadata so the post mirrors what Odoo itself writes when a human edits in the rich-text editor:

```html
<p style="text-align: justify;" data-oe-version="2.0">First paragraph…</p>
```

Subsequent paragraphs do **not** have `data-oe-version` — only the first one.

Do not add any other attributes, classes, or inline styles to paragraphs. No `dir="rtl"` on Arabic paragraphs — Odoo's theme handles direction from the page/language context, not per-element.

## Byline (first line of the first paragraph)

The first paragraph opens with the author byline, followed by a `<br>`, then the body text on the next visual line. This keeps "Dr. Name |" visually separate from the opening sentence while still living inside one `<p>` element.

### English — byline in bold

```html
<p style="text-align: justify;" data-oe-version="2.0"><strong>Dr. Ola Alkahlout |&nbsp;</strong><br>Recent developments across multiple humanitarian crisis contexts…</p>
```

Rules:
- The byline sits inside `<strong>…</strong>`.
- Exactly one `|` after the name, followed by `&nbsp;` (non-breaking space) **inside** the `<strong>` block.
- `<br>` sits **outside** `<strong>`, immediately after the closing tag.
- Body text starts right after `<br>` with no leading space.

### Arabic — mirror of the English byline

```html
<p style="text-align: justify;" data-oe-version="2.0"><strong>د. علا الكحلوت |&nbsp;</strong><br>تشير التطورات الإنسانية الأخيرة في عدد من بؤر الأزمات…</p>
```

Same pattern: name + ` |` + `&nbsp;` inside `<strong>`, then `<br>`, then body. (Post 119's AR byline happened to be rendered without `<strong>` — treat that as an editor slip; match post 110's style, which bolds both languages, for consistency.)

### Why `&nbsp;` and not a regular space?

The non-breaking space keeps `|` from sitting alone on a line if the line wraps right before the body begins. It also matches exactly what Odoo's editor emits when a human types this structure.

## Body paragraphs after the byline

Split the docx body on blank lines (paragraph breaks) and emit one `<p>` per source paragraph, each justified:

```html
<p style="text-align: justify;">Second paragraph of the body…</p>
<p style="text-align: justify;">Third paragraph of the body…</p>
```

Keep sentences and punctuation verbatim from the docx, including em-dashes (`—`), smart quotes (`"`, `"`, `'`, `'`), and parenthetical acronyms like `(OCHA)`. Do not "clean up" the punctuation style.

## Unordered lists

When the docx uses a bulleted list, emit a `<ul>` block between paragraphs:

```html
<p style="text-align: justify;">Paragraph before the list introduces it.</p>
<ul>
    <li>First bullet item.</li>
    <li>Second bullet item.</li>
    <li>Third bullet item.</li>
</ul>
<p style="text-align: justify;">Paragraph after the list continues the discussion.</p>
```

Rules:
- `<ul>` sits **between** `<p>` elements, never inside one.
- Each `<li>` contains plain text (no inner `<p>`).
- Do not apply `text-align: justify` to list items — leave them at the theme default.

## Ordered lists

Same pattern, with `<ol>`:

```html
<p style="text-align: justify;">Paragraph before the numbered list.</p>
<ol>
    <li>First step.</li>
    <li>Second step.</li>
    <li>Third step.</li>
</ol>
<p style="text-align: justify;">Paragraph after the list.</p>
```

## Inline emphasis within paragraphs

- Bold: `<strong>text</strong>` (never `<b>`).
- Italic: `<em>text</em>` (never `<i>`).
- External link: `<a href="https://example.com">link text</a>` with no `target` or `rel` attributes — Odoo's theme handles link styling.

Use these sparingly. The vast majority of article body text is plain prose inside `<p>` elements; bold is reserved for the byline and (rarely) for key terms that the docx itself emphasises.

## Font size, color, weight

**Do not set any of these.** The blog theme controls font family, base size, line-height, heading sizes, and link color. Custom inline styles like `style="font-size: 14px"` or `style="color: #333"` are **not** part of the house style and should be avoided.

The only inline styles the template uses are:
- `style="text-align: justify;"` on every `<p>`
- `data-oe-version="2.0"` on the first `<p>`

## Alignment and direction

- `<p>` always carries `style="text-align: justify;"`, for both EN and AR.
- No `dir="rtl"` or `dir="ltr"` anywhere — Odoo's theme derives direction from the page language. The HTML for `website_content_ar` looks structurally identical to the English `content`; the text inside is what makes it Arabic.
- Headings (`<h1>`, `<h2>`, etc.) are not used in article bodies. The title of the post lives in `name`, not inside the content.

## Special characters to preserve verbatim from the docx

- Smart quotes: `"` `"` `'` `'` — keep as-is; do not normalise to straight quotes.
- Em-dash (`—`) vs en-dash (`–`) vs hyphen (`-`) — keep whichever the docx uses. Common pattern: em-dash flanked by non-breaking spaces (e.g., "aid—particularly in Gaza" or "needs—particularly Gaza and Lebanon").
- Non-breaking space (`&nbsp;`): only introduce it in the byline after the `|`. Do not add `&nbsp;` elsewhere unless the docx itself has one.
- HTML-sensitive characters inside body text: escape `&` as `&amp;`, `<` as `&lt;`, `>` as `&gt;`. The HTML-renderer in Odoo is strict about these.

## Complete first-paragraph template

Use this as the skeleton for a minimal article body (byline + one body paragraph). Fill in the placeholders:

```html
<p style="text-align: justify;" data-oe-version="2.0"><strong>{{AUTHOR_NAME}} |&nbsp;</strong><br>{{FIRST_PARAGRAPH_BODY}}</p>
<p style="text-align: justify;">{{SECOND_PARAGRAPH}}</p>
<p style="text-align: justify;">{{THIRD_PARAGRAPH}}</p>
```

Substitute EN or AR versions appropriately, and repeat the plain `<p style="text-align: justify;">…</p>` shape for every additional paragraph. Insert `<ul>` / `<ol>` blocks between paragraphs wherever the docx uses lists.

## Trailing whitespace

Existing posts sometimes end the final paragraph with a space or trailing dots (e.g., `…fragile contexts....</p>`). Treat any trailing whitespace in the source docx as content and preserve it; don't trim or normalise.

## What NOT to emit

- `<div>` wrappers around paragraphs — use `<p>` directly inside `content` / `website_content_ar`.
- `<br>` between paragraphs — use separate `<p>` elements.
- `<span class="…">` with Odoo editor classes (`o_…`) — these get added by Odoo's editor if a human later edits, but they shouldn't appear in freshly-authored HTML.
- Inline `<img>`, `<figure>`, or other media — cover image is handled separately via `cover_properties`, and the skill doesn't set it.
- `data-oe-*` attributes other than `data-oe-version="2.0"` on the first `<p>`. Other `data-oe-id`, `data-oe-model`, etc. are internal Odoo bookkeeping and should not be synthesised by the skill.
