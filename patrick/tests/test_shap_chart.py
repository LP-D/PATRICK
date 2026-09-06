"""Fast, dependency-free tests for `webapp/shap_chart.py`'s pure SVG
generator (no DB, no model, no pipeline -- unlike `test_explain.py`, which
needs a real trained model and is marked `slow`)."""
from __future__ import annotations

import re

from patrick.webapp.shap_chart import render_waterfall_svg


def _contributions():
    return [
        {"name": "feat_a", "value": 1.23, "shap": 0.40},
        {"name": "feat_b", "value": -0.5, "shap": -0.25},
        {"name": "feat_c", "value": 0.0, "shap": 0.05},
    ]


def test_render_waterfall_svg_is_well_formed_svg():
    contributions = _contributions()
    base_value = -0.1
    final_value = base_value + sum(c["shap"] for c in contributions)
    svg = render_waterfall_svg(base_value, contributions, final_value)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert 'role="img"' in svg


def test_render_waterfall_svg_has_one_bar_per_row():
    contributions = _contributions()
    base_value = 0.2
    final_value = base_value + sum(c["shap"] for c in contributions)
    svg = render_waterfall_svg(base_value, contributions, final_value)
    # one <rect> per row: base + each contribution + final
    assert svg.count("<rect") == len(contributions) + 2


def test_render_waterfall_svg_escapes_feature_names():
    contributions = [{"name": "HG=F & <weird>", "value": 1.0, "shap": 0.1}]
    base_value = 0.0
    final_value = base_value + 0.1
    svg = render_waterfall_svg(base_value, contributions, final_value)
    assert "<weird>" not in svg
    assert "&lt;weird&gt;" in svg
    assert "&amp;" in svg


def test_render_waterfall_svg_positive_and_negative_use_distinct_colors():
    contributions = _contributions()  # one positive, one negative, one positive
    base_value = 0.0
    final_value = base_value + sum(c["shap"] for c in contributions)
    svg = render_waterfall_svg(base_value, contributions, final_value)
    from patrick.webapp.shap_chart import POSITIVE_COLOR, NEGATIVE_COLOR
    assert POSITIVE_COLOR in svg
    assert NEGATIVE_COLOR in svg


def test_render_waterfall_svg_handles_no_contributions():
    svg = render_waterfall_svg(0.5, [], 0.5)
    assert svg.startswith("<svg")
    assert svg.count("<rect") == 2  # base + final only


def test_render_waterfall_svg_handles_flat_domain():
    # base == final == every value -> degenerate (zero-range) domain, must
    # not divide by zero or produce NaNs in the output. `\bnan\b` (word
    # boundaries), not a bare substring check -- "dominant-baseline" (a
    # legitimate SVG attribute this generator emits on every row) contains
    # the literal substring "nan" and would otherwise false-positive.
    contributions = [{"name": "flat", "value": 0.0, "shap": 0.0}]
    svg = render_waterfall_svg(0.0, contributions, 0.0)
    assert not re.search(r"\bnan\b", svg, re.IGNORECASE)
    assert re.search(r'width="\d', svg)
