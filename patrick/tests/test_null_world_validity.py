"""Le protocole protège-t-il vraiment ? Le pipeline COMPLET sur des marches aléatoires (audit externe du 2026-10-19).

Sur une marche aléatoire il n'y a rien à prédire : tout ce que le pipeline y « trouve » est du hasard. Les garde-fous
statistiques doivent donc faire leur travail :
- la correction multi-tests (BH) ne rejette pas, et aucune cible ou presque n'a de p-value Diebold-Mariano « le modèle
  fait mieux » < 5 % ;
- le PBO (probabilité de surapprentissage) est élevé : le meilleur essai du passé ne gagne pas hors échantillon ;
- le Sharpe déflaté (DSR) de la stratégie simulée sur le holdout reste bas.
Un monde à SIGNAL sert de contrôle positif : si la chaîne ne voit pas un vrai signal, le monde nul ne prouve rien --
le protocole serait aveugle, pas prudent. Le signal passe par le NIVEAU d'un facteur lent (voir
`null_world_support.make_raw`), pas par un rendement de la veille : le garde anti-fuite d'alignement écarterait celui-là,
à raison.

Ce que la mesure a montré (12 mondes nuls, 3 mondes à signal, 2026-10-19), et que ces tests ne masquent pas :
- aucune p-value « modèle meilleur » < 5 %, aucun rejet BH, PBO moyen 0,59, aucun DSR >= 0,95 sur le bruit ;
- MAIS la p-value Diebold-Mariano BILATÉRALE est < 5 % dans 3 mondes nuls sur 12 (au lieu de ~0,6), toujours avec le
  modèle PIRE que sa baseline (statistique moyenne +0,75) : sur du bruit le modèle sélectionné fait systématiquement moins
  bien que la baseline, et la variance du test ne couvre pas la dérive propre au chemin du holdout. Le garde de la famille
  BH ne regarde que le sens « le modèle fait mieux » : il est protégé, la taille bilatérale du test ne l'est pas ;
- le test DM a peu de puissance : sur 3 mondes à signal fort (Sharpe holdout 2 à 9) aucune p-value « meilleur » < 5 %.
Voir `KNOWN_ISSUES.md`.

Lent (~1 min par monde) : marqueur `validity`, exclu de `pytest` et de la CI poussée ; lancer `pytest -m validity`
(hebdomadaire : `.github/workflows/validity.yml`). Effectifs : `PATRICK_NULL_WORLD_RUNS` (12), `PATRICK_SIGNAL_WORLD_RUNS`
(3). `PATRICK_WORLD_CACHE_DIR` : dossier où les mondes calculés sont conservés (base, magasin, un JSON par monde) --
une exécution interrompue reprend où elle s'est arrêtée.
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import os
from pathlib import Path

import numpy as np
import pytest
from null_world_support import WorldResult, one_sided_p, run_world

from patrick.data.store import DataStore
from patrick.pipeline import engine
from patrick.tracking import db as trackdb
from patrick.tracking import stats as trackstats

pytestmark = pytest.mark.validity

N_NULL = int(os.environ.get("PATRICK_NULL_WORLD_RUNS", "12"))
N_SIGNAL = int(os.environ.get("PATRICK_SIGNAL_WORLD_RUNS", "3"))


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    """Tous les mondes, calculés une fois pour le module (le coût est là), ou relus du cache s'ils y sont déjà."""
    cache = os.environ.get("PATRICK_WORLD_CACHE_DIR")
    root = Path(cache) if cache else tmp_path_factory.mktemp("worlds")
    (root / "results").mkdir(parents=True, exist_ok=True)
    patch = pytest.MonkeyPatch()
    for var, sub in (("PATRICK_STORE_ROOT", "store"), ("PATRICK_CACHE_ROOT", "cache"),
                     ("PATRICK_FEATURE_CACHE_ROOT", "fcache")):
        patch.setenv(var, str(root / sub))
    patch.setattr(engine, "download_ohlc", lambda *a, **k: None)
    with contextlib.suppress(Exception):   # ne pas écraser une machine qui fait déjà autre chose (confort seulement)
        import psutil
        psutil.Process().nice(getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10))
    out: dict[str, list[WorldResult]] = {"null": [], "signal": []}
    dbs = {"null": str(root / "null.db"), "signal": str(root / "signal.db")}
    store = DataStore(root=str(root / "store"))
    try:
        for kind, count in (("null", N_NULL), ("signal", N_SIGNAL)):
            for k in range(count):
                saved = root / "results" / f"{kind.upper()}_{k:02d}.json"
                if saved.exists():
                    out[kind].append(WorldResult(**json.loads(saved.read_text(encoding="utf-8"))))
                    continue
                world = run_world(kind, k, root / "runs", dbs[kind], store)
                saved.write_text(json.dumps(dataclasses.asdict(world)), encoding="utf-8")
                out[kind].append(world)
        yield {"results": out, "dbs": dbs}
    finally:
        patch.undo()


