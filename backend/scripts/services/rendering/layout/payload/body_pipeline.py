from __future__ import annotations

from collections.abc import Callable
from statistics import median

from services.rendering.layout.payload.body_common import resolve_body_targets
from services.rendering.layout.payload import body_policy_facade as body_policy


BodyStage = Callable[..., None]
BODY_PRE_GROW_STAGES: tuple[BodyStage, ...] = (
    body_policy.tighten_body_payloads,
    body_policy.mark_force_fit_dense_outliers,
)
BODY_POST_GROW_STAGES: tuple[BodyStage, ...] = (
    body_policy.inherit_short_body_fonts,
    body_policy.unify_similar_body_fonts,
    body_policy.inherit_low_height_body_fonts,
    body_policy.relax_short_body_context_heights,
    body_policy.grow_underfilled_body_payloads,
    body_policy.harmonize_underfilled_body_fonts,
    body_policy.restore_comfort_body_leading,
    body_policy.harmonize_long_body_payloads,
    body_policy.smooth_adjacent_body_payloads,
)


def _run_stage(
    stage: BodyStage,
    body_payloads: list[dict],
    *,
    body_font_median: float,
    body_density_target: float,
    body_pressure_median: float,
    ordered_payloads: list[dict],
    page_text_width_med: float,
) -> None:
    stage(
        body_payloads,
        body_font_median=body_font_median,
        body_density_target=body_density_target,
        body_pressure_median=body_pressure_median,
        ordered_payloads=ordered_payloads,
        page_text_width_med=page_text_width_med,
    )


def apply_body_payload_pipeline(ordered_payloads: list[dict], *, page_text_width_med: float) -> None:
    body_payloads = [payload for payload in ordered_payloads if payload["is_body"]]
    if not body_payloads:
        return

    body_font_median, body_density_target, body_pressure_median = resolve_body_targets(body_payloads)
    for stage in BODY_PRE_GROW_STAGES:
        _run_stage(
            stage,
            body_payloads,
            body_font_median=body_font_median,
            body_density_target=body_density_target,
            body_pressure_median=body_pressure_median,
            ordered_payloads=ordered_payloads,
            page_text_width_med=page_text_width_med,
        )

    body_font_median = median(payload["font_size_pt"] for payload in body_payloads)
    for stage in BODY_POST_GROW_STAGES:
        _run_stage(
            stage,
            body_payloads,
            body_font_median=body_font_median,
            body_density_target=body_density_target,
            body_pressure_median=body_pressure_median,
            ordered_payloads=ordered_payloads,
            page_text_width_med=page_text_width_med,
        )
