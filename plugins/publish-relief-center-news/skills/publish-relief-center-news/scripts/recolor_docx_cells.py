"""
Rewrite specific table cells' fill color from white to purple, in place,
and optionally replace one cell's text (e.g., "Unpublished" -> "Published").

Used by the publish-relief-center-news orchestrator after a successful
publish: every cell of the article's table gets recolored so the docx
stays in sync with reality, and the Status cell's text is updated so the
row reads as published at a glance.

Usage:
    python recolor_docx_cells.py <docx_path> [--set-text <cell_index>=<text> ...] \\
        <cell_index> [<cell_index> ...]

Behavior:
  - Only cells whose current fill is "unpublished" (null/empty/FFFFFF) are
    recolored. Cells at target indices with any other fill are skipped and
    reported.
  - New fill: #B4A7D6 (light purple), visually distinct from both green
    shades (#D9F2D0 pale, #8DD873 saturated) the manual workflow uses.
  - For each --set-text flag, the first <w:t> inside the given cell is
    overwritten with the provided text; any additional <w:t> elements in
    that cell are blanked to avoid duplicating text split across runs.
  - The docx is rewritten atomically in place (temp file + rename).

IMPORTANT: This script does NOT parse+reserialize the document's XML.
ElementTree (and other XML libraries that preserve semantics only) drop or
reorder namespace declarations, which Word flags as "unreadable content"
even though Odoo and other consumers accept them. Instead, we locate each
target <w:tc> by position, find its <w:shd> element via regex, and rewrite
only the `w:fill` attribute — every other byte of the XML is preserved.
Cell-text rewrites follow the same byte-surgical pattern on <w:t>.

Exit code: 0 on full success; 1 if any target cell was skipped or missing;
2 on usage / IO errors. Always prints a JSON summary on stdout.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


UNPUBLISHED_FILLS = {"", "FFFFFF"}          # plus None for "no shd element"
PUBLISHED_BY_AI_FILL = "B4A7D6"

_TC_TOKEN = re.compile(rb"<w:tc\b[^>]*?>|</w:tc>")
_TC_OPEN = re.compile(rb"<w:tc\b[^>]*?>")
_TCPR_OPEN = re.compile(rb"<w:tcPr\b[^>]*?>")
_SHD_RE = re.compile(rb"<w:shd\b[^>]*?/>")
_FILL_ATTR = re.compile(rb'\s*w:fill="([^"]*)"')
_WT_RE = re.compile(rb"<w:t(\s[^>]*)?>([^<]*)</w:t>")


def _find_cell_span(xml: bytes, cell_index: int) -> tuple[int, int]:
    """Return (open_tag_start, close_tag_end) for the Nth <w:tc> in document order.

    Walks <w:tc> open and close tokens while tracking nesting depth. `cell_index`
    counts every <w:tc> in document order (matches ET.iter() order), including
    cells inside nested tables — though in this project article cells are all
    top-level.
    """
    opens = list(_TC_OPEN.finditer(xml))
    if cell_index >= len(opens):
        raise IndexError(f"cell_index {cell_index} >= total w:tc count {len(opens)}")
    start = opens[cell_index].start()
    depth = 1
    pos = opens[cell_index].end()
    while depth > 0:
        m = _TC_TOKEN.search(xml, pos)
        if not m:
            raise RuntimeError("unbalanced <w:tc> tags while scanning")
        if m.group().startswith(b"</"):
            depth -= 1
        else:
            depth += 1
        pos = m.end()
    return start, pos


def _rewrite_cell(cell_xml: bytes, new_fill: str) -> tuple[bytes, str | None]:
    """Rewrite this cell's fill color. Returns (new_cell_bytes, previous_fill)."""
    shd_match = _SHD_RE.search(cell_xml)
    if shd_match:
        old_shd = shd_match.group()
        fill_match = _FILL_ATTR.search(old_shd)
        if fill_match:
            previous = fill_match.group(1).decode("ascii")
            # Replace the fill value, preserving surrounding attributes/whitespace.
            new_shd = (
                old_shd[: fill_match.start()]
                + b' w:fill="' + new_fill.encode("ascii") + b'"'
                + old_shd[fill_match.end():]
            )
        else:
            # shd exists but has no fill attribute — inject one before the `/>`.
            previous = None
            assert old_shd.endswith(b"/>")
            new_shd = old_shd[:-2] + b' w:fill="' + new_fill.encode("ascii") + b'"/>'
        return (
            cell_xml[: shd_match.start()] + new_shd + cell_xml[shd_match.end():],
            previous,
        )

    # No shd. Need to inject one. Prefer injecting into existing <w:tcPr>; if
    # there is no tcPr at all, create one right after the <w:tc> open tag.
    injected = (
        b'<w:shd w:val="clear" w:color="auto" w:fill="'
        + new_fill.encode("ascii") + b'"/>'
    )
    tcpr = _TCPR_OPEN.search(cell_xml)
    if tcpr:
        return (cell_xml[: tcpr.end()] + injected + cell_xml[tcpr.end():], None)

    tc_open = _TC_OPEN.match(cell_xml)
    if not tc_open:
        raise RuntimeError("cell bytes do not start with <w:tc>")
    wrap = b"<w:tcPr>" + injected + b"</w:tcPr>"
    return (cell_xml[: tc_open.end()] + wrap + cell_xml[tc_open.end():], None)


