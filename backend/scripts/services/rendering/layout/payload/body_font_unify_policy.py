from __future__ import annotations

from services.rendering.layout.payload.body_common import BODY_CONTEXT_MIN_ANCHORS
from services.rendering.layout.payload.body_common import body_context_anchors
from services.rendering.layout.payload.body_common import is_body_context_text_payload
from services.rendering.layout.payload.body_common import same_body_column


BODY_SIMILAR_FONT_UNIFY_MAX_RATIO = 1.10


def unify_similar_body_fonts(
    body_payloads: list[dict],
    all_payloads: list[dict],
    *,
    page_text_width_med: float,
) -> None:
    anchors = body_context_anchors(body_payloads, page_text_width_med=page_text_width_med)
    if len(anchors) < BODY_CONTEXT_MIN_ANCHORS:
        return
    eligible_payloads = [
        payload
        for payload in all_payloads
        if is_body_context_text_payload(payload)
        and float(payload.get("font_size_pt") or 0.0) > 0
        and sum(1 for anchor in anchors if same_body_column(payload, anchor, page_text_width_med=page_text_width_med))
        >= BODY_CONTEXT_MIN_ANCHORS
    ]
    if len(eligible_payloads) < 2:
        return

    min_font = min(float(payload["font_size_pt"]) for payload in eligible_payloads)
    max_font = max(float(payload["font_size_pt"]) for payload in eligible_payloads)
    if min_font <= 0 or max_font / min_font > BODY_SIMILAR_FONT_UNIFY_MAX_RATIO:
        return

    unified_font = round(min_font, 2)
    for payload in eligible_payloads:
        if payload["font_size_pt"] <= unified_font:
            continue
        payload["font_size_pt"] = unified_font
        floor = float(payload.get("_short_body_inherited_font_floor_pt") or 0.0)
        if floor > 0:
            payload["_short_body_inherited_font_floor_pt"] = round(min(floor, unified_font), 2)
