"""
Extract unpublished articles from a Relief Center news .docx.

Template shape:

    Each article is its own table with 6 labeled field rows:

      cell[0] label   cell[1] EN              cell[2] AR
      "Title"         English title           Arabic title
      "Author"        Author name             (not used)
      "Date"          "15 April 2026"         (not used)
      "Country"       "International"         (not used)
      "Body"          English body text       Arabic body text
      "Status"        "Unpublished"           (not used)

    Publication state is determined by the Status EN cell text:
    "Unpublished" → article is unpublished (included in output).
    "Published" → article is already published (filtered out).

The script walks every <w:tbl> in the document. A table is only treated
as an article when all six labeled rows are present (structural tables
are ignored). The first valid table (template) is skipped.

Output: JSON list of unpublished articles only, one element per article:

    {
      "article_index": 0,           # 0-based, sequential (renumbered after filtering)
      "title_en": "...",
      "title_ar": "...",
      "author_en": "...",
      "date_en": "15 April 2026",
      "country_en": "International",
      "body_en": "full body text with \\n between paragraphs",
      "body_ar": "full Arabic body text",
      "status_en": "Unpublished",
      "status_en_cell_index": 21,    # document-order w:tc index of EN status cell
      "status_ar_cell_index": 22,    # document-order w:tc index of AR status cell
      "article_cell_indices": [...]  # all w:tc indices in this table for recoloring
    }

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
    """Pull an article out of a table, or return None if the table
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

    # A table isn't an article unless every labeled row is present.
    # Skipping partial/structural tables silently keeps the extractor
    # robust to cover pages, tables of contents, etc. that might share
    # the document.
    if set(field_cells.keys()) != REQUIRED_KEYS:
        return None

    status_en, status_ar = field_cells["status"]

    # For bilingual content, we extract both EN and AR
    # But for metadata (author, date, country), only EN is used downstream
    body_ar_text = _cell_text(field_cells["body"][1]).strip()
    title_ar_text = _cell_text(field_cells["title"][1]).strip()

    # Check if article is unpublished before extracting indices
    status_en_text = fields["status_en"].strip()
    if status_en_text != UNPUBLISHED_STATUS:
        return None

    # Every <w:tc> inside this table — in document order — so the
    # recolor step can flip the whole article table's fill in one call
    # rather than only the Status cells.
    article_cell_indices = [
        cell_index_map[id(tc)] for tc in tbl.iter(f"{W}tc")
    ]

    return {
        "article_index": 0,  # caller renumbers across valid articles
        "title_en": fields["title_en"],
        "title_ar": title_ar_text,
        "author_en": fields["author_en"],
        "date_en": fields["date_en"],
        "country_en": fields["country_en"],
        "body_en": fields["body_en"],
        "body_ar": body_ar_text,
        "status_en": status_en_text,
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
