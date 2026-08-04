"""Rapport de correction, C7 -- `patrick audit degradation` : mesure l'impact
réel des corrections de fuite de la phase 0 (purge/embargo, alignement as-of
par classe d'actif, vintages FRED/ALFRED) en comparant 4 configurations
empilées sur le même univers de cibles et le même seed. Exécute le pipeline
RÉEL (`ingest()`/`run_pipeline()`, pas de monkeypatch) -- nécessite donc un
accès réseau réel (yfinance/FRED), jamais disponible dans ce sandbox. Validé
ici via `tests/test_audit_degradation.py` (sources monkeypatchées au niveau
`yfinance.download`/`requests.get`, pas `ingest()` lui-même, pour que le vrai
code de `ingest()`/`_attach_snapshot_context` tourne quand même).

Les 4 configurations sont CUMULATIVES (chacune ajoute une correction à la
précédente), pas indépendantes -- pour isoler la contribution marginale de
chaque correction plutôt que mesurer 4 combinaisons non ordonnées :
  - baseline_avant : aucune correction phase 0 (purge/embargo désactivés,
    alignement as-of désactivé, pas de vintage).
  - +purge         : + purge/embargo (Phase 0.1).
  - +vintages      : + vintages FRED/ALFRED (Phase 0.5) -- nécessite
    FRED_API_KEY (repli scrape = toujours la révision actuelle, un vintage y
    est impossible, cf. `data/sources/fred_source.py`).
  - complet        : + alignement as-of par classe d'actif (Phase 0.4) --
    configuration de production actuelle.
"""
from __future__ import annotations

import csv
import os
from datetime import date, timedelta

from patrick.config.schema import (
    ModelsConfig,
    ObjectiveConfig,
    OutputConfig,
    RunConfig,
    SamplerConfig,
    SelectionConfig,
    TuningConfig,
    UniverseConfig,
    ValidationConfig,
)
from patrick.data.sources.fred_source import FRED_API_KEY_ENV, FRED_API_URL
from patrick.data.store import DataStore
from patrick.pipeline.engine import run_pipeline
from patrick.tracking import db as trackdb

CONFIGURATIONS: tuple[str, ...] = ("baseline_avant", "+purge", "+vintages", "complet")

METRIC_COLUMNS: tuple[str, ...] = ("BalAcc_4cls", "MCC_4cls", "F1_dir")

# Un actif par classe (Phase 0 concerne toute la surface yfinance/FRED, pas un
# seul marché) -- tickers/séries FRED réalistes, cohérents avec
# `configs/examples/*.yaml` et `webapp/forms.py::TARGET_GROUPS`.
DEFAULT_TARGETS: list[dict] = [
    {"label": "indice_us", "target_symbol": "^GSPC", "target_source": "yfinance",
     "yf_tickers": ["^VIX", "TLT"], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
     "start_date": "2015-01-01"},
    {"label": "action_europe", "target_symbol": "MC.PA", "target_source": "yfinance",
     "yf_tickers": ["^FCHI", "EURUSD=X"], "fred_series": {"T10Y2Y": "T10Y2Y"},
     "start_date": "2015-01-01"},
    {"label": "paire_fx", "target_symbol": "EURUSD=X", "target_source": "yfinance",
     "yf_tickers": ["^GSPC", "GC=F"], "fred_series": {"DTWEXBGS": "DTWEXBGS"},
     "start_date": "2015-01-01"},
    {"label": "matiere_premiere", "target_symbol": "GC=F", "target_source": "yfinance",
     "yf_tickers": ["^GSPC", "DX-Y.NYB"], "fred_series": {"T10YIE": "T10YIE"},
     "start_date": "2015-01-01"},
    {"label": "crypto", "target_symbol": "BTC-USD", "target_source": "yfinance",
     "yf_tickers": ["^GSPC", "ETH-USD"], "fred_series": {"NFCI": "NFCI"},
     "start_date": "2018-01-01"},
]


def _vintage_date_for_audit() -> str:
    """Délibérément distincte d'aujourd'hui : omettre `realtime_date` (ou lui
    donner la date du jour) fait renvoyer par l'API FRED `realtime_start=
    realtime_end=aujourd'hui` PAR DÉFAUT -- indiscernable du cas sans vintage.
    Un an en arrière rend la différence visible (URL loggée, valeurs
    récupérées) et vérifiable par l'utilisateur en conditions réelles."""
    return (date.today() - timedelta(days=365)).isoformat()


def _config_for(target: dict, configuration: str, seed: int, output_dir: str) -> RunConfig:
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"configuration inconnue : {configuration!r} (attendu : {CONFIGURATIONS})")
    purge_on = configuration in ("+purge", "+vintages", "complet")
    vintages_on = configuration in ("+vintages", "complet")
    session_lag_on = configuration == "complet"

    return RunConfig(
        name=f"audit_degradation_{target['label']}_{configuration.lstrip('+').replace(' ', '_')}",
        objective=ObjectiveConfig(
            target_symbol=target["target_symbol"],
            target_source=target.get("target_source", "yfinance"),
            horizons=[5],
            regimes=["GLOBAL"],
            disable_session_lag=not session_lag_on,
        ),
        universe=UniverseConfig(
            yf_tickers=target.get("yf_tickers", []),
            fred_series=target.get("fred_series", {}),
            start_date=target.get("start_date", "2015-01-01"),
            vintage_realtime_date=_vintage_date_for_audit() if vintages_on else None,
        ),
        validation=ValidationConfig(
            n_wf_folds=3, purge=purge_on, embargo_enabled=purge_on,
        ),
        selection=SelectionConfig(method="shap", n_features_grid=[8]),
        sampler=SamplerConfig(candidates=["SMOTE"]),
        models=ModelsConfig(algos=["RandomForest"]),
        # Tuning désactivé : l'audit compare l'effet des corrections de fuite,
        # pas la qualité d'un budget Optuna -- 4 configs x 5 cibles avec
        # tuning activé serait inutilement long pour la question posée ici.
        tuning=TuningConfig(enabled=False),
        output=OutputConfig(dir=output_dir, seed=seed),
    )


