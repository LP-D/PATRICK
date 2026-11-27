"""Pages /simulate et /fonds et API /api/fund/* (spec §11).

Les écritures passent par `fund.service` / `fund.store` : les motifs de refus
d'un ordre deviennent un 422 `{"detail": {"blocking": [...]}}`, les erreurs de
saisie un 400. `search_symbols` est une fonction de module pour que les tests
remplacent la recherche réseau."""
from __future__ import annotations

import json
import logging
import sqlite3
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from patrick.fund import (
    asset_classes,
    autopilot,
    combo,
    envelopes,
    insight,
    instruments,
    real_funds,
    service,
    store,
    systematic,
)
from patrick.tracking import db as trackdb
from patrick.wealth import symbols
from patrick.webapp import cached_views
from patrick.webapp import instruments as display_names
from patrick.webapp.routes.wealth import fmt_eur, fmt_pct, fmt_qty, symbol_groups

log = logging.getLogger("patrick.fund")

SEARCH_TYPES = {"equity": {"EQUITY"}, "etf": {"ETF", "MUTUALFUND"},
                "cfd": {"EQUITY", "ETF", "INDEX", "CURRENCY", "FUTURE", "CRYPTOCURRENCY"}}


def search_symbols(query: str, kind: str) -> list[dict]:
    wanted = SEARCH_TYPES.get(kind, SEARCH_TYPES["equity"])
    out = []
    for q in symbols.yahoo_search(query):
        quote_type = (q.get("quoteType") or "").upper()
        if quote_type in wanted and q.get("symbol"):
            out.append({"symbol": q["symbol"], "name": q.get("shortname") or q.get("longname") or "",
                        "exchange": q.get("exchDisp") or "", "type": quote_type})
    return out[:10]


def futures_payload(today) -> list[dict]:
    return [{"root": s.root, "name": s.name, "currency": s.currency, "multiplier": s.multiplier,
             "tick_size": s.tick_size, "margin": s.margin, "commission": s.commission, "group": s.group,
             "contracts": instruments.listed_contracts(s.root, today)}
            for s in instruments.FUTURES_CATALOG.values()]


def ticker_bank(labels: dict[str, str]) -> dict[str, list[dict]]:
    """Banque de tickers du ticket, par type d'instrument : {type: [{group, items: [[symbole, nom]]}]}. Action/ETF :
    titres cotés au comptant seulement (groupes « ETF » pour le type ETF, les autres pour Action) ; CFD : tout,
    indices, devises, matières premières et cryptos compris. Un ticker absent de la banque se saisit à la main."""
    out: dict[str, list[dict]] = {"equity": [], "etf": [], "cfd": []}
    for group, items in symbol_groups([]):
        label = labels.get(group, group)
        out["cfd"].append({"group": label, "items": [[s, n] for s, n in items]})
        cash = [[s, n] for s, n in items
                if instruments.classify_cfd_underlying(s) == "equity" and not s.upper().endswith(".NYB")]
        if cash:
            out["etf" if "ETF" in group else "equity"].append({"group": label, "items": cash})
    return out


async def _json_body(request: Request) -> dict:
    """Corps JSON d'une écriture. Le type de contenu est exigé : un formulaire ou un `fetch` en text/plain venu d'un
    autre site (requête « simple », sans contrôle préalable du navigateur) ne doit rien pouvoir écrire."""
    if (request.headers.get("content-type") or "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type application/json requis")
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="corps JSON invalide") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="objet JSON attendu")
    return body


def _labelled(models: list[dict]) -> list[dict]:
    """Chaque modèle avec son nom d'affichage (`label` : le nom de l'instrument, pas son symbole), triés par nom puis horizon."""
    for model in models:
        model["label"] = display_names.display(model["target"])
    return sorted(models, key=lambda m: (m["kind"] != "raw", m["label"].lower(), m["horizon"]))


def _models_signature(conn: sqlite3.Connection) -> tuple:
    """Ce qui change la liste des modèles : un run terminé, un champion promu, un essai de plus."""
    return tuple(conn.execute(
        "SELECT (SELECT COUNT(*) FROM champion), (SELECT COALESCE(MAX(promoted_at), '') FROM champion), "
        "(SELECT COUNT(*) FROM run), (SELECT COALESCE(MAX(finished_at), '') FROM run), "
        "(SELECT COALESCE(MAX(trial_id), 0) FROM trial)").fetchone())


def _cached_models(conn: sqlite3.Connection) -> list[dict]:
    """Liste des modèles du sélecteur, lue dans le cache persistant (`cached_views.FUND_MODELS`) : 3 à 10 s à calculer sur la vraie base, jamais
    à l'ouverture d'une page. Vide tant que le tout premier calcul n'est pas fini."""
    snap = cached_views.FUND_MODELS.get(None, wait_first=cached_views.FIRST_BUILD_WAIT_S)
    return [] if snap is None else snap.value


_OPTIONS: dict[tuple, object] = {}


