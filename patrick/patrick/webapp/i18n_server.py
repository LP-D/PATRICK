"""Traduction FR → EN des messages produits côté serveur (domaine, validation, API), affichés tels quels par l'interface.

Ces textes naissent dans des modules sans notion de langue (`validation/`, `tracking/`, `fund/`…, aussi utilisés par la ligne de
commande) : le français y reste la source. Au moment de l'affichage, `translate(texte, lang)` les remplace par leur équivalent anglais
quand l'interface est en anglais ; un message inconnu reste inchangé (jamais de perte d'information, au pire du français).
Exposé aux gabarits par le filtre Jinja `tx` et au code Python par `translate`.

Chaque entrée est `(motif regex, gabarit anglais)` ; les groupes nommés du motif remplissent les `{champs}` du gabarit.
`rest` désigne une suite traduite récursivement. Un test (`tests/test_i18n_server.py`) vérifie chaque motif sur un message réel.
"""
from __future__ import annotations

import re

# Les motifs et gabarits longs sont écrits en chaînes adjacentes : lisibles tels quels, un tuple par règle.
# ruff: noqa: ISC004

# (motif, gabarit EN). Les motifs sont ancrés (fullmatch) ; `\.?` tolère le point final.
_RULES: list[tuple[str, str]] = [
    # --- validation/pbo_reliability.py
    (r"PBO non calculé \((?P<n>\d+) blocs disponibles\)\. (?P<rest>.+)", "PBO not computed ({n} blocks available). {rest}"),
    (r"PBO nécessite au moins (?P<k>\d+) blocs temporels \(n_wf_folds, après retrait éventuel du bloc le plus ancien pour parité\) : "
     r"C\((?P<a>\d+), (?P<b>\d+)\) = (?P<c>\d+) combinaisons IS/OOS, au-dessus du plancher de (?P<f>\d+) "
     r"\(règle n\*p>=5 et n\*\(1-p\)>=5 pour une proportion, pire cas p=0\.5\) -- un plancher NÉCESSAIRE mais pas suffisant : "
     r"les combinaisons CSCV ne sont pas indépendantes \(elles partagent des blocs\), le vrai besoin est plus élevé\.",
     "PBO needs at least {k} time blocks (n_wf_folds, after dropping the oldest block if needed for parity): C({a}, {b}) = {c} IS/OOS "
     "combinations, above the floor of {f} (rule n*p>=5 and n*(1-p)>=5 for a proportion, worst case p=0.5) -- a NECESSARY but not "
     "sufficient floor: CSCV combinations are not independent (they share blocks), the real requirement is higher."),
    # --- tracking/kpi_summary.py
    (r"Aucun candidat de la grille d'exploration n'a de résultat pour ce lancement\.",
     "No candidate of the exploration grid has a result for this launch."),
    (r"Tous les candidats sont comparés sur la même fenêtre : la fenêtre totale \(un seul entraînement par candidat, testé d'un coup "
     r"sur toute la période hors-échantillon ; seul le meilleur de chaque horizon passe ensuite au walk-forward\)\. Le meilleur y étant "
     r"choisi, son score sur cette fenêtre est optimiste : compare-le à sa performance en walk-forward \(toute sa période\) et au "
     r"holdout\.",
     "All candidates are compared on the same window: the total window (a single training per candidate, tested at once over the whole "
     "out-of-sample period; only the best of each horizon then goes on to the walk-forward). Since the best one is picked there, its "
     "score on this window is optimistic: compare it with its walk-forward performance (its whole period) and with the holdout."),
    (r"Tous les candidats sont comparés sur la même fenêtre : le premier fold \(dépistage par étapes : seul le meilleur de chaque "
     r"horizon est évalué sur les folds suivants\)\. Le meilleur y étant choisi, son score sur cette fenêtre est optimiste : "
     r"compare-le à sa performance sur toute sa période et au holdout\.",
     "All candidates are compared on the same window: the first fold (staged screening: only the best of each horizon is evaluated "
     "on the following folds). Since the best one is picked there, its score on this window is optimistic: compare it with its "
     "performance over its whole period and with the holdout."),
    (r"Tous les candidats sont comparés sur la même fenêtre : l'ensemble des folds de validation\.",
     "All candidates are compared on the same window: all the validation folds."),
    # --- validation/equity_sufficiency.py, feasibility.py, history_length.py
    (r"(?P<n>\d+) jours de cotation disponibles \(seuil minimum : (?P<m>\d+)j / (?P<y>[\d.]+) ans\)\.",
     "{n} trading days available (minimum threshold: {m}d / {y} years)."),
    (r"Historique insuffisant pour (?P<s>\S+) : (?P<n>\d+) jour\(s\) de cotation disponible\(s\), (?P<m>\d+)j \((?P<y>[\d.]+) ans\) "
     r"requis avant tout entraînement \(l'affichage prix/fondamentaux reste consultable sous ce seuil\)\.",
     "Insufficient history for {s}: {n} trading day(s) available, {m}d ({y} years) required before any training "
     "(price/fundamentals display remains available below this threshold)."),
    (r"Historique suffisant pour (?P<s>\S+) : (?P<n>\d+)j disponibles, (?P<m>\d+)j requis pour un horizon de (?P<h>\d+)j\.",
     "Sufficient history for {s}: {n}d available, {m}d required for a {h}d horizon."),
    (r"Historique insuffisant pour (?P<s>\S+) : (?P<n>\d+)j disponibles, (?P<m>\d+)j requis pour un horizon de (?P<h>\d+)j\.",
     "Insufficient history for {s}: {n}d available, {m}d required for a {h}d horizon."),
    (r"Historique suffisant pour (?P<s>\S+) : disponible depuis (?P<d>[\d-]+)\.", "Sufficient history for {s}: available since {d}."),
    (r"Historique insuffisant pour (?P<s>\S+) : disponible depuis (?P<d>[\d-]+), (?P<y>[\d.]+) ans requis \(seuil (?P<t>[\d-]+)\)\.",
     "Insufficient history for {s}: available since {d}, {y} years required (threshold {t})."),
    (r"(?P<head>.+) \[données insuffisantes : (?P<n>\d+)j/(?P<m>\d+)j\]", "{head} [insufficient data: {n}d/{m}d]"),
    (r"\s*\[données insuffisantes : (?P<n>\d+)j/(?P<m>\d+)j\]", " [insufficient data: {n}d/{m}d]"),
    # --- features/guida.py
    (r"Carry non applicable aux actions individuelles au sens Guida : ce facteur repose sur une structure de futures/differentiel de "
     r"taux qui n'existe pas pour une action au comptant\.",
     "Carry does not apply to individual stocks in the Guida sense: this factor relies on a futures / rate-differential structure "
     "that does not exist for a cash equity."),
    (r"Cross-sectional momentum desactive pour les actions individuelles : l'univers actions \((?P<n>\d+) tickers\) est sous le seuil "
     r"minimum \((?P<m>\d+)\) requis pour un classement relatif non degenere\.",
     "Cross-sectional momentum is disabled for individual stocks: the equity universe ({n} tickers) is below the minimum "
     "({m}) required for a non-degenerate relative ranking."),
    # --- tracking/history.py
    (r"aucune P\(hausse\) enregistrée \(run antérieur à la migration 0024\)", "no P(up) recorded (run predates migration 0024)"),
    (r"(?P<n>\d+) prédictions hors échantillon < (?P<m>\d+)", "{n} out-of-sample predictions < {m}"),
    # --- validation/drift.py
    (r"Seulement (?P<n>\d+) observation\(s\) recente\(s\) pour (?P<s>\S+) -- (?P<m>\d+) requises pour un PSI fiable\.",
     "Only {n} recent observation(s) for {s} -- {m} required for a reliable PSI."),
    (r"Data drift calculable \(PSI=(?P<psi>[\d.]+), (?P<st>\w+)\) mais cible pas encore realisee en volume suffisant "
     r"\((?P<a>\d+)/(?P<b>\d+)\) pour le concept drift -- badge provisoire tant que l'horizon \((?P<h>\d+)j\) n'est pas ecoule sur "
     r"assez de predictions\.",
     "Data drift computable (PSI={psi}, {st}) but target not yet realised in sufficient volume ({a}/{b}) for concept drift -- "
     "provisional badge until the horizon ({h}d) has elapsed on enough predictions."),
    (r"Data drift : PSI=(?P<psi>[\d.]+) \((?P<st>\w+)\)\. Concept drift \(Page-Hinkley sur (?P<n>\d+) predictions realisees\) : "
     r"(?P<v>detecte|non detecte)\.",
     "Data drift: PSI={psi} ({st}). Concept drift (Page-Hinkley on {n} realised predictions): {v}."),
    # --- fund/prices.py
    (r"taux de référence (?P<c>\w+) : constante (?P<v>[\d.,]+ ?%) \(FRED indisponible ou non configuré\)",
     "{c} reference rate: constant {v} (FRED unavailable or not configured)"),
    (r"(?P<s>\S+) : aucune cotation disponible", "{s}: no quote available"),
    (r"(?P<s>\S+) : cotations hors ligne \(dernière donnée stockée (?P<d>[\d-]+)\)", "{s}: offline quotes (last stored data {d})"),
    (r"change (?P<a>\w+)/(?P<b>\w+) indisponible", "{a}/{b} exchange rate unavailable"),
    # --- webapp/app.py : libellés et messages d'API
    (r"Run introuvable.*", "Run not found."),
    (r"Résultat introuvable", "Result not found."),
    (r"Artefact introuvable", "Artifact not found."),
    (r"Cible inconnue", "Unknown target."),
    (r"Symbole inconnu", "Unknown symbol."),
    (r"Famille inconnue", "Unknown family."),
    (r"Profil d'entraînement inconnu\.", "Unknown training profile."),
    (r"Configuration de run introuvable\.", "Run configuration not found."),
    (r"Configuration du run illisible : (?P<e>.+)", "The run configuration cannot be read: {e}"),
    (r"Stratégie introuvable", "Strategy not found."),
    (r"Position introuvable", "Position not found."),
    (r"Règle introuvable", "Rule not found."),
    (r"Racine de future inconnue", "Unknown future root."),
    (r"Ce run n'est plus actif\.", "This run is no longer active."),
    (r"Cet élément n'est plus dans la file\.", "This item is no longer in the queue."),
    (r"Un run sélectionné est introuvable\.", "A selected run cannot be found."),
    (r"Un run en cours ne peut pas être renommé\.", "A running run cannot be renamed."),
    (r"Sélectionne entre 2 et 4 runs à comparer\.", "Select between 2 and 4 runs to compare."),
    (r"Les runs de reinforcement learning se comparent entre eux, pas avec des runs ML ou DL\.",
     "Reinforcement learning runs are compared with each other, not with ML or DL runs."),
    (r"La date de début doit précéder la date de fin\.", "The start date must be before the end date."),
    (r"La durée minimale dépasse la durée maximale\.", "The minimum duration exceeds the maximum duration."),
    (r"Run pas encore terminé.*", "Run not finished yet."),
    (r"Aucun run conseillé à lancer\.", "No recommended run to launch."),
    (r"FRED_API_KEY absente : ALFRED est inaccessible\.", "FRED_API_KEY is missing: ALFRED is unreachable."),
    (r"Suggestion de réentraînement indisponible pour cette famille\.", "Retraining suggestion unavailable for this family."),
    (r"Suggestion de réentraînement introuvable pour ce run\.", "Retraining suggestion not found for this run."),
    (r"jobs doit être un entier\.", "jobs must be an integer."),
    (r"order doit être une liste d'identifiants\.", "order must be a list of identifiers."),
    (r"Base de données occupée \(un run écrit \?\) : réessaie dans un instant\.", "Database busy (a run is writing?): try again in a moment."),
    (r"(?P<name>\w+) doit être strictement compris entre 0 et 1 \(reçu (?P<v>.+)\)\.", "{name} must be strictly between 0 and 1 (got {v})."),
    # --- webapp/app.py : les quatre mouvements du modèle et les directions (libellés produits côté Python)
    (r"Hausse forte", "Strong up"), (r"Hausse faible", "Slight up"), (r"Baisse faible", "Slight down"), (r"Baisse forte", "Strong down"),
    (r"Hausse prédite", "Predicted up"), (r"Baisse prédite", "Predicted down"), (r"Hausse", "Up"), (r"Baisse", "Down"),
    (r"Surperformance forte", "Strong outperformance"), (r"Surperformance faible", "Slight outperformance"),
    (r"Sous-performance forte", "Strong underperformance"), (r"Sous-performance faible", "Slight underperformance"),
    # --- wealth/ledger.py (types de mouvement) et tracking/history.py (libellé du PBO)
    (r"Versement", "Deposit"), (r"Retrait", "Withdrawal"), (r"Achat", "Buy"), (r"Vente", "Sale"), (r"Dividende", "Dividend"),
    (r"Frais", "Fees"), (r"Intérêts / bonus", "Interest / bonus"), (r"Dépôt à terme", "Term deposit"),
    (r"blocs walk-forward", "walk-forward blocks"), (r"chemins CPCV", "CPCV paths"),
    # --- webapp/forms.py, forms_rl.py : erreurs de validation des formulaires (`l` = libellé du champ, traduit à part)
    (r"« (?P<l>.+?) » : valeur numérique invalide\.", "“{l}”: invalid numeric value."),
    (r"« (?P<l>.+?) » : valeur numérique décimale invalide\.", "“{l}”: invalid decimal value."),
    (r"« (?P<l>.+?) » : valeur entière invalide\.", "“{l}”: invalid integer value."),
    (r"« (?P<l>.+?) » : choix invalide\.", "“{l}”: invalid choice."),
    (r"« (?P<l>.+?) » doit être compris entre (?P<lo>\S+) et (?P<hi>\S+)\.", "“{l}” must be between {lo} and {hi}."),
    (r"« (?P<l>.+?) » : le minimum doit être strictement inférieur au maximum\.", "“{l}”: the minimum must be strictly below the maximum."),
    (r"« (?P<l>.+?) » : hors de la plage autorisée \[(?P<lo>[^,\]]+), (?P<hi>[^\]]+)\]\.", "“{l}”: outside the allowed range [{lo}, {hi}]."),
    (r"« (?P<l>.+?) » : valeur\(s\) (?P<v>.+) hors de la plage autorisée \[(?P<lo>[^,\]]+), (?P<hi>[^\]]+)\]\.",
     "“{l}”: value(s) {v} outside the allowed range [{lo}, {hi}]."),
    (r"« (?P<l>.+?) » : liste d'entiers invalide\.", "“{l}”: invalid list of integers."),
    (r"« (?P<l>.+?) » ne peut pas être vide\.", "“{l}” cannot be empty."),
    (r"« (?P<l>.+?) » doit être un entier strictement positif\.", "“{l}” must be a strictly positive integer."),
    (r"« (?P<l>.+?) » doit être un entier >= (?P<n>\d+)\.", "“{l}” must be an integer >= {n}."),
    (r"« (?P<l>.+?) » doit être dans \]0, 1\] \(vide = désactivé\)\.", "“{l}” must be in ]0, 1] (empty = disabled)."),
    (r"« (?P<l>.+?) » : choisis-en au moins une \((?P<f>.+)\)\.", "“{l}”: pick at least one ({f})."),
    (r"« Répertoire de sortie » : chemin invalide \(remontée de répertoire « \.\. » ou caractère interdit\)\.",
     "“Output directory”: invalid path (parent-directory traversal “..” or forbidden character)."),
    (r"« Type de cible » : l'alpha n'est pas disponible pour une cible FRED \(série macro\)\.",
     "“Target type”: alpha is not available for a FRED target (macro series)."),
    (r"« Cible » : (?P<s>\S+) est une série FRED : le RL tient une position sur une cible cotée\.",
     "“Target”: {s} is a FRED series: RL holds a position on a listed target."),
    (r"Régime : les seuils doivent vérifier 0 <= bas < haut <= 1\.", "Regime: thresholds must satisfy 0 <= low < high <= 1."),
    (r"Sélectionne au moins une cible\.", "Select at least one target."),
    (r"PyTorch n'est pas installé : les réseaux de neurones sont indisponibles\. Installe-le avec : (?P<cmd>.+?) \(ou (?P<alt>.+?)\)\.",
     "PyTorch is not installed: neural networks are unavailable. Install it with: {cmd} (or {alt})."),
    (r"« (?P<l>.+?) » : (?P<rest>.+)", "“{l}”: {rest}"),
    # --- paths.py : disque de données absent
    (r"Le disque de données (?P<p>.+) est introuvable\. Branche-le, ou lance `patrick data use <dossier>` "
     r"\(ou `patrick data use --none`\) pour changer de racine de données\.",
     "The data disk {p} was not found. Plug it in, or run `patrick data use <folder>` (or `patrick data use --none`) to change "
     "the data root."),
]
_COMPILED = [(re.compile(pat, re.DOTALL), en) for pat, en in _RULES]