def _masked_fred_url(series_id: str, start: str, api_key: str, realtime_date: str | None) -> str:
    masked = f"{api_key[:4]}{'*' * max(len(api_key) - 4, 4)}" if api_key else "*absent*"
    url = f"{FRED_API_URL}?series_id={series_id}&api_key={masked}&file_type=json&observation_start={start}"
    if realtime_date:
        url += f"&realtime_start={realtime_date}&realtime_end={realtime_date}"
    return url


def _last_snapshot_fred_source(db_path: str | None) -> str | None:
    """Le `fred_source` de la ligne `snapshot` la plus récente -- fiable ici
    car chaque appel `run_pipeline(force_ingest=True)` insère une ligne
    fraîche (snapshot_id dérivé du contenu, cf. `data/store.py::save`), jamais
    de collision entre deux configurations qui diffèrent réellement."""
    conn = trackdb.connect(db_path)
    try:
        row = conn.execute(
            "SELECT fred_source FROM snapshot ORDER BY created_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _extract_row(target_label: str, configuration: str, result: dict, db_path: str | None) -> dict:
    final_best = result.get("final_best") or {}
    fred_src = _last_snapshot_fred_source(db_path)
    if fred_src is None:
        print(f"  [WARN AUDIT] snapshot.fred_source est NULL pour {target_label}/{configuration} -- "
              "inattendu sur un run réel (rapport de correction, C7 : ce champ n'est None que si "
              "`ingest()` a été monkeypatché sans reproduire `_attach_snapshot_context`, jamais sur "
              "ce chemin). Vérifier qu'aucun monkeypatch de `ingest()` ne subsiste.")
    row = {"target": target_label, "configuration": configuration, "fred_source": fred_src,
           "n_evaluations": len(result.get("leaderboard")) if result.get("leaderboard") is not None else 0}
    for col in METRIC_COLUMNS:
        row[col] = final_best.get(col)
    return row


def _export(rows: list[dict], output_dir: str) -> tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    fieldnames = ["target", "configuration", *METRIC_COLUMNS, "fred_source", "n_evaluations"]

    csv_path = os.path.join(output_dir, "degradation_audit.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    md_path = os.path.join(output_dir, "degradation_audit.md")
    header = "| " + " | ".join(fieldnames) + " |"
    sep = "|" + "|".join(["---"] * len(fieldnames)) + "|"
    body = "\n".join("| " + " | ".join(str(row.get(c, "")) for c in fieldnames) + " |" for row in rows)
    with open(md_path, "w") as f:
        f.write("\n".join([header, sep, body]) + "\n")

    return csv_path, md_path


def run_degradation_audit(targets: list[dict] | None = None, seed: int = 42,
                           output_dir: str = "runs/audit_degradation",
                           db_path: str | None = None, store: DataStore | None = None) -> dict:
    api_key = os.environ.get(FRED_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            "FRED_API_KEY non défini : la configuration \"+vintages\" est dénuée de sens sans lui "
            "-- le repli scrape (CSV public fredgraph.csv) ne peut renvoyer que la révision "
            "ACTUELLE de chaque série, jamais un vintage ALFRED point-in-time (cf. "
            "patrick/data/sources/fred_source.py). Définir la variable d'environnement avant de "
            "relancer `patrick audit degradation` (clé gratuite : "
            "https://fred.stlouisfed.org/docs/api/api_key.html)."
        )

    targets = targets if targets is not None else DEFAULT_TARGETS
    store = store or DataStore()

    rows: list[dict] = []
    url_logged = False
    for target in targets:
        for configuration in CONFIGURATIONS:
            cfg = _config_for(target, configuration, seed, output_dir)
            if not url_logged and cfg.universe.fred_series:
                series_id = next(iter(cfg.universe.fred_series.values()))
                print(f"[AUDIT] URL FRED (1re série de la 1re cible, clé masquée) : "
                      f"{_masked_fred_url(series_id, cfg.universe.start_date, api_key, cfg.universe.vintage_realtime_date)}")
                url_logged = True
            print(f"[AUDIT] {target['label']} / {configuration} ...")
            # force_ingest=True : la clé de cache de `ingest()` ne dépend pas de
            # `vintage_realtime_date`/`disable_session_lag` (cf. docstring
            # `data/ingest.py::ingest`) -- sans ça, la 2e-4e configuration d'une
            # même cible réutiliserait silencieusement les données de la 1re.
            result = run_pipeline(cfg, store=store, force_ingest=True, db_path=db_path)
            rows.append(_extract_row(target["label"], configuration, result, db_path))

    csv_path, md_path = _export(rows, output_dir)
    print(f"[AUDIT] {len(rows)} lignes -> {csv_path} / {md_path}")
    return {"rows": rows, "csv_path": csv_path, "md_path": md_path}
