from __future__ import annotations

import sys
from unittest.mock import patch
from pathlib import Path

import fitz


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.rendering.source.cleanup.vector_text_cleanup import collect_vector_text_rects
from services.rendering.source.cleanup.vector_text_cleanup import cleanup_vector_text_drawings
from services.rendering.source.preparation.bbox_text_strip import _page_text_rects


def test_collect_vector_text_rects_detects_black_filled_glyph_drawings() -> None:
    page = fitz.open().new_page(width=300, height=400)
    target_rect = fitz.Rect(250, 40, 560, 60)
    drawings = [
        {
            "type": "f",
            "fill": (0.0, 0.0, 0.0),
            "rect": fitz.Rect(252, 46, 430, 55),
            "items": [("l", fitz.Point(0, 0), fitz.Point(1, 1))] * 20,
        },
        {
            "type": "f",
            "fill": (0.8, 0.8, 0.8),
            "rect": fitz.Rect(252, 46, 430, 55),
            "items": [("l", fitz.Point(0, 0), fitz.Point(1, 1))] * 20,
        },
        {
            "type": "f",
            "fill": (0.0, 0.0, 0.0),
            "rect": fitz.Rect(20, 200, 200, 240),
            "items": [("l", fitz.Point(0, 0), fitz.Point(1, 1))] * 20,
        },
    ]
    page.get_drawings = lambda: drawings  # type: ignore[method-assign]

    rects = collect_vector_text_rects(page, [target_rect])

    assert rects == [fitz.Rect(252, 46, 430, 55)]


def test_collect_vector_text_rects_detects_large_black_text_clusters_by_intersection() -> None:
    page = fitz.open().new_page(width=300, height=400)
    target_rect = fitz.Rect(50, 300, 250, 360)
    drawings = [
        {
            "type": "f",
            "fill": (0.0, 0.0, 0.0),
            "rect": fitz.Rect(20, 280, 280, 380),
            "items": [("l", fitz.Point(0, 0), fitz.Point(1, 1))] * 1000,
        }
    ]
    page.get_drawings = lambda: drawings  # type: ignore[method-assign]

    rects = collect_vector_text_rects(page, [target_rect])

    assert rects == [fitz.Rect(50, 300, 250, 360)]


def test_cleanup_vector_text_drawings_uses_background_covers_instead_of_redaction() -> None:
    page = fitz.open().new_page(width=300, height=400)
    target_rect = fitz.Rect(250, 40, 560, 60)
    vector_rect = fitz.Rect(252, 46, 430, 55)

    with patch(
        "services.rendering.source.cleanup.vector_text_cleanup.collect_vector_text_rects",
        return_value=[vector_rect],
    ), patch(
        "services.rendering.source.cleanup.vector_text_cleanup.prepare_background_covers",
        return_value=["cover"],
    ) as prepare_mock, patch(
        "services.rendering.source.cleanup.vector_text_cleanup.apply_prepared_background_covers",
    ) as apply_mock:
        count = cleanup_vector_text_drawings(page, [target_rect])

    assert count == 1
    prepare_mock.assert_called_once_with(page, [vector_rect])
    apply_mock.assert_called_once_with(page, ["cover"])


def test_bbox_text_strip_rects_shrink_away_from_adjacent_display_formula() -> None:
    page_height = 818.362
    items = [
        {
            "block_type": "text",
            "bbox": [319.967, 244.459, 566.442, 417.43],
            "protected_translated_text": "正文译文",
        },
        {
            "block_type": "formula",
            "bbox": [333.466, 419.929, 472.452, 445.425],
            "source_text": "$$ E^{(1)} $$",
        },
    ]

    rects = _page_text_rects(page_height=page_height, translated_items=items)

    assert len(rects) == 1
    formula_top_in_pdf_coords = page_height - items[1]["bbox"][3]
    assert rects[0].y0 > formula_top_in_pdf_coords


def test_bbox_text_strip_rects_split_around_overlapping_display_formula() -> None:
    page_height = 655.228
    items = [
        {
            "block_type": "text",
            "bbox": [44.5, 455.8, 385.7, 507.3],
            "protected_translated_text": "正文译文",
        },
        {
            "block_type": "formula",
            "bbox": [177.9, 458.8, 250.8, 484.8],
            "source_text": "$$ \\frac{a}{b} $$",
        },
    ]

    rects = _page_text_rects(page_height=page_height, translated_items=items)
    formula = fitz.Rect(
        items[1]["bbox"][0],
        page_height - items[1]["bbox"][3],
        items[1]["bbox"][2],
        page_height - items[1]["bbox"][1],
    )

    assert rects
    assert all((rect & formula).is_empty for rect in rects)
