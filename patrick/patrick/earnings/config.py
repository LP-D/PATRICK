"""Réglages d'une étude d'événements de résultats.

`EarningsConfig` ne porte que ce qui change les MESURES stockées par événement (modèle de rendement attendu, fenêtre
d'estimation) ; ses autres champs (fenêtres de cumul, test par défaut, seuils) se relisent à l'affichage depuis les
trajectoires stockées, sans recalcul. `measure_hash()` est la clé de cache des mesures : changer le modèle ou la fenêtre
d'estimation recalcule, changer une fenêtre de cumul non.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

ENGINE_VERSION = 3                      # à incrémenter quand le calcul des mesures change (invalide le cache)
RETURN_MODELS = ("market", "market_adjusted", "factor", "sector")
TESTS = ("bmp", "patell", "corrado", "sign", "kp", "bootstrap")
PATH_LO, PATH_HI = -10, 60              # trajectoire stockée par événement (séances relatives à J0)
EST_LO_MIN = -400                       # plus loin que cela, l'historique est trop ancien pour l'estimation


@dataclass(frozen=True)
class EarningsConfig:
    model: str = "market"
    est_window: tuple[int, int] = (-250, -30)
    est_exclude: int = 2                # séances exclues de l'estimation autour d'une autre annonce du titre
    min_est_obs: int = 100
    winsorize: float = 0.0              # part rognée de chaque côté (0 = aucune) pour les moyennes affichées
    reaction: str = "auto"              # auto : [0] si le timing est certain, sinon [0, +1] ; d0 ; d01
    run_up: tuple[int, int] = (-10, -1)
    short_post: tuple[int, int] = (2, 5)
    drift_windows: tuple[tuple[int, int], ...] = ((2, 20), (2, 60))
    test: str = "bmp"
    min_events: int = 8                 # sous ce nombre, la statistique est marquée « N insuffisant »
    big_move_sigma: float = 3.0         # un « gros mouvement » dépasse k écarts-types quotidiens du titre
    start: str = "2005-01-01"           # début de l'historique de prix demandé

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict | None) -> EarningsConfig:
        raw = dict(raw or {})
        known = {f for f in cls.__dataclass_fields__}
        raw = {k: v for k, v in raw.items() if k in known}
        for key in ("est_window", "run_up", "short_post"):
            if key in raw:
                raw[key] = tuple(raw[key])
        if "drift_windows" in raw:
            raw["drift_windows"] = tuple(tuple(w) for w in raw["drift_windows"])
        return cls(**raw)

    def validate(self) -> EarningsConfig:
        if self.model not in RETURN_MODELS:
            raise ValueError(f"modèle inconnu {self.model!r} (attendu : {', '.join(RETURN_MODELS)})")
        if self.test not in TESTS:
            raise ValueError(f"test inconnu {self.test!r} (attendu : {', '.join(TESTS)})")
        lo, hi = self.est_window
        if not EST_LO_MIN <= lo < hi < PATH_LO:
            raise ValueError("la fenêtre d'estimation doit se terminer avant la trajectoire stockée "
                             f"({PATH_LO}) et tenir dans [{EST_LO_MIN}, {PATH_LO - 1}]")
        if not 0.0 <= self.winsorize < 0.25:
            raise ValueError("winsorize doit être dans [0, 0.25[")
        if self.reaction not in ("auto", "d0", "d01"):
            raise ValueError("reaction : auto, d0 ou d01")
        return self

    def measure_hash(self) -> str:
        """Clé de cache des mesures par événement : ne dépend que de ce qui change le calcul."""
        payload = {"v": ENGINE_VERSION, "model": self.model, "est": list(self.est_window), "excl": self.est_exclude,
                   "min": self.min_est_obs}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


DEFAULT = EarningsConfig()


@dataclass
class StudyParams:
    """Réglages d'une carte d'étude. `values` ne contient que les écarts avec les défauts de l'étude."""
    values: dict = field(default_factory=dict)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.values, sort_keys=True, default=str).encode()).hexdigest()[:10]