def _model_options(templates, models: list[dict], t, lang: str):
    """Les options du sélecteur de modèle, rendues UNE fois par liste de modèles et par langue (~4 400 `<option>` : 2 s de rendu à chaque ouverture
    de /simulate sinon). La liste est la même tant que la vue n'a pas été recalculée : `id(models)` change avec elle."""
    key = (id(models), lang)
    cached = _OPTIONS.get(key)
    if cached is None:
        from markupsafe import Markup

        directional = [m for m in models if m["kind"] == "raw"]
        alphas = [m for m in models if m["kind"] == "alpha"]
        html_ = templates.get_template("_fund_model_options.html").render(directional=sorted(directional, key=lambda m: m["label"]),
                                                                          alphas=sorted(alphas, key=lambda m: m["label"]), t=t)
        if len(_OPTIONS) > 8:
            _OPTIONS.clear()
        cached = _OPTIONS[key] = (Markup(html_), models)       # `models` gardée : son `id` ne peut pas être réutilisé tant que l'entrée existe
    return cached[0]


def _call(fn, *args, **kwargs):
    """Ouvre une connexion, appelle `fn(conn, ...)`, traduit les erreurs métier en HTTP."""
    conn = trackdb.connect()
    try:
        return fn(conn, *args, **kwargs)
    except service.FundRuleError as exc:
        raise HTTPException(status_code=422, detail={"blocking": exc.blocking}) from exc
    except store.FundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"contrainte violée : {exc}") from exc
    except HTTPException:
        raise
    except sqlite3.OperationalError as exc:
        log.exception("API fonds : erreur SQLite")
        if "locked" in str(exc) or "busy" in str(exc):
            raise HTTPException(status_code=503,
                                detail="Base de données occupée (un run écrit ?) : réessaie dans un instant.") from exc
        raise HTTPException(status_code=500, detail=(
            f"Erreur de base de données : {exc}. Si elle parle d'une colonne ou d'une table, redémarre "
            "« patrick serve » pour appliquer les migrations.")) from exc
    except Exception as exc:  # frontière web : on montre la cause plutôt qu'un « HTTP 500 » muet
        log.exception("API fonds : erreur inattendue")
        raise HTTPException(status_code=500, detail=f"Erreur interne ({type(exc).__name__}) : {exc}") from exc
    finally:
        conn.close()


