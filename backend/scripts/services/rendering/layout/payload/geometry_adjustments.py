from __future__ import annotations

from statistics import median

from services.rendering.layout.font_roles import is_title_like_block
from services.rendering.layout.typography.geometry import inner_bbox


BODY_TIGHT_GAP_MAX_INSET_RATIO = 0.03
BODY_TIGHT_GAP_MIN_INSET_PT = 0.35
BODY_TIGHT_GAP_MIN_TARGET_PT = 1.2
BODY_TIGHT_GAP_MAX_TARGET_PT = 4.0
TITLE_BODY_LEFT_TOLERANCE_PT = 18.0
TITLE_BODY_WIDTH_MAX_SCALE = 1.18


def build_effective_inner_bboxes(
    translated_items: list[dict],
    *,
    body_flags: dict[int, bool],
    page_width: float | None,
) -> dict[int, list[float]]:
    effective = {
        index: list(cached_inner if cached_inner is not None else inner)
        for index, item in enumerate(translated_items)
        if len(inner := inner_bbox(item)) == 4
        if (cached_inner := _cached_render_inner_bbox(item)) is None or len(cached_inner) == 4
    }
    if not effective:
        return effective

    locked_indices = {
        index
        for index, item in enumerate(translated_items)
        if _cached_render_inner_bbox(item) is not None
    }
    _apply_body_tight_gap_inset(effective, body_flags=body_flags, page_width=page_width, locked_indices=locked_indices)
    _apply_title_body_width_alignment(
        effective,
        translated_items,
        body_flags=body_flags,
        page_width=page_width,
        locked_indices=locked_indices,
    )
    return effective


def _cached_render_inner_bbox(item: dict) -> list[float] | None:
    bbox = item.get("_render_inner_bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            return [float(value) for value in bbox]
        except Exception:
            return None
    return None


def _apply_body_tight_gap_inset(
    effective: dict[int, list[float]],
    *,
    body_flags: dict[int, bool],
    page_width: float | None,
    locked_indices: set[int],
) -> None:
    body_indices = [index for index in effective if body_flags.get(index)]
    if len(body_indices) < 2:
        return

    heights = [max(0.0, effective[index][3] - effective[index][1]) for index in body_indices]
    median_height = median([height for height in heights if height > 0.0] or [0.0])
    if median_height <= 0:
        return
    target_gap = min(BODY_TIGHT_GAP_MAX_TARGET_PT, max(BODY_TIGHT_GAP_MIN_TARGET_PT, median_height * 0.08))

    ordered = sorted(body_indices, key=lambda index: (effective[index][1], effective[index][0]))
    for position, current_index in enumerate(ordered):
        if current_index in locked_indices:
            continue
        current = effective[current_index]
        nxt = _next_same_column_box(current, ordered[position + 1 :], effective, page_width=page_width)
        if nxt is None:
            continue
        gap = nxt[1] - current[3]
        if gap <= -target_gap or gap >= target_gap:
            continue

        tightness = min(1.0, (target_gap - gap) / max(target_gap, 0.01))
        current_height = max(0.0, current[3] - current[1])
        if current_height <= 0:
            continue
        total_inset = current_height * BODY_TIGHT_GAP_MAX_INSET_RATIO * tightness
        if total_inset < BODY_TIGHT_GAP_MIN_INSET_PT:
            continue
        inset_each_side = min(current_height * 0.08, total_inset / 2.0)
        if inset_each_side > 0.0 and current_height - inset_each_side * 2.0 >= 8.0:
            current[1] = round(current[1] + inset_each_side, 3)
            current[3] = round(current[3] - inset_each_side, 3)


def _next_same_column_box(
    current: list[float],
    later_indices: list[int],
    effective: dict[int, list[float]],
    *,
    page_width: float | None,
) -> list[float] | None:
    for index in later_indices:
        candidate = effective[index]
        if _same_text_column(current, candidate, page_width=page_width):
            return candidate
    return None


def _apply_title_body_width_alignment(
    effective: dict[int, list[float]],
    translated_items: list[dict],
    *,
    body_flags: dict[int, bool],
    page_width: float | None,
    locked_indices: set[int],
) -> None:
    body_boxes = [effective[index] for index in effective if body_flags.get(index)]
    if not body_boxes:
        return

    for index, item in enumerate(translated_items):
        if index not in effective or not is_title_like_block(item):
            continue
        if index in locked_indices:
            continue
        title = effective[index]
        title_width = max(0.0, title[2] - title[0])
        if title_width <= 0.0:
            continue
        candidates = [
            body
            for body in body_boxes
            if body[1] >= title[1]
            and abs(body[0] - title[0]) <= TITLE_BODY_LEFT_TOLERANCE_PT
            and body[2] > title[2]
        ]
        if not candidates:
            continue
        target_right = max(body[2] for body in candidates)
        if page_width and page_width > 0:
            target_right = min(target_right, page_width - 4.0)
        max_right = title[0] + title_width * TITLE_BODY_WIDTH_MAX_SCALE
        title[2] = round(max(title[2], min(target_right, max_right)), 3)


def _same_text_column(first: list[float], second: list[float], *, page_width: float | None) -> bool:
    first_width = max(1.0, first[2] - first[0])
    second_width = max(1.0, second[2] - second[0])
    overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    if overlap >= min(first_width, second_width) * 0.55:
        return True
    tolerance = max(18.0, (page_width or 0.0) * 0.035)
    return abs(first[0] - second[0]) <= tolerance


__all__ = ["build_effective_inner_bboxes"]
