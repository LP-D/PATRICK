"""Propriétés de la fiscalité de sortie et des frais estimés (AM16 du 25/11), vérifiées sur des milliers de cas tirés au hasard.

`hypothesis` génère des montants, durées et enveloppes ; chaque test énonce une règle qui doit tenir pour TOUS : un impôt n'est jamais
négatif, ne dépasse jamais le gain (hors PER, dont le capital versé est imposé), ne monte pas quand l'abattement double, et des frais
ne diminuent pas quand l'ordre grossit."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from patrick.fund.fees import FeeContext, estimate_fees
from patrick.placements.envelopes import ENVELOPES, exit_tax

money = st.floats(min_value=0, max_value=5_000_000, allow_nan=False, allow_infinity=False)
signed_money = st.floats(min_value=-1_000_000, max_value=5_000_000, allow_nan=False, allow_infinity=False)
years = st.floats(min_value=0, max_value=40, allow_nan=False)
kinds = st.sampled_from(sorted(ENVELOPES))


@settings(max_examples=400, deadline=None)
@given(gains=signed_money, contributions=money, yrs=years, kind=kinds, taxed=money, couple=st.booleans())
def test_exit_tax_is_never_negative_and_adds_up(gains, contributions, yrs, kind, taxed, couple):
    out = exit_tax(gains, contributions, yrs, ENVELOPES[kind], already_taxed=taxed, couple=couple)
    assert out["ps"] >= 0 and out["ir"] >= 0
    assert abs(out["total"] - (out["ps"] + out["ir"])) < 1e-6


@settings(max_examples=400, deadline=None)
@given(gains=money, contributions=money, yrs=years, kind=kinds.filter(lambda k: not ENVELOPES[k]["deductible"]))
def test_outside_the_per_the_tax_never_exceeds_the_gain(gains, contributions, yrs, kind):
    out = exit_tax(gains, contributions, yrs, ENVELOPES[kind])
    assert out["total"] <= gains + 1e-6


@settings(max_examples=300, deadline=None)
@given(gains=money, contributions=money, yrs=years, kind=kinds)
def test_a_couple_never_pays_more_than_a_single_person(gains, contributions, yrs, kind):
    single = exit_tax(gains, contributions, yrs, ENVELOPES[kind])["total"]
    couple = exit_tax(gains, contributions, yrs, ENVELOPES[kind], couple=True)["total"]
    assert couple <= single + 1e-6


@settings(max_examples=300, deadline=None)
@given(gains=money, contributions=money, kind=kinds)
def test_holding_past_the_threshold_never_raises_the_tax(gains, contributions, kind):
    env = ENVELOPES[kind]
    if env["years_threshold"] <= 0 or env["ir_after"] > env["ir_before"]:
        return
    before = exit_tax(gains, contributions, env["years_threshold"] - 0.5, env)["total"]
    after = exit_tax(gains, contributions, env["years_threshold"] + 0.5, env)["total"]
    assert after <= before + 1e-6


@settings(max_examples=300, deadline=None)
@given(notional=st.floats(min_value=1, max_value=10_000_000), factor=st.floats(min_value=1, max_value=50),
       kind=st.sampled_from(["equity", "etf"]), adv=st.one_of(st.none(), st.floats(min_value=1e4, max_value=1e10)), seed=st.integers(0, 10_000))
def test_equity_fees_are_positive_and_grow_with_the_order(notional, factor, kind, adv, seed):
    small = estimate_fees(FeeContext(kind, notional, 1.0, "EUR", adv_notional_base=adv), seed)
    big = estimate_fees(FeeContext(kind, notional * factor, 1.0, "EUR", adv_notional_base=adv), seed)
    assert small.commission > 0 and small.spread >= 0 and small.fx >= 0
    assert big.total >= small.total - 0.01                       # même tirage (graine) : seul le montant change


@settings(max_examples=200, deadline=None)
@given(flat=st.floats(min_value=0, max_value=50), notional=st.floats(min_value=1, max_value=1e7), seed=st.integers(0, 1000))
def test_a_flat_fee_replaces_every_other_cost(flat, notional, seed):
    out = estimate_fees(FeeContext("equity", notional, 1.0, "USD", flat_fee=flat), seed)
    assert out.spread == 0 and out.fx == 0 and abs(out.commission - flat) < 1e-6
