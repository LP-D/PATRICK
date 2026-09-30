"""CLI : `python -m patrick.benchmark run|compare` (voir `__init__`)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")

NOT_AVAILABLE = [
    "Probabilités complètes par classe : seuls `y_proba` (probabilité de la classe prédite) et `p_up` sont persistés.",
    ("Prédictions des essais Optuna internes (CV interne) : seuls les scores/paramètres existent (`optuna_trials.csv`) ; "
    "les prédictions ne sont persistées que pour le ré-entraînement de la config tunée sur chaque fold."),
    ("Modèle exporté : le fichier joblib n'est pas comparé octet à octet ; on compare ses features et ses `predict_proba` "
    "sur une matrice fixe (`exported_models.json`)."),
    "Le champion « duel » (`champion_duel`) écrit dans la base/dossier de modèles du run isolé : sa décision est dans `result_summary.json`.",
]
LIMITS = [
    ("`config_hash` du moteur inclut `output.dir` (chemin) : il varie d'un espace de travail à l'autre et est donc exclu des "
    "artefacts comparés (`config_digest` du benchmark l'exclut aussi). Noms d'études Optuna normalisés pour la même raison."),
    "Téléchargement (Yahoo/FRED) et ingestion réseau : NON mesurés (snapshot rejoué hors ligne). `ingestion` = lecture parquet du snapshot.",
    ("Dataset synthétique, pas ^GSPC : les proportions entre phases dépendent de la taille de l'univers et de la grille ; "
    "à confirmer sur un run réel avant de fixer des seuils (le module accepte un autre profil)."),
    ("CPU = `time.process_time()` du process (somme des threads, hors processus enfants) ; les workers loky éventuels ne sont pas comptés en CPU "
    "(leur RSS l'est dans le pic mémoire)."),
    "Pic mémoire = échantillonnage RSS à 20 Hz : un pic plus court que 50 ms peut être manqué.",
    ("`models.constructed` compte les appels à `get_classifier` ; le RandomForest « bootstrap séquentiel » est instancié directement dans "
    "`_fit_eval_full` et n'y figure pas : `fit_eval_full.calls` est le décompte exact des entraînements de la grille/re-évaluation."),
    "Les fits internes à Optuna sont comptés par `optuna.cv_fits` (un par split de CV interne et par essai non élagué).",
    ("Le temps SQLite mesure `execute`/`executemany`/`commit` de la connexion du pipeline ; le stockage propre d'Optuna (`optuna.db`) "
    "est inclus dans `optuna.tune_config`, non séparé."),
    ("Le décompte de « features calculées » = colonnes du base pool + colonnes des pools paramétriques construits ; "
    "avec le cache disque les colonnes ne sont pas recalculées (voir hits/miss)."),
]


def _ensure_threads(threads: int) -> None:
    """Les variables de threads doivent être posées AVANT le chargement de
    numpy/BLAS : on relance le process une fois avec l'environnement fixé."""
    if all(os.environ.get(v) == str(threads) for v in THREAD_VARS):
        return
    env = dict(os.environ)
    env.update({v: str(threads) for v in THREAD_VARS})
    sys.exit(subprocess.call([sys.executable, "-m", "patrick.benchmark", *sys.argv[1:]], env=env))


def _git() -> dict:
    root = Path(__file__).resolve().parents[2]

    def run(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=False).stdout.strip()
    return {"sha": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "patrick")), "branch": run("branch", "--show-current")}


