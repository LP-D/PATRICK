"""Lecture d'un run de reinforcement learning : les chiffres qui disent ce qu'un run vaut, communs à toutes les pages qui en affichent
(Historique et son panneau, page /rl, comparaison, page d'analyse, vue d'ensemble /analyses).

Analyse du 2026-11-16 (`docs/modelisation/analyse-rl-2026-11-16.md`, ADR 0022) : le Sharpe et le rendement total seuls trompaient.
Ce qui compte pour juger un run :

- l'écart avec acheter-garder (Sharpe, et croissance par an frais compris) et sa significativité (bootstrap unilatéral) ;
- la part des dates où l'agent a eu la main (moteur 2 : un pli que la validation replie tient acheter-garder) ;
- les frais par an (le moteur 1 rendait son talent de timing en frais : 4,6 %/an en médiane) ;
- les alertes : fuite (test du décalage d'un jour, paire de change sous la règle des séances 1) et cible non négociable.

Un run du moteur 1 n'a ni `excess_log_growth`, ni `agent_share`, ni `cost_ann` : on les reconstitue à partir de ce qu'il a. Croissance
au-delà d'acheter-garder = log(1 + CAGR) − log(1 + CAGR d'acheter-garder) (annualisée sur le calendrier, celle du moteur 2 sur 252
séances : écart négligeable) ; part de l'agent = 100 % (pas de repli) ; frais par an = somme des coûts × 252 / nombre de séances (exact).
Le test du décalage d'un jour (moteur 2) est rejoué sur le fichier hors échantillon d'un run du moteur 1 (`rl_oos.csv`) : pour un run
affiché seul, et dans les listes pour les seuls runs qui battraient acheter-garder (une poignée de fichiers à lire, mémorisés). Il a
écarté 5 indices d'Asie sur 6 parmi les 11 runs « gagnants » du moteur 1 (Sharpe brut 1,5-2,5, 0,1-0,5 une fois décalé).
"""
from __future__ import annotations

import functools
import math
from pathlib import Path

PERIODS = 252
SIGNIFICANCE = 0.05

# (clé, chemin JSON dans `job.result_json`) : lus par `json_extract` pour les listes, où relire des centaines de résultats complets
# (~130 Ko chacun) coûterait des secondes. `from_result` lit les mêmes chemins dans un résultat déjà chargé.
SQL_FIELDS: tuple[tuple[str, str], ...] = (
    ("engine_version", "$.engine_version"),
    ("session_rule", "$.session_rule"),
    ("sharpe", "$.strategy.sharpe"),
    ("sharpe_buy_hold", "$.baselines.buy_hold.sharpe"),
    ("sharpe_trend", "$.baselines.trend.sharpe"),
    ("total_return", "$.strategy.total_return"),
    ("max_drawdown", "$.strategy.max_drawdown"),
    ("cagr", "$.strategy.cagr"),
    ("cagr_buy_hold", "$.baselines.buy_hold.cagr"),
    ("excess_log_growth", "$.stats.excess_log_growth"),
    ("p_vs_buy_hold", "$.stats.vs_buy_hold.p_one_sided"),
    ("agent_share", "$.strategy.agent_share"),
    ("turnover", "$.strategy.turnover"),
    ("cost_ann", "$.strategy.cost_ann"),
    ("cost_drag", "$.strategy.cost_drag"),
    ("n_days", "$.strategy.n"),
    ("delay_suspect", "$.stats.delay.suspect"),
    ("dsr", "$.stats.dsr.dsr"),
    ("oos_csv", "$.artifacts.oos_csv"),
)
FIELD_KEYS: tuple[str, ...] = tuple(key for key, _path in SQL_FIELDS)

# Verdicts, du plus grave au plus favorable ; libellés `rlp_rd_<verdict>` (et `ra_rl_rd_<verdict>` sur les pages d'analyse).
VERDICTS: tuple[str, ...] = ("leak", "untradable", "held_bh", "beats", "better", "worse")
# État visuel de chaque verdict (classes `status-<état>` de `status_badge`, `chip` de rl.js) : les couleurs de sens restent rares.
VERDICT_STATE: dict[str, str] = {"leak": "error", "untradable": "pending", "held_bh": "neutral", "beats": "ok", "better": "neutral",
                                 "worse": "neutral"}


