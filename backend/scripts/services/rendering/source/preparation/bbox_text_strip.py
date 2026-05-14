from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import time

import fitz
import pikepdf
from pikepdf import Name

from services.rendering.source.cleanup.ops import merge_rects
from services.translation.item_reader import item_block_kind


TEXT_SHOW_OPERATORS = {"Tj", "TJ", "'", '"'}
DEFAULT_TEXT_ADVANCE_PT = 18.0
MIN_TEXT_BOX_HEIGHT_PT = 2.0
BBOX_TEXT_STRIP_CONTENT_STREAM_SIZE_THRESHOLD = 1_000_000
FORMULA_PROTECTION_GAP_PT = 6.0
FORMULA_PROTECTION_X_OVERLAP_RATIO = 0.18
BBOX_TEXT_STRIP_SKIP_FORMULA_PAGE_MIN = 1
TEXT_INVISIBLE_RENDER_MODE = 3
TEXT_DEFAULT_RENDER_MODE = 0
BBoxTextOpMode = str


@dataclass(frozen=True)
class BBoxTextStripResult:
    changed: bool
    output_pdf_path: Path | None = None
    pages_changed: int = 0
    text_show_ops_removed: int = 0
    pages_skipped_complex: int = 0
    pages_skipped_no_text_overlap: int = 0
    forms_changed: int = 0
    changed_page_indices: frozenset[int] = frozenset()
    skipped_complex_page_indices: frozenset[int] = frozenset()
    skipped_no_text_overlap_page_indices: frozenset[int] = frozenset()


@dataclass(frozen=True)
class BBoxTextStripCandidates:
    page_rects: dict[int, tuple[tuple[float, float, float, float], ...]]
    page_protected_rects: dict[int, tuple[tuple[float, float, float, float], ...]] | None = None
    pages_skipped_complex: int = 0
    pages_skipped_no_text_overlap: int = 0
    skipped_complex_page_indices: frozenset[int] = frozenset()
    skipped_no_text_overlap_page_indices: frozenset[int] = frozenset()

    def fitz_page_rects(self) -> dict[int, list[fitz.Rect]]:
        return {
            page_idx: [fitz.Rect(rect) for rect in rects]
            for page_idx, rects in self.page_rects.items()
        }

    def fitz_page_protected_rects(self) -> dict[int, list[fitz.Rect]]:
        return {
            page_idx: [fitz.Rect(rect) for rect in rects]
            for page_idx, rects in (self.page_protected_rects or {}).items()
        }


def build_bbox_text_strip_candidates(
    *,
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    op_mode: BBoxTextOpMode = "strip",
) -> BBoxTextStripCandidates:
    page_rects: dict[int, tuple[tuple[float, float, float, float], ...]] = {}
    page_protected_rects: dict[int, tuple[tuple[float, float, float, float], ...]] = {}
    skipped_complex_page_indices: set[int] = set()
    skipped_no_text_overlap_page_indices: set[int] = set()
    doc = fitz.open(source_pdf_path)
    try:
        for page_idx, items in translated_pages.items():
            if page_idx < 0 or page_idx >= len(doc):
                continue
            page = doc[page_idx]
            item_rects = _page_item_rects(items)
            if not item_rects:
                continue
            if _page_content_stream_size(doc, page) >= BBOX_TEXT_STRIP_CONTENT_STREAM_SIZE_THRESHOLD:
                skipped_complex_page_indices.add(page_idx)
                continue
            formula_rects = _page_formula_rects(page_height=page.rect.height, translated_items=items)
            if op_mode != "hide" and len(formula_rects) >= BBOX_TEXT_STRIP_SKIP_FORMULA_PAGE_MIN:
                skipped_complex_page_indices.add(page_idx)
                continue
            _drawing_count, text_overlap_count = _page_bboxlog_stats(page, item_rects)
            if text_overlap_count <= 0:
                skipped_no_text_overlap_page_indices.add(page_idx)
                continue
            rects = _page_text_rects(
                page_height=page.rect.height,
                translated_items=items,
                op_mode=op_mode,
            )
            if rects:
                page_rects[page_idx] = tuple(_rect_tuple(rect) for rect in rects)
                protected_rects = _expanded_formula_rects(formula_rects)
                if protected_rects:
                    page_protected_rects[page_idx] = tuple(_rect_tuple(rect) for rect in protected_rects)
    finally:
        doc.close()
    return BBoxTextStripCandidates(
        page_rects=page_rects,
        page_protected_rects=page_protected_rects,
        pages_skipped_complex=len(skipped_complex_page_indices),
        pages_skipped_no_text_overlap=len(skipped_no_text_overlap_page_indices),
        skipped_complex_page_indices=frozenset(skipped_complex_page_indices),
        skipped_no_text_overlap_page_indices=frozenset(skipped_no_text_overlap_page_indices),
    )


