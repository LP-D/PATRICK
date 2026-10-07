"""Human-readable steps for the launch station's "Avancement" panel.

The pipeline prints technical lines (`[SCAN] 48 evaluations in 2.8min`,
`h= 5d fold2: 12 cumulative rows [83s]`, parameter dumps...). Showing them
raw made the panel read like a debugger. `humanize_log` turns the lines it
recognises into short sentences in the user's language and drops the rest
(tables, parameter dumps, file paths, blank lines) — the raw log stays
available, collapsed, under "Journal technique".

Pure functions, no I/O: the worker keeps writing the raw lines unchanged
(`jobs.log_tail`), only the web layer rewrites them, so a run launched before
this module existed is displayed just as well.
"""
from __future__ import annotations

import re

DEFAULT_LANG = "fr"
MAX_STEPS = 40

# {key: {"fr": ..., "en": ...}} -- placeholders are filled by `_STEPS` below.
STEP_STRINGS: dict[str, dict[str, str]] = {
    "ingest_start": {"fr": "Téléchargement des données de marché…", "en": "Downloading market data…"},
    "yf_kept": {"fr": "Yahoo Finance : {kept} séries retenues sur {total} demandées.",
                "en": "Yahoo Finance: {kept} of {total} requested series kept."},
    "alignment": {"fr": "Alignement des clôtures : {n} séries décalées d'une séance pour éviter toute fuite d'information du futur.",
                  "en": "Close alignment: {n} series shifted by one session so no future information leaks in."},
    "fred_no_key": {"fr": "Clé FRED absente : les séries macro sont prises dans leur version révisée aujourd'hui, pas telle que connue à l'époque.",
                    "en": "No FRED key: macro series use today's revised values, not as originally published."},
    "alfred_fallback": {"fr": "Mode historique ALFRED indisponible sans clé FRED : repli sur les données publiques.",
                        "en": "ALFRED vintage mode needs a FRED key: falling back to public data."},
    "quality": {"fr": "Contrôle qualité : {n} séries écartées sur {total}.",
                "en": "Quality check: {n} of {total} series excluded."},
    "quality_item": {"fr": "   • {series} écartée ({reason}).", "en": "   • {series} excluded ({reason})."},
    "reason_rendement_aberrant": {"fr": "rendement aberrant", "en": "outlier return"},
    "reason_trou_de_cotation": {"fr": "trou dans les cotations", "en": "gap in quotes"},
    "ingest_done": {"fr": "Données prêtes : {rows} séances, {cols} séries ({sec} s). Cible : {target}.",
                    "en": "Data ready: {rows} sessions, {cols} series ({sec}s). Target: {target}."},
    "data_ready": {"fr": "Données rassemblées : {rows} séances × {cols} séries ({sec} s).",
                   "en": "Data gathered: {rows} sessions × {cols} series ({sec}s)."},
    "cache_hit": {"fr": "Données déjà en cache : réutilisées sans retéléchargement.",
                  "en": "Data already cached: reused without re-downloading."},
    "cache_refetch": {"fr": "Cache obsolète : nouveau téléchargement des données.",
                      "en": "Stale cache: downloading the data again."},
    "features_start": {"fr": "Construction des variables explicatives (prix, volatilité, macro…)…",
                       "en": "Building the explanatory variables (prices, volatility, macro…)…"},
    "features_base": {"fr": "{n} variables de base construites ({sec} s).",
                      "en": "{n} base variables built ({sec}s)."},
    "features_full": {"fr": "Jeu complet de variables prêt : {n} colonnes.",
                      "en": "Full variable set ready: {n} columns."},
    "fold": {"fr": "Découpage de validation, pli {k} : test du {start} au {end}.",
             "en": "Validation split, fold {k}: tested from {start} to {end}."},
    "holdout": {"fr": "Période de contrôle finale réservée : {n} séances ({start} → {end}), jamais utilisée pour choisir ni régler un modèle.",
                "en": "Final control period set aside: {n} sessions ({start} → {end}), never used to pick or tune a model."},
    "holdout_short": {"fr": "Historique trop court pour réserver {months} mois de contrôle : période de contrôle désactivée.",
                      "en": "History too short to set aside {months} months of control data: control period disabled."},
    "interactions": {"fr": "{n} interactions entre variables découvertes.",
                     "en": "{n} variable interactions discovered."},
    "interactions_skipped": {"fr": "Interactions entre variables : données insuffisantes, étape ignorée.",
                             "en": "Variable interactions: not enough data, step skipped."},
    "cpcv": {"fr": "Validation croisée purgée : {combos} combinaisons de test, {paths} trajectoires reconstituées.",
             "en": "Purged cross-validation: {combos} test combinations, {paths} rebuilt paths."},
    "scan_fold": {"fr": "Balayage des configurations — horizon {h} j, pli {k} évalué ({rows} évaluations, {sec} s).",
                  "en": "Configuration sweep — {h}-day horizon, fold {k} evaluated ({rows} evaluations, {sec}s)."},
    "scan_screening": {"fr": "Balayage des configurations — horizon {h} j, présélection terminée ({rows} évaluations, {sec} s).",
                       "en": "Configuration sweep — {h}-day horizon, screening done ({rows} evaluations, {sec}s)."},
    "screening": {"fr": "Présélection, horizon {h} j : {kept} configurations finalistes sur {total}.",
                  "en": "Screening, {h}-day horizon: {kept} finalist configurations out of {total}."},
    "scan_done": {"fr": "Balayage terminé : {n} évaluations en {minutes} min.",
                  "en": "Sweep finished: {n} evaluations in {minutes} min."},
    "best": {"fr": "Meilleure configuration avant réglage (horizon {h} j) : {algo}, {n} variables, F1 directionnel {f1}.",
             "en": "Best configuration before tuning ({h}-day horizon): {algo}, {n} variables, directional F1 {f1}."},
    "stability_low": {"fr": "Stabilité de la sélection faible à {h} j (indice de Jaccard {jaccard}, seuil {threshold}) : les variables retenues changent beaucoup d'un pli à l'autre.",
                      "en": "Low selection stability at {h} days (Jaccard {jaccard}, threshold {threshold}): the chosen variables change a lot from fold to fold."},
    "stability_other": {"fr": "Stabilité de la sélection (horizon {h} j) : avertissement émis, voir le journal technique.",
                        "en": "Selection stability ({h}-day horizon): warning raised, see the technical log."},
    "holdout_diag": {"fr": "Diagnostic sur la période de contrôle : {n} essais évalués (lecture seule, aucun choix n'en dépend).",
                     "en": "Control-period diagnostic: {n} trials evaluated (read-only, nothing is chosen from it)."},
    "champion": {"fr": "Duel avec le modèle de référence (horizon {h} j) : {decision}.",
                 "en": "Duel against the reference model ({h}-day horizon): {decision}."},
    "champion_promoted_first": {"fr": "premier modèle de référence enregistré", "en": "first reference model recorded"},
    "champion_not_compared": {"fr": "comparaison impossible", "en": "comparison not possible"},
    "champion_challenger_wins": {"fr": "le nouveau modèle l'emporte", "en": "the new model wins"},
    "champion_champion_wins": {"fr": "le modèle de référence est conservé", "en": "the reference model is kept"},
    "champion_error": {"fr": "erreur pendant le duel", "en": "error during the duel"},
    "optuna": {"fr": "Réglage fin (Optuna) des {n} meilleures configurations : {trials} essais chacune.",
               "en": "Fine tuning (Optuna) of the {n} best configurations: {trials} trials each."},
    "optuna_done": {"fr": "Réglage terminé (horizon {h} j, {algo}, {n} variables) : F1 directionnel {f1} en validation croisée.",
                    "en": "Tuning done ({h}-day horizon, {algo}, {n} variables): directional F1 {f1} in cross-validation."},
    "export_model": {"fr": "Modèle gagnant sauvegardé : {algo}, horizon {h} j.",
                     "en": "Winning model saved: {algo}, {h}-day horizon."},
    "export_tuned": {"fr": "Configurations affinées exportées.", "en": "Tuned configurations exported."},
    "export_leaderboard": {"fr": "Classement des configurations exporté.", "en": "Configuration leaderboard exported."},
    "kpi": {"fr": "Synthèse des modèles produite.", "en": "Model summary produced."},
    "calibration": {"fr": "Calibration : {skipped} évaluations sur {total} n'ont pas pu être calibrées, leurs scores ne sont pas comparables aux autres.",
                    "en": "Calibration: {skipped} of {total} evaluations could not be calibrated, so their scores are not comparable."},
    "dm_last_fold": {"fr": "Test de Diebold-Mariano calculé sur le dernier pli (pas de période de contrôle).",
                     "en": "Diebold-Mariano test computed on the last fold (no control period)."},
    "warn_generic": {"fr": "Avertissement technique émis par le pipeline (détail dans le journal technique).",
                     "en": "Technical warning raised by the pipeline (details in the technical log)."},
    "error_generic": {"fr": "Erreur signalée : {message}", "en": "Error reported: {message}"},
}


