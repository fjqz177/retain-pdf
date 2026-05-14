from __future__ import annotations

from pathlib import Path

import fitz

from services.rendering.layout.payload.prepare import prepare_render_payloads_by_page
from services.rendering.layout.payload.blocks import build_render_blocks
from services.rendering.layout.model.models import RenderLayoutBlock
from services.rendering.layout.model.models import RenderPageSpec
from services.rendering.layout.title_fit import apply_title_fit_budget_to_render_blocks


def _layout_block_from_render_block(block, *, page_index: int) -> RenderLayoutBlock:
    return RenderLayoutBlock(
        block_id=f"item-{block.source_item_id}" if block.source_item_id else block.block_id,
        page_index=page_index,
        background_rect=list(block.cover_bbox),
        content_rect=list(block.inner_bbox),
        content_kind=block.render_kind,
        content_text=block.plain_text if block.render_kind == "plain" else block.markdown_text,
        plain_text=block.plain_text,
        math_map=list(block.math_map if hasattr(block, "math_map") else []),
        font_size_pt=block.font_size_pt,
        leading_em=block.leading_em,
        font_weight=block.font_weight,
        fit_to_box=block.fit_to_box,
        fit_single_line=block.fit_single_line,
        fit_min_font_size_pt=block.fit_min_font_size_pt,
        fit_max_font_size_pt=block.fit_max_font_size_pt,
        fit_min_leading_em=block.fit_min_leading_em,
        fit_max_height_pt=block.fit_max_height_pt,
        fit_target_width_pt=block.fit_target_width_pt,
        fit_target_height_pt=block.fit_target_height_pt,
        fit_shift_up_pt=block.fit_shift_up_pt,
        first_line_indent_pt=block.first_line_indent_pt,
        justify_text=block.justify_text,
        skip_reason=block.skip_reason,
    )


def _layout_page_spec(
    *,
    page_index: int,
    page_width_pt: float,
    page_height_pt: float,
    items: list[dict],
    background_pdf_path: Path | None,
) -> RenderPageSpec:
    blocks = [
        _layout_block_from_render_block(block, page_index=page_index)
        for block in build_render_blocks(items, page_width=page_width_pt, page_height=page_height_pt)
    ]
    apply_title_fit_budget_to_render_blocks(
        blocks,
        page_width=page_width_pt,
        page_height=page_height_pt,
    )
    return RenderPageSpec(
        page_index=page_index,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        background_pdf_path=background_pdf_path,
        blocks=blocks,
    )


def build_render_page_specs(
    *,
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    background_pdf_path: Path | None = None,
    prepared: bool = False,
) -> list[RenderPageSpec]:
    prepared_pages = translated_pages if prepared else prepare_render_payloads_by_page(translated_pages)
    source_doc = fitz.open(source_pdf_path)
    try:
        page_specs: list[RenderPageSpec] = []
        for page_index in sorted(page_idx for page_idx in prepared_pages if 0 <= page_idx < len(source_doc)):
            page = source_doc[page_index]
            page_specs.append(
                _layout_page_spec(
                    page_index=page_index,
                    page_width_pt=page.rect.width,
                    page_height_pt=page.rect.height,
                    items=prepared_pages[page_index],
                    background_pdf_path=background_pdf_path,
                )
            )
        return page_specs
    finally:
        source_doc.close()