def _rect_tuple(rect: fitz.Rect) -> tuple[float, float, float, float]:
    return (round(float(rect.x0), 3), round(float(rect.y0), 3), round(float(rect.x1), 3), round(float(rect.y1), 3))


def _mul(left: tuple[float, float, float, float, float, float], right: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def _point(matrix: tuple[float, float, float, float, float, float]) -> tuple[float, float]:
    return matrix[4], matrix[5]


def _inside_any_rect(x: float, y: float, rects: list[fitz.Rect]) -> bool:
    probe = fitz.Point(x, y)
    return any(rect.contains(probe) for rect in rects)


def _intersects_any_rect(rect: fitz.Rect, rects: list[fitz.Rect]) -> bool:
    return any(not (rect & target).is_empty for target in rects)


def _is_protected_text_op(
    *,
    user_point: tuple[float, float],
    text_rect: fitz.Rect,
    protected_rects: list[fitz.Rect],
) -> bool:
    if not protected_rects:
        return False
    if _inside_any_rect(user_point[0], user_point[1], protected_rects):
        return True
    return _intersects_any_rect(text_rect, protected_rects)


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _matrix_from_operands(operands: object) -> tuple[float, float, float, float, float, float] | None:
    if len(operands) < 6:
        return None
    return tuple(_to_float(operands[index]) for index in range(6))  # type: ignore[return-value]


def _matrix_from_object(value: object) -> tuple[float, float, float, float, float, float]:
    try:
        if len(value) >= 6:
            return tuple(_to_float(value[index]) for index in range(6))  # type: ignore[return-value]
    except Exception:
        pass
    return (1, 0, 0, 1, 0, 0)


def _text_operand_length(operands: object) -> int:
    if not operands:
        return 0
    value = operands[-1] if len(operands) > 1 else operands[0]
    if isinstance(value, (str, bytes, pikepdf.String)):
        return len(str(value))
    if isinstance(value, pikepdf.Array):
        return sum(len(str(item)) for item in value if isinstance(item, (str, bytes, pikepdf.String)))
    return 1


def _estimated_text_rect(
    matrix: tuple[float, float, float, float, float, float],
    *,
    text_length: int,
) -> fitz.Rect:
    x, y = _point(matrix)
    font_height = max(abs(matrix[3]), abs(matrix[1]), MIN_TEXT_BOX_HEIGHT_PT)
    char_width = max(abs(matrix[0]) * 0.5, 1.0)
    width = max(char_width, min(DEFAULT_TEXT_ADVANCE_PT, char_width * max(text_length, 1)))
    return fitz.Rect(x, y - font_height * 0.35, x + width, y + font_height * 1.05)


def _page_text_rects(
    *,
    page_height: float,
    translated_items: list[dict],
    op_mode: BBoxTextOpMode = "strip",
) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    protected_formula_rects = _page_formula_rects(page_height=page_height, translated_items=translated_items)
    for item in translated_items:
        if not _should_strip_item_text(item):
            continue
        bbox = item.get("bbox", [])
        if len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (_to_float(value) for value in bbox)
        rect = fitz.Rect(x0, page_height - y1, x1, page_height - y0)
        if rect.is_empty:
            continue
        if op_mode == "hide":
            width = max(0.0, rect.x1 - rect.x0)
            height = max(0.0, rect.y1 - rect.y0)
            expand_x = min(3.0, max(1.0, width * 0.012))
            expand_y = min(2.0, max(0.75, height * 0.008))
            rect = rect + (-expand_x, -expand_y, expand_x, expand_y)
        protected_rects = _split_rect_away_from_formulas(rect, protected_formula_rects)
        for protected_rect in protected_rects:
            if not protected_rect.is_empty:
                if op_mode == "hide":
                    rects.append(protected_rect)
                else:
                    rects.append(protected_rect + (-1.0, -1.0, 1.0, 1.0))
    return merge_rects(rects)


def _page_formula_rects(
    *,
    page_height: float,
    translated_items: list[dict],
) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for item in translated_items:
        if item_block_kind(item) != "formula":
            continue
        bbox = item.get("bbox", [])
        if len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (_to_float(value) for value in bbox)
        rect = fitz.Rect(x0, page_height - y1, x1, page_height - y0)
        if not rect.is_empty:
            rects.append(rect)
    return rects


def _expanded_formula_rects(formula_rects: list[fitz.Rect]) -> list[fitz.Rect]:
    return [
        fitz.Rect(
            rect.x0 - FORMULA_PROTECTION_GAP_PT,
            rect.y0 - FORMULA_PROTECTION_GAP_PT,
            rect.x1 + FORMULA_PROTECTION_GAP_PT,
            rect.y1 + FORMULA_PROTECTION_GAP_PT,
        )
        for rect in formula_rects
        if not rect.is_empty
    ]


def _x_overlap_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
    overlap = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    width = max(1.0, min(left.width, right.width))
    return overlap / width


def _split_rect_away_from_formulas(rect: fitz.Rect, formula_rects: list[fitz.Rect]) -> list[fitz.Rect]:
    protected_segments = [fitz.Rect(rect)]
    for formula in formula_rects:
        next_segments: list[fitz.Rect] = []
        formula_guard = fitz.Rect(
            formula.x0,
            formula.y0 - FORMULA_PROTECTION_GAP_PT,
            formula.x1,
            formula.y1 + FORMULA_PROTECTION_GAP_PT,
        )
        for segment in protected_segments:
            if _x_overlap_ratio(segment, formula) < FORMULA_PROTECTION_X_OVERLAP_RATIO:
                next_segments.append(segment)
                continue
            if (segment & formula_guard).is_empty:
                next_segments.append(segment)
                continue
            upper = fitz.Rect(segment.x0, segment.y0, segment.x1, min(segment.y1, formula_guard.y0))
            lower = fitz.Rect(segment.x0, max(segment.y0, formula_guard.y1), segment.x1, segment.y1)
            if upper.height >= MIN_TEXT_BOX_HEIGHT_PT and upper.width > 0:
                next_segments.append(upper)
            if lower.height >= MIN_TEXT_BOX_HEIGHT_PT and lower.width > 0:
                next_segments.append(lower)
        protected_segments = next_segments
        if not protected_segments:
            break
    return [segment for segment in protected_segments if not segment.is_empty]


def _shrink_rect_away_from_formulas(rect: fitz.Rect, formula_rects: list[fitz.Rect]) -> fitz.Rect:
    protected_segments = _split_rect_away_from_formulas(rect, formula_rects)
    if not protected_segments:
        return fitz.Rect()
    if len(protected_segments) == 1:
        return protected_segments[0]
    largest = max(protected_segments, key=lambda segment: segment.get_area())
    return largest


def _shrink_rect_away_from_formulas_legacy(rect: fitz.Rect, formula_rects: list[fitz.Rect]) -> fitz.Rect:
    protected = fitz.Rect(rect)
    for formula in formula_rects:
        if _x_overlap_ratio(protected, formula) < FORMULA_PROTECTION_X_OVERLAP_RATIO:
            continue
        gap_below = protected.y0 - formula.y1
        if 0 <= gap_below <= FORMULA_PROTECTION_GAP_PT:
            protected.y0 = max(protected.y0, formula.y1 + FORMULA_PROTECTION_GAP_PT)
        gap_above = formula.y0 - protected.y1
        if 0 <= gap_above <= FORMULA_PROTECTION_GAP_PT:
            protected.y1 = min(protected.y1, formula.y0 - FORMULA_PROTECTION_GAP_PT)
    if protected.y1 <= protected.y0 or protected.x1 <= protected.x0:
        return fitz.Rect()
    return protected


def _page_item_rects(translated_items: list[dict]) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for item in translated_items:
        if not _should_strip_item_text(item):
            continue
        bbox = item.get("bbox", [])
        if len(bbox) != 4:
            continue
        rect = fitz.Rect(_to_float(bbox[0]), _to_float(bbox[1]), _to_float(bbox[2]), _to_float(bbox[3]))
        if not rect.is_empty:
            rects.append(rect)
    return merge_rects(rects)


def _item_render_text(item: dict) -> str:
    return str(
        item.get("protected_translated_text")
        or item.get("translated_text")
        or item.get("render_text")
        or ""
    ).strip()


def _item_has_renderable_source_text(item: dict) -> bool:
    return bool(
        str(
            item.get("translation_unit_protected_source_text")
            or item.get("protected_source_text")
            or item.get("source_text")
            or ""
        ).strip()
    )


def _should_strip_item_text(item: dict) -> bool:
    return item_block_kind(item) == "text" and (bool(_item_render_text(item)) or _item_has_renderable_source_text(item))


def _page_bboxlog_stats(
    page: fitz.Page,
    target_rects: list[fitz.Rect],
) -> tuple[int, int]:
    try:
        bboxlog = page.get_bboxlog()
    except Exception:
        return 0, 0
    nontext_count = 0
    text_overlap_count = 0
    for entry in bboxlog:
        kind = str(entry[0])
        if "text" not in kind:
            nontext_count += 1
            continue
        if len(entry) < 2:
            continue
        try:
            text_rect = fitz.Rect(entry[1])
        except Exception:
            continue
        if any(not (text_rect & target_rect).is_empty for target_rect in target_rects):
            text_overlap_count += 1
    return nontext_count, text_overlap_count


def _page_content_stream_size(doc: fitz.Document, page: fitz.Page) -> int:
    try:
        content_xrefs = page.get_contents() or []
    except Exception:
        return 0
    total = 0
    for xref in content_xrefs:
        try:
            total += len(doc.xref_stream(xref) or b"")
        except Exception:
            continue
        if total >= BBOX_TEXT_STRIP_CONTENT_STREAM_SIZE_THRESHOLD:
            return total
    return total


def _xobject_dict(container: pikepdf.Page | pikepdf.Object) -> object | None:
    try:
        resources = container.obj.get(Name("/Resources")) if isinstance(container, pikepdf.Page) else container.get(Name("/Resources"))
        if resources is None:
            return None
        return resources.get(Name("/XObject"))
    except Exception:
        return None


def _strip_bbox_text_from_stream(
    stream_obj: pikepdf.Page | pikepdf.Object,
    rects: list[fitz.Rect],
    *,
    protected_rects: list[fitz.Rect] | None = None,
    op_mode: BBoxTextOpMode = "strip",
    recurse_forms: bool = True,
    initial_ctm: tuple[float, float, float, float, float, float] = (1, 0, 0, 1, 0, 0),
    visited_forms: set[tuple[int, int]] | None = None,
) -> tuple[bytes | None, int, int]:
    instructions = list(pikepdf.parse_content_stream(stream_obj))
    if not instructions or not rects:
        return None, 0, 0

    output: list[tuple] = []
    protected_rects = protected_rects or []
    removed = 0
    forms_changed = 0
    ctm: tuple[float, float, float, float, float, float] = initial_ctm
    ctm_stack: list[tuple[float, float, float, float, float, float]] = []
    text_matrix: tuple[float, float, float, float, float, float] = (1, 0, 0, 1, 0, 0)
    line_matrix: tuple[float, float, float, float, float, float] = (1, 0, 0, 1, 0, 0)
    leading = 0.0
    text_render_mode = TEXT_DEFAULT_RENDER_MODE
    render_mode_stack: list[int] = []

    xobjects = _xobject_dict(stream_obj)

    def move_text(tx: float, ty: float) -> None:
        nonlocal text_matrix, line_matrix
        move = (1, 0, 0, 1, tx, ty)
        line_matrix = _mul(line_matrix, move)
        text_matrix = line_matrix

    def advance_text(operands: object) -> None:
        nonlocal text_matrix
        text_length = _text_operand_length(operands)
        font_size = max(abs(text_matrix[0]), 1.0)
        tx = min(DEFAULT_TEXT_ADVANCE_PT, max(1.0, text_length * font_size * 0.5))
        text_matrix = _mul(text_matrix, (1, 0, 0, 1, tx / font_size, 0))

    for operands, operator in instructions:
        op = str(operator)
        if op == "q":
            ctm_stack.append(ctm)
            render_mode_stack.append(text_render_mode)
            output.append((operands, operator))
            continue
        if op == "Q":
            ctm = ctm_stack.pop() if ctm_stack else (1, 0, 0, 1, 0, 0)
            text_render_mode = render_mode_stack.pop() if render_mode_stack else TEXT_DEFAULT_RENDER_MODE
            output.append((operands, operator))
            continue
        if op == "cm":
            matrix = _matrix_from_operands(operands)
            if matrix is not None:
                ctm = _mul(ctm, matrix)
            output.append((operands, operator))
            continue
        if op == "Do" and operands:
            xobject_name = operands[0]
            xobject = None
            if xobjects is not None:
                try:
                    xobject = xobjects.get(xobject_name)
                except Exception:
                    xobject = None
            if recurse_forms and xobject is not None and str(xobject.get(Name("/Subtype"))) == "/Form":
                objgen = getattr(xobject, "objgen", None)
                form_key = tuple(objgen) if objgen is not None else (id(xobject), 0)
                if visited_forms is None:
                    visited_forms = set()
                if form_key not in visited_forms:
                    visited_forms.add(form_key)
                    form_matrix = _matrix_from_object(xobject.get(Name("/Matrix"), []))
                    form_content, form_removed, nested_forms_changed = _strip_bbox_text_from_stream(
                        xobject,
                        rects,
                        protected_rects=protected_rects,
                        op_mode=op_mode,
                        recurse_forms=recurse_forms,
                        initial_ctm=_mul(ctm, form_matrix),
                        visited_forms=visited_forms,
                    )
                    if form_content and form_removed > 0:
                        xobject.write(form_content)
                        forms_changed += 1
                        removed += form_removed
                    forms_changed += nested_forms_changed
                    visited_forms.remove(form_key)
            output.append((operands, operator))
            continue
        if op == "BT":
            text_matrix = (1, 0, 0, 1, 0, 0)
            line_matrix = text_matrix
            output.append((operands, operator))
            continue
        if op == "Tm":
            matrix = _matrix_from_operands(operands)
            if matrix is not None:
                text_matrix = matrix
                line_matrix = matrix
            output.append((operands, operator))
            continue
        if op in {"Td", "TD"} and len(operands) >= 2:
            tx = _to_float(operands[0])
            ty = _to_float(operands[1])
            if op == "TD":
                leading = -ty
            move_text(tx, ty)
            output.append((operands, operator))
            continue
        if op == "TL" and operands:
            leading = _to_float(operands[0])
            output.append((operands, operator))
            continue
        if op == "Tr" and operands:
            text_render_mode = int(_to_float(operands[0], TEXT_DEFAULT_RENDER_MODE))
            output.append((operands, operator))
            continue
        if op == "T*":
            move_text(0, -leading)
            output.append((operands, operator))
            continue
        if op in {"'", '"'}:
            move_text(0, -leading)

        if op in TEXT_SHOW_OPERATORS:
            user_matrix = _mul(ctm, text_matrix)
            user_point = _point(user_matrix)
            text_rect = _estimated_text_rect(user_matrix, text_length=_text_operand_length(operands))
            should_remove = (
                _inside_any_rect(user_point[0], user_point[1], rects)
                or _intersects_any_rect(text_rect, rects)
            ) and not _is_protected_text_op(
                user_point=user_point,
                text_rect=text_rect,
                protected_rects=protected_rects,
            )
            advance_text(operands)
            if should_remove:
                removed += 1
                if op_mode == "hide":
                    output.append(([TEXT_INVISIBLE_RENDER_MODE], pikepdf.Operator("Tr")))
                    output.append((operands, operator))
                    output.append(([text_render_mode], pikepdf.Operator("Tr")))
                    continue
                continue

        output.append((operands, operator))

    if removed <= 0:
        return None, 0, forms_changed
    return pikepdf.unparse_content_stream(output), removed, forms_changed


def _strip_bbox_text_from_page(
    page: pikepdf.Page,
    rects: list[fitz.Rect],
    *,
    protected_rects: list[fitz.Rect] | None = None,
    op_mode: BBoxTextOpMode = "strip",
    recurse_forms: bool = True,
) -> tuple[bytes | None, int, int]:
    return _strip_bbox_text_from_stream(
        page,
        rects,
        protected_rects=protected_rects,
        op_mode=op_mode,
        recurse_forms=recurse_forms,
    )


def build_bbox_text_stripped_pdf_copy(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    candidates: BBoxTextStripCandidates | None = None,
    op_mode: BBoxTextOpMode = "strip",
    recurse_forms: bool | None = None,
) -> BBoxTextStripResult:
    if not translated_pages:
        return BBoxTextStripResult(changed=False)

    candidate_started = time.perf_counter()
    candidates = candidates or build_bbox_text_strip_candidates(
        source_pdf_path=source_pdf_path,
        translated_pages=translated_pages,
        op_mode=op_mode,
    )
    page_rects = candidates.fitz_page_rects()
    page_protected_rects = candidates.fitz_page_protected_rects()
    skipped_complex = candidates.pages_skipped_complex
    skipped_no_text_overlap = candidates.pages_skipped_no_text_overlap
    skipped_complex_page_indices = candidates.skipped_complex_page_indices
    skipped_no_text_overlap_page_indices = candidates.skipped_no_text_overlap_page_indices
    candidate_elapsed = time.perf_counter() - candidate_started

    if not page_rects:
        return BBoxTextStripResult(
            changed=False,
            pages_skipped_complex=skipped_complex,
            pages_skipped_no_text_overlap=skipped_no_text_overlap,
            skipped_complex_page_indices=frozenset(skipped_complex_page_indices),
            skipped_no_text_overlap_page_indices=frozenset(skipped_no_text_overlap_page_indices),
        )

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    copy_started = time.perf_counter()
    shutil.copy2(source_pdf_path, output_pdf_path)
    copy_elapsed = time.perf_counter() - copy_started

    pages_changed = 0
    changed_page_indices: set[int] = set()
    removed_total = 0
    forms_changed_total = 0
    parse_elapsed = 0.0
    save_elapsed = 0.0
    effective_recurse_forms = op_mode != "hide" if recurse_forms is None else recurse_forms
    with pikepdf.Pdf.open(output_pdf_path, allow_overwriting_input=True) as pdf:
        for page_idx, rects in page_rects.items():
            parse_started = time.perf_counter()
            content_stream, removed, forms_changed = _strip_bbox_text_from_page(
                pdf.pages[page_idx],
                rects,
                protected_rects=page_protected_rects.get(page_idx, []),
                op_mode=op_mode,
                recurse_forms=effective_recurse_forms,
            )
            parse_elapsed += time.perf_counter() - parse_started
            forms_changed_total += forms_changed
            if not content_stream or removed <= 0:
                if forms_changed > 0:
                    pages_changed += 1
                    changed_page_indices.add(page_idx)
                    removed_total += removed
                continue
            pdf.pages[page_idx].obj[Name("/Contents")] = pdf.make_stream(content_stream)
            pages_changed += 1
            changed_page_indices.add(page_idx)
            removed_total += removed

        if pages_changed <= 0:
            output_pdf_path.unlink(missing_ok=True)
            return BBoxTextStripResult(
                changed=False,
                pages_skipped_complex=skipped_complex,
                pages_skipped_no_text_overlap=skipped_no_text_overlap,
                skipped_complex_page_indices=frozenset(skipped_complex_page_indices),
                skipped_no_text_overlap_page_indices=frozenset(skipped_no_text_overlap_page_indices),
            )

        save_started = time.perf_counter()
        pdf.save(
            output_pdf_path,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            compress_streams=True,
            recompress_flate=False,
        )
        save_elapsed = time.perf_counter() - save_started

    print(
        f"bbox text strip: mode={op_mode} pages={pages_changed} text_show_ops={removed_total} "
        f"forms={forms_changed_total} skipped_complex_pages={skipped_complex} "
        f"skipped_no_text_overlap_pages={skipped_no_text_overlap} "
        f"copy={copy_elapsed:.2f}s candidates={candidate_elapsed:.2f}s parse={parse_elapsed:.2f}s save={save_elapsed:.2f}s "
        f"output={output_pdf_path}",
        flush=True,
    )
    return BBoxTextStripResult(
        changed=True,
        output_pdf_path=output_pdf_path,
        pages_changed=pages_changed,
        text_show_ops_removed=removed_total,
        pages_skipped_complex=skipped_complex,
        pages_skipped_no_text_overlap=skipped_no_text_overlap,
        forms_changed=forms_changed_total,
        changed_page_indices=frozenset(changed_page_indices),
        skipped_complex_page_indices=frozenset(skipped_complex_page_indices),
        skipped_no_text_overlap_page_indices=frozenset(skipped_no_text_overlap_page_indices),
    )
