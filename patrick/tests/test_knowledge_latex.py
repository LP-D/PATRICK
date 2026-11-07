"""Convertisseur LaTeX -> MathML du module Connaissances : le sous-ensemble utilisé par les cours (fractions, indices, exposants, lettres grecques, chapeaux,
sommes, racines, texte, `cases`...), sans dépendance externe. Le MathML est affiché par le navigateur ; ici on vérifie qu'il est bien formé et qu'il contient
ce qu'il faut. Toute commande inconnue est signalée (jamais avalée) et ne fait jamais planter une page."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from patrick.knowledge import latex_lite as L

MATH_NS = "{http://www.w3.org/1998/Math/MathML}"
ROOT = Path(__file__).resolve().parents[2] / "docs" / "cours"


def _tree(markup: str) -> ET.Element:
    """Le MathML produit doit être du XML bien formé une fois enveloppé."""
    return ET.fromstring(f'<math xmlns="http://www.w3.org/1998/Math/MathML">{markup}</math>')


def _conv(src: str, display: bool = False) -> str:
    out, unknown = L.to_mathml(src, display=display)
    assert unknown == [], unknown
    _tree(out)
    return out


def test_a_simple_ratio_becomes_a_fraction():
    out = _conv(r"\frac{a}{b}")
    assert "<mfrac>" in out and out.count("<mi>") == 2


def test_subscripts_superscripts_and_both_together():
    assert "<msub>" in _conv("P_t") and "<msup>" in _conv("x^2")
    both = _conv("x_i^2")
    assert "<msubsup>" in both


def test_braced_scripts_group_their_content():
    out = _conv("P_{t-1}")
    assert "<msub>" in out and "<mrow>" in out and "−" in out          # le tiret du 6 est le vrai signe moins


def test_greek_letters_and_operators_use_unicode():
    out = _conv(r"\alpha + \beta \times \gamma \approx \pm \infty")
    for ch in "αβγ×≈±∞":
        assert ch in out


def test_the_french_decimal_comma_stays_one_number():
    out = _conv(r"1{,}38\times10^{-4}")
    assert "<mn>1,38</mn>" in out and "<mn>10</mn>" in out


def test_hats_bars_and_tildes_are_accents():
    for src in (r"\hat\sigma", r"\widehat{\sigma}^2", r"\bar{x}", r"\overline{CAR}", r"\tilde{x}"):
        assert "<mover" in _conv(src), src


def test_sums_take_limits_in_display_mode_and_scripts_inline():
    display = _conv(r"\sum_{i=1}^{N} x_i", display=True)
    inline = _conv(r"\sum_{i=1}^{N} x_i", display=False)
    assert "<munderover>" in display and "<msubsup>" in inline and "∑" in display


def test_square_roots_and_nth_roots():
    assert "<msqrt>" in _conv(r"\sqrt{n}")
    assert "<mroot>" in _conv(r"\sqrt[3]{x}")


def test_text_and_function_names_are_upright():
    out = _conv(r"\ln(x) + \operatorname{Var}(r) + \text{si AMC}")
    assert '<mi mathvariant="normal">ln</mi>' in out and '<mi mathvariant="normal">Var</mi>' in out and "<mtext>si AMC</mtext>" in out


def test_bold_vectors_and_double_struck_letters():
    assert 'mathvariant="bold"' in _conv(r"\mathbf{x}_t") and 'mathvariant="bold"' in _conv(r"\boldsymbol\theta")
    assert 'mathvariant="double-struck"' in _conv(r"\mathbb{E}[x]")


def test_sizing_commands_are_dropped_but_the_delimiter_stays():
    out = _conv(r"\Big( x \Big) \left[ y \right] \lvert z \rvert")
    assert "Big" not in out and "(" in out and "[" in out and "|" in out


def test_spacing_commands_become_spaces():
    out = _conv(r"a\,b\;c\quad d\qquad e")
    assert out.count("<mspace") == 4


def test_escaped_symbols_are_literal():
    out = _conv(r"50\% \{x\} a\_b")
    assert "%" in out and "{" in out and "}" in out and "_" in out


def test_cases_environment_is_a_left_aligned_table():
    out = _conv(r"J0 = \begin{cases} a & \text{si AMC},\\[2pt] b & \text{sinon} \end{cases}", display=True)
    assert "<mtable" in out and out.count("<mtr>") == 2 and out.count("<mtd>") == 4


def test_underbrace_and_boxed():
    assert "<munder>" in _conv(r"\underbrace{a+b}_{c}") and "tex-boxed" in _conv(r"\boxed{x=1}")


def test_primes_are_superscripts():
    assert "′" in _conv("X'X")


def test_unknown_commands_are_reported_not_swallowed():
    out, unknown = L.to_mathml(r"\foo{x} + y")
    assert unknown == ["foo"] and "foo" in out and "<mi>y</mi>" in out


def test_unbalanced_input_never_raises():
    for src in ("{", "x_", r"\frac{a}", "}}", r"\begin{cases} a"):
        out, _ = L.to_mathml(src)
        _tree(out)                                       # bien formé malgré tout


def test_script_tags_in_math_are_inert_text():
    out, _ = L.to_mathml("<script>alert(1)</script> x")
    assert "<script>" not in out and "&lt;" in out


def _math_spans(markdown: str) -> list[tuple[str, bool]]:
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    blocks = [(m, True) for m in re.findall(r"\$\$(.+?)\$\$", markdown, flags=re.DOTALL)]
    rest = re.sub(r"\$\$.+?\$\$", "", markdown, flags=re.DOTALL)
    return blocks + [(m, False) for m in re.findall(r"(?<!\\)\$([^$\n]+?)\$", rest)]


def test_every_formula_of_the_earnings_course_converts_without_an_unknown_command():
    source = (ROOT / "evenements-de-resultats.md").read_text(encoding="utf-8")
    spans = _math_spans(source)
    assert len(spans) > 600
    unknown_all: dict[str, int] = {}
    for src, display in spans:
        out, unknown = L.to_mathml(src, display=display)
        _tree(out)
        for name in unknown:
            unknown_all[name] = unknown_all.get(name, 0) + 1
    assert unknown_all == {}, unknown_all
