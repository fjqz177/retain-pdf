from __future__ import annotations

from math import exp
from statistics import median

from services.rendering.layout.payload.body_common import body_context_anchors
from services.rendering.layout.payload.body_common import is_body_context_text_payload
from services.rendering.layout.payload.body_common import payload_density
from services.rendering.layout.payload.body_common import required_lines
from services.rendering.layout.payload.body_common import same_body_column


BODY_UNDERFILLED_FONT_GROW_DENSITY_TRIGGER = 0.90
BODY_UNDERFILLED_FONT_GROW_DENSITY_LIMIT = 1.06
BODY_UNDERFILLED_FONT_GROW_MAX_PT = 2.35
BODY_UNDERFILLED_FONT_GROW_CONTEXT_BONUS_PT = 1.10
BODY_UNDERFILLED_FONT_GROW_PAGE_BONUS_PT = 1.25
BODY_UNDERFILLED_FONT_GROW_EXP_RATE = 4.8
BODY_UNDERFILLED_FONT_GROW_MAX_LINES = 8
BODY_UNDERFILLED_FONT_GROW_SHORT_LINE_BONUS = 0.28
BODY_UNDERFILLED_FONT_GROW_TALL_SLACK_BONUS = 0.55
BODY_UNDERFILLED_FONT_HARMONIZE_MAX_RATIO = 1.16


def grow_underfilled_body_payloads(
    body_payloads: list[dict],
    *,
    body_font_median: float,
    page_text_width_med: float,
) -> None:
    page_font_target = _page_font_target(body_payloads, body_font_median, page_text_width_med=page_text_width_med)
    page_underfill_ratio = _page_underfill_ratio(body_payloads)
    for payload in body_payloads:
        if not _is_underfilled_growth_candidate(payload):
            continue
        density = payload_density(payload)
        if density >= BODY_UNDERFILLED_FONT_GROW_DENSITY_TRIGGER:
            continue

        previous_font = float(payload["font_size_pt"])
        target_font = _target_font_for_payload(
            payload,
            page_font_target=page_font_target,
            density=density,
            page_underfill_ratio=page_underfill_ratio,
        )
        if target_font <= previous_font + 0.03:
            continue

        best = _largest_font_within_density(payload, previous_font, target_font)
        if best <= previous_font + 0.04:
            continue

        payload["_body_underfill_seed_font_pt"] = round(previous_font, 2)
        payload["font_size_pt"] = round(best, 2)
        payload["_body_underfill_font_grew_pt"] = round(payload["font_size_pt"] - previous_font, 2)
        payload["_body_underfill_font_slack_ratio"] = round(_density_slack_ratio(density), 3)


def harmonize_underfilled_body_fonts(
    body_payloads: list[dict],
    all_payloads: list[dict],
    *,
    page_text_width_med: float,
) -> None:
    anchors = body_context_anchors(body_payloads, page_text_width_med=page_text_width_med)
    if len(anchors) < 2:
        return
    eligible = [
        payload
        for payload in all_payloads
        if _is_underfilled_growth_candidate(payload)
        and is_body_context_text_payload(payload)
        and float(payload.get("font_size_pt") or 0.0) > 0
        and sum(1 for anchor in anchors if same_body_column(payload, anchor, page_text_width_med=page_text_width_med)) >= 2
    ]
    if len(eligible) < 2 or not any(payload.get("_body_underfill_font_grew_pt") for payload in eligible):
        return

    min_font = min(float(payload["font_size_pt"]) for payload in eligible)
    max_font = max(float(payload["font_size_pt"]) for payload in eligible)
    if min_font <= 0 or max_font / min_font > BODY_UNDERFILLED_FONT_HARMONIZE_MAX_RATIO:
        return

    target_font = median(float(payload["font_size_pt"]) for payload in eligible)
    for payload in eligible:
        previous_font = float(payload["font_size_pt"])
        if abs(previous_font - target_font) <= 0.04:
            continue
        if previous_font > target_font:
            payload["font_size_pt"] = round(target_font, 2)
        else:
            payload["font_size_pt"] = round(_largest_font_within_density(payload, previous_font, target_font), 2)
        seed_font = float(payload.get("_body_underfill_seed_font_pt") or previous_font)
        if payload["font_size_pt"] > seed_font:
            payload["_body_underfill_font_grew_pt"] = round(payload["font_size_pt"] - seed_font, 2)