# Libellés de champs des formulaires qui n'ont pas d'équivalent exact dans le catalogue de traductions de l'interface.
_EXTRA_LABELS = {
    "Embargo (barres)": "Embargo (bars)", "Historique minimum": "Minimum history", "Que prédire": "What to predict",
    "Seuil de réduction |corr|": "Reduction threshold |corr|", "Répertoire de sortie": "Output directory",
    "Appareil de calcul": "Compute device", "Couches du réseau": "Network layers",
    "Agents moyennés (graines)": "Averaged agents (seeds)", "Réseaux moyennés (graines)": "Averaged networks (seeds)",
    "Espace d'actions": "Action space", "Facteur d'actualisation (gamma)": "Discount factor (gamma)",
    "Lignes empilées (observation)": "Stacked rows (observation)", "Pas d'entraînement": "Training steps",
    "Taille du noyau (CNN1D)": "Kernel size (CNN1D)", "Vente à découvert": "Short selling",
}
_FR_TO_EN: dict[str, str] | None = None


def _label_en(label: str) -> str:
    """Libellé de champ en anglais : retrouvé par son texte français dans le catalogue de traductions (sinon inchangé)."""
    global _FR_TO_EN
    if _FR_TO_EN is None:
        from patrick.webapp.i18n import STRINGS
        _FR_TO_EN = {v["fr"].strip(): v["en"].strip() for v in STRINGS.values() if v.get("fr") and v.get("en")}
    return _EXTRA_LABELS.get(label.strip()) or _FR_TO_EN.get(label.strip(), label)


def translate(text: str, lang: str) -> str:
    """`text` en anglais si `lang == "en"` et que le message est connu ; sinon `text` tel quel."""
    if lang != "en" or not isinstance(text, str) or not text:
        return text
    for pattern, template in _COMPILED:
        m = pattern.fullmatch(text.strip())
        if m is None:
            continue
        fields = m.groupdict()
        if "rest" in fields:
            fields["rest"] = translate(fields["rest"], lang)
        if "l" in fields:
            fields["l"] = _label_en(fields["l"])
        return template.format(**fields)
    return text
