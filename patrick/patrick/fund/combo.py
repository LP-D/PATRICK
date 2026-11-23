"""Fonds de test combinés (ADR 0029) : au lieu de trader chaque signal ML/DL tel quel, combiner plusieurs sources avant de décider.

Quatre fonds, mêmes signaux, mêmes conditions (CTO, 10 M€ virtuels, vente à découvert par CFD, frais estimés), un seul ingrédient qui change :

- `Combiné Référence` : le signal de direction brut du champion, taille fixe : le témoin à battre ;
- `Combiné ML + RL` : l'agent RL de la cible (meilleur run crédible du moteur 2, rejoué chaque jour par `rl/live.py`) doit être d'accord : un
  achat ML exige un agent acheteur, une vente ML un agent à plat ou vendeur ; un désaccord = pas de position. Sans agent crédible sur la
  cible, le signal ML passe seul ;
- `Combiné ML + volatilité` : trois informations de volatilité, toutes connues le jour du signal :
  1. la volatilité prévue de l'actif (moyenne exponentielle des rendements, λ = 0,94, le modèle RiskMetrics) ;
  2. le modèle ML de l'indice de volatilité de sa classe (VIX pour les actions, indices et crypto, OVX pour le pétrole, GVZ pour l'or,
     MOVE pour les taux) : s'il prévoit une hausse de la volatilité, les achats d'actifs risqués (et les ventes de valeurs refuges) sont
     réduits ;
  3. un filtre de coût : le gain attendu d'une position, conviction × 0,8 × σ prévue × √(horizon × durée de tenue attendue), doit payer
     l'aller-retour (frais estimés de l'instrument, financement du CFD compris). Sinon pas d'ouverture ; une position déjà ouverte dans le
     même sens est renouvelée (garder ne coûte rien).
  La taille d'une ouverture suit conviction / volatilité prévue (relative à sa moyenne d'un an), réduite par le régime, entre 25 % et 100 %
  de la taille de la règle ;
- `Combiné ML + RL + volatilité` : les deux.

Toutes les décisions d'une séance sont figées dans la règle (`combo_log`) dès que la séance est passée : un fonds ne voit jamais son passé
changer (un cours révisé ou une position RL recalculée ne réécrit aucune décision déjà prise).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import math
import sqlite3

import numpy as np
import pandas as pd

from patrick.config import universe_extension as UX
from patrick.data.session_calendar import classify_asset_class
from patrick.fund import fees as fees_mod
from patrick.fund import instruments, prices, store
from patrick.simulate import engine as sim_engine

logger = logging.getLogger("patrick.fund.combo")

VARIANTS: dict[str, dict] = {
    "reference": {"name": "Combiné Référence", "combo": None},
    "rl": {"name": "Combiné ML + RL", "combo": {"rl": True, "vol": False}},
    "vol": {"name": "Combiné ML + volatilité", "combo": {"rl": False, "vol": True}},
    "full": {"name": "Combiné ML + RL + volatilité", "combo": {"rl": True, "vol": True}},
}
DEFAULTS = {"capital": 10_000_000, "tier": "auc", "horizons": [1], "max_models": 100, "gross": 1.0, "cost_multiple": 1.0}

EWMA_LAMBDA = 0.94               # RiskMetrics : poids de la variance de la veille
REF_WINDOW = 252                 # volatilité de référence : un an de séances
MIN_HISTORY = 30                 # séances minimales pour une volatilité
EDGE_PER_SIGMA = 0.8             # E|r| d'un rendement normal d'écart-type σ (√(2/π)) : gain attendu = conviction × 0,8 × σ
MAX_HOLD_RUN = 10.0              # durée de tenue attendue au plus 10 horizons (renouvellements successifs)
REGIME_STRENGTH = 1.0            # P(hausse de la vol) = 0,75 : taille des achats risqués × 0,5
MIN_WEIGHT, MAX_WEIGHT = 0.25, 1.0
CFD_CARRY_PER_DAY = 0.06 / 365   # financement d'un CFD acheteur (taux de référence + marge), par jour calendaire
ASOF_DAYS = 5                    # une donnée auxiliaire (position RL, régime, volatilité) vaut au plus 5 jours

# Indices de volatilité par famille : le premier qui a un champion à 1 jour avec des signaux live sert de régime.
REGIME_INDICES = {"equity": ("^VIX", "^VIX9D", "^VIX3M", "^VXD", "^VXN"), "oil": ("^OVX",), "gold": ("^GVZ",), "rates": ("^MOVE",)}
GOLD = frozenset({"GC=F", "SI=F", "GLD", "SLV", "IAU", "SGOL", "GDX", "XAUUSD=X"})
OIL = frozenset({"CL=F", "BZ=F", "HO=F", "RB=F", "USO", "BNO", "XLE", "XOP"})
RATES = frozenset({"ZN=F", "ZB=F", "ZF=F", "ZT=F", "TLT", "IEF", "SHY", "AGG", "BND", "LQD", "HYG", "TIP"})
ROLES = ("risk", "haven", "vol_only")


# --------------------------------------------------------------------------- réglages

def check_settings(raw) -> dict | None:
    """Réglages `combo` d'un pilote : None (fonds classique) ou {rl, vol, cost_multiple}."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise store.FundError("combo invalide : objet {rl, vol, cost_multiple} attendu")
    rl, vol = raw.get("rl", False), raw.get("vol", False)
    if not isinstance(rl, bool) or not isinstance(vol, bool):
        raise store.FundError("combo invalide : rl et vol sont des booléens")
    if not (rl or vol):
        raise store.FundError("combo invalide : au moins une source en plus du ML (rl ou vol)")
    multiple = _float(raw.get("cost_multiple", DEFAULTS["cost_multiple"]), "cost_multiple")
    if not 0.0 <= multiple <= 10.0:
        raise store.FundError("cost_multiple invalide : entre 0 et 10 attendu")
    return {"rl": rl, "vol": vol, "cost_multiple": multiple}


