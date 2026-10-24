"""Pages /simulate et /fonds et API /api/fund/* (spec §11).

Les écritures passent par `fund.service` / `fund.store` : les motifs de refus
d'un ordre deviennent un 422 `{"detail": {"blocking": [...]}}`, les erreurs de
saisie un 400. `search_symbols` est une fonction de module pour que les tests
remplacent la recherche réseau."""
from __future__ import annotations

import json
import logging
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from patrick.fund import autopilot, instruments, service, store, systematic
from patrick.tracking import db as trackdb
from patrick.wealth import symbols
from patrick.webapp import instruments as display_names
from patrick.webapp.wealth_routes import fmt_eur, fmt_pct, fmt_qty, symbol_groups

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


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n/glossaire de l'application."""
    templates.env.filters.setdefault("eur", fmt_eur)
    templates.env.filters.setdefault("pct", fmt_pct)
    templates.env.filters.setdefault("qty", fmt_qty)

    # -------------------------------------------------------------- pages

    @app.get("/simulate")
    def simulate_page(request: Request, strategy: str | None = None, placed: int = 0):
        today = service.current_date()
        data = _call(service.overview, today)
        ctx = context(request)
        return templates.TemplateResponse(request, "simulate.html", {
            "models": _labelled(_call(systematic.available_models)),
            "strategies": data["strategies"], "selected_id": strategy, "placed": bool(placed),
            "today": today.isoformat(), "futures": futures_payload(today),
            "cfd_classes": list(instruments.CFD_LEVERAGE_CAPS),
            "ticker_bank": ticker_bank(ctx.get("group_labels") or {}), **ctx})

    @app.get("/fonds")
    def fonds_page(request: Request, strategy: str | None = None):
        """Le cadre seul (titre, panneau, listes sans cotations) : la valeur de chaque stratégie se calcule en 3 à 5 s sur la vraie
        base ; elle arrive par `/fragments/fund-overview` après l'affichage. Seules les stratégies archivées, une lecture de table,
        se lisent ici."""
        archived = _call(lambda conn: [s for s in store.list_strategies(conn, include_archived=True) if s["archived"]])
        return templates.TemplateResponse(request, "fonds.html", {
            "selected_id": strategy, "archived": archived, **context(request)})

    @app.get("/fragments/fund-overview")
    def fund_overview_fragment(request: Request, strategy: str | None = None):
        """Total consolidé, répartition et tableau des stratégies de /fonds (chargé par `static/lazy.js`)."""
        data = _call(service.overview, service.current_date())
        return templates.TemplateResponse(request, "_fund_overview.html", {
            "strategies": data["strategies"], "fund": data["fund"], "selected_id": strategy, **context(request)})

    @app.get("/patrimoine-simulation")
    def legacy_wealth_simulation_page():
        """Ancienne page « Simulateur patrimoine » : remplacée par /fonds."""
        return RedirectResponse("/fonds", status_code=308)

    @app.get("/api/fund/strategies/{strategy_id}/panel")
    def api_strategy_panel(request: Request, strategy_id: str):
        """Fragment HTML (rendu serveur, échappé) du détail d'une stratégie pour /fonds."""
        today = service.current_date()

        def run(conn):
            snap = service.strategy_snapshot(conn, _require_strategy(conn, strategy_id), today)
            rules = systematic.rule_summaries(conn, strategy_id)
            return snap, rules, _labelled(systematic.available_models(conn)), autopilot.status(conn, strategy_id, rules)
        snap, rules, models, auto = _call(run)
        manual = [r for r in rules if not (r["config"].get("managed") or {}).get("by")]     # celles du pilote : dans son bloc
        return templates.TemplateResponse(request, "_fund_panel.html", {
            "snap": snap, "rules": manual, "models": models, "autopilot": auto, "today": today.isoformat(),
            **context(request)})

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
                                              b.get("initial_capital"), b.get("opened_on"))
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
        return await run_in_threadpool(_call, service.place_order, {**b, "strategy_id": strategy_id})

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
        return {"models": _labelled(_call(systematic.available_models))}

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
        for key in ("gross", "min_confidence", "alpha_dm", "alpha_bh"):
            if key in params:
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
        """Active le pilote avec ces réglages (les absents prennent leur défaut)."""
        return await run_in_threadpool(_call, autopilot.configure, strategy_id, await _json_body(request))

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
            settings = autopilot.Settings.from_dict(body) if body else None
            return autopilot.preview(conn, strategy_id, service.current_date(), settings)
        return await run_in_threadpool(_call, run)

    @app.get("/api/fund/strategies/{strategy_id}/autopilot/preview.html")
    async def api_autopilot_preview_html(request: Request, strategy_id: str):
        """Fragment HTML (rendu serveur, échappé) de l'aperçu, pour le panneau de /fonds."""
        params = dict(request.query_params)

        def run(conn):
            settings = autopilot.Settings.from_dict(_query_settings(params)) if params else None
            return autopilot.preview(conn, strategy_id, service.current_date(), settings)
        plan = await run_in_threadpool(_call, run)
        return templates.TemplateResponse(request, "_fund_autopilot_preview.html", {"plan": plan, **context(request)})