def _require_strategy(conn: sqlite3.Connection, strategy_id: str) -> dict:
    strategy = store.get_strategy(conn, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Stratégie introuvable")
    return strategy


def _overview_snapshot():
    """La valeur de chaque stratégie, lue dans le cache (`cached_views.FUND_OVERVIEW`) : instantanée tant qu'on n'a rien modifié dans les fonds ;
    après une modification (stratégie, ordre, règle) la page attend le nouveau calcul pour montrer le résultat, sinon on affiche l'ancien et
    le recalcul (cotations) tourne en tâche de fond. None : premier calcul pas encore fini."""
    return cached_views.FUND_OVERVIEW.get(None, wait_first=cached_views.FIRST_BUILD_WAIT_S, hard_wait=HARD_WAIT_S)


def _view_ctx(snap) -> dict:
    """Ce que la page dit de son instantané (de quand, recalcul en cours) et la barre de chargement qui suit le calcul."""
    view = cached_views.FUND_OVERVIEW
    return {"snapshot_at": None if snap is None else snap.computed_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            "snapshot_refreshing": view.status()["running"], "refresh_views": [view.name], "refresh_live": False}


HARD_WAIT_S = 180.0                      # attente maximale d'une page après une modification des fonds (le calcul prend 15 à 40 s)


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n/glossaire de l'application."""
    templates.env.filters.setdefault("eur", fmt_eur)
    templates.env.filters.setdefault("pct", fmt_pct)
    templates.env.filters.setdefault("qty", fmt_qty)

    def _preparing(request: Request, ctx: dict):
        """Premier calcul des fonds (aucun instantané) : le cadre, un message et la barre de chargement ; la page se recharge toute seule."""
        return templates.TemplateResponse(request, "_preparing_page.html", {**_view_ctx(None), "auto_reload": True, **ctx}, status_code=202)

    # -------------------------------------------------------------- pages

    @app.get("/simulate")
    def simulate_page(request: Request, strategy: str | None = None, placed: int = 0):
        today = service.current_date()
        data = _overview_snapshot()
        ctx = context(request)
        if data is None:
            return _preparing(request, ctx)
        models = _call(_cached_models)
        return templates.TemplateResponse(request, "simulate.html", {
            "models": models, "model_options_html": _model_options(templates, models, ctx["t"], ctx["lang"]),
            "strategies": data.value["strategies"], "selected_id": strategy, "placed": bool(placed),
            "today": today.isoformat(), "futures": futures_payload(today),
            "cfd_classes": list(instruments.CFD_LEVERAGE_CAPS),
            "ticker_bank": ticker_bank(ctx.get("group_labels") or {}), **_view_ctx(data), **ctx})

    def _category(value: str | None) -> str | None:
        """Filtre `?categorie=` de /fonds : `quant`, `real` ou `lab` (ADR 0030) ; toute autre valeur (ou rien) = toutes les catégories."""
        return value if value in store.CATEGORIES else None

    @app.get("/fonds")
    def fonds_page(request: Request, strategy: str | None = None, categorie: str | None = None):
        """Le cadre seul (titre, panneau, listes sans cotations) : la valeur de chaque stratégie se calcule en 3 à 5 s sur la vraie
        base ; elle arrive par `/fragments/fund-overview` après l'affichage. Seules les stratégies archivées, une lecture de table,
        se lisent ici."""
        every_signal = {real_funds.fund_name(k) for k in real_funds.KINDS}
        combo_names = {v["name"] for v in combo.VARIANTS.values()}

        def run(conn):
            every = store.list_strategies(conn, include_archived=True)
            live = [s for s in every if not s["archived"]]
            return ([s for s in every if s["archived"]], [s for s in live if s["category"] == "real" and s["name"] in every_signal],
                    [s for s in live if s["category"] == "lab" and s["name"] in combo_names])
        archived, real_existing, combo_existing = _call(run)
        return templates.TemplateResponse(request, "fonds.html", {
            "selected_id": strategy, "archived": archived, "class_names": list(asset_classes.CLASSES),
            "class_families": {name: [f.key for f in asset_classes.FAMILIES.values() if name in f.classes] for name in asset_classes.CLASSES},
            "families": asset_classes.FAMILIES,
            "class_defaults": asset_classes.DEFAULTS, "category": _category(categorie), "categories": store.CATEGORIES,
            "real_existing": real_existing, "real_defaults": real_funds.DEFAULTS, "pea_groups": envelopes.PEA_GROUPS,
            "pea_cap": store.PEA_DEPOSIT_CAP_EUR, "combo_existing": combo_existing, "combo_defaults": combo.DEFAULTS,
            "combo_variants": list(combo.VARIANTS), **context(request)})

    @app.get("/fragments/fund-overview")
    def fund_overview_fragment(request: Request, strategy: str | None = None, categorie: str | None = None):
        """Total, répartition et tableau des stratégies de /fonds, une section par catégorie (chargé par `static/lazy.js`) ;
        `?categorie=quant|real` n'en garde qu'une."""
        snap = _overview_snapshot()
        if snap is None:
            return templates.TemplateResponse(request, "_view_preparing.html", {**_view_ctx(None), **context(request)}, status_code=202)
        data = snap.value
        wanted = _category(categorie)
        shown = [c for c in data["categories"] if wanted in (None, c["category"])]
        return templates.TemplateResponse(request, "_fund_overview.html", {
            "strategies": data["strategies"], "fund": data["fund"], "categories": shown, "selected_id": strategy,
            **_view_ctx(snap), **context(request)})

    _regime_cache: dict = {}

    @app.get("/fragments/market-regime")
    def market_regime_fragment(request: Request):
        """A11 : régime de marché du jour (classification de `research/phase9.py`), en contexte sur /fonds ; gardé 30 min."""
        from patrick.fund import regime

        now = time.monotonic()
        if "at" not in _regime_cache or now - _regime_cache["at"] > 1800:
            try:
                value = regime.current()
            except Exception as exc:  # noqa: BLE001 -- frontière fournisseur : un bandeau de contexte ne casse jamais la page
                log.info("régime de marché indisponible : %s: %s", type(exc).__name__, exc)
                value = None
            _regime_cache.update(at=now, value=value)
        return templates.TemplateResponse(request, "_market_regime.html", {"regime": _regime_cache["value"], **context(request)})

    @app.get("/patrimoine-simulation")
    def legacy_wealth_simulation_page():
        """Ancienne page « Simulateur patrimoine » : remplacée par /fonds."""
        return RedirectResponse("/fonds", status_code=308)

    def _insight(conn, strategy_id: str, snap: dict, today) -> dict:
        """Attribution, témoins et journal des remplacements du panneau. Une lecture en panne (cotation manquante pour un témoin)
        n'empêche jamais le panneau de s'afficher : le bloc concerné est simplement absent."""
        out = {"attribution": {"by_rule": [], "by_class": [], "by_side": []}, "witnesses": None, "replacements": [],
               "replaced_total": None}
        for key, read in (("attribution", lambda: insight.attribution(conn, strategy_id, snap)),
                          ("witnesses", lambda: insight.witnesses(conn, snap["strategy"], snap, today)),
                          ("replacements", lambda: insight.replacements(conn, strategy_id)),
                          ("replaced_total", lambda: insight.replacement_totals(conn, strategy_id))):
            try:
                out[key] = read()
            except Exception:
                log.exception("fund insight %s failed for %s", key, strategy_id)
        return out

    @app.get("/api/fund/strategies/{strategy_id}/panel")
    def api_strategy_panel(request: Request, strategy_id: str):
        """Fragment HTML (rendu serveur, échappé) du détail d'une stratégie pour /fonds."""
        today = service.current_date()

        def run(conn):
            from patrick.fund import limit_orders
            snap = service.strategy_snapshot(conn, _require_strategy(conn, strategy_id), today)
            rules = systematic.rule_summaries(conn, strategy_id)
            return (snap, rules, autopilot.status(conn, strategy_id, rules), _insight(conn, strategy_id, snap, today),
                    limit_orders.list_for(conn, strategy_id)[:20])
        snap, rules, auto, seen, limits = _call(run)
        manual = [r for r in rules if not (r["config"].get("managed") or {}).get("by")]     # celles du pilote : dans son bloc
        return templates.TemplateResponse(request, "_fund_panel.html", {
            "snap": snap, "rules": manual, "autopilot": auto, "insight": seen, "today": today.isoformat(), "limit_orders": limits,
            **context(request)})

    @app.get("/api/fund/strategies/{strategy_id}/vitrine.html")
    def api_strategy_showcase(strategy_id: str):
        """Page vitrine autonome (A26) : pourcentages seulement, aucun montant, aucun script ; téléchargée en fichier."""
        from fastapi.responses import Response

        from patrick.fund import showcase
        today = service.current_date()

        def run(conn):
            return showcase.render(service.strategy_snapshot(conn, _require_strategy(conn, strategy_id), today))
        page = _call(run)
        return Response(page, media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="vitrine-{strategy_id}.html"'})

    @app.get("/api/fund/strategies/{strategy_id}/series")
    def api_strategy_series(strategy_id: str):
        """Valeur nette quotidienne d'une stratégie (D22 : la superposer à une autre sur le graphique de /fonds, en base 100)."""
        today = service.current_date()

        def run(conn):
            strategy = _require_strategy(conn, strategy_id)
            snap = service.strategy_snapshot(conn, strategy, today)
            return {"strategy_id": strategy_id, "name": strategy["name"], "series": [{"t": p["t"], "nav": p.get("nav")} for p in snap["series"]]}
        return _call(run)

    @app.get("/api/fund/strategies/{strategy_id}/rule-form")
    def api_rule_form(request: Request, strategy_id: str):
        """Fragment HTML du formulaire « Nouvelle règle » (tous les modèles) : le panneau le charge à part, car la liste des
        modèles est la partie lente de la page."""
        def run(conn):
            _require_strategy(conn, strategy_id)
            return _cached_models(conn)
        models = _call(run)
        ctx = context(request)
        return templates.TemplateResponse(request, "_fund_rule_form_block.html", {
            "models": models, "strategy_id": strategy_id, "today": service.current_date().isoformat(),
            "model_options_html": _model_options(templates, models, ctx["t"], ctx["lang"]), **ctx})

    # ---------------------------------------------------------------- API

    @app.get("/api/fund/overview")
    def api_overview():
        return _call(service.overview, service.current_date())

    @app.get("/api/fund/strategies/{strategy_id}/detail")
    def api_strategy_detail(strategy_id: str):
        def run(conn):
            return service.strategy_snapshot(conn, _require_strategy(conn, strategy_id), service.current_date())
        return _call(run)

    @app.post("/api/fund/strategies")
    async def api_create_strategy(request: Request):
        b = await _json_body(request)
        strategy_id = await run_in_threadpool(_call, store.create_strategy, b.get("name"), b.get("wrapper"),
                                              b.get("initial_capital"), b.get("opened_on"), "EUR", b.get("category") or "quant",
                                              b.get("fee_flat"))
        return {"strategy_id": strategy_id}

    @app.patch("/api/fund/strategies/{strategy_id}")
    async def api_update_strategy(request: Request, strategy_id: str):
        b = await _json_body(request)
        fields = {k: b[k] for k in ("name", "archived") if k in b}
        if "archived" in fields:
            fields["archived"] = 1 if fields["archived"] else 0

        def run(conn):
            _require_strategy(conn, strategy_id)
            store.update_strategy(conn, strategy_id, **fields)
            return {"ok": True}
        return await run_in_threadpool(_call, run)

    @app.delete("/api/fund/strategies/{strategy_id}")
    def api_delete_strategy(strategy_id: str):
        def run(conn):
            _require_strategy(conn, strategy_id)
            store.delete_strategy(conn, strategy_id)
            return {"ok": True}
        return _call(run)

    @app.get("/api/fund/instruments/search")
    def api_search_instruments(q: str = "", kind: str = "equity"):
        query = q.strip()
        return {"results": search_symbols(query, kind) if len(query) >= 2 else []}

    @app.get("/api/fund/futures/catalog")
    def api_futures_catalog():
        return {"futures": futures_payload(service.current_date())}

    @app.get("/api/fund/futures/{root}/contracts")
    def api_futures_contracts(root: str):
        if root not in instruments.FUTURES_CATALOG:
            raise HTTPException(status_code=404, detail="Racine de future inconnue")
        return {"root": root, "contracts": instruments.listed_contracts(root, service.current_date())}

    @app.post("/api/fund/quote")
    async def api_quote(request: Request):
        return await run_in_threadpool(_call, service.quote, await _json_body(request))

    @app.post("/api/fund/strategies/{strategy_id}/orders")
    async def api_place_order(request: Request, strategy_id: str):
        b = await _json_body(request)
        if b.get("limit_price") not in (None, ""):          # A12 : ordre limite, exécuté sur les séances suivantes (fund/limit_orders.py)
            from patrick.fund import limit_orders

            def run(conn):
                row = limit_orders.create(conn, {**b, "strategy_id": strategy_id}, b["limit_price"], expires_on=b.get("expires_on") or None,
                                          participation=float(b.get("participation") or limit_orders.DEFAULT_PARTICIPATION))
                return {"limit_order": row}
            return await run_in_threadpool(_call, run)
        return await run_in_threadpool(_call, service.place_order, {**b, "strategy_id": strategy_id})

    @app.get("/api/fund/strategies/{strategy_id}/limit-orders")
    def api_limit_orders(strategy_id: str):
        from patrick.fund import limit_orders

        def run(conn):
            _require_strategy(conn, strategy_id)
            return {"limit_orders": limit_orders.list_for(conn, strategy_id)}
        return _call(run)

    @app.post("/api/fund/limit-orders/{limit_id}/cancel")
    def api_cancel_limit_order(limit_id: int):
        from patrick.fund import limit_orders
        return _call(lambda conn: {"limit_order": limit_orders.cancel(conn, limit_id)})

    @app.patch("/api/fund/orders/{order_id}")
    async def api_correct_order(request: Request, order_id: int):
        return await run_in_threadpool(_call, service.correct_order, order_id, await _json_body(request))

    @app.delete("/api/fund/positions/{position_id}")
    def api_delete_position(position_id: str):
        def run(conn):
            if store.delete_position(conn, position_id) == 0:
                raise HTTPException(status_code=404, detail="Position introuvable")
            return {"ok": True}
        return _call(run)

    # ------------------------------------------------- règles automatiques (mode ML à seuils)

    @app.get("/api/fund/models")
    def api_models():
        """Essais gagnants dont on peut rejouer les signaux (formulaire de création d'une règle)."""
        return {"models": _call(_cached_models)}

    @app.get("/api/fund/strategies/{strategy_id}/rules")
    def api_list_rules(strategy_id: str):
        def run(conn):
            _require_strategy(conn, strategy_id)
            return {"rules": systematic.rule_summaries(conn, strategy_id)}
        return _call(run)

    @app.post("/api/fund/strategies/{strategy_id}/rules")
    async def api_create_rule(request: Request, strategy_id: str):
        b = await _json_body(request)
        rule_id = await run_in_threadpool(_call, systematic.create_rule, strategy_id, b.get("name"), b.get("config"))
        return {"rule_id": rule_id}

    @app.post("/api/fund/rules/{rule_id}/apply")
    async def api_apply_rule(request: Request, rule_id: str):
        await _json_body(request)
        return await run_in_threadpool(_call, systematic.apply, rule_id, service.current_date())

    @app.delete("/api/fund/rules/{rule_id}")
    def api_delete_rule(rule_id: str):
        def run(conn):
            if not systematic.delete_rule(conn, rule_id):
                raise HTTPException(status_code=404, detail="Règle introuvable")
            return {"ok": True}
        return _call(run)

    # ------------------------------------------------- pilote automatique (sélection des modèles + cycle quotidien)

    def _query_settings(params) -> dict:
        """Réglages passés dans l'adresse de l'aperçu (`?tier=large&gross=0.5&max_models=10&allow_short=0`)."""
        raw: dict = {}
        for key in ("gross", "min_confidence", "alpha_dm", "alpha_bh", "auc_floor", "min_position"):
            if key in params:
                if key == "min_position" and params[key].strip() == "":
                    raw[key] = None                                  # vide : aucune taille minimale
                    continue
                try:
                    raw[key] = float(params[key])
                except ValueError as exc:
                    raise store.FundError(f"{key} invalide : nombre attendu ({params[key]!r})") from exc
        for key in ("fresh_days", "max_models"):
            if key in params:
                if key == "max_models" and params[key].strip() == "":
                    raw[key] = None                                  # vide : aucun plafond
                    continue
                try:
                    raw[key] = int(params[key])
                except ValueError as exc:
                    raise store.FundError(f"{key} invalide : entier attendu ({params[key]!r})") from exc
        if "tier" in params:
            raw["tier"] = params["tier"]
        if "allow_short" in params:
            raw["allow_short"] = params["allow_short"].strip().lower() in ("1", "true", "on", "oui")
        return raw

    @app.get("/api/fund/strategies/{strategy_id}/autopilot")
    def api_autopilot_status(strategy_id: str):
        def run(conn):
            _require_strategy(conn, strategy_id)
            return autopilot.status(conn, strategy_id)
        return _call(run)

    @app.put("/api/fund/strategies/{strategy_id}/autopilot")
    async def api_autopilot_configure(request: Request, strategy_id: str):
        """Active le pilote avec ces réglages posés sur ceux déjà enregistrés (le périmètre qu'un formulaire ne montre pas est conservé ;
        sur une stratégie sans pilote, les absents prennent leur défaut)."""
        body = await _json_body(request)

        def run(conn):
            return autopilot.configure(conn, strategy_id, autopilot.overlay(conn, strategy_id, body))
        return await run_in_threadpool(_call, run)

    @app.delete("/api/fund/strategies/{strategy_id}/autopilot")
    def api_autopilot_disable(strategy_id: str):
        def run(conn):
            _require_strategy(conn, strategy_id)
            return autopilot.disable(conn, strategy_id)
        return _call(run)

    @app.post("/api/fund/strategies/{strategy_id}/autopilot/run")
    async def api_autopilot_run(request: Request, strategy_id: str):
        await _json_body(request)
        return await run_in_threadpool(_call, autopilot.run, strategy_id, service.current_date())

    @app.post("/api/fund/strategies/{strategy_id}/autopilot/preview")
    async def api_autopilot_preview(request: Request, strategy_id: str):
        """Sélection, instruments et tailles que le pilote appliquerait ; corps vide = réglages enregistrés."""
        body = await _json_body(request)

        def run(conn):
            settings = autopilot.Settings.from_dict(autopilot.overlay(conn, strategy_id, body)) if body else None
            return autopilot.preview(conn, strategy_id, service.current_date(), settings)
        return await run_in_threadpool(_call, run)

    @app.get("/fragments/fund-correlation/{strategy_id}")
    def fund_correlation_fragment(request: Request, strategy_id: str):
        """VI4 (26/11) : corrélation des rendements quotidiens (un an) des positions ouvertes, ordonnée par regroupement hiérarchique."""
        import datetime as _dt

        from patrick.fund import prices as fund_prices
        from patrick.wealth import prices as wealth_prices
        from patrick.webapp import fund_visuals
        conn = trackdb.connect()
        try:
            strategy = store.get_strategy(conn, strategy_id)
            if strategy is None:
                raise HTTPException(status_code=404, detail="stratégie introuvable")
            snap = service.strategy_snapshot(conn, strategy)
            symbols = sorted({p["symbol"] for p in snap["positions"] if p.get("status") == "open" and p.get("symbol")})
            since = (service.current_date() - _dt.timedelta(days=400)).isoformat()
            # cours déjà stockés pour le fonds (table fund_price) : ceux qui servent à sa valorisation, sans réseau
            series = {}
            for sym in symbols:
                bars = fund_prices.load_bars(conn, sym, since=since)
                series[sym] = bars["close"] if bars is not None else None
        finally:
            conn.close()
        missing = [s for s, v in series.items() if v is None]
        if missing:                                   # repli : séries du cache général (un symbole jamais valorisé par le fonds)
            provider = wealth_prices.make_provider(allow_network=False)
            series.update({s: provider(s) for s in missing})
        corr = fund_visuals.correlation(series)
        return templates.TemplateResponse(request, "_fund_correlation.html", {**context(request), "corr": corr})

    @app.get("/api/fund/strategies/{strategy_id}/report.pdf")
    def api_fund_monthly_report(strategy_id: str, month: str | None = None):
        """FO14/FO15 (25/11) : rapport mensuel du fonds en PDF (performance, attribution, ordres, positions, stress tests)."""
        import re as _re

        from fastapi.responses import Response

        from patrick.fund import monthly_report
        month = month or service.current_date().strftime("%Y-%m")
        if not _re.fullmatch(r"\d{4}-\d{2}", month):
            raise HTTPException(status_code=400, detail="mois attendu au format AAAA-MM")
        conn = trackdb.connect()
        try:
            pdf = monthly_report.report_pdf(conn, strategy_id, month)
        except store.FundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            conn.close()
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="fonds-{strategy_id[:8]}-{month}.pdf"'})

    @app.get("/api/fund/strategies/{strategy_id}/stress")
    def api_fund_stress(strategy_id: str):
        """FO15 (25/11) : positions ouvertes du fonds rejouées sur les grandes crises passées."""
        from patrick.fund import monthly_report
        conn = trackdb.connect()
        try:
            strategy = store.get_strategy(conn, strategy_id)
            if strategy is None:
                raise HTTPException(status_code=404, detail="stratégie introuvable")
            return {"windows": monthly_report.stress(service.strategy_snapshot(conn, strategy))}
        finally:
            conn.close()

    @app.get("/api/fund/strategies/{strategy_id}/autopilot/preview.html")
    async def api_autopilot_preview_html(request: Request, strategy_id: str):
        """Fragment HTML (rendu serveur, échappé) de l'aperçu, pour le panneau de /fonds."""
        params = dict(request.query_params)

        def run(conn):
            settings = autopilot.Settings.from_dict(autopilot.overlay(conn, strategy_id, _query_settings(params))) if params else None
            return autopilot.preview(conn, strategy_id, service.current_date(), settings)
        plan = await run_in_threadpool(_call, run)
        return templates.TemplateResponse(request, "_fund_autopilot_preview.html", {"plan": plan, **context(request)})

    # ------------------------------------------------- stratégies par classe d'actifs (création rapide)

    def _class_options(raw: dict) -> dict:
        """Réglages d'une création, validés AVANT toute écriture : `family` (gamme), `split` (`classes` : une stratégie par classe ;
        `tiers` : une par preuve statistique), `classes` (celles de la gamme, toutes si absent), `tiers` (dm, bh ; les deux si absent),
        `horizons`, `tier` (niveau des stratégies par classe), `gross` (fraction du capital), `capital` (celui de la gamme si absent),
        `max_models` (None : aucun plafond), `run`."""
        keys = (*asset_classes.DEFAULTS, "classes", "run", "split", "tiers")
        merged = {**asset_classes.DEFAULTS, **{k: v for k, v in raw.items() if k in keys}}
        family = asset_classes.family_of(merged["family"])
        if "capital" not in raw:
            merged["capital"] = family.capital
        split = merged.get("split") or "classes"
        if split not in ("classes", "tiers"):
            raise store.FundError(f"découpage inconnu : {split!r} (classes, tiers)")
        classes = merged.get("classes") or list(family.classes)
        if not isinstance(classes, list) or not all(isinstance(c, str) for c in classes):
            raise store.FundError("classes invalides : liste de noms attendue")
        unknown = [c for c in classes if c not in family.classes]
        if unknown and split == "classes":
            raise store.FundError(f"classe inconnue dans la gamme {family.prefix} : {', '.join(unknown)}")
        tiers = merged.get("tiers") or list(asset_classes.TIER_STRATEGIES)
        if not isinstance(tiers, list) or any(t not in asset_classes.TIER_STRATEGIES for t in tiers):
            raise store.FundError(f"preuves inconnues : {tiers!r} ({', '.join(asset_classes.TIER_STRATEGIES)})")
        store._check_capital(merged["capital"], family.wrapper)
        autopilot.Settings.from_dict({"tier": merged["tier"], "gross": merged["gross"], "max_models": merged["max_models"],
                                      "horizons": merged["horizons"], "groups": ["x"]})
        common = {"family": family.key, "horizons": tuple(merged["horizons"]), "gross": float(merged["gross"]),
                  "capital": merged["capital"], "max_models": merged["max_models"]}
        if split == "tiers":
            return {"split": split, "run": bool(merged.get("run")), "args": {**common, "tiers": tuple(tiers)}}
        return {"split": split, "run": bool(merged.get("run")), "args": {**common, "only": classes, "tier": merged["tier"]}}

    def _class_setup(conn, options: dict, *, dry_run: bool) -> list[dict]:
        """La création (ou l'aperçu) que `_class_options` décrit : par classe ou par preuve, dans la gamme choisie."""
        make = asset_classes.setup_tiers if options["split"] == "tiers" else asset_classes.setup
        return make(conn, today=service.current_date(), dry_run=dry_run, **options["args"])

    def _class_query(params) -> dict:
        """Les mêmes réglages passés dans l'adresse (`?classes=Future,Devises&horizons=1,5&tier=large&capital=1e7`)."""
        raw: dict = {}
        if "classes" in params:
            raw["classes"] = [c for c in params["classes"].split(",") if c]
        if "horizons" in params:
            try:
                raw["horizons"] = [int(h) for h in params["horizons"].split(",") if h.strip()]
            except ValueError as exc:
                raise store.FundError(f"horizons invalides : entiers séparés par des virgules ({params['horizons']!r})") from exc
        for key in ("gross", "capital"):
            if key in params:
                try:
                    raw[key] = float(params[key])
                except ValueError as exc:
                    raise store.FundError(f"{key} invalide : nombre attendu ({params[key]!r})") from exc
        for key in ("tier", "family", "split"):
            if key in params:
                raw[key] = params[key]
        if "tiers" in params:
            raw["tiers"] = [t for t in params["tiers"].split(",") if t]
        if "max_models" in params:
            try:
                raw["max_models"] = int(params["max_models"]) if params["max_models"].strip() else None
            except ValueError as exc:
                raise store.FundError(f"max_models invalide : entier attendu ({params['max_models']!r})") from exc
        return raw

    @app.get("/api/fund/asset-classes")
    def api_asset_classes(family: str = "systematic"):
        """Les classes de la gamme (et la stratégie qui porte déjà leur nom), les réglages par défaut et la description des gammes."""
        families = {f.key: {"prefix": f.prefix, "wrapper": f.wrapper, "allow_short": f.allow_short, "capital": f.capital,
                            "classes": list(f.classes)} for f in asset_classes.FAMILIES.values()}
        return {"classes": _call(asset_classes.class_rows, family), "defaults": asset_classes.DEFAULTS, "families": families}

    @app.post("/api/fund/asset-classes/preview")
    async def api_asset_classes_preview(request: Request):
        body = await _json_body(request)

        def run(conn):
            return {"rows": _class_setup(conn, _class_options(body), dry_run=True)}
        return await run_in_threadpool(_call, run)

    @app.get("/api/fund/asset-classes/preview.html")
    async def api_asset_classes_preview_html(request: Request):
        """Fragment HTML (rendu serveur, échappé) de l'aperçu par classe, pour la section de /fonds."""
        params = dict(request.query_params)

        def run(conn):
            return _class_setup(conn, _class_options(_class_query(params)), dry_run=True)
        rows = await run_in_threadpool(_call, run)
        return templates.TemplateResponse(request, "_fund_classes_preview.html",
                                          {"rows": rows, "tier_labels": asset_classes.TIER_STRATEGIES, **context(request)})

    # ------------------------------------------------- fonds réels : un PEA et un CTO fictifs, 5 000 €, 1 € par ordre (ADR 0026)

    def _real_options(raw: dict) -> dict:
        """Réglages d'une création des fonds réels (`only`, `capital`, `fee_flat`, `tier`, `gross`, `max_models`, `min_position`, `run`, `dry_run`),
        les absents prenant `real_funds.DEFAULTS`. La validation fine (capital, plafond du PEA, réglages du pilote) est celle de `real_funds.setup`."""
        merged = {**real_funds.DEFAULTS, **{k: v for k, v in raw.items() if k in (*real_funds.DEFAULTS, "only", "run", "dry_run")}}
        only = merged.get("only")
        if only is not None and (not isinstance(only, list) or not all(isinstance(k, str) for k in only)):
            raise store.FundError("only invalide : liste de fonds (PEA, CTO) attendue")
        return {"only": only, "capital": merged["capital"], "fee_flat": merged["fee_flat"], "tier": merged["tier"], "gross": merged["gross"],
                "max_models": merged["max_models"], "min_position": merged["min_position"], "run": bool(merged.get("run")),
                "dry_run": bool(merged.get("dry_run"))}

    @app.get("/api/fund/real")
    def api_real_funds():
        """Les deux fonds réels (créés ou non), leurs réglages par défaut et ce que le PEA exclut."""
        def run(conn):
            existing = {s["name"]: s["strategy_id"] for s in store.list_strategies(conn) if s["category"] == "real"}
            return [{"kind": k, "name": real_funds.fund_name(k), "strategy_id": existing.get(real_funds.fund_name(k))} for k in real_funds.KINDS]
        return {"funds": _call(run), "defaults": real_funds.DEFAULTS,
                "pea": {"groups": list(envelopes.PEA_GROUPS), "euro_suffixes": list(envelopes.PEA_EURO_SUFFIXES),
                        "non_euro_suffixes": list(envelopes.PEA_NON_EURO_SUFFIXES)}}

    @app.post("/api/fund/real")
    async def api_real_funds_create(request: Request):
        """Crée (ou reprend) le fonds PEA et le fonds CTO en pilote automatique, puis, si `run`, un premier cycle en arrière-plan.
        `dry_run` : rien n'est écrit, seuls les modèles candidats sont comptés."""
        body = await _json_body(request)

        def run(conn):
            options = _real_options(body)
            start = options.pop("run")
            return real_funds.setup(conn, today=service.current_date(), **options), start and not options["dry_run"]
        rows, start = await run_in_threadpool(_call, run)
        if start:
            autopilot.start_cycles([r["strategy_id"] for r in rows])
        return {"rows": rows, "cycle_started": bool(start)}

    # ------------------------------------------------- fonds de test combinés : ML/DL croisé avec le RL et la volatilité (ADR 0030)

    def _combo_options(raw: dict) -> dict:
        """Réglages d'une création des fonds combinés (`only`, `capital`, `tier`, `horizons`, `max_models`, `gross`, `cost_multiple`, `run`,
        `dry_run`), les absents prenant `combo.DEFAULTS`. La validation fine est celle de `combo.setup`."""
        merged = {**combo.DEFAULTS, **{k: v for k, v in raw.items() if k in (*combo.DEFAULTS, "only", "run", "dry_run")}}
        only = merged.get("only")
        if only is not None and (not isinstance(only, list) or not all(isinstance(k, str) for k in only)):
            raise store.FundError("only invalide : liste de fonds (reference, rl, vol, full) attendue")
        if only == []:
            raise store.FundError("aucun fonds combiné coché")
        horizons = merged["horizons"]
        if not isinstance(horizons, list) or not horizons or not all(isinstance(h, int) and not isinstance(h, bool) and h > 0 for h in horizons):
            raise store.FundError("horizons invalides : liste d'entiers positifs attendue")
        return {"only": only, "capital": merged["capital"], "tier": merged["tier"], "horizons": tuple(horizons),
                "max_models": merged["max_models"], "gross": merged["gross"], "cost_multiple": merged["cost_multiple"],
                "run": bool(merged.get("run")), "dry_run": bool(merged.get("dry_run"))}

    @app.post("/api/fund/combo")
    async def api_combo_create(request: Request):
        """Crée (ou reprend) les fonds de test combinés en pilote automatique, puis, si `run`, un premier cycle en arrière-plan.
        `dry_run` : rien n'est écrit, seuls les modèles candidats sont comptés."""
        body = await _json_body(request)

        def run(conn):
            options = _combo_options(body)
            start = options.pop("run")
            return combo.setup(conn, today=service.current_date(), **options), start and not options["dry_run"]
        rows, start = await run_in_threadpool(_call, run)
        if start:
            autopilot.start_cycles([r["strategy_id"] for r in rows])
        return {"rows": rows, "cycle_started": bool(start)}

    @app.post("/api/fund/asset-classes")
    async def api_asset_classes_create(request: Request):
        """Une stratégie en pilote automatique par classe (créée ou reprise), puis, si `run`, un premier cycle en arrière-plan."""
        body = await _json_body(request)

        def run(conn):
            options = _class_options(body)
            return _class_setup(conn, options, dry_run=False), options["run"]
        rows, start = await run_in_threadpool(_call, run)
        if start:
            autopilot.start_cycles([r["strategy_id"] for r in rows])
        return {"rows": rows, "cycle_started": bool(start)}
