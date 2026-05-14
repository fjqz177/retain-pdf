from __future__ import annotations

from services.rendering.layout.payload.collision_context import adjacent_collision_context
from services.rendering.layout.payload.collision_context import collision_fit_item
from services.rendering.layout.payload.metrics import estimated_render_height_pt
from services.rendering.layout.payload.fit_vertical import fit_block_to_vertical_limit


VERTICAL_COLLISION_TRIGGER_RATIO = 0.9


def mark_adjacent_collision_risk(ordered_payloads: list[dict]) -> None:
    for current, nxt in zip(ordered_payloads, ordered_payloads[1:]):
        context = adjacent_collision_context(current, nxt)
        if context is None:
            continue

        estimated_height = estimated_render_height_pt(
            current["inner_bbox"],
            current["translated_text"],
            current["formula_map"],
            current["font_size_pt"],
            current["leading_em"],
        )
        if estimated_height <= context.max_height_pt * VERTICAL_COLLISION_TRIGGER_RATIO:
            continue

        current["adjacent_collision_risk"] = True
        fitted_font_size, fitted_leading = fit_block_to_vertical_limit(
            collision_fit_item(current),
            current["translated_text"],
            current["formula_map"],
            current["font_size_pt"],
            current["leading_em"],
            context.max_height_pt,
            page_body_font_size_pt=current["page_body_font_size_pt"],
        )
        current["font_size_pt"] = fitted_font_size
        current["leading_em"] = fitted_leading
        current["prefer_typst_fit"] = True
        previous_limit = current.get("adjacent_available_height_pt")
        if previous_limit is None or context.max_height_pt < previous_limit:
            current["adjacent_available_height_pt"] = max(6.0, context.max_height_pt)
