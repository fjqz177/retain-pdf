from __future__ import annotations

from pathlib import Path
import math

import fitz

from services.rendering.source.document_ops import page_has_editable_text
from services.rendering.source.document_ops import page_is_pseudo_editable_scan


def resolve_page_range(total_pages: int, start_page: int, end_page: int) -> tuple[int, int]:
    start = max(0, start_page)
    stop = total_pages - 1 if end_page < 0 else min(end_page, total_pages - 1)
    if start > stop:
        raise RuntimeError(f"Invalid page range: start_page={start}, end_page={stop}")
    return start, stop


def is_editable_pdf(doc: fitz.Document, start_page: int, end_page: int) -> bool:
    sample_pages = range(start_page, min(end_page, start_page + 2) + 1)
    sampled = 0
    editable_pages = 0
    pseudo_scan_pages = 0
    for page_idx in sample_pages:
        if 0 <= page_idx < len(doc):
            sampled += 1
            page = doc[page_idx]
            if page_is_pseudo_editable_scan(page):
                pseudo_scan_pages += 1
            if page_has_editable_text(page):
                editable_pages += 1
    if sampled == 0:
        return False
    if pseudo_scan_pages >= sampled:
        return False
    return editable_pages >= max(1, math.ceil(sampled / 2))


def resolve_effective_render_mode(
    *,
    render_mode: str,
    source_pdf_path: Path,
    start_page: int,
    end_page: int,
    translated_pages_map: dict[int, list[dict]] | None = None,
) -> str:
    if render_mode != "auto":
        return render_mode

    if not translated_pages_map:
        print("auto render mode selected: typst (no translated pages map)")
        return "typst"

    doc = fitz.open(source_pdf_path)
    try:
        total_pages = len(doc)
        sample_stop = total_pages - 1 if end_page < 0 else min(end_page, total_pages - 1)
        editable = is_editable_pdf(doc, start_page, sample_stop)
        if not editable:
            print(
                "auto render mode selected: typst_visual "
                "(non-editable or pseudo-editable scan PDF; visual-only cleaned-background route)"
            )
            return "typst_visual"
    finally:
        doc.close()

    print("auto render mode selected: typst (background render route by default)")
    return "typst"
