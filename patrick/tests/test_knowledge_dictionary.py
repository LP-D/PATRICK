"""Le dictionnaire du quant : cohérence (clés uniques, renvois existants, deux langues, ancres de cours valides, formules convertibles), couverture (thèmes et niveaux),
recherche sans accents et reprise intégrale du lexique déjà présent (bulles « ? »)."""
from __future__ import annotations

import collections

import pytest

from patrick.knowledge import courses as C
from patrick.knowledge import dictionary as D
from patrick.webapp.glossary import GLOSSARY


def test_the_dictionary_is_internally_consistent():
    assert D.check() == []


def test_the_dictionary_is_hyper_complete_and_covers_every_theme_and_level():
    terms = D.all_terms()
    new = [t for t in terms if not t.legacy]
    assert len(terms) >= 700 and len(new) >= 480
    by_theme = collections.Counter(t.theme for t in terms)
    by_level = collections.Counter(t.level for t in terms)
    assert all(by_theme[k] >= 15 for k in D.THEME_KEYS), by_theme
    assert all(by_level[k] >= 100 for k in D.LEVEL_KEYS), by_level
    assert sum(1 for t in terms if t.formula) >= 90


def test_the_basics_theme_starts_at_level_one_and_the_econometrics_theme_is_advanced():
    m = D.matrix()
    assert m[("bases", 1)] >= 50 and m.get(("bases", 3), 0) == 0
    assert m[("series", 3)] > m.get(("series", 1), 0) and m[("risque", 2)] >= 25


def test_every_entry_of_the_existing_lexicon_is_kept_with_its_text_in_both_languages():
    index = D.by_key()
    for key, entry in GLOSSARY.items():
        t = index[key]
        assert t.legacy and t.text_fr == entry["fr"] and t.text_en == (entry.get("en") or entry["fr"])


def test_new_entries_are_written_in_both_languages_with_reasonable_lengths():
    for t in D.all_terms():
        if t.legacy:
            continue
        assert 60 <= len(t.text_fr) <= 900 and 60 <= len(t.text_en) <= 900, t.key
        assert t.text_fr != t.text_en and len(t.label_fr) <= 90 and len(t.label_en) <= 90, t.key
        assert "TODO" not in t.text_fr + t.text_en, t.key


def test_a_new_entry_never_repeats_the_label_of_another_one():
    seen: dict[tuple[str, str], str] = {}
    for t in D.all_terms():
        if t.legacy:
            continue
        for lang in ("fr", "en"):
            label = D.normalize(t.label(lang))
            owner = seen.get((lang, label))
            assert owner is None, f"{t.key} et {owner} : même libellé {lang}"
            seen[(lang, label)] = t.key
    for t in D.all_terms():
        if t.legacy:
            continue
        for other in D.all_terms():
            if other.legacy and other.key != t.key:
                assert D.normalize(other.label_fr) != D.normalize(t.label_fr), f"{t.key} répète le libellé du lexique : {other.key}"


def test_cross_references_work_in_both_directions():
    index = D.by_key()
    for t in D.all_terms():
        for ref in t.see:
            assert t in D.related(index[ref]), (t.key, ref)


def test_course_links_point_to_real_chapters_and_each_course_has_linked_entries():
    for slug, minimum in (("econometrie", 30), ("evenements-de-resultats", 8)):
        assert C.available(slug)
        assert len(D.terms_of_course(slug)) >= minimum, slug


@pytest.mark.parametrize("query, expected", [
    ("sharpe", "sharpe_ratio"), ("Ratio de Sharpe", "sharpe_ratio"), ("GARCH", "garch_notion"), ("ecart type", "ecart_type"),
    ("écart-type", "ecart_type"), ("duration", "duration"), ("value at risk", "exp_var_es"), ("PEAD", "derive_post_annonce"),
])
def test_search_ignores_accents_and_case_and_finds_labels_aliases_and_english_names(query, expected):
    keys = [t.key for t in D.search(query, "fr", limit=8)]
    assert expected in keys, (query, keys)


def test_search_ranks_an_exact_label_first_and_an_empty_query_finds_nothing():
    assert D.search("Sharpe ratio", "en")[0].key == "sharpe_ratio"
    assert D.search("", "fr") == [] and D.search("zzzqqqxxx", "fr") == []


def test_labels_are_translated_for_themes_and_levels():
    assert D.theme_label("risque", "fr") == "Risque et performance" and D.theme_label("risque", "en") == "Risk and performance"
    assert D.level_label(2, "fr") == "Intermédiaire" and D.level_label(2, "en") == "Intermediate"
