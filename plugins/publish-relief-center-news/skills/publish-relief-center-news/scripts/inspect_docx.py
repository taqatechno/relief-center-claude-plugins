"""
Walk every table row in a .docx file and emit its cells as "article units".

Each news article in the Relief Center bilingual docx is one table ROW with
two cells: the left cell carries the English half, the right cell carries
the Arabic mirror. Both cells share the same fill color, which encodes the
article's publication status (white = unpublished, green = manually
published, purple = AI-published by this skill).

This script groups cells by row, identifies which rows are real articles
(vs. template header rows, column labels, date separators, or empty
trailing rows), and emits a JSON list keyed to rows. Agent A in the
publish-relief-center-news skill consumes this and filters to unpublished
article rows.

Usage:
    python inspect_docx.py <docx_path>

Output (JSON list, one entry per row in document order):
    [
      {
        "row_index": 3,
        "en_cell_index": 5,
        "ar_cell_index": 6,
        "fill": "D9F2D0",            # hex, or null; fills of EN and AR cells match on articles
        "en_text": "News No.: 1\\n...",
        "ar_text": "خبر رقم: 1\\n...",
        "is_article": true
      },
      ...
    ]

Rows that aren't articles (template header, column labels, date separator
strips, empty rows) still appear in the output with `is_article: false` so
callers can see the full table. Only use `is_article: true` entries for
publishing decisions.
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

# Body-content markers. Real articles always contain a body, and the body
# is introduced by one of these markers. Template header rows carry the
# label strings ("News No.:", "Title:", etc.) but not these body markers,
# which cleanly distinguishes template from content without length
# heuristics.
EN_BODY_MARKERS = ("News details:", "News Text:")
AR_BODY_MARKERS = ("نص الخبر:",)


def _cell_fill(cell: ET.Element) -> str | None:
    tc_pr = cell.find(f"{W}tcPr")
    if tc_pr is None:
        return None
    shd = tc_pr.find(f"{W}shd")
    if shd is None:
        return None
    return shd.get(f"{W}fill")


def _cell_text(cell: ET.Element) -> str:
    parts: list[str] = []
    for para in cell.iter(f"{W}p"):
        run_texts = [t.text for t in para.iter(f"{W}t") if t.text]
        if run_texts:
            parts.append("".join(run_texts))
    return "\n".join(parts)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def inspect(docx_path: Path) -> list[dict]:
    with zipfile.ZipFile(docx_path) as z:
        with z.open("word/document.xml") as fh:
            tree = ET.parse(fh)

    root = tree.getroot()

    # First pass: assign a stable cell_index in document order (matches
    # what recolor_docx_cells.py uses, which walks w:tc in the same order).
    cell_index_by_element: dict[int, int] = {}
    for idx, cell in enumerate(root.iter(f"{W}tc")):
        cell_index_by_element[id(cell)] = idx

    rows: list[dict] = []
    row_index = 0
    for tr in root.iter(f"{W}tr"):
        cells = list(tr.findall(f"{W}tc"))
        if not cells:
            continue

        # For article rows we expect exactly 2 cells (left=EN, right=AR).
        # Rows with 1 cell (date separators, merged headers) or other counts
        # are valid but not article candidates.
        en_cell = cells[0] if len(cells) >= 1 else None
        ar_cell = cells[1] if len(cells) >= 2 else None

        en_text = _cell_text(en_cell) if en_cell is not None else ""
        ar_text = _cell_text(ar_cell) if ar_cell is not None else ""

        is_article = (
            len(cells) == 2
            and _has_any(en_text, EN_BODY_MARKERS)
            and _has_any(ar_text, AR_BODY_MARKERS)
        )

        fill_en = _cell_fill(en_cell) if en_cell is not None else None
        fill_ar = _cell_fill(ar_cell) if ar_cell is not None else None
        # If the two cells disagree on fill (shouldn't happen on articles,
        # but the docx could drift), surface it as the EN fill — the EN cell
        # is the canonical one since orchestrator publishes from EN primary.
        fill = fill_en if fill_en == fill_ar else fill_en

        rows.append({
            "row_index": row_index,
            "en_cell_index": cell_index_by_element.get(id(en_cell)) if en_cell is not None else None,
            "ar_cell_index": cell_index_by_element.get(id(ar_cell)) if ar_cell is not None else None,
            "fill": fill,
            "fill_en": fill_en,
            "fill_ar": fill_ar,
            "en_text": en_text,
            "ar_text": ar_text,
            "is_article": is_article,
        })
        row_index += 1

    return rows


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    if len(sys.argv) != 2:
        sys.stderr.write(f"usage: {sys.argv[0]} <docx_path>\n")
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        sys.stderr.write(f"file not found: {path}\n")
        return 2

    rows = inspect(path)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