def sql_columns(prefix: str = "") -> str:
    """Colonnes `json_extract(...)` de `SQL_FIELDS`, dans l'ordre de `FIELD_KEYS`, nulles tant que le job n'est pas terminé."""
    return ", ".join(f"CASE WHEN {prefix}status = 'done' THEN json_extract({prefix}result_json, '{path}') END" for _key, path in SQL_FIELDS)


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def from_result(result: dict | None) -> dict:
    """Les champs de `SQL_FIELDS` lus dans un résultat complet (mêmes clés que la lecture SQL, `None` quand absents)."""
    def dig(path: str):
        node = result
        for key in path.removeprefix("$.").split("."):
            node = node.get(key) if isinstance(node, dict) else None
        return node
    if not isinstance(result, dict) or not result:
        return dict.fromkeys(FIELD_KEYS)
    return {key: dig(path) for key, path in SQL_FIELDS}


APP_ROOT = Path(__file__).resolve().parents[2]


@functools.lru_cache(maxsize=2048)
def _delay_cached(path: str, mtime_ns: int, size: int) -> dict | None:
    import pandas as pd

    from patrick.rl.walkforward import delay_test
    df = pd.read_csv(path, usecols=["position", "buy_hold_return"])
    if len(df) < 60:
        return None
    out = delay_test(df["position"].to_numpy(dtype=float), df["buy_hold_return"].to_numpy(dtype=float))
    return {k: (_num(v) if k != "suspect" else bool(v)) for k, v in out.items()}      # NaN -> None : la réponse JSON les refuse


def delay_from_csv(oos_csv) -> dict | None:
    """Test du décalage d'un jour rejoué sur le `rl_oos.csv` d'un run (chemin tel qu'enregistré, absolu ou relatif au projet) ; None si
    le fichier manque (supprimé, autre poste) ou ne se lit pas. Mémorisé par fichier (chemin, date, taille)."""
    if not isinstance(oos_csv, str) or not oos_csv:
        return None
    for cand in (Path(oos_csv), APP_ROOT / oos_csv):
        try:
            st = cand.stat()
        except OSError:
            continue
        try:
            return _delay_cached(str(cand), st.st_mtime_ns, st.st_size)
        except (OSError, ValueError, KeyError):
            return None
    return None


def leak_reason(target: str | None, session_rule, delay_suspect) -> str | None:
    """« delay » si le test du décalage d'un jour s'est déclenché, « fx_rule1 » pour une paire Yahoo `=X` entraînée sous la règle des
    séances 1 (tous les runs RL de change d'avant le 2026-11-16), sinon None."""
    if delay_suspect in (True, 1):
        return "delay"
    from patrick.validation.suspicion import alignment_reason
    rule = session_rule if isinstance(session_rule, int) and not isinstance(session_rule, bool) else 1
    return "fx_rule1" if alignment_reason(target, {"objective": {"session_rule": rule}}) else None