def _page_font_target(body_payloads: list[dict], body_font_median: float, *, page_text_width_med: float) -> float:
    anchors = [
        payload
        for payload in body_context_anchors(body_payloads, page_text_width_med=page_text_width_med)
        if not payload["dense_small_box"] and not payload["heavy_dense_small_box"]
    ]
    if not anchors:
        return body_font_median
    return max(body_font_median, median(float(payload["font_size_pt"]) for payload in anchors))


def _is_underfilled_growth_candidate(payload: dict) -> bool:
    if payload["dense_small_box"] or payload["heavy_dense_small_box"]:
        return False
    if payload["render_kind"] != "markdown" or payload["prefer_typst_fit"]:
        return False
    return required_lines(payload) <= BODY_UNDERFILLED_FONT_GROW_MAX_LINES


def _target_font_for_payload(
    payload: dict,
    *,
    page_font_target: float,
    density: float,
    page_underfill_ratio: float,
) -> float:
    line_count = required_lines(payload)
    slack_ratio = _density_slack_ratio(density)
    growth_budget = BODY_UNDERFILLED_FONT_GROW_MAX_PT
    growth_budget += BODY_UNDERFILLED_FONT_GROW_SHORT_LINE_BONUS * _short_line_weight(line_count)
    growth_budget += BODY_UNDERFILLED_FONT_GROW_TALL_SLACK_BONUS * _height_slack_weight(payload, line_count)
    eased_growth = growth_budget * (1.0 - exp(-BODY_UNDERFILLED_FONT_GROW_EXP_RATE * slack_ratio))
    context_cap = page_font_target
    context_cap += BODY_UNDERFILLED_FONT_GROW_PAGE_BONUS_PT * page_underfill_ratio
    context_cap += BODY_UNDERFILLED_FONT_GROW_CONTEXT_BONUS_PT * slack_ratio
    return min(context_cap, float(payload["font_size_pt"]) + eased_growth)


def _largest_font_within_density(payload: dict, low: float, high: float) -> float:
    best = low
    density_limit = _density_limit_for_payload(payload)
    for _ in range(9):
        mid = (low + high) / 2.0
        if payload_density(payload, font_size_pt=mid) <= density_limit:
            best = mid
            low = mid
        else:
            high = mid
    return best


def _density_limit_for_payload(payload: dict) -> float:
    line_count = required_lines(payload)
    if line_count <= 4:
        return BODY_UNDERFILLED_FONT_GROW_DENSITY_LIMIT
    return min(BODY_UNDERFILLED_FONT_GROW_DENSITY_LIMIT, 1.00 + 0.01 * max(0, 8 - line_count))


def _page_underfill_ratio(body_payloads: list[dict]) -> float:
    densities = [
        payload_density(payload)
        for payload in body_payloads
        if not payload["dense_small_box"] and not payload["heavy_dense_small_box"]
    ]
    if not densities:
        return 0.0
    page_density = median(densities)
    return _density_slack_ratio(page_density)


def _density_slack_ratio(density: float) -> float:
    slack_ratio = (BODY_UNDERFILLED_FONT_GROW_DENSITY_TRIGGER - density) / max(
        0.01,
        BODY_UNDERFILLED_FONT_GROW_DENSITY_TRIGGER,
    )
    return max(0.0, min(1.0, slack_ratio))


def _short_line_weight(line_count: int) -> float:
    return max(0.0, min(1.0, (5.0 - float(line_count)) / 4.0))


def _height_slack_weight(payload: dict, line_count: int) -> float:
    inner = payload.get("inner_bbox") or []
    font_size = float(payload.get("font_size_pt") or 0.0)
    if len(inner) != 4 or font_size <= 0 or line_count <= 0:
        return 0.0
    height = max(8.0, float(inner[3]) - float(inner[1]))
    natural_height = font_size * max(1, line_count) * 1.1
    return max(0.0, min(1.0, (height - natural_height) / max(height, 1.0)))
