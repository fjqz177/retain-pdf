from __future__ import annotations

from dataclasses import dataclass
from math import exp

from services.rendering.layout.font_fit import BODY_LEADING_MAX
from services.rendering.layout.font_fit import BODY_LEADING_MIN
from services.rendering.layout.payload.body_common import payload_density
from services.rendering.layout.payload.body_common import required_lines
from services.rendering.layout.typography.measurement import local_line_pitch
from services.rendering.layout.typography.measurement import median_line_pitch
from services.rendering.layout.typography.measurement import source_visual_line_count


BODY_COMFORT_LEADING_MIN = 0.56
BODY_COMFORT_LEADING_DENSITY_MAX = 0.985
BODY_COMFORT_BASE_FILL = 0.74
BODY_COMFORT_TARGET_FILL_MAX = 0.94
BODY_COMFORT_LONG_LINE_THRESHOLD = 9
BODY_COMFORT_LONG_LEADING_MAX = 0.82
BODY_COMFORT_SOURCE_LINE_LEADING_MAX = 1.38
BODY_COMFORT_SOLVER_MAX_ITERATIONS = 6
BODY_COMFORT_SOLVER_DENSITY_TOLERANCE = 0.002
BODY_COMFORT_SOLVER_MIN_BRACKET_WIDTH = 0.005
BODY_COMFORT_SOLVER_EXTRAPOLATION_MIN_FRACTION = 0.12
BODY_COMFORT_SOLVER_EXTRAPOLATION_MAX_FRACTION = 0.88

# Target density is the fraction of the paragraph bbox height that translated
# text should occupy after line-spacing recovery.
BODY_COMFORT_SLACK_NORMALIZER = 0.38
BODY_COMFORT_SOURCE_LINE_RATIO_OFFSET = 1.0
BODY_COMFORT_SOURCE_LINE_RATIO_MAX_GAP = 4.0
BODY_COMFORT_SOURCE_LEADING_MAX_GAP = 1.0
BODY_COMFORT_LINE_COUNT_BASE = 2.0
BODY_COMFORT_LINE_COUNT_NORMALIZER = 12.0
BODY_COMFORT_SLACK_GAIN_MAX = 0.10
BODY_COMFORT_SOURCE_LINE_GAIN_MAX = 0.13
BODY_COMFORT_SOURCE_PITCH_GAIN_MAX = 0.05
BODY_COMFORT_MULTI_LINE_GAIN_MAX = 0.14
BODY_COMFORT_FONT_GROWTH_DISCOUNT_MAX = 0.035

# Exponential response rates. Larger values make that signal saturate faster.
BODY_COMFORT_SLACK_RESPONSE_RATE = 2.0
BODY_COMFORT_MULTI_LINE_WEIGHT_RATE = 0.42
BODY_COMFORT_SOURCE_LINE_RESPONSE_RATE = 0.78
BODY_COMFORT_SOURCE_PITCH_RESPONSE_RATE = 2.6
BODY_COMFORT_LINE_COUNT_RESPONSE_RATE = 1.6
BODY_COMFORT_LONG_LINE_CAP_RESPONSE_RATE = 0.38
BODY_COMFORT_SOURCE_LINE_CAP_RESPONSE_RATE = 0.7
BODY_COMFORT_SOURCE_PITCH_CAP_RESPONSE_RATE = 1.1

# Existing font growth means the font-size policy already spent part of the
# vertical slack. Discount the line-spacing target so both policies cooperate.
BODY_COMFORT_FONT_GROWTH_NORMALIZER_PT = 1.2


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _exp_response(value: float, rate: float) -> float:
    return 1.0 - exp(-rate * max(0.0, value))