def check_signal(signal: dict) -> dict:
    """Signal `combo` d'une règle, normalisé (appelé par `systematic.validate_config`). Une règle d'un fonds « ML + RL » dont la cible n'a pas
    d'agent crédible porte `rl = None` et pas de volatilité : son signal ML passe seul, c'est voulu."""
    vol = signal.get("vol", False)
    if not isinstance(vol, bool):
        raise store.FundError("combo : vol est un booléen")
    multiple = _float(signal.get("cost_multiple", DEFAULTS["cost_multiple"]), "cost_multiple")
    if not 0.0 <= multiple <= 10.0:
        raise store.FundError("cost_multiple invalide : entre 0 et 10 attendu")
    out = {"mode": "combo", "rl": None, "vol": vol, "cost_multiple": multiple, "regime": None,
           "cost_rt": None, "persistence": 0.0, "median_conviction": 0.1}
    rl = signal.get("rl")
    if isinstance(rl, dict):
        if not isinstance(rl.get("job_id"), str) or not rl["job_id"]:
            raise store.FundError("combo : rl.job_id attendu")
        out["rl"] = {"job_id": rl["job_id"], "target": str(rl.get("target") or "")}
    elif rl is not None:
        raise store.FundError("combo : rl invalide ({job_id} ou rien)")
    regime = signal.get("regime")
    if regime is not None:
        if not isinstance(regime, dict) or isinstance(regime.get("trial_id"), bool) or not isinstance(regime.get("trial_id"), int) \
                or regime.get("role") not in ROLES:
            raise store.FundError("combo : regime {trial_id, role, symbol} attendu")
        out["regime"] = {"trial_id": regime["trial_id"], "role": regime["role"], "symbol": str(regime.get("symbol") or "")}
    if signal.get("cost_rt") is not None:
        cost = _float(signal["cost_rt"], "cost_rt")
        if not 0.0 <= cost < 1.0:
            raise store.FundError("combo : cost_rt entre 0 et 1 attendu")
        out["cost_rt"] = cost
    persistence = _float(signal.get("persistence", 0.0), "persistence")
    conviction = _float(signal.get("median_conviction", 0.1), "median_conviction")
    if not 0.0 <= persistence < 1.0 or not 0.0 < conviction <= 1.0:
        raise store.FundError("combo : persistence dans [0, 1) et median_conviction dans (0, 1] attendus")
    out["persistence"], out["median_conviction"] = persistence, conviction
    if out["vol"] and out["cost_rt"] is None:
        raise store.FundError("combo : cost_rt requis avec la volatilité (filtre de coût)")
    return out


