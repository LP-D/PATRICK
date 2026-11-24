"""Les vues lourdes de l'application, une `CachedView` chacune (`webapp/view_cache.py` dit la politique : lues d'abord, recalculées ensuite).

Mesures à froid sur la vraie base (76 Go) avant ce cache, ce que la page attendait à chaque ouverture après 5 minutes :

| page | vue | durée |
|---|---|---|
| Accueil | `home-overview` (tableaux de prédictions) | 22-25 s |
| Accueil | `home-summary` (cadre, « À faire », classes) | 3 s |
| Simulation, Fonds | `fund-overview` (valeur de chaque stratégie) | 15-38 s |
| Séries & modèles | `analysis-usage` | 6-10 s |
| Classes d'actifs | `class-stats` | 1-8 s |
| Portefeuille | `portfolio`, `portfolio-bl` | 3-6 s, 1-3 s |
| Résultat réel | `live-board` | 2 s |

Les routes (`app.py`, `routes/fund.py`, `routes/analysis.py`) ne calculent plus rien : elles lisent la vue. Le tableau de `/predictions` a la sienne
(`webapp/predictions_snapshot.py`). Deux familles de signal pour recalculer :

- `marker` : la base a bougé (un run terminé, de nouveaux signaux) -> recalcul en tâche de fond, la page garde l'ancien en attendant ;
- `hard_marker` : l'état que l'utilisateur modifie lui-même (un fonds, un ordre, une règle) -> la page attend le nouveau calcul pour qu'on voie
  sa modification, au lieu d'afficher l'ancien."""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import timedelta

from patrick.core.clock import utc_now
from patrick.tracking import memo
from patrick.webapp import view_cache
from patrick.webapp.view_cache import CachedView, Progress


def runs_marker(conn) -> tuple:
    """La base de suivi a bougé : signaux live, runs terminés, champions, tests de significativité, jobs en cours (`tracking/memo.py`)."""
    return memo.fingerprint(conn)


def judged_marker(conn) -> tuple:
    """Des signaux live viennent d'être jugés ou écrits : de quoi rafraîchir « Résultat réel »."""
    return tuple(conn.execute("SELECT COUNT(*), COUNT(y_true), MAX(ts) FROM prediction WHERE split = 'live'").fetchone())


def fund_state(conn) -> tuple:
    """Tout ce que l'utilisateur change dans les fonds : stratégies, règles, remplacements, ordres. Les petites tables sont relues en entier
    (une empreinte de leurs lignes), les ordres par leurs agrégats : un ordre modifié ajoute une ligne."""
    def digest(sql: str) -> str:
        return hashlib.blake2s(repr(conn.execute(sql).fetchall()).encode("utf-8"), digest_size=8).hexdigest()

    orders = tuple(conn.execute("SELECT COUNT(*), COALESCE(MAX(order_id), 0), TOTAL(quantity), TOTAL(COALESCE(price, 0)), TOTAL(fees) "
                                "FROM fund_order").fetchone())
    return (digest("SELECT * FROM fund_strategy ORDER BY strategy_id"), digest("SELECT * FROM fund_rule ORDER BY rule_id"),
            digest("SELECT * FROM fund_deleted ORDER BY 1"), digest("SELECT * FROM fund_replacement ORDER BY 1"), *orders)


# ---------------------------------------------------------------------------------------------------------------------- calculs

def _home_summary(db_path, key, progress: Progress) -> dict:
    from patrick.tracking import history as trackhistory
    from patrick.tracking import home as trackhome
    from patrick.tracking.db import connect
    from patrick.webapp import forms

    conn = connect(db_path)
    try:
        coverage = {**trackhistory.universe_coverage(conn), "last_inference_at": trackhistory.last_inference_at(conn)}
        return {"coverage": coverage, "home": trackhome.home_summary(conn, forms.TARGET_GROUPS)}
    finally:
        conn.close()


def _home_overview(db_path, key, progress: Progress):
    from patrick.tracking import history as trackhistory
    from patrick.tracking.db import connect

    conn = connect(db_path)
    try:
        return trackhistory.synthesis_overview(conn, alpha=key)
    finally:
        conn.close()


def _class_stats(db_path, key, progress: Progress):
    from patrick.tracking import class_overview
    from patrick.tracking.db import connect

    conn = connect(db_path)
    try:
        return class_overview.model_stats_by_asset(conn)
    finally:
        conn.close()