def _text(lang: str, key: str, **params) -> str:
    entry = STEP_STRINGS[key]
    return (entry.get(lang) or entry[DEFAULT_LANG]).format(**params)


def _num(value: str | float, digits: int, lang: str) -> str:
    """`0.5128` -> `0,513` in French, `0.513` in English."""
    out = f"{float(value):.{digits}f}"
    return out.replace(".", ",") if lang == "fr" else out


def _int(value: str | int, lang: str) -> str:
    """Thousands separated by a no-break space in French (4 892), a comma otherwise."""
    n = f"{int(value):,}"
    return n.replace(",", "\u00a0") if lang == "fr" else n


def _date(iso: str, lang: str) -> str:
    """`2017-08-16` -> `16/08/2017` in French; unchanged otherwise."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m and lang == "fr" else iso


def _horizon(h: str) -> str:
    return str(int(h))


# Each rule: (regex, handler(match, lang) -> (key, params, level, group) | None).
# `group`: consecutive steps of the same group replace each other (a sweep
# prints one line per fold; only the latest one is worth showing).
# `level`: "info" | "warn" | "error".
_Rule = tuple["re.Pattern[str]", object]


def _rules() -> list[_Rule]:
    R = re.compile

    def rule(pattern, key, level="info", group=None, params=None):
        def handler(m, lang):
            return key, (params(m, lang) if params else {}), level, group
        return R(pattern), handler

    def quality_item(m, lang):
        reason_key = f"reason_{m.group('reason')}"
        reason = _text(lang, reason_key) if reason_key in STEP_STRINGS else m.group("reason").replace("_", " ")
        return "quality_item", {"series": m.group("series"), "reason": reason}, "warn", None

    def champion(m, lang):
        decision_key = f"champion_{m.group('decision')}"
        decision = _text(lang, decision_key) if decision_key in STEP_STRINGS else m.group("decision").replace("_", " ")
        return "champion", {"h": _horizon(m.group("h")), "decision": decision}, "info", None

    def stability(m, lang):
        jm = re.search(r"Mean Jaccard \(([\d.]+)\) below the threshold \(([\d.]+)\)", m.group("rest"))
        if jm:
            return "stability_low", {"h": _horizon(m.group("h")), "jaccard": _num(jm.group(1), 2, lang),
                                     "threshold": _num(jm.group(2), 2, lang)}, "warn", None
        return "stability_other", {"h": _horizon(m.group("h"))}, "warn", None

    def export_line(m, lang):
        path = m.group("path")
        if path.endswith("_tuned.csv"):
            return "export_tuned", {}, "info", None
        if path.endswith("_leaderboard.csv"):
            return "export_leaderboard", {}, "info", None
        return None

    return [
        rule(r"^\[DATA\] Ingestion", "ingest_start"),
        rule(r"^\[DATA\] (?P<rows>\d+) rows × (?P<cols>\d+) columns \((?P<sec>[\d.]+)s",
             "data_ready", params=lambda m, l: {"rows": _int(m["rows"], l), "cols": _int(m["cols"], l),
                                                "sec": _num(m["sec"], 1, l)}),
        rule(r"^\s*\[yfinance\] (?P<kept>\d+)/(?P<total>\d+) tickers kept",
             "yf_kept", params=lambda m, l: {"kept": m["kept"], "total": m["total"]}),
        rule(r"^\s*\[ALIGNMENT\] (?P<n>\d+) tickers shifted", "alignment",
             params=lambda m, l: {"n": m["n"]}),
        rule(r"FRED_API_KEY not set", "fred_no_key", "warn"),
        rule(r"fred_point_in_time='alfred' requires FRED_API_KEY", "alfred_fallback", "warn"),
        rule(r"^\s*\[QUALITY\] (?P<n>\d+)/(?P<total>\d+) series excluded", "quality", "warn",
             params=lambda m, l: {"n": m["n"], "total": m["total"]}),
        (R(r"^\s+- (?P<series>\S+): (?P<reason>\w+) --"), quality_item),
        rule(r"^\[INGEST\] \((?P<rows>\d+), (?P<cols>\d+)\) \((?P<sec>[\d.]+)s\) \| cible=(?P<target>\S+)",
             "ingest_done", params=lambda m, l: {"rows": _int(m["rows"], l), "cols": _int(m["cols"], l),
                                                 "sec": _num(m["sec"], 1, l), "target": m["target"]}),
        rule(r"^\[(?:CACHE|CACHE_LOCAL|REPLAY)\] .*(?:already cached|reused from local cache|snapshot)",
             "cache_hit"),
        rule(r"^\[CACHE\] .*refetching", "cache_refetch", "warn"),
        rule(r"^\[FEATURES\] [Bb]uilding (?:the )?base pool", "features_start"),
        rule(r"^\[FEATURES\] [Bb]ase pool: (?P<n>\d+) columns \((?P<sec>[\d.]+)s\)", "features_base",
             params=lambda m, l: {"n": m["n"], "sec": _num(m["sec"], 0, l)}),
        rule(r"^\[FEATURES\] [Ff]ull pool.*?(?P<n>\d+) columns", "features_full",
             params=lambda m, l: {"n": m["n"]}),
        rule(r"^\s*Fold (?P<k>\d+): train -> \S+ \| test (?P<start>\S+) -> (?P<end>\S+)", "fold",
             params=lambda m, l: {"k": m["k"], "start": _date(m["start"], l), "end": _date(m["end"], l)}),
        rule(r"^\[HOLDOUT\] (?P<n>\d+) rows reserved \((?P<start>\S+) -> (?P<end>\S+)\)", "holdout",
             params=lambda m, l: {"n": m["n"], "start": _date(m["start"], l), "end": _date(m["end"], l)}),
        rule(r"history too short for a (?P<months>\d+)-month holdout", "holdout_short", "warn",
             params=lambda m, l: {"months": m["months"]}),
        rule(r"^\s*\[INTERACTIONS\] (?P<n>\d+) formulas discovered", "interactions",
             params=lambda m, l: {"n": m["n"]}),
        rule(r"^\s*\[INTERACTIONS\] not enough data", "interactions_skipped", "warn"),
        rule(r"^\[CPCV\] N=\d+ groups, k=\d+ -> (?P<combos>\d+) combinations, (?P<paths>\d+) ",
             "cpcv", params=lambda m, l: {"combos": m["combos"], "paths": m["paths"]}),
        rule(r"^\s*h=\s*(?P<h>\d+)d fold(?P<k>\d+): (?P<rows>\d+) cumulative rows \[(?P<sec>\d+)s\]",
             "scan_fold", group="scan",
             params=lambda m, l: {"h": _horizon(m["h"]), "k": m["k"], "rows": m["rows"], "sec": m["sec"]}),
        rule(r"^\s*h=\s*(?P<h>\d+)d screening: (?P<rows>\d+) cumulative rows \[(?P<sec>\d+)s\]",
             "scan_screening", group="scan",
             params=lambda m, l: {"h": _horizon(m["h"]), "rows": m["rows"], "sec": m["sec"]}),
        rule(r"^\s*\[SCREENING\] h=(?P<h>\d+)d \S+: (?P<kept>\d+)/(?P<total>\d+) finalistes",
             "screening", params=lambda m, l: {"h": _horizon(m["h"]), "kept": m["kept"], "total": m["total"]}),
        rule(r"^\s*\[SCREENING\] h=(?P<h>\d+)d \S+: (?P<total>\d+) candidats .*?(?P<kept>\d+) finaliste",
             "screening", params=lambda m, l: {"h": _horizon(m["h"]), "kept": m["kept"], "total": m["total"]}),
        rule(r"^\[SCAN\] (?P<n>\d+) evaluations in (?P<minutes>[\d.]+)min", "scan_done",
             params=lambda m, l: {"n": m["n"], "minutes": _num(m["minutes"], 1, l)}),
        rule(r"^\[BEST before Optuna\] h=(?P<h>\d+)d \S+ N=(?P<n>\d+) \S+ (?P<algo>\S+) -> F1_dir=(?P<f1>[\d.]+)",
             "best", params=lambda m, l: {"h": _horizon(m["h"]), "n": m["n"], "algo": m["algo"],
                                          "f1": _num(m["f1"], 3, l)}),
        (R(r"^\s*\[STABILITY\] h=(?P<h>\d+)d: (?P<rest>.*)$"), lambda m, lang: stability(m, lang)),
        rule(r"^\[HOLDOUT DIAGNOSTIC\] evaluating (?P<n>\d+) trials", "holdout_diag",
             params=lambda m, l: {"n": m["n"]}),
        (R(r"^\[CHAMPION\] h=(?P<h>\d+)d: (?P<decision>\w+)"), lambda m, lang: champion(m, lang)),
        rule(r"^\[OPTUNA\] tuning the (?P<n>\d+) best configs \((?P<trials>\d+) trials",
             "optuna", params=lambda m, l: {"n": m["n"], "trials": m["trials"]}),
        rule(r"^\s*h=\s*(?P<h>\d+)d \S+ N=(?P<n>\d+) \S+ (?P<algo>\S+): cv_F1_dir=(?P<f1>[\d.]+)",
             "optuna_done", params=lambda m, l: {"h": _horizon(m["h"]), "n": m["n"], "algo": m["algo"],
                                                 "f1": _num(m["f1"], 3, l)}),
        rule(r"^\[EXPORT\] winning model \((?P<algo>[^,]+), h=(?P<h>\d+)d",
             "export_model", params=lambda m, l: {"algo": m["algo"], "h": _horizon(m["h"])}),
        (R(r"^\[EXPORT\] (?P<path>(?!winning model|phase timing)\S+)"), lambda m, lang: export_line(m, lang)),
        rule(r"^\[KPI\] ", "kpi"),
        rule(r"^\[CALIBRATION\] (?P<skipped>\d+) of (?P<total>\d+) scan fits ran UNCALIBRATED",
             "calibration", "warn", params=lambda m, l: {"skipped": m["skipped"], "total": m["total"]}),
        rule(r"Diebold-Mariano on the last walk-forward fold", "dm_last_fold", "warn"),
        (R(r"^\[ERREUR\] (?P<message>.*)$"),
         lambda m, lang: ("error_generic", {"message": m.group("message")}, "error", None)),
        # Must stay last among the warnings: any `[WARN...]` line not matched above.
        rule(r"^\s*\[WARN[^\]]*\]", "warn_generic", "warn"),
    ]


_RULES = _rules()


def humanize_log(lines: list[str], lang: str = DEFAULT_LANG, max_steps: int = MAX_STEPS) -> list[dict]:
    """Recognised pipeline lines -> `[{"text", "level"}]`, oldest first.

    Unrecognised lines are dropped. Consecutive lines of the same group (one
    per fold of a sweep) collapse into the latest one, and a repeat of the
    exact same sentence is not shown twice in a row. Only the last
    `max_steps` steps are returned.
    """
    steps: list[dict] = []
    last_group: str | None = None
    for line in lines or []:
        if not isinstance(line, str) or not line.strip():
            continue
        for pattern, handler in _RULES:
            m = pattern.search(line)
            if not m:
                continue
            outcome = handler(m, lang)
            if outcome is None:
                break  # recognised but deliberately hidden (e.g. a timing-log path)
            key, params, level, group = outcome
            step = {"text": _text(lang, key, **params), "level": level}
            if steps and steps[-1]["text"] == step["text"]:
                break
            if group is not None and group == last_group and steps:
                steps[-1] = step
            else:
                steps.append(step)
            last_group = group
            break
    return steps[-max_steps:]
