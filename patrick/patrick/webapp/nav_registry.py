"""feature/nav-categories-registry -- SEULE source de la navigation laterale
(`templates/base_v2.html`). Remplace les 12 liens `<a href="/...">` codes en
dur qui y vivaient. Documente dans design-system/patrick/MASTER.md, section
"Navigation Registry".

Regle : toute page HTML servie par `webapp/app.py` est declaree ici --
soit comme entree de nav (`NavEntry.url`), soit comme route enfant d'une
entree (`NavEntry.child_routes`, page parametree non listee dans la nav :
detail d'un run, fiche cible...). Toute autre route GET doit correspondre a
`NON_PAGE_PREFIXES`/`NON_PAGE_ROUTES` (API JSON, fichiers, redirects).
`tests/test_nav_registry.py::test_no_orphan_page_route` echoue sinon.

Aucune logique de nav ailleurs : le template itere `nav_sections(path)`
(expose en global Jinja par `app.py`), rien d'autre.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class NavCategory:
    key: str
    label: str        # libelle FR de repli (si `t` absent du contexte)
    label_key: str    # cle i18n.STRINGS


@dataclass(frozen=True)
class NavGroup:
    """Sous-dossier de l'arborescence (style explorateur de VS Code) : regroupe des entrees d'une meme categorie."""
    key: str
    category: str     # NavCategory.key
    label: str        # libelle FR de repli
    label_key: str    # cle i18n.STRINGS


@dataclass(frozen=True)
class NavEntry:
    slug: str
    label: str                  # libelle FR de repli
    url: str
    category: str               # NavCategory.key
    order: int                  # tri a l'interieur de la categorie
    label_key: str | None = None  # cle i18n.STRINGS, None = `label` tel quel
    child_routes: tuple[str, ...] = ()  # patterns FastAPI des pages enfants
    group: str = ""             # NavGroup.key ; vide = feuille directement sous la categorie


# Ordre fixe, jamais trie : c'est l'ordre des sections dans la sidebar.
CATEGORIES: tuple[NavCategory, ...] = (
    NavCategory("pilotage", "PILOTAGE", "nav_cat_pilotage"),
    NavCategory("modeles", "MODÈLES", "nav_cat_models"),
    NavCategory("classes_actifs", "CLASSES D'ACTIFS", "nav_cat_classes_actifs"),
    NavCategory("simulation", "SIMULATION", "nav_cat_simulation"),
    NavCategory("patrimoine", "PATRIMOINE", "nav_cat_patrimoine"),
)

# Sous-dossiers de l'arborescence. Un dossier prend la place de sa premiere entree (plus petit `order`) dans sa categorie ;
# une entree sans `group` est une feuille posee directement sous la categorie.
GROUPS: tuple[NavGroup, ...] = (
    NavGroup("suivi", "pilotage", "Suivi des modèles", "nav_grp_suivi"),
    NavGroup("signaux", "pilotage", "Signaux", "nav_grp_signaux"),
    NavGroup("recherche", "pilotage", "Recherche", "nav_grp_recherche"),
    NavGroup("donnees", "pilotage", "Données", "nav_grp_donnees"),
    NavGroup("marches", "classes_actifs", "Marchés", "nav_grp_marches"),
)

NAV_ENTRIES: tuple[NavEntry, ...] = (
    # PILOTAGE -- piloter la station : vue d'ensemble, suivi des modeles, signaux, recherche, sante des donnees.
    NavEntry("synthese", "Synthèse", "/", "pilotage", 10, "nav_home"),
    # Historique = la liste des runs ET leurs analyses (vue « Analyses » : carte cible x horizon, scores par algorithme, nuage RL) ;
    # la page d'analyse d'un run et la comparaison detaillee en dependent.
    NavEntry("runs", "Historique", "/runs", "pilotage", 20, "nav_runs", group="suivi",
             child_routes=("/runs/{run_id}", "/runs/{run_id}/detail", "/compare-runs",
                           "/runs/{run_id}/analyse", "/analyses/comparer")),
    NavEntry("models_registry", "Registre de modèles", "/modeles", "pilotage", 21, "nav_models_registry", group="suivi",
             child_routes=("/modeles/fiche",)),
    NavEntry("guardrails", "Garde-fous", "/garde-fous", "pilotage", 22, "nav_guardrails", group="suivi"),
    NavEntry("predictions", "Prédictions", "/predictions", "pilotage", 30, "nav_predictions", group="signaux"),
    NavEntry("drift", "Dérive", "/derive", "pilotage", 31, "nav_drift", group="signaux"),
    NavEntry("journal", "Journal", "/journal", "pilotage", 32, "nav_journal", group="signaux"),
    NavEntry("analysis", "Séries & modèles", "/analysis", "pilotage", 40, "nav_analysis", group="recherche"),
    NavEntry("variables", "Variables", "/variables", "pilotage", 41, "nav_variables", group="recherche"),
    NavEntry("exploration", "Exploration", "/exploration", "pilotage", 42, "nav_exploration", group="recherche"),
    NavEntry("news", "News", "/news", "pilotage", 43, "nav_news", group="recherche"),
    NavEntry("carnet", "Carnet", "/carnet", "pilotage", 44, "nav_carnet", group="recherche"),
    NavEntry("donnees", "Données", "/donnees", "pilotage", 50, "nav_donnees", group="donnees"),
    NavEntry("data_quality", "Qualité des données", "/data-quality", "pilotage", 52, "nav_data_quality", group="donnees"),
    # MODELES -- cadrer et lancer l'entrainement, une page par famille : machine learning (arbres, boosting),
    # deep learning (reseaux de neurones, memes runs que le ML), reinforcement learning (agent qui apprend une position).
    NavEntry("ml", "Machine learning", "/ml", "modeles", 10, "nav_ml"),
    NavEntry("dl", "Deep learning", "/dl", "modeles", 20, "nav_dl"),
    NavEntry("rl", "Reinforcement learning", "/rl", "modeles", 30, "nav_rl"),
    # CLASSES D'ACTIFS -- ce que PATRICK modelise, par famille de sous-jacents.
    NavEntry("universe", "Univers", "/universe", "classes_actifs", 10, "nav_universe",
             child_routes=("/targets/{ticker}",)),
    # /portfolio = agregation de signaux par classe d'actifs + allocation HRP
    # sur l'univers PATRICK : vue cross-actifs, pas gestion patrimoniale.
    NavEntry("portfolio", "Portefeuille", "/portfolio", "classes_actifs", 11, "nav_portfolio"),
    NavEntry("equity", "Equity", "/equity", "classes_actifs", 20, "nav_equity", group="marches"),
    NavEntry("indices", "Indices", "/indices", "classes_actifs", 22, "nav_indices", group="marches"),
    NavEntry("crypto", "Cryptos", "/crypto", "classes_actifs", 24, "nav_crypto", group="marches"),
    NavEntry("fx", "Devises", "/fx", "classes_actifs", 26, "nav_fx", group="marches"),
    NavEntry("rates", "Taux & crédit", "/rates", "classes_actifs", 28, "nav_rates", group="marches"),
    NavEntry("commodities", "Matières premières", "/commodities", "classes_actifs", 30, "nav_commodities", group="marches"),
    NavEntry("etfs", "ETF", "/etfs", "classes_actifs", 32, "nav_etfs", group="marches"),
    NavEntry("macro", "Macro (FRED)", "/macro", "classes_actifs", 40, "nav_macro", group="marches"),
    # SIMULATION -- ouvrir des positions fictives (ticket d'ordres) puis suivre les strategies du fonds.
    NavEntry("simulate", "Simulation", "/simulate", "simulation", 10, "nav_simulate"),
    NavEntry("fonds", "Fonds", "/fonds", "simulation", 20, "nav_fonds"),
    # PATRIMOINE -- comptes reels et fictifs (PEA, CTO, AV, livret, DAT) et
    # leurs mouvements (roadmap bloc 4, webapp/wealth_routes.py). URLs a plat
    # (`/mouvements`, pas `/patrimoine/mouvements`) : l'etat actif est par
    # prefixe, une page enfant allumerait aussi `/patrimoine`.
    NavEntry("patrimoine", "Comptes", "/patrimoine", "patrimoine", 10, "nav_patrimoine",
             child_routes=("/patrimoine/comptes/{account_id}",)),
    NavEntry("mouvements", "Mouvements", "/mouvements", "patrimoine", 20, "nav_mouvements"),
    NavEntry("risque", "Risque", "/risque", "patrimoine", 30, "nav_risque"),
)

# Pages d'USAGE de l'application (pas des classes d'analyse) : hors des 4 categories, elles ont leur propre
# bouton en pied de barre laterale (engrenage) et figurent dans la palette de commandes.
UTILITY_ENTRIES: tuple[NavEntry, ...] = (
    NavEntry("vocabulary", "Vocabulaire", "/vocabulary", "utility", 5, "nav_vocabulary"),
    NavEntry("settings", "Réglages", "/reglages", "utility", 10, "nav_settings"),
    NavEntry("diagnostics", "Diagnostics", "/diagnostics", "utility", 20, "nav_diagnostics"),
)

# Routes GET qui ne sont PAS des pages (JSON, fichiers, redirects).
NON_PAGE_PREFIXES: tuple[str, ...] = ("/api/", "/static", "/set-lang/", "/fragments/")
NON_PAGE_ROUTES: frozenset[str] = frozenset({
    "/runs/{run_id}/status",
    "/runs/{run_id}/panel",
    "/runs/{run_id}/results",
    "/runs/{run_id}/download/{artifact}",
    "/runs/{run_id}/analyse/export",   # rapport HTML autonome (téléchargement)
    "/launch",                  # redirection permanente vers /ml (ancien poste de lancement, liens et marque-pages conserves)
    "/patrimoine-simulation",   # redirection permanente vers /fonds (ancienne page « Simulateur patrimoine »)
    "/equities",                # redirection permanente vers /equity (ancienne page « Actions individuelles »)
    "/data-freshness",          # redirection permanente vers /universe (page « Fraîcheur » fusionnée avec l'Univers)
    "/analyses",                # redirection permanente vers /runs?vue=analyses (page « Analyses » fusionnée avec l'Historique)
})


def entries_for(category: str) -> list[NavEntry]:
    return sorted((e for e in NAV_ENTRIES if e.category == category), key=lambda e: e.order)


def registered_routes() -> list[str]:
    """Toutes les routes de page connues du registre (entrees + enfants)."""
    return [r for e in (*NAV_ENTRIES, *UTILITY_ENTRIES) for r in (e.url, *e.child_routes)]


def is_non_page_route(path: str) -> bool:
    return path in NON_PAGE_ROUTES or path.startswith(NON_PAGE_PREFIXES)


_PARAM = re.compile(r"\{[^/}]+\}")


@cache
def _child_pattern(route: str) -> re.Pattern[str]:
    """`/targets/{ticker}` -> motif qui reconnait `/targets/^VIX` (un segment par parametre)."""
    return re.compile("[^/]+".join(re.escape(part) for part in _PARAM.split(route)))


def is_active(entry: NavEntry, path: str) -> bool:
    """`/` en egalite stricte, les autres par prefixe de segment (`/runs` allume `/runs/{id}/detail`) ; une page enfant declaree dans
    `child_routes` allume aussi son entree (`/targets/^VIX` allume Univers, `/compare-runs` allume Historique)."""
    if entry.url == "/":
        return path == "/"
    return (path == entry.url or path.startswith(entry.url + "/")
            or any(_child_pattern(route).fullmatch(path) for route in entry.child_routes))


def utility_links(path: str) -> list[dict]:
    """Pages d'usage (Réglages) pour le pied de barre laterale : meme forme que les entrees de `nav_sections`."""
    return [{"slug": e.slug, "url": e.url, "label": e.label, "label_key": e.label_key,
             "active": is_active(e, path)} for e in sorted(UTILITY_ENTRIES, key=lambda e: e.order)]


