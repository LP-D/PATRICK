"""Arrêt anticipé du scan d'un challenger : OBSERVÉ SANS AGIR (2026-11-07).

Le scan est 45 % du temps de calcul et un réentraînement sur deux est jeté par le duel des champions. Arrêter tôt un challenger « clairement distancé »
économiserait la moitié du balayage de ces runs, mais rien ne dit encore qu'un challenger distancé au pli 2 l'est resté à la fin : les journaux ne
gardent pas les scores du scan d'un challenger battu (son run est élagué), donc aucune règle ne peut être validée sur l'historique.

Ce module ne change donc rien au run : après chaque pli d'un horizon, il compare la meilleure configuration du challenger jusque-là (moyenne du critère du run sur
les plis déjà faits) au critère moyen du champion en titre sur ses propres plis de test, et note le premier pli où l'écart dépasse `MARGIN`. Le duel enregistre
ensuite cette note à côté de son issue (`duel_outcome.shadow_*`). Quand assez de duels auront été vus, la question « que vaut cette règle ? » se lira dans la base :
parmi les challengers que la règle aurait arrêtés, combien ont tout de même gagné ? Ce n'est qu'alors qu'elle pourra agir.

Même si le critère des plis du champion (ancien millésime de données) n'est pas exactement celui du challenger, les deux sont des maximums sur un balayage
de configurations : le biais de sélection est du même sens des deux côtés.
"""
from __future__ import annotations

import math

from patrick.tracking import champions

MARGIN = 0.03          # critère (AUC_dir) du challenger sous celui du champion de plus que ça
MIN_FOLDS = 2          # jamais sur un seul pli : une moyenne d'un pli n'est qu'un tirage


def _champion_criterion(st, horizon: int, criterion: str) -> float | None:
    """Moyenne sur les plis de test du critère du meilleur essai du champion en titre pour (cible, horizon) ; `None` s'il n'y en a pas."""
    champion = champions.current(st.conn, st.config.objective.run_label(), horizon, exclude_run_ids=list(st.run_ids.values()))
    if champion is None or champion.get("trial_id") is None:
        return None
    value = champions._metrics(st.conn, champion["trial_id"], "test").get(criterion)
    return None if value is None or math.isnan(value) else float(value)


def observe(st, horizon: int, fold_k: int, *, criterion: str, board) -> dict | None:
    """À appeler après le pli `fold_k` (0 pour le premier) de `horizon` ; `board` : le classement de cet horizon. Renvoie la note de l'horizon
    (`n_folds`, `best`, `champion`, `stop_fold`) ou `None` quand il n'y a rien à comparer (pas de champion, pas de critère)."""
    notes = st.early_stop_shadow
    note = notes.setdefault(horizon, {"n_folds": 0, "stop_fold": None, "best": None, "champion": None, "_asked": False})
    note["n_folds"] = fold_k + 1
    if not note["_asked"]:
        note["_asked"] = True
        note["champion"] = _champion_criterion(st, horizon, criterion)
    if note["champion"] is None or note["n_folds"] < MIN_FOLDS:
        return note if note["champion"] is not None else None
    top = board.top_k(1, metric=criterion)
    if not top:
        return note
    best = top[0].get(criterion)
    if best is None or math.isnan(best):
        return note
    note["best"] = float(best)
    if note["stop_fold"] is None and note["best"] < note["champion"] - MARGIN:
        note["stop_fold"] = note["n_folds"]
        print(f"  [EARLY-STOP?] h={horizon}d : après {note['n_folds']} plis le meilleur candidat ({criterion} {note['best']:.4f}) est sous le champion "
              f"({note['champion']:.4f}) de plus de {MARGIN} ; observation seule, le scan continue.")
    return note
