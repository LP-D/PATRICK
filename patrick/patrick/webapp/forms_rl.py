"""Formulaire de la page /rl <-> `RLRunConfig`.

Champs HTML : `target_symbols` (liste), `start_date`, `families` (cases), `output_dir`, `seed`, puis un champ `rl_<réglage>` par entrée de
`config.defaults.DEFAULT_RL` (case à cocher pour les booléens). Même convention que `webapp/forms.py` : une valeur invalide ajoute une
erreur nommée et retombe sur le défaut de CE champ seulement ; les bornes sont celles de `config.defaults.RL_BOUNDS`.
"""
from __future__ import annotations

from patrick.config import defaults as D
from patrick.webapp import forms

RL_FIELD_LABELS: dict[str, str] = {
    "action_space": "Espace d'actions", "n_levels": "Niveaux de position", "allow_short": "Vente à découvert",
    "max_leverage": "Levier maximal", "cost_bps": "Frais (points de base)", "slippage_bps": "Glissement (points de base)",
    "reward": "Récompense", "risk_aversion": "Aversion au risque", "dsr_eta": "Oubli du Sharpe différentiel",
    "obs_lookback": "Lignes empilées (observation)", "include_position": "Position dans l'observation",
    "episode_length": "Longueur d'épisode", "random_start": "Départ d'épisode aléatoire", "max_features": "Variables retenues",
    "feature_selection": "Sélection des variables", "algo": "Algorithme", "policy_layers": "Couches du réseau",
    "policy_units": "Neurones par couche", "activation": "Activation", "learning_rate": "Taux d'apprentissage",
    "gamma": "Facteur d'actualisation (gamma)", "total_timesteps": "Pas d'entraînement", "n_steps": "Pas par mise à jour",
    "batch_size": "Taille de lot", "n_epochs": "Passages par mise à jour", "ent_coef": "Coefficient d'entropie",
    "clip_range": "Plage de coupure", "gae_lambda": "Lambda GAE", "buffer_size": "Taille du tampon",
    "learning_starts": "Pas avant apprentissage", "train_freq": "Fréquence d'entraînement",
    "target_update_interval": "Mise à jour du réseau cible", "exploration_fraction": "Part d'exploration",
    "tau": "Tau (mise à jour douce)", "n_seeds": "Agents moyennés (graines)", "device": "Appareil de calcul",
    "threads": "Fils de calcul", "n_folds": "Plis walk-forward", "min_train_frac": "Part minimale d'entraînement",
    "retrain": "Fenêtre d'entraînement", "rolling_bars": "Barres (fenêtre glissante)", "bootstrap_samples": "Tirages du bootstrap",
}
_BOOL_KEYS = ("allow_short", "include_position", "random_start")
_CHOICES = {"action_space": D.RL_ACTION_SPACES, "reward": D.RL_REWARDS, "feature_selection": D.RL_FEATURE_SELECTION,
            "algo": D.RL_ALGOS, "activation": D.RL_ACTIVATIONS, "device": ("auto", "cpu", "cuda"), "retrain": D.RL_RETRAIN}
_INT_KEYS = tuple(k for k, v in D.DEFAULT_RL.items() if isinstance(v, int) and not isinstance(v, bool))
_FLOAT_KEYS = tuple(k for k, v in D.DEFAULT_RL.items() if isinstance(v, float))
RL_TARGET_GROUPS_EXCLUDED = ("Macro (FRED)", "Séries FRED d'entraînement")      # pas de position tenable sur une série macro


def rl_target_groups() -> dict[str, list]:
    """Groupes de cibles cotées : le RL tient une position, il n'y en a pas sur une série FRED (macro, taux de la Fed...)."""
    out = {}
    for group, items in forms.TARGET_GROUPS.items():
        if group in RL_TARGET_GROUPS_EXCLUDED:
            continue
        kept = [(sym, label) for sym, label in items if forms.TARGET_SOURCE_BY_SYMBOL.get(sym) == "yfinance"]
        if kept:
            out[group] = kept
    return out


def default_rl_config_dict() -> dict:
    target = "^GSPC"
    yf_tickers, fred_series = forms.universe_excluding(target)
    return {
        "name": "mon_run_rl",
        "objective": {"target_symbol": target, "target_source": "yfinance", "horizons": [1]},
        "universe": {"yf_tickers": yf_tickers, "fred_series": fred_series, "start_date": D.DEFAULT_RL_START_DATE, "yf_coverage": 0.85,
                     "fred_point_in_time": D.DEFAULT_FRED_POINT_IN_TIME},
        "data_quality": {"enabled": True, "max_frozen_run": D.DEFAULT_QUALITY_MAX_FROZEN_RUN, "max_gap_bdays": D.DEFAULT_QUALITY_MAX_GAP_BDAYS,
                         "max_robust_z": D.DEFAULT_QUALITY_MAX_ROBUST_Z,
                         "max_universe_exclusion_frac": D.DEFAULT_QUALITY_MAX_UNIVERSE_EXCLUSION_FRAC,
                         "min_history_years": D.DEFAULT_MIN_HISTORY_YEARS},
        "features": {"families": ["technical", "spike", "macro"]},
        "rl": dict(D.DEFAULT_RL),
        "output": {"dir": "", "seed": D.DEFAULT_SEED},
    }


