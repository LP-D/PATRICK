"""Sentiment par dictionnaire (au format Loughran-McDonald) et ton des banques centrales."""
from __future__ import annotations

import pytest

from patrick.text import central_bank, lexicon


def test_positive_and_negative_words_give_a_signed_polarity():
    up = lexicon.score_text("Shares surge as profit beats expectations")
    down = lexicon.score_text("Shares plunge after profit warning and layoffs, analysts downgrade")
    assert up.polarity > 0.5 and up.n_positive >= 2
    assert down.polarity < -0.5 and down.n_negative >= 2


def test_text_without_sentiment_words_has_no_polarity_not_a_neutral_one():
    out = lexicon.score_text("The company will hold its annual meeting on Tuesday")
    assert out.polarity is None and out.n_positive == 0 and out.n_negative == 0
    assert out.n_tokens == 9


def test_negated_positive_counts_as_negative_and_negated_negative_is_dropped():
    assert lexicon.score_text("results were not good").n_negative == 1
    assert lexicon.score_text("results were not good").n_positive == 0
    neg = lexicon.score_text("there was no loss this quarter")
    assert neg.n_negative == 0 and neg.polarity is None
    assert lexicon.score_text("they didn't improve margins").n_negative == 1


def test_negation_only_reaches_a_few_words_ahead():
    out = lexicon.score_text("not a single analyst ever doubted the strong results")
    assert out.n_positive == 1 and out.n_negative == 0


def test_french_words_and_negation():
    assert lexicon.score_text("Le titre bondit après un bénéfice record").polarity > 0
    assert lexicon.score_text("Le titre s'effondre après un avertissement").polarity < 0
    assert lexicon.score_text("des résultats pas bons").n_negative == 1


def test_uncertainty_and_litigious_counts():
    out = lexicon.score_text("The outlook is uncertain and a lawsuit may follow")
    assert out.n_uncertainty >= 2 and out.n_litigious == 1


def test_polarity_is_bounded():
    for text in ("gain gain gain", "loss loss", "gain loss", "surge crash plunge win"):
        assert -1.0 <= lexicon.score_text(text).polarity <= 1.0


def test_loughran_mcdonald_master_dictionary_file_is_loaded(tmp_path):
    path = tmp_path / "lm.csv"
    path.write_text("Word,Negative,Positive,Uncertainty,Litigious\n"
                    "ZORGLUB,0,2009,0,0\nGLORBLE,2009,0,0,0\nPERHAPSY,0,0,2009,0\nSUEIT,0,0,0,2009\nNEUTRAL,0,0,0,0\n",
                    encoding="utf-8")
    lex = lexicon.load_loughran_mcdonald(path)
    assert lex.positive == {"zorglub"} and lex.negative == {"glorble"}
    assert lex.uncertainty == {"perhapsy"} and lex.litigious == {"sueit"}
    assert lex.name == "lm:lm.csv"
    out = lexicon.score_text("zorglub zorglub glorble", lex)
    assert out.polarity == pytest.approx((2 - 1) / 3)


def test_lexicon_name_identifies_the_scorer_version():
    assert lexicon.default_lexicon().name.startswith("builtin")


def test_hawkish_statement_scores_positive_and_dovish_negative():
    hawk = central_bank.score_tone("The Committee judges that further rate hikes may be appropriate; "
                                   "inflation remains elevated and policy should stay restrictive.")
    dove = central_bank.score_tone("The Committee decided to cut rates; the labor market has softened and "
                                   "inflation has eased, so policy can become more accommodative.")
    assert hawk.tone > 0.5 and dove.tone < -0.5


def test_balanced_or_empty_statement_has_no_tone():
    assert central_bank.score_tone("The meeting will take place on 18 September.").tone is None
    assert central_bank.score_tone("rate hike and rate cut").tone == pytest.approx(0.0)


def test_french_central_bank_vocabulary():
    assert central_bank.score_tone("Le Conseil poursuit le resserrement et juge la politique restrictive").tone > 0
    assert central_bank.score_tone("Une baisse des taux et une politique accommodante").tone < 0


def test_v2_stock_headline_verbs_are_scored():
    for text in ("Anheuser-Busch shares slip as sales come up shy", "Barclays cutting 5,000 jobs", "US stocks set for rebound after AI sell-off"):
        assert lexicon.score_text(text).polarity is not None, text
    assert lexicon.score_text("Microsoft to lay off 650 people").polarity == -1.0
    assert lexicon.score_text("Oil hits $117 on fears of flare-up in Iran hostilities").polarity == -1.0
    assert lexicon.score_text("Shares rebound after the sell-off").polarity == pytest.approx(0.0)


def test_the_builtin_lexicon_version_changes_with_its_content():
    assert lexicon.default_lexicon().name == "builtin-fr-en-reduced-2"