def _analysis_usage(db_path, key, progress: Progress):
    from patrick.tracking import usage as trackusage
    from patrick.tracking.db import connect

    conn = connect(db_path)
    try:
        return trackusage.analyse(conn)
    finally:
        conn.close()


def _portfolio(db_path, key, progress: Progress) -> dict:
    """`key` = le texte des paires corrélées saisi par l'utilisateur (vide : les trois par défaut)."""
    from patrick.tracking import hrp as trackhrp
    from patrick.tracking import portfolio as trackportfolio
    from patrick.tracking.db import connect

    pairs = trackportfolio.parse_correlated_pairs(key or None)
    conn = connect(db_path)
    try:
        overview = trackportfolio.portfolio_overview(conn, pairs=pairs)
    finally:
        conn.close()
    try:
        hrp = trackhrp.hrp_overview()
    except Exception as exc:  # noqa: BLE001 -- le panneau HRP échoue vers un panneau vide, jamais vers une page en erreur
        logger.warning("le panneau HRP échoue vers un panneau vide, jamais vers une page en erreur : %s: %s", type(exc).__name__, exc)
        hrp = {"weights": None, "skipped": [], "as_of": None, "n_assets": 0}
    return {"overview": overview, "hrp": hrp}


def _portfolio_bl(db_path, key, progress: Progress) -> dict:
    from patrick.tracking import black_litterman as trackbl
    from patrick.tracking.db import connect

    conn = connect(db_path)
    try:
        overview = trackbl.bl_overview(conn, key)
    except Exception as exc:  # noqa: BLE001 -- un échec de calcul devient un panneau vide
        logger.warning("un échec de calcul devient un panneau vide : %s: %s", type(exc).__name__, exc)
        overview = {"n_assets": 0, "n_views": 0}
    finally:
        conn.close()
    return {"overview": overview, "rows": trackbl.table_rows(overview) if overview.get("n_views") else []}


def _live_board(db_path, key, progress: Progress):
    from patrick.tracking import live_board
    from patrick.tracking.db import connect

    conn = connect(db_path)
    try:
        return live_board.board(conn)
    finally:
        conn.close()


def _models_marker(conn) -> tuple:
    from patrick.webapp.routes import fund as fund_routes

    return fund_routes._models_signature(conn)


def _fund_models(db_path, key, progress: Progress) -> list[dict]:
    """La liste des modèles du sélecteur de règles (une requête par cellule de la table `prediction` : 3 à 10 s sur la vraie base)."""
    from patrick.fund import systematic
    from patrick.tracking.db import connect
    from patrick.webapp.routes import fund as fund_routes

    conn = connect(db_path)
    try:
        return fund_routes._labelled(systematic.available_models(conn))
    finally:
        conn.close()


def _fund_overview(db_path, key, progress: Progress) -> dict:
    """La valeur de chaque stratégie (cotations, simulation des ordres) : une étape par stratégie dans la barre de chargement."""
    from patrick.fund import service, store
    from patrick.tracking.db import connect

    conn = connect(db_path)
    try:
        names = [s["name"] for s in store.list_strategies(conn)]
        progress.plan({f"Fonds {name}": 1.5 for name in names})
        return service.overview(conn, service.current_date(), on_step=lambda i: progress.step(f"Fonds {names[i]}"))
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------------------------------- les vues

HOME_SUMMARY = CachedView("home-summary", _home_summary, max_age=timedelta(minutes=30), min_interval=timedelta(minutes=2),
                          marker=runs_marker)
HOME_OVERVIEW = CachedView("home-overview", _home_overview, max_age=timedelta(hours=6), min_interval=timedelta(minutes=30),
                           marker=runs_marker)
CLASS_STATS = CachedView("class-stats", _class_stats, max_age=timedelta(hours=2), min_interval=timedelta(minutes=10),
                         marker=runs_marker)
ANALYSIS_USAGE = CachedView("analysis-usage", _analysis_usage, max_age=timedelta(hours=6), min_interval=timedelta(minutes=30),
                            marker=runs_marker)
PORTFOLIO = CachedView("portfolio", _portfolio, max_age=timedelta(hours=6), min_interval=timedelta(minutes=30), marker=judged_marker)
PORTFOLIO_BL = CachedView("portfolio-bl", _portfolio_bl, max_age=timedelta(hours=6), min_interval=timedelta(minutes=30),
                          marker=judged_marker)