def to_view_rl(cfg: dict) -> dict:
    """Valeurs plates pour pré-remplir le formulaire (`rl_<réglage>`)."""
    rl = cfg.get("rl") or {}
    obj, uni = cfg.get("objective", {}), cfg.get("universe", {})
    out = {
        "name": cfg.get("name", ""), "target_symbol": obj.get("target_symbol", ""),
        "start_date": uni.get("start_date", D.DEFAULT_RL_START_DATE),
        "families": list((cfg.get("features") or {}).get("families", ["technical", "spike", "macro"])),
        "output_dir": (cfg.get("output") or {}).get("dir", "runs"), "seed": (cfg.get("output") or {}).get("seed", D.DEFAULT_SEED),
    }
    for key, default in D.DEFAULT_RL.items():
        out[f"rl_{key}"] = rl.get(key, default)
    return out


def build_rl_config_dict(form, *, target_symbol: str, name: str) -> tuple[dict, list[str]]:
    """`form` : `starlette.datastructures.FormData`. Retourne (config_dict, erreurs) ; ne pas valider `config_dict` s'il y a des erreurs."""
    errors: list[str] = []
    if forms.TARGET_SOURCE_BY_SYMBOL.get(target_symbol) is None:
        errors.append("« Cible » : choix invalide.")
    elif forms.TARGET_SOURCE_BY_SYMBOL[target_symbol] != "yfinance":
        errors.append(f"« Cible » : {target_symbol} est une série FRED : le RL tient une position sur une cible cotée.")
    yf_tickers, fred_series = forms.universe_excluding(target_symbol)
    families = [f for f in form.getlist("families") if f in D.RL_FEATURE_FAMILIES]
    if "macro" not in families:
        fred_series = {}                  # sans la famille « macro », télécharger ~100 séries FRED serait du temps perdu
    if not families:
        errors.append("« Familles de variables » : choisis-en au moins une (" + ", ".join(D.RL_FEATURE_FAMILIES) + ").")
    start = (form.get("start_date") or D.DEFAULT_RL_START_DATE).strip()
    rl: dict = {}
    for key, default in D.DEFAULT_RL.items():
        label = RL_FIELD_LABELS[key]
        if key in _BOOL_KEYS:
            rl[key] = form.get(f"rl_{key}") in ("on", "true", "1")
            continue
        raw = form.get(f"rl_{key}")
        if raw is None or str(raw).strip() == "":
            rl[key] = default
            continue
        raw = str(raw).strip().replace(",", ".")
        if key in _CHOICES:
            if raw not in _CHOICES[key]:
                errors.append(f"« {label} » : choix invalide.")
                rl[key] = default
            else:
                rl[key] = raw
            continue
        try:
            value: float | int = int(raw) if key in _INT_KEYS else float(raw)
        except ValueError:
            errors.append(f"« {label} » : valeur numérique invalide.")
            rl[key] = default
            continue
        lo, hi = D.RL_BOUNDS.get(key, (None, None))
        if lo is not None and not lo <= value <= hi:
            errors.append(f"« {label} » doit être compris entre {lo:g} et {hi:g}.")
            rl[key] = default
            continue
        rl[key] = value
    try:
        seed = int(form.get("seed") or D.DEFAULT_SEED)
    except ValueError:
        errors.append("« Graine (seed) » : valeur entière invalide.")
        seed = D.DEFAULT_SEED
    raw_dir = (form.get("output_dir") or "").strip()
    out_dir = f"runs/{name}"
    if raw_dir and forms.validate_output_dir(raw_dir, errors):
        out_dir = raw_dir
    cfg = {
        "name": name,
        "objective": {"target_symbol": target_symbol, "target_source": forms.TARGET_SOURCE_BY_SYMBOL.get(target_symbol, "yfinance"),
                      "horizons": [1]},
        "universe": {"yf_tickers": yf_tickers, "fred_series": fred_series, "start_date": start, "yf_coverage": 0.85,
                     "fred_point_in_time": D.DEFAULT_FRED_POINT_IN_TIME},
        "data_quality": {"enabled": True, "min_history_years": D.DEFAULT_MIN_HISTORY_YEARS},
        "features": {"families": families or ["technical"]},
        "rl": rl,
        "output": {"dir": out_dir, "seed": seed},
    }
    return cfg, errors