@dataclass(frozen=True)
class BodyLeadingContext:
    payload: dict
    current_density: float
    line_count: int
    source_lines: int
    source_leading_em: float
    font_growth_score: float

    @classmethod
    def from_payload(cls, payload: dict) -> BodyLeadingContext:
        item = payload.get("item") or {}
        font_size = max(0.1, float(payload.get("font_size_pt") or 0.0))
        pitch = local_line_pitch(item) or median_line_pitch(item)
        source_leading = pitch / font_size - 1.0 if pitch > 0 else 0.0
        grew = float(payload.get("_body_underfill_font_grew_pt") or 0.0)
        slack_ratio = float(payload.get("_body_underfill_font_slack_ratio") or 0.0)
        return cls(
            payload=payload,
            current_density=payload_density(payload),
            line_count=required_lines(payload),
            source_lines=source_visual_line_count(item),
            source_leading_em=_clamp(source_leading, 0.0, BODY_COMFORT_SOURCE_LINE_LEADING_MAX),
            font_growth_score=_clamp(
                (grew / BODY_COMFORT_FONT_GROWTH_NORMALIZER_PT) * max(0.0, slack_ratio),
                0.0,
                1.0,
            ),
        )

    @property
    def source_line_ratio(self) -> float:
        return self.source_lines / max(1, self.line_count)


@dataclass(frozen=True)
class BodyLeadingSolution:
    leading_em: float
    target_density: float
    leading_cap_em: float


def solve_body_leading(payload: dict) -> BodyLeadingSolution | None:
    ctx = BodyLeadingContext.from_payload(payload)
    if ctx.current_density > BODY_COMFORT_LEADING_DENSITY_MAX:
        return None

    leading_cap = _leading_cap(ctx)
    low = float(payload.get("leading_em") or BODY_LEADING_MIN)
    high = max(low, leading_cap)
    target_density = min(BODY_COMFORT_LEADING_DENSITY_MAX, _target_density(ctx))
    if payload_density(payload, leading_em=low) >= target_density:
        return None

    best = _solve_leading_em(
        payload,
        low=low,
        high=high,
        target_density=target_density,
    )

    return BodyLeadingSolution(
        leading_em=round(max(float(payload.get("leading_em") or 0.0), best), 2),
        target_density=round(target_density, 3),
        leading_cap_em=round(leading_cap, 2),
    )


def _solve_leading_em(payload: dict, *, low: float, high: float, target_density: float) -> float:
    best = low
    low_density = payload_density(payload, leading_em=low)
    high_density = payload_density(payload, leading_em=high)
    low_residual = target_density - low_density
    high_residual = target_density - high_density

    for _ in range(BODY_COMFORT_SOLVER_MAX_ITERATIONS):
        width = high - low
        if width <= BODY_COMFORT_SOLVER_MIN_BRACKET_WIDTH:
            break
        trial = _residual_extrapolated_leading(
            low=low,
            high=high,
            low_residual=low_residual,
            high_residual=high_residual,
        )
        density = payload_density(payload, leading_em=trial)
        residual = target_density - density
        if abs(residual) <= BODY_COMFORT_SOLVER_DENSITY_TOLERANCE:
            if density <= BODY_COMFORT_LEADING_DENSITY_MAX and residual >= 0:
                best = trial
            break
        if density <= BODY_COMFORT_LEADING_DENSITY_MAX and residual >= 0:
            best = trial
            low = trial
            low_residual = residual
        else:
            high = trial
            high_residual = residual
    return best


def _residual_extrapolated_leading(
    *,
    low: float,
    high: float,
    low_residual: float,
    high_residual: float,
) -> float:
    residual_span = low_residual - high_residual
    if abs(residual_span) <= 1e-9:
        return (low + high) / 2.0
    fraction = low_residual / residual_span
    fraction = _clamp(
        fraction,
        BODY_COMFORT_SOLVER_EXTRAPOLATION_MIN_FRACTION,
        BODY_COMFORT_SOLVER_EXTRAPOLATION_MAX_FRACTION,
    )
    return low + (high - low) * fraction


