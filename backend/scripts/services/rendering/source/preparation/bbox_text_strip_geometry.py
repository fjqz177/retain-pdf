from __future__ import annotations

import fitz

from services.rendering.source.preparation.bbox_text_strip_constants import BBOX_TEXT_STRIP_FORMULA_GUARD_PAD_X_PT
from services.rendering.source.preparation.bbox_text_strip_constants import BBOX_TEXT_STRIP_FORMULA_GUARD_PAD_Y_PT
from services.rendering.source.preparation.bbox_text_strip_policy_adapter import split_rect_away_from_formula_guard_rects


def rect_tuple(rect: fitz.Rect) -> tuple[float, float, float, float]:
    return (round(float(rect.x0), 3), round(float(rect.y0), 3), round(float(rect.x1), 3), round(float(rect.y1), 3))


def ocr_bbox_to_pdf_rect(page: fitz.Page, bbox: object) -> fitz.Rect | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    x0, y0, x1, y1 = (to_float(value) for value in bbox)
    rect = fitz.Rect(x0, y0, x1, y1)
    if rect.is_empty:
        return None
    pdf_rect = rect * ~page.transformation_matrix
    return None if pdf_rect.is_empty else pdf_rect


def formula_guard_rects(
    formula_rects: list[fitz.Rect],
    *,
    strip_rects: list[fitz.Rect] | None = None,
) -> list[fitz.Rect]:
    return [bbox_text_strip_formula_guard_rect(rect) for rect in formula_rects if not rect.is_empty]


def split_rect_away_from_formulas(rect: fitz.Rect, formula_rects: list[fitz.Rect]) -> list[fitz.Rect]:
    guards = [bbox_text_strip_formula_guard_rect(formula) for formula in formula_rects]
    return split_rect_away_from_formula_guard_rects(rect, guards)


def bbox_text_strip_formula_guard_rect(formula: fitz.Rect) -> fitz.Rect:
    return fitz.Rect(
        formula.x0 - BBOX_TEXT_STRIP_FORMULA_GUARD_PAD_X_PT,
        formula.y0 - BBOX_TEXT_STRIP_FORMULA_GUARD_PAD_Y_PT,
        formula.x1 + BBOX_TEXT_STRIP_FORMULA_GUARD_PAD_X_PT,
        formula.y1 + BBOX_TEXT_STRIP_FORMULA_GUARD_PAD_Y_PT,
    )


def shrink_rect_away_from_formulas(rect: fitz.Rect, formula_rects: list[fitz.Rect]) -> fitz.Rect:
    protected_segments = split_rect_away_from_formulas(rect, formula_rects)
    if not protected_segments:
        return fitz.Rect()
    if len(protected_segments) == 1:
        return protected_segments[0]
    largest = max(protected_segments, key=lambda segment: segment.get_area())
    return largest


def to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default