LIVE_BOARD = CachedView("live-board", _live_board, max_age=timedelta(hours=2), min_interval=timedelta(minutes=5), marker=judged_marker)
# La liste des modèles du sélecteur : change quand un run se termine ou qu'un champion est promu (de nouveaux signaux ne changent que les segments).
FUND_MODELS = CachedView("fund-models", _fund_models, max_age=timedelta(minutes=30), min_interval=timedelta(minutes=1), marker=_models_marker)
# Les fonds : la valeur dépend des cotations (douce : recalcul d'une heure à l'autre) ET de ce que l'utilisateur modifie (dure : on attend).
FUND_OVERVIEW = CachedView("fund-overview", _fund_overview, max_age=timedelta(hours=1), min_interval=timedelta(minutes=15),
                           hard_marker=fund_state)

ALL = (HOME_SUMMARY, HOME_OVERVIEW, CLASS_STATS, ANALYSIS_USAGE, PORTFOLIO, PORTFOLIO_BL, LIVE_BOARD, FUND_MODELS, FUND_OVERVIEW)
FIRST_BUILD_WAIT_S = view_cache.FIRST_BUILD_WAIT_S

# Les clés que les pages demandent par défaut : ce sont elles qu'on prépare la nuit, à la fin d'une actualisation live et au démarrage ; une autre
# clé (un autre seuil de FDR, d'autres paires, un autre horizon) se calcule à sa première demande.
DEFAULT_KEYS = ((HOME_SUMMARY, None), (HOME_OVERVIEW, 0.10), (CLASS_STATS, None), (ANALYSIS_USAGE, None), (PORTFOLIO, ""),
                (PORTFOLIO_BL, 5), (LIVE_BOARD, None), (FUND_MODELS, None), (FUND_OVERVIEW, None))
logger = logging.getLogger("patrick.cached_views")


def refresh_all_sync(db_path: str | None = None, force: bool = False) -> list[str]:
    """Tâche de nuit : recalcule, dans CE processus et l'une après l'autre, les vues par défaut qui manquent, sont trop vieilles ou dont la base a
    bougé (`force` : toutes, même si rien n'a bougé : des fichiers que le signal de changement ne voit pas, comme les signaux regroupés, viennent
    d'être réécrits). Une vue en échec est journalisée et n'arrête pas les suivantes. Renvoie les noms des vues recalculées."""
    done = []
    for view, key in DEFAULT_KEYS:
        try:
            if force:
                view.refresh_sync(key, db_path)
                done.append(view.name)
            elif view.refresh_if_stale_sync(key, db_path):
                done.append(view.name)
        except Exception:
            logger.exception("vue %s non recalculée", view.name)
    return done


def request_all_refresh(db_path: str | None = None, force: bool = False) -> None:
    """Fin d'une actualisation live (dans l'app) : relance, en tâche de fond et une par une, les vues par défaut que la nouvelle base rend périmées
    (`force` : toutes, voir `refresh_all_sync`)."""
    def run() -> None:
        for view, key in DEFAULT_KEYS:
            try:
                soft, hard = view.markers(db_path)
                snap = view.load(key, db_path)
                if not force and snap is not None and snap.marker == soft and snap.hard_marker == hard:
                    continue
                view.request_refresh(key, db_path, rerun_if_running=False)
                deadline = time.monotonic() + 1800
                while view.status(key, db_path)["running"] and time.monotonic() < deadline:
                    time.sleep(0.5)
            except Exception:
                logger.exception("vue %s non relancée", view.name)

    threading.Thread(target=run, name="views-refresh", daemon=True).start()


def warm_async(db_path: str | None = None) -> None:
    """Démarrage de l'app : prépare, une par une et en tâche de fond, les vues par défaut qui manquent ou sont trop vieilles, pour que la première
    ouverture de chaque page soit déjà prête. Rien n'est recalculé si l'instantané est récent."""
    def run() -> None:
        for view, key in DEFAULT_KEYS:
            try:
                snap = view.load(key, db_path)
                soft, hard = view.markers(db_path)
                if snap is not None and snap.hard_marker == hard and not view.needs_refresh(snap, soft, utc_now()):
                    continue                                 # état de l'utilisateur inchangé et instantané récent : rien à préparer
                view.request_refresh(key, db_path, rerun_if_running=False)
                deadline = time.monotonic() + 1800
                while view.status(key, db_path)["running"] and time.monotonic() < deadline:
                    time.sleep(0.5)
            except Exception:
                logger.exception("vue %s non préparée", view.name)

    threading.Thread(target=run, name="views-warm", daemon=True).start()