def derive(fields: dict, target: str | None, done: bool = True, delay: dict | None = None) -> dict:
    """Chiffres de lecture d'un run à partir de `fields` (sortie de `from_result` ou de la lecture SQL) : moteur, croissance au-delà
    d'acheter-garder, part de l'agent, frais par an, rotation, p-valeur contre acheter-garder, Sharpe de la tendance, verdict.
    `delay` : test du décalage déjà connu (`of_result`) ; sinon, un run sans test enregistré (moteur 1) qui battrait acheter-garder le
    rejoue sur son fichier hors échantillon avant d'être déclaré gagnant."""
    engine_raw = _num(fields.get("engine_version"))
    engine = int(engine_raw) if engine_raw else 1
    excess = _num(fields.get("excess_log_growth"))
    if excess is None:
        cagr, cagr_bh = _num(fields.get("cagr")), _num(fields.get("cagr_buy_hold"))
        if cagr is not None and cagr_bh is not None and cagr > -1 and cagr_bh > -1:
            excess = math.log1p(cagr) - math.log1p(cagr_bh)
    share = _num(fields.get("agent_share"))
    if share is None and engine == 1 and done and _num(fields.get("sharpe")) is not None:
        share = 1.0                                     # le moteur 1 n'avait pas de repli : l'agent tenait toutes les dates
    cost = _num(fields.get("cost_ann"))
    if cost is None:
        drag, n_days = _num(fields.get("cost_drag")), _num(fields.get("n_days"))
        if drag is not None and n_days:
            cost = drag * PERIODS / n_days
    sharpe, sharpe_bh = _num(fields.get("sharpe")), _num(fields.get("sharpe_buy_hold"))
    p_value = _num(fields.get("p_vs_buy_hold"))
    suspect = fields.get("delay_suspect")
    if delay is not None:
        suspect = delay.get("suspect")
    elif (suspect is None and done and sharpe is not None and sharpe_bh is not None and sharpe > sharpe_bh
          and p_value is not None and p_value < SIGNIFICANCE):
        delay = delay_from_csv(fields.get("oos_csv"))
        suspect = delay.get("suspect") if delay else None
    leak = leak_reason(target, fields.get("session_rule"), suspect) if done else None
    verdict = None
    if done and sharpe is not None:
        from patrick.data.session_calendar import untradable_kind
        if leak:
            verdict = "leak"
        elif isinstance(target, str) and untradable_kind(target):
            verdict = "untradable"
        elif engine >= 2 and share is not None and share <= 0:
            verdict = "held_bh"
        elif sharpe_bh is None:
            verdict = None
        elif sharpe > sharpe_bh and p_value is not None and p_value < SIGNIFICANCE:
            verdict = "beats"
        else:
            verdict = "better" if sharpe > sharpe_bh else "worse"
    return {"engine": engine, "excess": excess, "agent_share": share, "cost_ann": cost, "turnover": _num(fields.get("turnover")),
            "p_vs_buy_hold": p_value, "sharpe_trend": _num(fields.get("sharpe_trend")), "leak": leak, "verdict": verdict,
            "verdict_state": VERDICT_STATE.get(verdict or "", "neutral"), "delay": delay}


def of_result(result: dict | None, target: str | None = None) -> dict:
    """`derive` appliqué à un résultat complet (panneau, comparaison, page d'analyse, résultats de /rl)."""
    result = result if isinstance(result, dict) else {}
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    target = target or result.get("target") or (config.get("objective") or {}).get("target_symbol")
    fields = from_result(result)
    done = bool(result.get("strategy"))
    stored = (result.get("stats") or {}).get("delay")
    delay = stored if isinstance(stored, dict) else (delay_from_csv(fields.get("oos_csv")) if done else None)
    return derive(fields, target, done=done, delay=delay)


def is_credible_win(reading: dict) -> bool:
    """Run qui bat acheter-garder de façon significative, sans alerte de fuite ni cible non négociable."""
    return reading.get("verdict") == "beats"


_VERDICT_LOG = {"leak": "fuite probable", "untradable": "cible non négociable", "held_bh": "égal à acheter-garder (tous les plis repliés)",
                "beats": "bat acheter-garder (significatif à 5 %)", "better": "au-dessus d'acheter-garder, non significatif",
                "worse": "sous acheter-garder"}


def log_line(result: dict) -> str:
    """Ligne de fin du journal d'un run (`[RL-RESULT]`) : Sharpe contre acheter-garder, écart par an, part de l'agent, frais, verdict."""
    rd = of_result(result)
    fields = from_result(result)
    parts = []
    sharpe, sharpe_bh = _num(fields.get("sharpe")), _num(fields.get("sharpe_buy_hold"))
    if sharpe is not None:
        parts.append(f"Sharpe {sharpe:.2f}" + (f" (acheter-garder {sharpe_bh:.2f})" if sharpe_bh is not None else ""))
    if rd["excess"] is not None:
        parts.append(f"{100 * rd['excess']:+.1f} %/an contre acheter-garder")
    if rd["agent_share"] is not None:
        parts.append(f"agent aux commandes {100 * rd['agent_share']:.0f} % des dates")
    if rd["cost_ann"] is not None:
        parts.append(f"frais {100 * rd['cost_ann']:.1f} %/an")
    if rd["verdict"]:
        parts.append(f"lecture : {_VERDICT_LOG[rd['verdict']]}")
    return " · ".join(parts)
