"""`scripts/mutation_summary.py` : résumé des résultats de mutmut pour `.github/workflows/mutation.yml`.

Les journaux de la CI ne sont pas lisibles sans compte ; le résumé (mutants par module et par statut, survivants nommés) sort donc
en annotation et dans le résumé de l'exécution. Le script vit hors du paquet `patrick` : chargé par chemin de fichier.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mutation_summary.py"

RESULTS = """\
    patrick.validation.fdr.x_benjamini_hochberg__mutmut_1: survived
    patrick.validation.fdr.x_benjamini_hochberg__mutmut_2: killed
    patrick.validation.fdr.x_benjamini_hochberg__mutmut_3: killed
    patrick.validation.dsr.x_deflated_sharpe__mutmut_4: no tests
    patrick.validation.dsr.xǁDsrǁcompute__mutmut_1: timeout
    patrick.validation.dsr.x_deflated_sharpe__mutmut_5: survived
"""


def _load():
    spec = importlib.util.spec_from_file_location("mutation_summary", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_results_are_counted_per_module_and_status():
    counts = _load().count_by_module(RESULTS)
    assert counts == {
        "patrick.validation.fdr": {"survived": 1, "killed": 2},
        "patrick.validation.dsr": {"no tests": 1, "timeout": 1, "survived": 1},
    }


def test_lines_that_are_not_results_are_ignored():
    noisy = "Generating mutants\n    done in 12ms\n" + RESULTS + "\n"
    assert sum(sum(c.values()) for c in _load().count_by_module(noisy).values()) == 6


def test_the_summary_gives_the_score_and_names_the_survivors():
    text = _load().summarize(RESULTS)
    assert "fdr" in text and "dsr" in text
    assert "patrick.validation.fdr.x_benjamini_hochberg__mutmut_1" in text       # un survivant est nommé
    assert "x_benjamini_hochberg__mutmut_2" not in text                           # un mutant tué ne l'est pas
    assert "50 %" in text                                                         # 3 tués ou signalés sur 6 : (2 killed + 1 timeout) / 6


def test_a_module_that_was_not_run_is_said_to_be_out_of_scope():
    text = _load().summarize(RESULTS + "    patrick.validation.pbo.x_f__mutmut_1: not checked\n")
    assert "patrick.validation.pbo : hors périmètre" in text
    assert "0/0" not in text


def test_the_survivor_list_is_capped():
    many = "".join(f"    patrick.validation.fdr.x_f__mutmut_{i}: survived\n" for i in range(100))
    text = _load().summarize(many, max_listed=5)
    assert text.count("__mutmut_") == 5 and "95 autres" in text


def test_no_result_is_said_plainly():
    assert "aucun" in _load().summarize("").lower()


def test_the_annotation_is_one_escaped_line():
    line = _load().annotation("a\nb 100%", title="t")
    assert line == "::notice title=t::a%0Ab 100%25" and "\n" not in line