def _summary(worlds_) -> str:
    return "\n".join(f"  {w.target}: p1={one_sided_p(w):.3f} F1={w.holdout_f1} PBO={w.pbo} Sharpe={w.sharpe} DSR={w.dsr}"
                     for kind in ("null", "signal") for w in worlds_["results"][kind])


def test_pure_noise_is_rarely_found_better_than_the_baseline(worlds):
    """Au plus 5 % de cibles « le modèle fait mieux » à 5 % (Diebold-Mariano du holdout, unilatéral) ; la borne
    laisse la place au hasard : P(X >= borne) < 1 % pour X ~ Binomiale(N, 5 %)."""
    from scipy import stats

    p_values = [one_sided_p(w) for w in worlds["results"]["null"]]
    n_significant = sum(p < 0.05 for p in p_values)
    bound = int(stats.binom.ppf(0.99, len(p_values), 0.05)) + 1
    assert n_significant < bound, (f"{n_significant}/{len(p_values)} marches aléatoires 'meilleures que la baseline' "
                                   f"à 5 % (borne {bound}) :\n{_summary(worlds)}")


def test_the_multiple_testing_family_rejects_nothing_on_noise(worlds):
    conn = trackdb.connect(worlds["dbs"]["null"])
    try:
        fdr = trackstats.fdr_across_targets(conn, alpha=0.10)
    finally:
        conn.close()
    assert fdr["n_tested"] == N_NULL
    assert fdr["n_bh_significant"] == 0, f"BH a rejeté du bruit :\n{fdr['results']}\n{_summary(worlds)}"


def test_pbo_flags_overfitting_on_noise(worlds):
    """Sur du bruit, l'essai gagnant en échantillon n'a aucune raison de gagner hors échantillon : PBO ~ 0,5 en
    moyenne (écart-type ~0,16 sur un tirage, plus avec 6 blocs). Un PBO moyen bas voudrait dire que le PBO ne voit
    pas le surapprentissage."""
    pbos = [w.pbo for w in worlds["results"]["null"] if w.pbo is not None and not np.isnan(w.pbo)]
    assert len(pbos) >= N_NULL * 0.8, "PBO non calculable sur la plupart des mondes"
    assert float(np.mean(pbos)) >= 0.40, f"PBO moyen {np.mean(pbos):.2f} sur du bruit :\n{_summary(worlds)}"


def test_the_deflated_sharpe_stays_low_on_noise(worlds):
    dsr = [w.dsr for w in worlds["results"]["null"] if w.dsr is not None and not np.isnan(w.dsr)]
    assert len(dsr) >= N_NULL * 0.8, "stratégie non simulable sur la plupart des mondes"
    n_confident = sum(d >= 0.95 for d in dsr)
    assert n_confident <= max(1, int(0.1 * len(dsr))), f"{n_confident}/{len(dsr)} DSR >= 0,95 :\n{_summary(worlds)}"


def test_positive_control_the_chain_does_see_a_real_signal(worlds):
    """Sans ce contrôle, une chaîne qui répondrait toujours « rien de convaincant » passerait tout ce qui précède.
    Le critère est le Sharpe holdout et son DSR, pas la p-value DM (peu puissante, voir l'en-tête)."""
    signal, null = worlds["results"]["signal"], worlds["results"]["null"]
    confident = sum(w.dsr is not None and w.dsr >= 0.95 for w in signal)
    assert confident >= int(np.ceil(len(signal) * 2 / 3)), f"DSR >= 0,95 dans {confident}/{len(signal)} mondes à signal :\n{_summary(worlds)}"
    sharpe_signal = float(np.mean([w.sharpe for w in signal if w.sharpe is not None]))
    sharpe_null = float(np.mean([w.sharpe for w in null if w.sharpe is not None]))
    assert sharpe_signal - sharpe_null >= 1.0, f"Sharpe signal {sharpe_signal:.2f} vs bruit {sharpe_null:.2f}"
