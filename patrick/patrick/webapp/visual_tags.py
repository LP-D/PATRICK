"""Repères visuels stables (26/11) : une couleur fixe par famille de modèle (VI21) et un badge de classe d'actifs devant un nom (VI22).

- `algo_tag("XGBoost")` -> `<span class="algo-tag" data-algo="xgboost">XGBoost</span>` : la teinte vient de la feuille de style, la même
  sur toutes les pages (un XGBoost est toujours orange, un GRU toujours violet…).
- `iclass("EURUSD=X")` -> `<span class="ac-badge" data-ac="fx" title="Devise">FX</span>` : la classe se lit d'un coup d'œil dans une
  longue liste. Rien pour une classe inconnue.
"""
from __future__ import annotations

from markupsafe import Markup, escape

ALGO_KEYS = {"xgboost": "xgboost", "lightgbm": "lightgbm", "catboost": "catboost", "randomforest": "forest", "extratrees": "forest",
             "logistic": "linear", "logisticregression": "linear", "ridge": "linear", "svm": "linear", "mlp": "mlp", "gru": "rnn", "lstm": "rnn",
             "cnn1d": "cnn", "tcn": "cnn", "transformer": "transformer", "stacking": "stack", "stack": "stack",
             "ppo": "rl", "a2c": "rl", "dqn": "rl", "sac": "rl"}

AC_BADGES = {"fx": ("FX", "Devise"), "crypto": ("CRY", "Cryptoactif"), "futures": ("FUT", "Contrat à terme"),
             "volatility_index": ("VOL", "Indice de volatilité"), "macro": ("MAC", "Série macro"), "index": ("IND", "Indice"),
             "equity": ("ACT", "Action")}


def algo_key(name: str | None) -> str:
    key = "".join(ch for ch in str(name or "").lower() if ch.isalnum())
    return ALGO_KEYS.get(key, "other")


def algo_tag(name: str | None) -> Markup:
    if not name:
        return Markup("—")
    return Markup('<span class="algo-tag" data-algo="{}">{}</span>').format(algo_key(name), escape(name))


def asset_class_key(symbol: str | None) -> str | None:
    from patrick.data.session_calendar import classify_asset_class
    if not symbol:
        return None
    if str(symbol).startswith("^") and symbol not in ("^VIX", "^VXN", "^VVIX", "^MOVE"):
        return "index"
    cls = classify_asset_class(str(symbol))
    if cls.startswith("equities"):
        return "equity"
    return cls if cls in AC_BADGES else None


def iclass(symbol: str | None) -> Markup:
    key = asset_class_key(symbol)
    if key is None:
        return Markup("")
    short, title = AC_BADGES[key]
    return Markup('<span class="ac-badge" data-ac="{}" title="{}">{}</span> ').format(key, title, short)