def cmd_run(args) -> int:
    _ensure_threads(args.threads)
    from patrick.benchmark import artifacts, reference, report, runner

    spec = reference.PROFILES[args.profile]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work_root = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="patrick_bench_"))
    schemes = [s for s in args.schemes.split(",") if s]
    extra_env = dict(kv.split("=", 1) for kv in args.env)
    scenarios: dict = {}
    data_hash = None
    cfg_digests = {}

    for scheme in schemes:
        print(f"\n=== scénario {scheme} ({spec.name}) ===", flush=True)
        runs = []
        for i in range(args.repeats):
            wd = work_root / f"{scheme}_rep{i + 1}"
            base = out / "baseline" / scheme if i == 0 else wd / "baseline"
            if base.exists():
                shutil.rmtree(base)
            print(f"  run instrumenté {i + 1}/{args.repeats} ...", flush=True)
            r = runner.run_scenario(spec, scheme, wd, instrument=True, baseline_dir=base, label=f"rep{i + 1}",
                                   extra_env=extra_env)
            print(f"    -> {r['wall_s']:.1f}s", flush=True)
            runs.append(r)
        plain = None
        if not args.skip_plain:
            wd = work_root / f"{scheme}_plain"
            base = wd / "baseline"
            print("  run non instrumenté ...", flush=True)
            plain = runner.run_scenario(spec, scheme, wd, instrument=False, baseline_dir=base, label="plain",
                                        extra_env=extra_env)
            print(f"    -> {plain['wall_s']:.1f}s", flush=True)
        warm = None
        if args.warm:
            print("  run cache de features tiède ...", flush=True)
            warm = runner.run_scenario(spec, scheme, work_root / f"{scheme}_warm", instrument=True,
                                       feature_cache_dir=work_root / f"{scheme}_rep1" / "feature_cache", label="warm",
                                       extra_env=extra_env)
        ref = min(runs, key=lambda r: r["wall_s"])   # le moins perturbé par le bruit machine (mêmes compteurs/artefacts)
        ref_first = runs[0]
        data_hash = ref["snapshot"]["data_hash"]
        cfg_digests[scheme] = ref["config_digest"]
        diffs = []
        for r in runs[1:]:
            if r["digests"]["__all__"] != ref_first["digests"]["__all__"]:
                diffs.append({"vs_rep": r["label"], "artifacts": [k for k in ref_first["digests"] if ref_first["digests"][k] != r["digests"].get(k)]})
        plain_same = plain is None or plain["digests"]["__all__"] == ref_first["digests"]["__all__"]
        if plain is not None and not plain_same:
            diffs.append({"vs_plain": [k for k in ref_first["digests"] if ref_first["digests"][k] != plain["digests"].get(k)]})
        walls = [r["wall_s"] for r in runs]
        scenarios[scheme] = {
            "reference_run": {k: v for k, v in ref.items() if k != "deterministic_view"},
            "repeat_walls_s": walls,
            "reference_run_label": ref["label"],
            "repeat_phase_walls_s": [{n: p["wall_s"] for n, p in r["profile_data"]["phases"].items()} for r in runs],
            "plain_wall_s": plain["wall_s"] if plain else None,
            "instrumentation_overhead_pct": (100 * (min(walls) - plain["wall_s"]) / plain["wall_s"]) if plain else None,
            "warm_run": {k: warm[k] for k in ("wall_s", "profile_data")} if warm else None,
            "reproducibility": {
                "same_data_hash": all(r["snapshot"]["data_hash"] == data_hash for r in runs),
                "same_config_digest": all(r["config_digest"] == ref_first["config_digest"] for r in runs),
                "same_seed": all(r["seed"] == ref_first["seed"] for r in runs),
                "digests_identical_across_repeats": all(r["digests"]["__all__"] == ref_first["digests"]["__all__"] for r in runs),
                "counters_identical_across_repeats": all(r["deterministic_view"] == ref_first["deterministic_view"] for r in runs),
                "instrumentation_leaves_results_unchanged": plain_same if plain is not None else None,
                "differences": diffs,
            },
        }

    jpath = out / "benchmark_reference.json"
    prev = json.loads(jpath.read_text(encoding="utf-8")) if jpath.exists() else {}
    if prev.get("profile_spec") == spec.to_dict():
        scenarios = {**prev.get("scenarios", {}), **scenarios}
        schemes = sorted(scenarios)
    data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "git": _git(), "profile_spec": spec.to_dict(), "data_hash": data_hash, "config_digests": cfg_digests,
        "seed": reference.PIPELINE_SEED, "repeats": args.repeats, "threads": args.threads,
        "environment": reference.capture_environment(), "scenarios": scenarios,
        "baseline_artifacts": sorted(k for k in json.loads((out / "baseline" / schemes[0] / "digests.json").read_text(encoding="utf-8")) if k != "__all__"),
        "not_available": NOT_AVAILABLE, "limits": LIMITS,
        "baseline_digests": {s: json.loads((out / "baseline" / s / "digests.json").read_text(encoding="utf-8"))["__all__"] for s in schemes},
    }
    (out / "benchmark_reference.json").write_text(json.dumps(data, indent=1, sort_keys=True, default=str), encoding="utf-8")
    notes = Path(args.notes).read_text(encoding="utf-8") if args.notes and Path(args.notes).exists() else None
    (out / "benchmark_reference.md").write_text(report.render_markdown(data, notes), encoding="utf-8")
    print(f"\nÉcrit : {out / 'benchmark_reference.json'} et .md")
    _ = artifacts
    return 0


def cmd_compare(args) -> int:
    from patrick.benchmark import artifacts
    res = artifacts.compare_baselines(args.dir_a, args.dir_b)
    print(json.dumps(res, indent=1))
    return 0 if res["identical"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m patrick.benchmark")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--profile", default="reference", choices=["reference", "tiny"])
    r.add_argument("--schemes", default="walkforward,cpcv")
    r.add_argument("--repeats", type=int, default=2)
    r.add_argument("--threads", type=int, default=4)
    r.add_argument("--out", default="benchmarks")
    r.add_argument("--workdir", default=None)
    r.add_argument("--notes", default="benchmarks/reference_notes.md")
    r.add_argument("--skip-plain", action="store_true")
    r.add_argument("--warm", action="store_true")
    r.add_argument("--env", action="append", default=[], metavar="KEY=VAL",
                   help="variables d'optimisation activées pour CE run (ex. PATRICK_PARAMETRIC_JOBS=4) ; "
                        "sans --env, le comportement historique est mesuré")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("compare")
    c.add_argument("dir_a")
    c.add_argument("dir_b")
    c.set_defaults(fn=cmd_compare)
    args = ap.parse_args(argv)
    return args.fn(args)
