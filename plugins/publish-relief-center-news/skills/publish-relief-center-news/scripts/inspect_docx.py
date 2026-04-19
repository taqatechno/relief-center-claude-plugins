"""
Extract structured article data from a v6 Relief Center news .docx.

Template shape (v6):

    Each article is its own table with 6 labeled field rows — the label
    text in cell[0] identifies the field, cell[1] is the English value,
    cell[2] is the Arabic value. A monthly docx holds one such table
    per article.

      cell[0] label   cell[1] EN              cell[2] AR
      -------------   --------------------    --------------------
      "Title"         English title           Arabic title
      "Author"        Author name EN          Author name AR
      "Date"          "15 April 2026"         "15 أبريل 2026"
      "Country"       "International"         "دولي"
      "Body"          English body text       Arabic body text
      "Status"        "Unpublished"           ""

    Publication state is encoded in the Status row's text content: if the
    English status cell reads "Unpublished", the article is unpublished.
    If it reads "Published", it's published and the table should be skipped.
    The Status cell's fill color is just for visualization.

The script walks every <w:tbl> in the document. A table is only treated
as a v6 article when all six labeled rows are present (structural tables
like headers or cover pages are ignored automatically).

Output: JSON list, one element per valid v6 article, shape:

    {
      "article_index": 0,           # 0-based, sequential among valid articles
      "table_index": 0,             # position among all <w:tbl> in the docx
      "title_en": "...",
      "title_ar": "...",
      "author_en": "...",
      "author_ar": "...",
      "date_en": "15 April 2026",
      "date_ar": "15 أبريل 2026",
      "country_en": "International",
      "country_ar": "دولي",
      "body_en": "full body text with \\n between paragraphs",
      "body_ar": "full Arabic body text",
      "status_en": "Unpublished",
      "status_ar": "",
      "status_fill": "FFFFFF",      # EN status cell fill, uppercased, or ""
      "is_unpublished": true,       # derived from status_fill
      "status_en_cell_index": 21,   # document-order w:tc index of EN status cell
      "status_ar_cell_index": 22    # document-order w:tc index of AR status cell
    }

`status_en_cell_index` / `status_ar_cell_index` are the cells that
`recolor_docx_cells.py` should flip white → purple once a post is
published, so the docx stays in sync with reality.

Usage:
    python inspect_docx.py <docx_path>
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"

# Exact label strings in cell[0] of a field row → the snake_case key we
# expose in the output JSON. The template uses English labels for all
# rows (including on Arabic-content rows) so this mapping is stable.
FIELD_LABELS: dict[str, str] = {
    "Title":   "title",
    "Author":  "author",
    "Date":    "date",
    "Country": "country",
    "Body":    "body",
    "Status":  "status",
}

REQUIRED_KEYS = set(FIELD_LABELS.values())

# Status text that means "unpublished"
UNPUBLISHED_STATUS = "Unpublished"


def _cell_fill(cell: ET.Element) -> str | None:
    tc_pr = cell.find(f"{W}tcPr")
    if tc_pr is None:
        return None
    shd = tc_pr.find(f"{W}shd")
    if shd is None:
        return None
    return shd.get(f"{W}fill")


def _cell_text(cell: ET.Element) -> str:
    """All paragraphs in a cell, joined by \\n. Preserves inline run
    splits within a paragraph."""
    parts: list[str] = []
    for para in cell.iter(f"{W}p"):
        run_texts = [t.text for t in para.iter(f"{W}t") if t.text]
        if run_texts:
            parts.append("".join(run_texts))
    return "\n".join(parts)


def _extract_article(
    tbl: ET.Element,
    table_idx: int,
    cell_index_map: dict[int, int],
) -> dict | None:
    """Pull a v6 article out of a table, or return None if the table
    doesn't have the full set of six labeled field rows."""
    fields: dict[str, str] = {}
    field_cells: dict[str, tuple[ET.Element, ET.Element]] = {}

    for tr in tbl.findall(f"{W}tr"):
        cells = list(tr.findall(f"{W}tc"))
        if len(cells) != 3:
            continue
        label = _cell_text(cells[0]).strip()
        key = FIELD_LABELS.get(label)
        if not key:
            continue
        fields[f"{key}_en"] = _cell_text(cells[1]).strip()
        fields[f"{key}_ar"] = _cell_text(cells[2]).strip()
        field_cells[key] = (cells[1], cells[2])

    # A table isn't a v6 article unless every labeled row is present.
    # Skipping partial/structural tables silently keeps the extractor
    # robust to cover pages, tables of contents, etc. that might share
    # the document.
    if set(field_cells.keys()) != REQUIRED_KEYS:
        return None

    status_en, status_ar = field_cells["status"]
    status_fill = (_cell_fill(status_en) or "").upper()

    # Every <w:tc> inside this table — in document order — so the
    # recolor step can flip the whole article table's fill in one call
    # rather than only the Status cells. This is the v6 convention:
    # "article published" = the entire article's table is tinted.
    article_cell_indices = [
        cell_index_map[id(tc)] for tc in tbl.iter(f"{W}tc")
    ]

    return {
        "article_index": 0,  # caller renumbers across valid articles
        "table_index": table_idx,
        **fields,
        "status_fill": status_fill,
        "is_unpublished": fields["status_en"] == UNPUBLISHED_STATUS,
        "status_en_cell_index": cell_index_map[id(status_en)],
        "status_ar_cell_index": cell_index_map[id(status_ar)],
        "article_cell_indices": article_cell_indices,
    }


def inspect(docx_path: Path) -> list[dict]:
    with zipfile.ZipFile(docx_path) as z:
        with z.open("word/document.xml") as fh:
            tree = ET.parse(fh)
    root = tree.getroot()

    # Document-order index of every <w:tc>. These indices are the handle
    # recolor_docx_cells.py uses to locate cells for in-place rewrite,
    # so we stamp them here while we still have element identity.
    cell_index_map = {
        id(cell): idx for idx, cell in enumerate(root.iter(f"{W}tc"))
    }

    articles: list[dict] = []
    article_count = 0
    for table_idx, tbl in enumerate(root.iter(f"{W}tbl")):
        article = _extract_article(tbl, table_idx, cell_index_map)
        if article is not None:
            # Skip the first article table (template)
            if article_count == 0:
                article_count += 1
                continue
            article["article_index"] = len(articles)
            articles.append(article)
            article_count += 1
    return articles


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    if len(sys.argv) != 2:
        sys.stderr.write(f"usage: {sys.argv[0]} <docx_path>\n")
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        sys.stderr.write(f"file not found: {path}\n")
        return 2

    articles = inspect(path)
    print(json.dumps(articles, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
