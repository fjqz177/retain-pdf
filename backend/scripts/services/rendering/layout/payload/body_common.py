from __future__ import annotations

from statistics import median

from services.document_schema.semantics import is_bodylike_block
from services.document_schema.semantics import is_caption_like_block
from services.document_schema.semantics import is_footnote_like_block
from services.rendering.layout.payload.body_context import BODY_DENSITY_TARGET_MAX
from services.rendering.layout.payload.body_context import payload_center_x
from services.rendering.layout.payload.metrics import estimated_render_height_pt
from services.rendering.layout.payload.metrics import estimated_required_lines
from services.rendering.layout.payload.metrics import text_demand_units
from services.translation.item_reader import item_block_kind


BODY_DENSITY_TARGET_MIN = 0.82
SHORT_BODY_INHERIT_MAX_HEIGHT_PT = 16.0
SHORT_BODY_INHERIT_LEFT_TOLERANCE_PT = 22.0
SHORT_BODY_INHERIT_CENTER_TOLERANCE_RATIO = 0.18
BODY_CONTEXT_MIN_ANCHORS = 2


def payload_density(payload: dict, *, font_size_pt: float | None = None, leading_em: float | None = None) -> float:
    inner_height = max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])
    estimated_height = estimated_render_height_pt(
        payload["inner_bbox"],
        payload["translated_text"],
        payload["formula_map"],
        font_size_pt if font_size_pt is not None else payload["font_size_pt"],
        leading_em if leading_em is not None else payload["leading_em"],
    )
    return estimated_height / inner_height


def payload_width(payload: dict) -> float:
    return max(0.0, payload["inner_bbox"][2] - payload["inner_bbox"][0])


def payload_height(payload: dict) -> float:
    return max(0.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])


def required_lines(payload: dict) -> int:
    inner = payload.get("inner_bbox") or []
    font_size = float(payload.get("font_size_pt") or 0.0)
    if len(inner) != 4 or font_size <= 0:
        return 1
    return estimated_required_lines(
        inner,
        payload.get("translated_text", ""),
        payload.get("formula_map", []),
        font_size,
    )


def resolve_body_targets(body_payloads: list[dict]) -> tuple[float, float, float]:
    stable_body_fonts = [
        payload["font_size_pt"]
        for payload in body_payloads
        if not payload["dense_small_box"] and not payload["heavy_dense_small_box"]
    ]
    body_font_median = median(stable_body_fonts or [payload["font_size_pt"] for payload in body_payloads])
    for payload in body_payloads:
        payload["page_body_font_size_pt"] = round(body_font_median, 2)

    body_density_values = []
    body_pressure_values = []
    for payload in body_payloads:
        inner_height = max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])
        inner_width = max(8.0, payload["inner_bbox"][2] - payload["inner_bbox"][0])
        demand = text_demand_units(payload["translated_text"], payload["formula_map"])
        estimated_height = estimated_render_height_pt(
            payload["inner_bbox"],
            payload["translated_text"],
            payload["formula_map"],
            payload["font_size_pt"],
            payload["leading_em"],
        )
        body_density_values.append(estimated_height / inner_height)
        body_pressure_values.append(demand / max(1.0, inner_width * inner_height))

    body_density_target = median(body_density_values) if body_density_values else 0.72
    body_density_target = max(BODY_DENSITY_TARGET_MIN, min(BODY_DENSITY_TARGET_MAX, body_density_target))
    body_pressure_median = median(body_pressure_values) if body_pressure_values else 0.0
    return body_font_median, body_density_target, body_pressure_median


def same_body_column(payload: dict, anchor: dict, *, page_text_width_med: float) -> bool:
    left_delta = abs(payload["inner_bbox"][0] - anchor["inner_bbox"][0])
    center_delta = abs(payload_center_x(payload) - payload_center_x(anchor))
    width_ref = max(page_text_width_med, payload_width(anchor), 1.0)
    return (
        left_delta <= SHORT_BODY_INHERIT_LEFT_TOLERANCE_PT
        or center_delta <= width_ref * SHORT_BODY_INHERIT_CENTER_TOLERANCE_RATIO
    )


def is_body_context_text_payload(payload: dict) -> bool:
    if payload["render_kind"] != "markdown":
        return False
    if payload.get("title_fit") is not None:
        return False
    item = payload.get("item") or {}
    if is_caption_like_block(item) or is_footnote_like_block(item):
        return False
    return payload["is_body"] or item_block_kind(item) == "text" or is_bodylike_block(item)


def body_context_anchors(body_payloads: list[dict], *, page_text_width_med: float) -> list[dict]:
    return [
        payload
        for payload in body_payloads
        if payload_width(payload) >= max(1.0, page_text_width_med * 0.72)
        and payload_height(payload) >= 18.0
    ]