def check_log(raw) -> dict:
    """`combo_log` : séance ISO -> [décision -2..2, poids ou None]. Une entrée illisible est refusée (le passé d'un fonds ne se devine pas)."""
    if not isinstance(raw, dict):
        raise store.FundError("combo_log invalide : objet attendu")
    out = {}
    for day, entry in raw.items():
        if not isinstance(day, str) or not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise store.FundError("combo_log invalide : séance -> [décision, poids]")
        value, weight = entry
        if isinstance(value, bool) or not isinstance(value, int) or not -2 <= value <= 2:
            raise store.FundError("combo_log invalide : décision entière entre -2 et 2")
        out[day] = [value, None if weight is None else float(weight)]
    return out


def _float(value, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise store.FundError(f"{name} invalide : nombre attendu ({value!r})") from exc
    if isinstance(value, bool) or not math.isfinite(out):
        raise store.FundError(f"{name} invalide : nombre fini attendu")
    return out


# --------------------------------------------------------------------------- sources

def regime_role(symbol: str, group: str | None = None) -> tuple[str, str] | None:
    """(famille d'indice de volatilité, rôle) d'un actif, ou None (devises, indices de volatilité, matières agricoles... : aucun régime).
    `risk` : la hausse de la volatilité nuit aux achats ; `haven` (or) : elle les sert ; `vol_only` (taux) : elle ne réduit que la taille."""
    sym = symbol.upper()
    cls = classify_asset_class(sym)
    if cls in ("volatility_index", "fx", "macro"):
        return None
    if sym in GOLD:
        return "gold", "haven"
    if sym in OIL:
        return "oil", "risk"
    g = group or ""
    if sym in RATES or "Taux" in g or "Obligataire" in g:
        return "rates", "vol_only"
    if cls == "crypto" or cls.startswith("equities") or sym == "HG=F":
        if "Matières premières" in g and sym != "HG=F":
            return None
        return "equity", "risk"
    return None


def regime_models(conn: sqlite3.Connection) -> dict[str, dict]:
    """Famille -> {symbol, trial_id} : le premier indice de volatilité de la famille dont le champion à 1 jour a des signaux live."""
    out = {}
    for family, symbols in REGIME_INDICES.items():
        for symbol in symbols:
            row = conn.execute("SELECT trial_id FROM champion WHERE target = ? AND horizon = 1", (symbol,)).fetchone()
            if row and conn.execute("SELECT 1 FROM prediction WHERE trial_id = ? AND split = 'live' LIMIT 1", (row[0],)).fetchone():
                out[family] = {"symbol": symbol, "trial_id": int(row[0])}
                break
    return out


def rl_candidates(conn: sqlite3.Connection) -> dict[str, dict]:
    """Cible -> meilleur run RL crédible : terminé, non supprimé, moteur 2 ou plus, lecture « bat » ou « au-dessus » d'acheter-garder, sans
    fuite ni cible non négociable, test du décalage non suspect, modèles du dernier pli présents, dernier pli non replié. Le meilleur = le plus
    grand écart de croissance par an contre acheter-garder."""
    import json

    from patrick.rl import live as rl_live
    from patrick.rl import reading

    best: dict[str, dict] = {}
    rows = conn.execute("SELECT job_id, result_json FROM job WHERE status = 'done' AND phase != 'deleted' "
                        "AND config_json LIKE '%\"kind\":\"rl\"%' AND result_json IS NOT NULL").fetchall()
    for job_id, raw in rows:
        try:
            result = json.loads(raw)
        except ValueError:
            continue
        target = result.get("target")
        if not target or int(result.get("engine_version") or 1) < 2:
            continue
        rd = reading.of_result(result, target)
        folds = result.get("folds") or []
        if rd.get("verdict") not in ("beats", "better") or (rd.get("delay") or {}).get("suspect") or not folds or folds[-1].get("gated"):
            continue
        models = [p for k, p in (result.get("artifacts") or {}).items() if k.startswith("model_seed")]
        if not models or not all(rl_live.resolve_artifact(p) for p in models):
            continue
        excess = rd.get("excess")
        excess = float(excess) if excess is not None and math.isfinite(excess) else -math.inf
        if target not in best or excess > best[target]["excess"]:
            best[target] = {"job_id": job_id, "target": target, "excess": excess, "verdict": rd["verdict"]}
    return best


def ewma_vol(close: pd.Series, lam: float = EWMA_LAMBDA) -> pd.Series:
    """Volatilité quotidienne prévue pour le lendemain, connue à chaque date (rendements jusqu'à cette date, jamais après)."""
    ret = np.log(close.dropna()).diff().dropna()
    if len(ret) < MIN_HISTORY:
        return pd.Series(dtype=float)
    var = (ret ** 2).ewm(alpha=1.0 - lam, adjust=False).mean()
    vol = np.sqrt(var)
    return vol.iloc[MIN_HISTORY - 1:]


def ref_vol(close: pd.Series) -> pd.Series:
    """Volatilité quotidienne de référence : écart-type des rendements de l'année écoulée, connu à chaque date."""
    ret = np.log(close.dropna()).diff().dropna()
    return ret.rolling(REF_WINDOW, min_periods=MIN_HISTORY).std().dropna()


def round_trip_cost(kind: str, symbol: str, notional: float, currency: str | None, flat_fee: float | None, horizon: int) -> float:
    """Coût d'un aller-retour en fraction du montant, au tarif médian des frais estimés (`fund/fees.py`) ou forfaitaire, financement d'un CFD
    acheteur pendant l'horizon compris (compté pour les deux sens : on ne sait pas encore lequel)."""
    notional = max(float(notional), 1.0)
    if flat_fee is not None:
        return 2.0 * float(flat_fee) / notional
    if kind in ("equity", "etf"):
        commission = max(fees_mod.EQUITY_MIN_COMMISSION, fees_mod.EQUITY_COMMISSION_RATE * notional) / notional
        spread = fees_mod.SPREAD_MEDIAN_BPS["etf" if kind == "etf" else "equity_mid"] / 1e4
        fx = fees_mod.FX_FEE_BPS / 1e4 if currency and currency != "EUR" else 0.0
        return 2.0 * (commission + spread + fx)
    fee_class = instruments.CFD_FEE_CLASS[instruments.classify_cfd_underlying(symbol)]
    spread = fees_mod.SPREAD_MEDIAN_BPS.get(fee_class, fees_mod.SPREAD_MEDIAN_BPS["cfd_other"]) / 1e4 * math.exp(fees_mod.SIGMA ** 2 / 2)
    carry = CFD_CARRY_PER_DAY * horizon * 7 / 5                    # séances -> jours calendaires
    return 2.0 * spread + carry


def _p_up(df: pd.DataFrame) -> pd.Series:
    """P(hausse) par séance : `p_up` enregistrée, sinon le repli signé du moteur de simulation (garde le sens, pas une probabilité)."""
    if df.empty:
        return pd.Series(dtype=float)
    conf = np.nan_to_num(df["y_proba"].to_numpy(dtype=float), nan=0.0)
    fallback = np.where(np.isin(np.round(df["y_pred"].to_numpy(dtype=float)), sim_engine._UP_CLASSES), 0.5 + conf / 2.0, 0.5 - conf / 2.0)
    known = df["p_up"].to_numpy(dtype=float)
    return pd.Series(np.where(np.isfinite(known), known, fallback), index=pd.DatetimeIndex(df["ts"])).sort_index()


def signal_stats(conn: sqlite3.Connection, trial_id: int) -> dict:
    """Sur le holdout du modèle (à défaut son test) : `persistence` = part des séances dont le sens répète celui de la veille (la durée de
    tenue attendue d'une position renouvelée en découle) et `median_conviction` = médiane de |2 P(hausse) − 1| (l'échelle des tailles)."""
    for segment in ("holdout", "test"):
        df = sim_engine._load_predictions(conn, trial_id, segment)
        if len(df) >= 20 and not df["ts"].duplicated().any():
            p = _p_up(df).to_numpy()
            d = np.sign(p - 0.5)
            same = d[1:] == d[:-1]
            return {"persistence": float(min(0.95, max(0.0, same.mean()))),
                    "median_conviction": float(min(1.0, max(0.02, np.median(np.abs(2 * p - 1)))))}
    return {"persistence": 0.0, "median_conviction": 0.1}


def _asof(series: pd.Series, day: pd.Timestamp) -> float | None:
    if series is None or series.empty:
        return None
    known = series[(series.index <= day) & (series.index > day - pd.Timedelta(days=ASOF_DAYS))]
    if known.empty:
        return None
    value = float(known.iloc[-1])
    return value if math.isfinite(value) else None


# --------------------------------------------------------------------------- décision

@dataclasses.dataclass(frozen=True)
class Inputs:
    p_up: float
    rl_position: float | None = None
    regime_p: float | None = None
    sigma: float | None = None
    sigma_ref: float | None = None


def regime_factor(direction: int, role: str | None, regime_p: float | None) -> float:
    """Multiplicateur (0..1) de la taille et du gain attendu selon le modèle de l'indice de volatilité de la classe."""
    if role is None or regime_p is None:
        return 1.0
    tau = 2.0 * regime_p - 1.0                       # > 0 : hausse de la volatilité attendue
    if role == "risk":
        cut = max(direction * tau, 0.0)               # achat d'un actif risqué quand la vol monte, vente quand elle baisse
    elif role == "haven":
        cut = max(-direction * tau, 0.0)
    else:
        cut = max(tau, 0.0) / 2.0
    return float(min(1.0, max(0.0, 1.0 - REGIME_STRENGTH * cut)))


def decide(inputs: Inputs, signal: dict, horizon: int) -> tuple[int, float | None]:
    """Décision d'une séance : 2 × sens (ouvrir ou renouveler), 1 × sens (renouveler seulement : le gain attendu ne paie pas l'ouverture),
    0 (rien : désaccord avec l'agent RL, ou signal neutre), et le poids de la taille (None : taille pleine de la règle)."""
    p = inputs.p_up
    if p is None or not math.isfinite(p) or p == 0.5:
        return 0, None
    direction = 1 if p > 0.5 else -1
    conviction = abs(2.0 * p - 1.0)
    if signal.get("rl"):
        from patrick.rl import live as rl_live

        rl_dir = rl_live.direction(inputs.rl_position)
        if rl_dir is not None and not ((direction == 1 and rl_dir == 1) or (direction == -1 and rl_dir <= 0)):
            return 0, None                               # l'agent n'est pas d'accord : pas de position
    if not signal.get("vol"):
        return 2 * direction, None
    if inputs.sigma is None or inputs.sigma <= 0:
        return direction, None                           # sans volatilité, pas de quoi juger le coût : renouveler seulement
    role = (signal.get("regime") or {}).get("role")
    factor = regime_factor(direction, role, inputs.regime_p)
    hold_run = min(MAX_HOLD_RUN, 1.0 / max(1e-9, 1.0 - float(signal.get("persistence") or 0.0)))
    edge = conviction * EDGE_PER_SIGMA * inputs.sigma * math.sqrt(max(1, horizon) * hold_run) * factor
    cost = float(signal.get("cost_rt") or 0.0) * float(signal.get("cost_multiple", 1.0))
    vol_ratio = min(1.0, inputs.sigma_ref / inputs.sigma) if inputs.sigma_ref else 1.0
    scale = conviction / (2.0 * float(signal.get("median_conviction") or 0.1))
    weight = float(min(MAX_WEIGHT, max(MIN_WEIGHT, scale * vol_ratio * factor)))
    return (2 * direction if edge >= cost else direction), round(weight, 4)


def daily_inputs(conn: sqlite3.Connection, cfg: dict) -> dict[pd.Timestamp, Inputs]:
    """Les entrées de chaque séance de signal de la règle (segment, `since`, `retired_on` respectés)."""
    from patrick.rl import live as rl_live

    signal = cfg["signal"]
    df = sim_engine._load_predictions(conn, cfg["trial_id"], cfg["segment"])
    if df.empty:
        raise store.FundError(f"aucun signal du segment {cfg['segment']!r} pour l'essai {cfg['trial_id']}")
    if df["ts"].duplicated().any():
        raise store.FundError("signaux dupliqués (essai CPCV) : choisir un essai walk-forward")
    p_up = _p_up(df)
    if cfg.get("since"):
        p_up = p_up[p_up.index >= pd.Timestamp(cfg["since"])]
    rl = rl_live.positions(conn, signal["rl"]["job_id"]) if signal.get("rl") else None
    regime = None
    if signal.get("regime"):
        regime = _p_up(sim_engine._load_predictions(conn, signal["regime"]["trial_id"], "live"))
    sigma = sigma_ref = None
    if signal.get("vol"):
        bars = prices.ensure_bars(conn, cfg["instrument"]["symbol"]).df
        if bars is not None and not bars.empty:
            close = bars["close"]
            sigma, sigma_ref = ewma_vol(close), ref_vol(close)
    out = {}
    for ts, p in p_up.items():
        out[ts] = Inputs(p_up=float(p), rl_position=_asof(rl, ts) if rl is not None else None,
                         regime_p=_asof(regime, ts) if regime is not None else None,
                         sigma=_asof(sigma, ts) if sigma is not None else None,
                         sigma_ref=_asof(sigma_ref, ts) if sigma_ref is not None else None)
    return out


def decisions(conn: sqlite3.Connection, cfg: dict) -> dict[str, list]:
    """Séance ISO -> [décision, poids] : les séances figées (`combo_log`) telles quelles, les autres calculées maintenant."""
    frozen = cfg.get("combo_log") or {}
    horizon = cfg["hold"].get("sessions") or 1
    out = {}
    for ts, inputs in daily_inputs(conn, cfg).items():
        day = ts.date().isoformat()
        out[day] = list(frozen[day]) if day in frozen else list(decide(inputs, cfg["signal"], horizon))
    return out


def events(conn: sqlite3.Connection, cfg: dict) -> list[dict]:
    """Événements de la règle (format de `systematic.decide_directional`, avec `weight` à l'ouverture)."""
    from patrick.fund import systematic

    made = decisions(conn, cfg)
    index = pd.DatetimeIndex(list(made))
    values = pd.Series([float(np.sign(v[0])) for v in made.values()], index=index)
    strong = {pd.Timestamp(day): abs(v[0]) == 2 for day, v in made.items()}
    weights = {pd.Timestamp(day): v[1] for day, v in made.items()}
    sessions = cfg["hold"]["sessions"] if cfg["hold"]["mode"] == "horizon" else None
    return systematic.decide_directional(values, cfg["allow_short"], sessions, cfg.get("retired_on"), strong=strong, weights=weights)


def freeze(conn: sqlite3.Connection, rule: dict, today: dt.date) -> int:
    """Fige dans la règle les décisions des séances passées (antérieures à `today`) pas encore figées. Renvoie le nombre de séances figées."""
    from patrick.fund import systematic

    cfg = rule["config"]
    frozen = dict(cfg.get("combo_log") or {})
    fresh = {day: v for day, v in decisions(conn, cfg).items() if day < today.isoformat() and day not in frozen}
    if fresh:
        systematic.update_rule_config(conn, rule["rule_id"], {**cfg, "combo_log": {**frozen, **fresh}})
    return len(fresh)


# --------------------------------------------------------------------------- pilote automatique

def plan_context(conn: sqlite3.Connection, combo: dict) -> dict:
    """Ce qui se calcule une fois par cycle : modèles de régime (volatilité) et agents RL crédibles (RL)."""
    return {"regimes": regime_models(conn) if combo.get("vol") else {},
            "rl": rl_candidates(conn) if combo.get("rl") else {},
            "groups": {sym: group for group, items in UX.all_target_groups().items() for sym, _ in items}}


def rule_signal(conn: sqlite3.Connection, model: dict, strategy: dict, combo: dict, ctx: dict) -> dict:
    """Le signal `combo` de la règle d'un modèle retenu par le pilote (sources disponibles pour sa cible, coût, statistiques du signal)."""
    target = model["target"]
    signal: dict = {"mode": "combo", "rl": None, "vol": bool(combo.get("vol")), "cost_multiple": combo.get("cost_multiple", 1.0),
                    "regime": None, "cost_rt": None, "persistence": 0.0, "median_conviction": 0.1}
    if combo.get("rl") and target in ctx["rl"]:
        signal["rl"] = {"job_id": ctx["rl"][target]["job_id"], "target": target}
    if combo.get("vol"):
        role = regime_role(target, ctx["groups"].get(target))
        if role and role[0] in ctx["regimes"]:
            reg = ctx["regimes"][role[0]]
            signal["regime"] = {"trial_id": reg["trial_id"], "role": role[1], "symbol": reg["symbol"]}
        instrument = model["instrument"]
        currency = prices.ensure_bars(conn, instrument["symbol"]).currency
        signal["cost_rt"] = round(round_trip_cost(instrument["kind"], instrument["symbol"], model.get("notional") or 0.0, currency,
                                                  strategy.get("fee_flat"), model["horizon"]), 6)
        signal.update(signal_stats(conn, model["trial_id"]))
    return signal


def is_combo(stored: dict | None) -> bool:
    return bool(((stored or {}).get("settings") or {}).get("combo"))


def needs_rl(stored: dict | None) -> bool:
    return bool((((stored or {}).get("settings") or {}).get("combo") or {}).get("rl"))


def rl_jobs_needed(conn: sqlite3.Connection) -> list[str]:
    """Agents RL dont un fonds combiné aura besoin aujourd'hui : ceux de ses règles actives et ceux des cibles que sa sélection retient."""
    from patrick.fund import autopilot, selection, systematic

    jobs: list[str] = []
    candidates = None
    for strategy in store.list_strategies(conn):
        stored = store.get_autopilot(conn, strategy["strategy_id"])
        if not stored or not stored.get("enabled") or not needs_rl(stored):
            continue
        for rule in systematic.list_rules(conn, strategy["strategy_id"]):
            rl = (rule["config"].get("signal") or {}).get("rl")
            if isinstance(rl, dict) and "retired_on" not in rule["config"]:
                jobs.append(rl["job_id"])
        candidates = candidates if candidates is not None else rl_candidates(conn)
        policy = dataclasses.replace(autopilot.Settings.from_dict(stored.get("settings")).selection, fresh_days=365)
        jobs += [candidates[m["target"]]["job_id"] for m in selection.select_models(conn, policy)["selected"] if m["target"] in candidates]
    return list(dict.fromkeys(jobs))


def auxiliary_cells(conn: sqlite3.Connection) -> set[tuple[str, int]]:
    """Cellules (cible, horizon) dont un fonds combiné lit le signal sans le trader : les modèles des indices de volatilité (régime)."""
    wanted = False
    for strategy in store.list_strategies(conn):
        stored = store.get_autopilot(conn, strategy["strategy_id"])
        if stored and stored.get("enabled") and ((stored.get("settings") or {}).get("combo") or {}).get("vol"):
            wanted = True
            break
    if not wanted:
        return set()
    return {(model["symbol"], 1) for model in regime_models(conn).values()}


def setup(conn: sqlite3.Connection, *, today: dt.date | None = None, only: list[str] | None = None, capital: float | None = None,
          tier: str = DEFAULTS["tier"], horizons: tuple[int, ...] = tuple(DEFAULTS["horizons"]), max_models: int | None = DEFAULTS["max_models"],
          gross: float = DEFAULTS["gross"], cost_multiple: float = DEFAULTS["cost_multiple"], dry_run: bool = False) -> list[dict]:
    """Les quatre fonds de test (ou `only`, clés de `VARIANTS`), créés ou repris par leur nom, catégorie `lab`. Tout est validé avant la première
    écriture. Renvoie, par fonds : `variant`, `name`, `strategy_id`, `created`, `capital_changed`, `candidates`."""
    from patrick.fund import asset_classes, autopilot, service

    today = service._today(today)
    unknown = [k for k in (only or []) if k not in VARIANTS]
    if unknown:
        raise store.FundError(f"fonds combiné inconnu : {', '.join(unknown)} (fonds : {', '.join(VARIANTS)})")
    capital = DEFAULTS["capital"] if capital is None else capital
    store._check_capital(capital, "CTO")
    plans = []
    for key, variant in VARIANTS.items():
        if only and key not in only:
            continue
        combo = None if variant["combo"] is None else {**variant["combo"], "cost_multiple": cost_multiple}
        settings = {"tier": tier, "gross": gross, "max_models": max_models, "allow_short": True, "horizons": list(horizons), "groups": None,
                    "combo": combo}
        autopilot.Settings.from_dict(settings)                         # tout est validé avant la première écriture
        plans.append((key, variant["name"], settings))
    out = []
    for key, name, settings in plans:
        row = asset_classes._provision(conn, name=name, settings=settings, capital=capital, wrapper="CTO", today=today, dry_run=dry_run,
                                       category="lab", fee_flat=None)
        out.append({"variant": key, **row})
    return out