def _target_density(ctx: BodyLeadingContext) -> float:
    slack = _clamp(
        (BODY_COMFORT_LEADING_DENSITY_MAX - ctx.current_density) / BODY_COMFORT_SLACK_NORMALIZER,
        0.0,
        1.0,
    )
    source_gap = _clamp(
        ctx.source_line_ratio - BODY_COMFORT_SOURCE_LINE_RATIO_OFFSET,
        0.0,
        BODY_COMFORT_SOURCE_LINE_RATIO_MAX_GAP,
    )
    source_leading_gap = _clamp(
        ctx.source_leading_em - BODY_COMFORT_LEADING_MIN,
        0.0,
        BODY_COMFORT_SOURCE_LEADING_MAX_GAP,
    )
    line_count_gap = _clamp(
        (ctx.line_count - BODY_COMFORT_LINE_COUNT_BASE) / BODY_COMFORT_LINE_COUNT_NORMALIZER,
        0.0,
        1.0,
    )

    slack_gain = BODY_COMFORT_SLACK_GAIN_MAX * _exp_response(slack, BODY_COMFORT_SLACK_RESPONSE_RATE)
    multi_line_weight = _exp_response(
        max(0.0, ctx.line_count - 1.0),
        BODY_COMFORT_MULTI_LINE_WEIGHT_RATE,
    )
    source_line_gain = (
        BODY_COMFORT_SOURCE_LINE_GAIN_MAX
        * _exp_response(source_gap, BODY_COMFORT_SOURCE_LINE_RESPONSE_RATE)
        * multi_line_weight
    )
    source_pitch_gain = (
        BODY_COMFORT_SOURCE_PITCH_GAIN_MAX
        * _exp_response(source_leading_gap, BODY_COMFORT_SOURCE_PITCH_RESPONSE_RATE)
        * multi_line_weight
    )
    multi_line_gain = BODY_COMFORT_MULTI_LINE_GAIN_MAX * _exp_response(
        line_count_gap,
        BODY_COMFORT_LINE_COUNT_RESPONSE_RATE,
    )
    font_growth_discount = BODY_COMFORT_FONT_GROWTH_DISCOUNT_MAX * ctx.font_growth_score
    return _clamp(
        BODY_COMFORT_BASE_FILL
        + slack_gain
        + source_line_gain
        + source_pitch_gain
        + multi_line_gain
        - font_growth_discount,
        BODY_COMFORT_BASE_FILL,
        BODY_COMFORT_TARGET_FILL_MAX,
    )


def _leading_cap(ctx: BodyLeadingContext) -> float:
    if ctx.line_count <= 1:
        return BODY_LEADING_MAX

    line_extra = max(0.0, float(ctx.line_count - BODY_COMFORT_LONG_LINE_THRESHOLD + 1))
    long_line_cap = BODY_LEADING_MAX + _exp_response(line_extra, BODY_COMFORT_LONG_LINE_CAP_RESPONSE_RATE) * (
        BODY_COMFORT_LONG_LEADING_MAX - BODY_LEADING_MAX
    )

    source_gap = max(0.0, ctx.source_line_ratio - 1.0)
    source_cap = BODY_LEADING_MAX + _exp_response(source_gap, BODY_COMFORT_SOURCE_LINE_CAP_RESPONSE_RATE) * (
        BODY_COMFORT_SOURCE_LINE_LEADING_MAX - BODY_LEADING_MAX
    )

    pitch_cap = BODY_LEADING_MAX + _exp_response(ctx.source_leading_em, BODY_COMFORT_SOURCE_PITCH_CAP_RESPONSE_RATE) * (
        BODY_COMFORT_SOURCE_LINE_LEADING_MAX - BODY_LEADING_MAX
    )
    cap = max(BODY_LEADING_MAX, long_line_cap, source_cap, pitch_cap)
    return _clamp(cap, BODY_COMFORT_LEADING_MIN, BODY_COMFORT_SOURCE_LINE_LEADING_MAX)
