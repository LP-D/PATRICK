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

from dataclasses import dataclass


@dataclass(frozen=True)
class NavCategory:
    key: str
    label: str        # libelle FR de repli (si `t` absent du contexte)
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


# Ordre fixe, jamais trie : c'est l'ordre des sections dans la sidebar.
CATEGORIES: tuple[NavCategory, ...] = (
    NavCategory("pilotage", "PILOTAGE", "nav_cat_pilotage"),
    NavCategory("classes_actifs", "CLASSES D'ACTIFS", "nav_cat_classes_actifs"),
    NavCategory("simulation", "SIMULATION", "nav_cat_simulation"),
    NavCategory("patrimoine", "PATRIMOINE", "nav_cat_patrimoine"),
)

NAV_ENTRIES: tuple[NavEntry, ...] = (
    # PILOTAGE -- piloter la station : vue d'ensemble, lancement/suivi des
    # runs, sorties modeles, sante des donnees, journal de decision.
    NavEntry("synthese", "Synthèse", "/", "pilotage", 10, "nav_home"),
    NavEntry("launch", "Lancer", "/launch", "pilotage", 20, "nav_launch"),
    NavEntry("runs", "Historique", "/runs", "pilotage", 30, "nav_runs",
             child_routes=("/runs/{run_id}", "/runs/{run_id}/detail")),
    NavEntry("predictions", "Prédictions", "/predictions", "pilotage", 40, "nav_predictions"),
    NavEntry("data_freshness", "Fraîcheur", "/data-freshness", "pilotage", 50, "nav_data_freshness"),
    NavEntry("phase9", "Phase 9", "/phase9", "pilotage", 60),
    # CLASSES D'ACTIFS -- ce que PATRICK modelise, par famille de sous-jacents.
    NavEntry("universe", "Univers", "/universe", "classes_actifs", 10, "nav_universe",
             child_routes=("/targets/{ticker}",)),
    NavEntry("commodities", "Matières premières", "/commodities", "classes_actifs", 20, "nav_commodities"),
    NavEntry("macro", "Macro (FRED)", "/macro", "classes_actifs", 30, "nav_macro"),
    NavEntry("equities", "Actions individuelles", "/equities", "classes_actifs", 40, "nav_equities"),
    # /portfolio = agregation de signaux par classe d'actifs + allocation HRP
    # sur l'univers PATRICK : vue cross-actifs, pas gestion patrimoniale.
    NavEntry("portfolio", "Portefeuille", "/portfolio", "classes_actifs", 50, "nav_portfolio"),
    # SIMULATION -- rejouer des signaux deja produits (jamais de re-entrainement).
    NavEntry("simulate", "Simulateur", "/simulate", "simulation", 10, "nav_simulate"),
    # PATRIMOINE -- comptes reels et fictifs (PEA, CTO, AV, livret, DAT) et
    # leurs mouvements (roadmap bloc 4, webapp/wealth_routes.py). URLs a plat
    # (`/mouvements`, pas `/patrimoine/mouvements`) : l'etat actif est par
    # prefixe, une page enfant allumerait aussi `/patrimoine`.
    NavEntry("patrimoine", "Comptes", "/patrimoine", "patrimoine", 10, "nav_patrimoine",
             child_routes=("/patrimoine/comptes/{account_id}",)),
    NavEntry("mouvements", "Mouvements", "/mouvements", "patrimoine", 20, "nav_mouvements"),
)

# Routes GET qui ne sont PAS des pages (JSON, fichiers, redirects).
NON_PAGE_PREFIXES: tuple[str, ...] = ("/api/", "/static", "/set-lang/")
NON_PAGE_ROUTES: frozenset[str] = frozenset({
    "/runs/{run_id}/status",
    "/runs/{run_id}/results",
    "/runs/{run_id}/download/{artifact}",
})


def entries_for(category: str) -> list[NavEntry]:
    return sorted((e for e in NAV_ENTRIES if e.category == category), key=lambda e: e.order)


def registered_routes() -> list[str]:
    """Toutes les routes de page connues du registre (entrees + enfants)."""
    return [r for e in NAV_ENTRIES for r in (e.url, *e.child_routes)]


def is_non_page_route(path: str) -> bool:
    return path in NON_PAGE_ROUTES or path.startswith(NON_PAGE_PREFIXES)


def is_active(entry: NavEntry, path: str) -> bool:
    """Regle historique de base_v2.html conservee : `/` en egalite stricte,
    les autres par prefixe de segment (`/runs` allume `/runs/{id}/detail`)."""
    if entry.url == "/":
        return path == "/"
    return path == entry.url or path.startswith(entry.url + "/")


def nav_sections(path: str) -> list[dict]:
    """Structure consommee par base_v2.html. Une categorie sans entree n'est
    pas rendue (pas d'en-tete orphelin)."""
    sections = []
    for cat in CATEGORIES:
        entries = entries_for(cat.key)
        if not entries:
            continue
        sections.append({
            "key": cat.key,
            "label": cat.label,
            "label_key": cat.label_key,
            "entries": [
                {"slug": e.slug, "url": e.url, "label": e.label, "label_key": e.label_key,
                 "active": is_active(e, path)}
                for e in entries
            ],
        })
    return sections
