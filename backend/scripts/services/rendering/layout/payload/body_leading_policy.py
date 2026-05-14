from __future__ import annotations

from services.rendering.layout.payload.body_leading_solver import solve_body_leading


def restore_comfort_body_leading(body_payloads: list[dict]) -> None:
    for payload in body_payloads:
        if not _eligible_for_body_leading(payload):
            continue
        solution = solve_body_leading(payload)
        if solution is None:
            continue
        if payload["leading_em"] >= solution.leading_em:
            continue
        payload["leading_em"] = solution.leading_em
        payload["_body_dynamic_leading_cap_em"] = solution.leading_cap_em
        payload["_body_leading_target_density"] = solution.target_density


def _eligible_for_body_leading(payload: dict) -> bool:
    if payload["render_kind"] != "markdown":
        return False
    if payload["dense_small_box"] or payload["heavy_dense_small_box"] or payload["prefer_typst_fit"]:
        return False
    return True