def _node(e: NavEntry, path: str) -> dict:
    return {"slug": e.slug, "url": e.url, "label": e.label, "label_key": e.label_key, "active": is_active(e, path)}


def _tree(category: str, entries: list[NavEntry], path: str) -> list[dict]:
    """Arbre d'une categorie : feuilles et dossiers (`NavGroup`) dans l'ordre des entrees ; un dossier prend la place de sa premiere
    entree. `active` d'un dossier = il contient la page courante (il s'ouvre alors tout seul)."""
    groups = {g.key: g for g in GROUPS if g.category == category}
    nodes: list[dict] = []
    folders: dict[str, dict] = {}
    for e in entries:
        leaf = _node(e, path)
        g = groups.get(e.group)
        if g is None:
            nodes.append({"type": "leaf", **leaf})
            continue
        folder = folders.get(g.key)
        if folder is None:
            folder = {"type": "folder", "key": f"{category}/{g.key}", "label": g.label, "label_key": g.label_key,
                      "entries": [], "active": False}
            folders[g.key] = folder
            nodes.append(folder)
        folder["entries"].append(leaf)
        folder["active"] = folder["active"] or leaf["active"]
    return nodes


def nav_sections(path: str) -> list[dict]:
    """Structure consommee par base_v2.html. Une categorie sans entree n'est pas rendue (pas d'en-tete orphelin).
    `entries` : liste plate de toutes les entrees (palette de commandes, etat actif) ; `nodes` : la meme chose en arbre
    (feuilles et dossiers) pour la barre laterale."""
    sections = []
    for cat in CATEGORIES:
        entries = entries_for(cat.key)
        if not entries:
            continue
        sections.append({
            "key": cat.key,
            "label": cat.label,
            "label_key": cat.label_key,
            "entries": [_node(e, path) for e in entries],
            "nodes": _tree(cat.key, entries, path),
        })
    return sections