def _xml_escape(text: str) -> bytes:
    """Minimal XML text escape for w:t content."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .encode("utf-8")
    )


def _rewrite_cell_text(cell_xml: bytes, new_text: str) -> tuple[bytes, str | None]:
    """Replace the first <w:t>...</w:t> inner content with new_text; blank out
    any subsequent <w:t> elements in the same cell so text split across runs
    doesn't produce duplicated or stale fragments.

    Returns (new_cell_bytes, previous_first_text). previous_first_text is
    None if there was no <w:t> to update.
    """
    matches = list(_WT_RE.finditer(cell_xml))
    if not matches:
        return cell_xml, None

    new_text_escaped = _xml_escape(new_text)
    previous = matches[0].group(2).decode("utf-8")

    out = bytearray()
    last_end = 0
    for i, m in enumerate(matches):
        out.extend(cell_xml[last_end:m.start()])
        attrs = m.group(1) or b""
        if i == 0:
            out.extend(b"<w:t" + attrs + b">" + new_text_escaped + b"</w:t>")
        else:
            out.extend(b"<w:t" + attrs + b"></w:t>")
        last_end = m.end()
    out.extend(cell_xml[last_end:])
    return bytes(out), previous


def recolor(
    docx_path: Path,
    cell_indices: list[int],
    text_overrides: dict[int, str] | None = None,
) -> dict:
    text_overrides = text_overrides or {}

    with zipfile.ZipFile(docx_path) as zin:
        xml = zin.read("word/document.xml")

    # Process cells in descending order so earlier spans' offsets don't shift
    # as we splice later ones in. (Each rewrite may change the byte length.)
    # The union covers both recolor targets and text-override targets — a
    # --set-text cell doesn't have to be in the recolor list (and vice versa).
    all_targets = sorted(set(cell_indices) | set(text_overrides.keys()), reverse=True)
    recolor_set = set(cell_indices)
    changed: list[dict] = []
    skipped: list[dict] = []
    text_changed: list[dict] = []

    for idx in all_targets:
        try:
            start, end = _find_cell_span(xml, idx)
        except IndexError:
            if idx in recolor_set:
                skipped.append({"cell_index": idx, "reason": "cell_index not found in document"})
            if idx in text_overrides:
                text_changed.append({
                    "cell_index": idx,
                    "skipped": True,
                    "reason": "cell_index not found in document",
                })
            continue

        cell_bytes = xml[start:end]

        if idx in recolor_set:
            shd = _SHD_RE.search(cell_bytes)
            current_fill: str | None = None
            if shd:
                fm = _FILL_ATTR.search(shd.group())
                current_fill = fm.group(1).decode("ascii") if fm else None

            normalized = (current_fill or "").upper()
            if normalized not in UNPUBLISHED_FILLS:
                skipped.append({
                    "cell_index": idx,
                    "reason": f"current fill {current_fill!r} is not unpublished (expected null/empty/FFFFFF)",
                })
            else:
                cell_bytes, previous = _rewrite_cell(cell_bytes, PUBLISHED_BY_AI_FILL)
                changed.append({
                    "cell_index": idx,
                    "old_fill": previous,
                    "new_fill": PUBLISHED_BY_AI_FILL,
                })

        if idx in text_overrides:
            new_text = text_overrides[idx]
            cell_bytes, previous_text = _rewrite_cell_text(cell_bytes, new_text)
            if previous_text is None:
                text_changed.append({
                    "cell_index": idx,
                    "skipped": True,
                    "reason": "cell contains no <w:t> element",
                })
            else:
                text_changed.append({
                    "cell_index": idx,
                    "old_text": previous_text,
                    "new_text": new_text,
                })

        xml = xml[:start] + cell_bytes + xml[end:]

    # Preserve insertion order of the input list for reporting.
    changed.sort(key=lambda r: cell_indices.index(r["cell_index"]) if r["cell_index"] in cell_indices else -1)
    skipped.sort(key=lambda r: cell_indices.index(r["cell_index"]) if r["cell_index"] in cell_indices else -1)

    any_write = bool(changed) or any("old_text" in r for r in text_changed)
    if any_write:
        _write_docx(docx_path, xml)

    result: dict = {
        "changed": changed,
        "skipped": skipped,
        "total_targeted": len(cell_indices),
    }
    if text_overrides:
        result["text_changed"] = text_changed
    return result


def _write_docx(docx_path: Path, new_xml_bytes: bytes) -> None:
    """Rewrite the docx, replacing word/document.xml and preserving everything else verbatim."""
    fd, tmp_str = tempfile.mkstemp(suffix=".docx", dir=docx_path.parent)
    os.close(fd)
    tmp_path = Path(tmp_str)
    try:
        with zipfile.ZipFile(docx_path) as zin, zipfile.ZipFile(
            tmp_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zout:
            for item in zin.infolist():
                if item.filename == "word/document.xml":
                    # Use writestr with the original ZipInfo to preserve timestamps,
                    # extra fields, external attrs, etc. — Word notices some of these.
                    zout.writestr(item, new_xml_bytes)
                else:
                    zout.writestr(item, zin.read(item.filename))
        shutil.move(str(tmp_path), str(docx_path))
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _parse_args(argv: list[str]) -> tuple[Path, list[int], dict[int, str]]:
    """Parse argv into (docx_path, cell_indices, text_overrides).

    --set-text <cell_index>=<text>  — repeatable; updates the given cell's
    first <w:t> content. The text may contain '=' characters; only the
    first '=' is treated as the separator.
    """
    if len(argv) < 3:
        raise SystemExit(
            f"usage: {argv[0]} <docx_path> [--set-text <cell_index>=<text> ...] "
            f"<cell_index> [<cell_index> ...]"
        )

    docx_path = Path(argv[1])
    indices: list[int] = []
    text_overrides: dict[int, str] = {}

    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg == "--set-text":
            if i + 1 >= len(argv):
                raise SystemExit("--set-text requires a <cell_index>=<text> argument")
            spec = argv[i + 1]
            if "=" not in spec:
                raise SystemExit(f"--set-text value must be <cell_index>=<text>, got: {spec}")
            idx_str, new_text = spec.split("=", 1)
            try:
                text_overrides[int(idx_str)] = new_text
            except ValueError:
                raise SystemExit(f"--set-text cell_index must be an integer: {idx_str!r}")
            i += 2
            continue
        try:
            indices.append(int(arg))
        except ValueError:
            raise SystemExit(f"cell_index must be an integer: {arg!r}")
        i += 1

    return docx_path, indices, text_overrides


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    try:
        docx_path, indices, text_overrides = _parse_args(sys.argv)
    except SystemExit as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    if not docx_path.is_file():
        sys.stderr.write(f"file not found: {docx_path}\n")
        return 2

    if not indices and not text_overrides:
        sys.stderr.write("no cell indices or --set-text overrides provided\n")
        return 2

    result = recolor(docx_path, indices, text_overrides)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["skipped"] else 1


if __name__ == "__main__":
    sys.exit(main())
