"""Identité d'un run (B7 : sortie de `pipeline/engine.py`, sans changement de comportement).

- `_config_hash` : l'empreinte de configuration (reprise des runs, noms d'études Optuna, points de reprise du scan). Chaque champ
  ajouté après coup en est exclu tant qu'il garde la valeur d'avant son existence : un run ancien garde son empreinte.
- `_features_payload` : ce qui entre dans la clé du cache de variables (`features/pool_cache.py`) en plus du contenu des données.
- `_fracdiff_levels` : la méthode 3 (ADR 0011) différencie fractionnairement les niveaux bruts.
`engine` les réexporte : les appels et les tests qui passent par `engine._config_hash` restent valables.
"""
from __future__ import annotations

import hashlib

from patrick.config.equity_universe import is_equity_symbol
from patrick.config.schema import RunConfig
from patrick.data.session_calendar import session_rule_tag

_ALPHA_FIELDS = {"objective": {"target_kind", "benchmark", "benchmark_source"}}


def _fracdiff_levels(config: RunConfig) -> bool:
    """Méthode 3 (ADR 0011) : les niveaux bruts (colonnes de cours et de séries macro) entrent dans la réserve différenciés fractionnairement."""
    return config.validation.method_version >= 3


def _features_payload(config: RunConfig) -> dict:
    # La clé de cache ne bouge que pour la méthode 3 : un run de méthode 1 ou 2 retrouve ses réserves déjà calculées.
    features = config.features.model_dump(mode="json")
    extra: dict = {}
    # A4 : le drapeau texte n'entre dans la clé que levé (sinon tout le cache existant serait invalidé) ; levé, l'état du magasin de
    # nouvelles y entre aussi (une nouvelle arrivée après la mise en cache changerait la dernière séance).
    if not features.get("enable_text_features"):
        features.pop("enable_text_features", None)
    else:
        from patrick.features import text_features
        extra["text_store"] = text_features.store_fingerprint()
    # A3 : les modèles de `vol_models_extra` portent leur propre empreinte de code, seulement pour les runs qui les choisissent.
    from patrick.features import vol_models_extra
    if set(config.features.vol_models) & set(vol_models_extra.MODELS):
        extra["vol_extra_code"] = vol_models_extra.CODE_HASH
    return {"features": features,
            "fred": sorted(config.universe.fred_series), "target": config.objective.target_symbol,
            **({"raw_level": "fracdiff"} if _fracdiff_levels(config) else {}), **extra}


def _config_hash(config: RunConfig) -> str:
    # Un run brut garde exactement le hachage d'avant l'ajout des champs alpha (reprise des runs existants,
    # noms d'études Optuna) : ils ne sont dans la charge utile que pour une cible alpha.
    obj_exclude: set[str] = set(_ALPHA_FIELDS["objective"]) if config.objective.target_kind == "raw" else set()
    # Idem pour la garde anti-fuite (`data/alignment.py`) : un run dont les entrées n'ont reçu aucun décalage (runs
    # antérieurs, ou audit sans rien à corriger) garde son hachage d'avant.
    align = config.objective.alignment
    if not (align.column_lags or align.dropped or align.drop_future):
        obj_exclude |= {"leak_guard", "alignment"}
    # Idem pour la règle d'alignement des séances : seule une cible de change sous la règle 2 est construite autrement,
    # toute autre cible (et tout run d'avant le champ) garde son hachage.
    if not session_rule_tag(config.objective.target_symbol, config.objective.target_source, config.objective.session_rule):
        obj_exclude.add("session_rule")
    # Idem pour l'objectif : un modèle de direction (tout run d'avant le champ) garde son hachage.
    if config.objective.task == "direction":
        obj_exclude.add("task")
    exclude: dict = {"objective": obj_exclude} if obj_exclude else {}
    # Idem pour les réseaux de neurones (`models.deep`) : absent de tout run de machine learning, donc hors du hachage tant qu'il est `None`.
    if config.models.deep is None:
        exclude["models"] = {"deep"}
    # Idem pour la règle de parcimonie « une erreur-type » : hors du hachage quand elle est désactivée, donc une config qui
    # la désactive garde le hachage d'avant le champ ; activée (défaut), elle change le gagnant et entre dans le hachage.
    selection_exclude = set()
    if not config.selection.one_se_rule:
        selection_exclude.add("one_se_rule")
    # Idem pour le critère de sélection : `F1_dir` (tout run d'avant le champ, relu par `from_stored_json`) garde son hachage.
    if config.selection.criterion == "F1_dir":
        selection_exclude.add("criterion")
    if selection_exclude:
        exclude["selection"] = selection_exclude
    # Idem pour la version de méthode : un run de méthode 1 (tout run d'avant le champ) garde son hachage.
    validation_exclude = set()
    if config.validation.method_version < 2:
        validation_exclude.add("method_version")
    # Idem pour l'exclusion des cours figés : hors du hachage tant qu'elle est fausse (tout run d'avant le champ).
    if not config.validation.drop_stale_returns:
        validation_exclude.add("drop_stale_returns")
    if not config.validation.cpcv_thresholds_per_combo:
        validation_exclude.add("cpcv_thresholds_per_combo")
    if validation_exclude:
        exclude["validation"] = validation_exclude
    # Idem pour les features de contexte des actions : sans effet sur une cible qui n'est pas une action, et absentes de tout run d'avant
    # le champ ; seul un run d'action qui les active les porte dans son hachage.
    features_exclude = set()
    if not (config.features.enable_equity_context_features and is_equity_symbol(config.objective.target_symbol)):
        features_exclude.add("enable_equity_context_features")
    if not config.features.enable_text_features:                 # A4 : idem, hors du hachage tant qu'il est faux
        features_exclude.add("enable_text_features")
    if features_exclude:
        exclude["features"] = features_exclude
    exclude = exclude or None
    return hashlib.sha256(config.model_dump_json(exclude=exclude).encode()).hexdigest()[:16]
