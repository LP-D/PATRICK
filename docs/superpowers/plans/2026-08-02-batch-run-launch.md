# Lancer plusieurs runs à la suite + relancer un run passé — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre de sélectionner plusieurs cibles à la fois sur le formulaire de lancement (elles s'enchaînent automatiquement dans la queue existante), relancer un run passé à l'identique en un clic, et dériver systématiquement le nom d'un run de sa cible + un numéro de séquence.

**Architecture:** Aucun nouvel orchestrateur — la queue FIFO existante (table `job`, `patrick/worker.py`) traite déjà un job à la fois. Le batch consiste à soumettre N jobs en une requête ; le reste (nommage, dossier de sortie) est calculé côté serveur avant l'enqueue.

**Tech Stack:** FastAPI (webapp), Jinja2 (templates), vanilla JS (`app.js`), SQLite (tables `job`/`run` existantes, aucune migration), pytest.

## Global Constraints

- Le nom d'un run est **toujours** `f"{slug(target_symbol)}_{n}"` — jamais de saisie libre, ni en soumission simple ni en batch ni en relance (cf. spec §2).
- `next_run_name` compte `SELECT COUNT(*) FROM run WHERE target = ?` (tout statut confondu) + 1 — pas de nouvelle colonne, pas de migration.
- `POST /runs` répond toujours `{"runs": [...]}` (une liste, même à un seul élément) — plus jamais `{"run_id": ...}` à plat.
- Si une config est invalide parmi N cibles soumises, **rien** n'est enqueue (le batch entier est rejeté) — comportement de validation-avant-enqueue déjà en place, étendu tel quel.
- Pas de confirmation JS avant lancement/relance (cohérent avec le bouton "Lancer" existant, outil local mono-utilisateur).
- Suivre la convention locale de chaque fichier : `index.html`/`app.js` passent par `t()`/`tr()` (i18n FR/EN) ; `run_detail.html`/`target.html` sont en français simple, sans `t()` (déjà le cas avant ce plan — ne pas introduire d'incohérence).

---

## File Structure

- `patrick/webapp/forms.py` — ajoute `slug_target()` ; `build_config_dict()` reçoit `target_symbol`/`name` en paramètres explicites au lieu de les lire dans `form`.
- `patrick/webapp/run_manager.py` — ajoute `next_run_name(target_symbol)`.
- `patrick/webapp/app.py` — `POST /runs` gère plusieurs cibles ; nouvelles routes `GET /api/next-run-names` et `POST /runs/{run_id}/relaunch`.
- `patrick/webapp/templates/index.html` — sélecteur de cible en multi-select, champ nom en lecture seule.
- `patrick/webapp/static/app.js` — soumission batch, aperçu de nom, sélection additive des quick-pick.
- `patrick/webapp/i18n.py` — nouvelle clé `target_multiselect_hint`, texte de `field_run_name` mis à jour.
- `patrick/webapp/templates/run_detail.html`, `target.html` — bouton "Relancer".
- `patrick/webapp/static/style.css` — `.inline-form { display: inline; }`.
- `tests/test_run_naming.py` (nouveau) — `slug_target`, `next_run_name`.
- `tests/test_webapp_forms.py` (nouveau) — `build_config_dict` direct, `GET /api/next-run-names`.
- `tests/test_webapp_smoke.py` (modifié) — contrat `{"runs": [...]}`, batch, relance.

---

### Task 1: `slug_target()` — dériver un nom de fichier/champ sûr depuis un symbole

**Files:**
- Modify: `patrick/webapp/forms.py`
- Test: `tests/test_run_naming.py` (nouveau fichier, créé à cette tâche)

**Interfaces:**
- Produces: `patrick.webapp.forms.slug_target(symbol: str) -> str`

- [ ] **Step 1: Write the failing test**

Crée `tests/test_run_naming.py` :

```python
"""Règle de nommage des runs (spec `docs/superpowers/specs/
2026-08-02-batch-run-launch-design.md` §2) : nom = slug(target) + numéro de
séquence, toujours -- jamais de saisie libre."""
from __future__ import annotations

from patrick.webapp import forms


def test_slug_target_strips_leading_caret():
    assert forms.slug_target("^VIX") == "VIX"


def test_slug_target_replaces_equals():
    assert forms.slug_target("EURUSD=X") == "EURUSD_X"


def test_slug_target_replaces_dot():
    assert forms.slug_target("000001.SS") == "000001_SS"


def test_slug_target_collapses_adjacent_separators():
    assert forms.slug_target("AB==CD") == "AB_CD"


def test_slug_target_leaves_plain_ticker_unchanged():
    assert forms.slug_target("AAPL") == "AAPL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_naming.py -v`
Expected: FAIL avec `AttributeError: module 'patrick.webapp.forms' has no attribute 'slug_target'`

- [ ] **Step 3: Write minimal implementation**

Dans `patrick/webapp/forms.py`, ajoute `import re` à côté des imports existants (`import glob`, `import os`, ligne ~9-10), puis ajoute cette fonction juste après `TARGET_SOURCE_BY_SYMBOL = ...` (ligne 35) :

```python
_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def slug_target(symbol: str) -> str:
    """`^VIX` -> `VIX`, `EURUSD=X` -> `EURUSD_X`, `000001.SS` -> `000001_SS`
    -- dérive un nom de run/dossier de sortie sûr (pas de caractère spécial)
    à partir d'un symbole de cible."""
    return _SLUG_RE.sub("_", symbol).strip("_")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_naming.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/forms.py tests/test_run_naming.py
git commit -m "feat: slug_target() pour dériver un nom de run sûr depuis un symbole"
```

---

### Task 2: `run_manager.next_run_name()` — nom généré + numéro de séquence

**Files:**
- Modify: `patrick/webapp/run_manager.py`
- Test: `tests/test_run_naming.py`

**Interfaces:**
- Consumes: `patrick.webapp.forms.slug_target(symbol: str) -> str` (Task 1)
- Produces: `patrick.webapp.run_manager.next_run_name(target_symbol: str) -> str`

- [ ] **Step 1: Write the failing test**

Ajoute à `tests/test_run_naming.py` (après les imports existants, avant les tests de `slug_target`) :

```python
import pytest

from patrick.tracking import db as trackdb
from patrick.webapp import run_manager


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))


def _seed_run(conn, run_id: str, target: str) -> None:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", 10, 5, "fred")
    trackdb.create_run(conn, run_id, target, 1, "snap1", "{}", "confighash", "sha", 42)
```

Puis, à la fin du fichier :

```python
def test_next_run_name_starts_at_one_with_no_history():
    assert run_manager.next_run_name("^VIX") == "VIX_1"


def test_next_run_name_increments_with_history():
    conn = trackdb.connect()
    try:
        _seed_run(conn, "run1", "^VIX")
        _seed_run(conn, "run2", "^VIX")
    finally:
        conn.close()
    assert run_manager.next_run_name("^VIX") == "VIX_3"


def test_next_run_name_counts_per_target_independently():
    conn = trackdb.connect()
    try:
        _seed_run(conn, "run1", "^VIX")
    finally:
        conn.close()
    assert run_manager.next_run_name("^AORD") == "AORD_1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_naming.py -v`
Expected: FAIL avec `AttributeError: module 'patrick.webapp.run_manager' has no attribute 'next_run_name'`

- [ ] **Step 3: Write minimal implementation**

Dans `patrick/webapp/run_manager.py`, ajoute l'import de `forms` en haut du fichier (à côté des imports `patrick.*` existants, ligne ~19-21) :

```python
from patrick.webapp import forms
```

Puis ajoute cette fonction après `_connect()` (ligne ~29) :

```python
def next_run_name(target_symbol: str) -> str:
    """Nom de run généré = slug(cible) + numéro de séquence (1 + nombre de
    runs déjà enregistrés pour cette cible, tout statut confondu). Seule
    règle de nommage du produit (cf. spec batch-run-launch §2) -- jamais de
    saisie libre, ni en soumission simple, ni en batch, ni en relance."""
    conn = _connect()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM run WHERE target = ?", (target_symbol,)
        ).fetchone()[0]
    finally:
        conn.close()
    return f"{forms.slug_target(target_symbol)}_{count + 1}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_naming.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/run_manager.py tests/test_run_naming.py
git commit -m "feat: run_manager.next_run_name() -- nom de run derive de la cible + numero"
```

---

### Task 3: `build_config_dict()` reçoit `target_symbol`/`name` en paramètres explicites

**Files:**
- Modify: `patrick/webapp/forms.py:169-197` (signature + début du corps de `build_config_dict`)
- Test: `tests/test_webapp_forms.py` (nouveau fichier)

**Interfaces:**
- Consumes: rien de nouveau (refactor pur)
- Produces: `patrick.webapp.forms.build_config_dict(form, *, target_symbol: str, name: str) -> tuple[dict, list[str]]` — signature CHANGÉE (avant : `build_config_dict(form)`, lisait `form.get("target_symbol")`/`form.get("name")` en interne). Seul appelant existant : `patrick/webapp/app.py:183` (traité en Task 5).

- [ ] **Step 1: Write the failing test**

Crée `tests/test_webapp_forms.py` :

```python
"""`build_config_dict` prend désormais `target_symbol`/`name` en paramètres
explicites (plus jamais lus dans `form`) -- un lancement peut soumettre
plusieurs cibles à la fois, une par appel (cf. patrick/webapp/app.py)."""
from __future__ import annotations

from starlette.datastructures import FormData

from patrick.webapp import forms


def _minimal_form(**overrides) -> FormData:
    base = {
        "horizons": "1,2",
        "regimes": "GLOBAL",
        "families": ["technical"],
        "n_features_grid": "5,8",
        "sampler_candidates": ["SMOTE"],
        "algos": ["RandomForest"],
    }
    base.update(overrides)
    items = []
    for k, v in base.items():
        if isinstance(v, list):
            items.extend((k, x) for x in v)
        else:
            items.append((k, v))
    return FormData(items)


def test_build_config_dict_uses_explicit_target_and_name():
    form = _minimal_form()
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_1")
    assert errors == []
    assert config_dict["objective"]["target_symbol"] == "^VIX"
    assert config_dict["name"] == "VIX_1"
    assert config_dict["output"]["dir"] == "runs/VIX_1"


def test_build_config_dict_rejects_unknown_target():
    form = _minimal_form()
    _config_dict, errors = forms.build_config_dict(form, target_symbol="NOT_A_TARGET", name="X_1")
    assert any("invalide" in e.lower() for e in errors)


def test_build_config_dict_respects_explicit_output_dir():
    form = _minimal_form(output_dir="/tmp/custom_runs")
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_2")
    assert errors == []
    assert config_dict["output"]["dir"] == "/tmp/custom_runs"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webapp_forms.py -v`
Expected: FAIL — `build_config_dict() got an unexpected keyword argument 'target_symbol'` (signature actuelle : `build_config_dict(form)`)

- [ ] **Step 3: Write minimal implementation**

Dans `patrick/webapp/forms.py`, remplace les lignes 169-197 (signature + les 4 premières lignes de logique métier du corps) :

```python
def build_config_dict(form) -> tuple[dict, list[str]]:
    """`form` est une `starlette.datastructures.FormData`. Renvoie
    (config_dict, erreurs) — `config_dict` reste utilisable même avec des
    erreurs (pour repeupler le formulaire), mais ne doit pas être passé à
    `RunConfig.model_validate` si `erreurs` est non vide."""
    errors: list[str] = []

    def _require_non_empty(lst: list, label: str) -> list:
        if not lst:
            errors.append(f"« {label} » ne peut pas être vide.")
        return lst

    name = (form.get("name") or "").strip() or "mon_run"
    horizons = _require_non_empty(_int_list(form.get("horizons", "")), "Horizons")
    regimes = _require_non_empty(_split_list(form.get("regimes", "GLOBAL")), "Régimes")
    families = _require_non_empty(form.getlist("families"), "Familles de features")
    vol_models = form.getlist("vol_models")
    if "vol_models" in families:
        vol_models = _require_non_empty(vol_models, "Modèles de volatilité")
    n_features_grid = _require_non_empty(
        _int_list(form.get("n_features_grid", "")), "Grille N (sélection)")
    sampler_candidates = _require_non_empty(form.getlist("sampler_candidates"), "Samplers")
    algos = _require_non_empty(form.getlist("algos"), "Algorithmes")

    target_symbol = (form.get("target_symbol") or "").strip()
    if target_symbol not in TARGET_SOURCE_BY_SYMBOL:
        errors.append("« Que prédire » : choix invalide.")
    target_source = TARGET_SOURCE_BY_SYMBOL.get(target_symbol, "yfinance")
    yf_tickers, fred_series = universe_excluding(target_symbol)
```

par :

```python
def build_config_dict(form, *, target_symbol: str, name: str) -> tuple[dict, list[str]]:
    """`form` est une `starlette.datastructures.FormData`. `target_symbol`/
    `name` sont passés explicitement par l'appelant (`app.py`, une fois par
    cible d'une soumission) plutôt que lus dans `form` : un lancement peut
    soumettre plusieurs cibles à la fois (`<select multiple>`), et le nom
    est toujours dérivé de la cible + un numéro de séquence
    (`run_manager.next_run_name`), jamais saisi à la main. Renvoie
    (config_dict, erreurs) — `config_dict` reste utilisable même avec des
    erreurs (pour repeupler le formulaire), mais ne doit pas être passé à
    `RunConfig.model_validate` si `erreurs` est non vide."""
    errors: list[str] = []

    def _require_non_empty(lst: list, label: str) -> list:
        if not lst:
            errors.append(f"« {label} » ne peut pas être vide.")
        return lst

    horizons = _require_non_empty(_int_list(form.get("horizons", "")), "Horizons")
    regimes = _require_non_empty(_split_list(form.get("regimes", "GLOBAL")), "Régimes")
    families = _require_non_empty(form.getlist("families"), "Familles de features")
    vol_models = form.getlist("vol_models")
    if "vol_models" in families:
        vol_models = _require_non_empty(vol_models, "Modèles de volatilité")
    n_features_grid = _require_non_empty(
        _int_list(form.get("n_features_grid", "")), "Grille N (sélection)")
    sampler_candidates = _require_non_empty(form.getlist("sampler_candidates"), "Samplers")
    algos = _require_non_empty(form.getlist("algos"), "Algorithmes")

    if target_symbol not in TARGET_SOURCE_BY_SYMBOL:
        errors.append("« Que prédire » : choix invalide.")
    target_source = TARGET_SOURCE_BY_SYMBOL.get(target_symbol, "yfinance")
    yf_tickers, fred_series = universe_excluding(target_symbol)
```

Le reste du corps de la fonction (construction de `config_dict`, utilisation de `name`/`target_symbol`/`target_source`/`yf_tickers`/`fred_series`) ne change pas — ces variables locales portent toujours les mêmes noms, seule leur origine (paramètre au lieu de `form.get(...)`) change.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webapp_forms.py -v`
Expected: PASS (3 tests). Ce test cassera aussi `tests/test_webapp_smoke.py` (appelant indirect via `app.py`) — traité en Task 5, ignore ces échecs pour l'instant.

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/forms.py tests/test_webapp_forms.py
git commit -m "refactor: build_config_dict prend target_symbol/name en parametres explicites"
```

---

### Task 4: `GET /api/next-run-names` — aperçu du nom généré

**Files:**
- Modify: `patrick/webapp/app.py`
- Test: `tests/test_webapp_forms.py`

**Interfaces:**
- Consumes: `run_manager.next_run_name(target_symbol: str) -> str` (Task 2)
- Produces: route `GET /api/next-run-names?target=A&target=B` -> `{"A": "A_1", "B": "B_1"}`

- [ ] **Step 1: Write the failing test**

Ajoute à `tests/test_webapp_forms.py` :

```python
import pytest
from fastapi.testclient import TestClient

from patrick.webapp.app import app


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))


def test_next_run_names_endpoint_returns_one_name_per_target():
    client = TestClient(app)
    resp = client.get("/api/next-run-names", params=[("target", "^VIX"), ("target", "^AORD")])
    assert resp.status_code == 200
    assert resp.json() == {"^VIX": "VIX_1", "^AORD": "AORD_1"}


def test_next_run_names_endpoint_dedupes_repeated_targets():
    client = TestClient(app)
    resp = client.get("/api/next-run-names", params=[("target", "^VIX"), ("target", "^VIX")])
    assert resp.json() == {"^VIX": "VIX_1"}
```

Note : le fixture `_isolated_db` ci-dessus duplique celui déjà ajouté en Task 3 (Step 1 de ce même fichier) — pytest autorise plusieurs fixtures `autouse` du même nom dans un module tant qu'il n'y en a qu'une définition ; si Task 3 l'a déjà ajouté, ne le redéfinis pas ici.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webapp_forms.py -v`
Expected: FAIL avec `404 Not Found` (route inexistante)

- [ ] **Step 3: Write minimal implementation**

Dans `patrick/webapp/app.py`, change l'import FastAPI (ligne 10) :

```python
from fastapi import FastAPI, HTTPException, Request
```

en :

```python
from fastapi import FastAPI, HTTPException, Query, Request
```

Puis ajoute cette route juste avant `@app.post("/runs")` (ligne 176) :

```python
@app.get("/api/next-run-names")
def next_run_names(target: list[str] = Query(default=[])):
    """Aperçu (lecture seule) du nom qui sera attribué à chaque cible si le
    formulaire est soumis maintenant — appelé par `app.js` quand la
    sélection de cibles change. Ne réserve rien : le nombre réel peut
    différer si d'autres runs pour la même cible s'intercalent avant la
    soumission (cf. spec batch-run-launch, limite connue)."""
    return {t: run_manager.next_run_name(t) for t in dict.fromkeys(target)}


@app.post("/runs")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webapp_forms.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/app.py tests/test_webapp_forms.py
git commit -m "feat: endpoint GET /api/next-run-names pour l'apercu de nom cote formulaire"
```

---

### Task 5: `POST /runs` accepte plusieurs cibles (batch)

**Files:**
- Modify: `patrick/webapp/app.py:176-202`
- Modify: `tests/test_webapp_smoke.py`

**Interfaces:**
- Consumes: `forms.build_config_dict(form, *, target_symbol, name)` (Task 3), `run_manager.next_run_name(target_symbol)` (Task 2)
- Produces: `POST /runs` répond désormais `{"runs": [{"run_id", "status", "queue_position", "target"}, ...]}` (toujours une liste) au lieu de `{"run_id", "status", "queue_position"}` à plat. Lit `form.getlist("target_symbols")` au lieu de `form.get("target_symbol")`.

- [ ] **Step 1: Write the failing test**

Dans `tests/test_webapp_smoke.py`, remplace la fonction `_form_data` (elle contient encore `"name"` et `"target_symbol"` singulier, incompatibles avec le nouveau contrat) :

```python
def _form_data(tmp_path) -> dict:
    return {
        "name": "smoke_web_test",
        "target_symbol": TARGET_SYMBOL,
        "horizons": "3,5",
```

par :

```python
def _form_data(tmp_path) -> dict:
    return {
        "target_symbols": [TARGET_SYMBOL],
        "horizons": "3,5",
```

(le reste du dict `_form_data` ne change pas).

Puis remplace les deux usages de `body["run_id"]` dans `test_run_via_web_form_end_to_end` :

```python
def test_run_via_web_form_end_to_end(tmp_path):
    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # `start_run` enfile désormais toujours en base ('queued') : la transition
    # vers 'running' est décidée par le worker séparé, jamais immédiate.
    assert body["status"] == "queued", body
    run_id = body["run_id"]
```

par :

```python
def test_run_via_web_form_end_to_end(tmp_path):
    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["runs"]) == 1, body
    run = body["runs"][0]
    # `start_run` enfile désormais toujours en base ('queued') : la transition
    # vers 'running' est décidée par le worker séparé, jamais immédiate.
    assert run["status"] == "queued", run
    run_id = run["run_id"]
```

Et dans `test_second_run_queues_then_auto_starts`, remplace :

```python
    form_a = _form_data(tmp_path)
    form_a["name"] = "run_a"
    form_a["output_dir"] = str(tmp_path / "runs_a")
    resp_a = client.post("/runs", data=form_a)
    assert resp_a.status_code == 200, resp_a.text
    run_a = resp_a.json()
    assert run_a["status"] == "queued"

    form_b = _form_data(tmp_path)
    form_b["name"] = "run_b"
    form_b["output_dir"] = str(tmp_path / "runs_b")
    resp_b = client.post("/runs", data=form_b)
    assert resp_b.status_code == 200, resp_b.text
    run_b = resp_b.json()
    assert run_b["status"] == "queued"
```

par :

```python
    form_a = _form_data(tmp_path)
    form_a["output_dir"] = str(tmp_path / "runs_a")
    resp_a = client.post("/runs", data=form_a)
    assert resp_a.status_code == 200, resp_a.text
    run_a = resp_a.json()["runs"][0]
    assert run_a["status"] == "queued"

    form_b = _form_data(tmp_path)
    form_b["output_dir"] = str(tmp_path / "runs_b")
    resp_b = client.post("/runs", data=form_b)
    assert resp_b.status_code == 200, resp_b.text
    run_b = resp_b.json()["runs"][0]
    assert run_b["status"] == "queued"
```

(les usages suivants de `run_a["run_id"]`/`run_b["run_id"]` plus bas dans ce test ne changent pas — `run_a`/`run_b` sont maintenant les dicts déjà extraits de `["runs"][0]`).

Ajoute aussi cet import en tête du fichier, à côté des imports `patrick.*` existants (`from patrick.data.store import DataStore`, `from patrick.webapp.app import app`) :

```python
from patrick.webapp import forms, run_manager
```

Enfin, ajoute ce nouveau test à la fin du fichier :

```python
def test_batch_submit_queues_one_job_per_target(tmp_path):
    """Sélectionner plusieurs cibles dans le formulaire enfile un job par
    cible, chacun avec un nom/dossier de sortie distinct -- pas de nouvel
    orchestrateur, juste plusieurs jobs pour la même queue FIFO."""
    DataStore(root=str(tmp_path / "store")).save("raw_^AORD", _synthetic_raw(seed=1))
    client = TestClient(app)

    form = _form_data(tmp_path)
    form["target_symbols"] = [TARGET_SYMBOL, "^AORD"]
    resp = client.post("/runs", data=form)
    assert resp.status_code == 200, resp.text
    runs = resp.json()["runs"]

    assert len(runs) == 2
    assert {r["target"] for r in runs} == {TARGET_SYMBOL, "^AORD"}
    assert len({r["run_id"] for r in runs}) == 2

    # Chaque job existe bien côté serveur, dans un état actif légitime, avec
    # un nom distinct dérivé de SA cible -- pas seulement "la réponse HTTP
    # avait 2 entrées" (assertion trop faible pour détecter un job perdu ou
    # mal routé).
    for r in runs:
        status = client.get(f"/runs/{r['run_id']}/status").json()
        assert status["status"] in ("queued", "running"), status
        assert status["name"].startswith(forms.slug_target(r["target"])), status
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webapp_smoke.py -v -m slow`
Expected: FAIL — `test_run_via_web_form_end_to_end` et `test_second_run_queues_then_auto_starts` échouent avec `KeyError: 'run_id'` (l'endpoint renvoie encore `{"run_id": ...}` à plat) ; `test_batch_submit_queues_one_job_per_target` échoue de la même façon.

- [ ] **Step 3: Write minimal implementation**

Dans `patrick/webapp/app.py`, remplace le bloc `create_run` (lignes 176-202) :

```python
@app.post("/runs")
async def create_run(request: Request):
    """Répond en JSON (consommé par `app.js` en AJAX, sans rechargement de
    page) : un run est démarré immédiatement s'il n'y en a pas d'actif, sinon
    mis en file d'attente — jamais rejeté, `start_run` ne lève plus d'erreur
    dans ce cas (cf. `run_manager.py`)."""
    form = await request.form()
    config_dict, errors = forms.build_config_dict(form)

    if not errors:
        try:
            config = RunConfig.model_validate(config_dict)
        except ValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()]
            config = None
    else:
        config = None

    if errors:
        return JSONResponse({"errors": errors}, status_code=400)

    job_view = run_manager.start_run(config)
    return JSONResponse({
        "run_id": job_view["id"],
        "status": job_view["status"],
        "queue_position": job_view["queue_position"],
    })
```

par :

```python
@app.post("/runs")
async def create_run(request: Request):
    """Répond en JSON (consommé par `app.js` en AJAX, sans rechargement de
    page) : un run est démarré immédiatement s'il n'y en a pas d'actif, sinon
    mis en file d'attente — jamais rejeté, `start_run` ne lève plus d'erreur
    dans ce cas (cf. `run_manager.py`).

    Une soumission peut cibler plusieurs symboles à la fois (`<select
    multiple name="target_symbols">`) : un job est enfilé par cible, avec un
    nom/dossier de sortie distincts (`run_manager.next_run_name`) — la queue
    FIFO existante les enchaîne, aucun nouvel orchestrateur. Si une seule
    config est invalide parmi les cibles soumises, rien n'est enqueue."""
    form = await request.form()
    targets = form.getlist("target_symbols")
    if not targets:
        return JSONResponse({"errors": ["Sélectionne au moins une cible."]}, status_code=400)

    raw_output_dir = (form.get("output_dir") or "").strip()
    errors: list[str] = []
    configs: list[RunConfig] = []
    for sym in targets:
        name = run_manager.next_run_name(sym)
        config_dict, errs = forms.build_config_dict(form, target_symbol=sym, name=name)
        if errs:
            errors.extend(f"{sym} : {e}" for e in errs)
            continue
        # Un dossier de sortie saisi à la main s'applique tel quel à une
        # cible unique ; pour un batch, il est partagé par le formulaire --
        # sans ce garde-fou, N cibles avec le même `output_dir` explicite
        # écraseraient les artefacts les unes des autres.
        if len(targets) > 1 and raw_output_dir:
            config_dict["output"]["dir"] = f"{raw_output_dir}/{name}"
        try:
            configs.append(RunConfig.model_validate(config_dict))
        except ValidationError as exc:
            errors.extend(
                f"{sym} : {'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()
            )

    if errors:
        return JSONResponse({"errors": errors}, status_code=400)

    runs = []
    for config in configs:
        job_view = run_manager.start_run(config)
        runs.append({
            "run_id": job_view["id"],
            "status": job_view["status"],
            "queue_position": job_view["queue_position"],
            "target": config.objective.target_symbol,
        })
    return JSONResponse({"runs": runs})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webapp_smoke.py -v -m slow`
Expected: PASS (3 tests). Attendu ~2-3 min (pipeline complet réel via worker séparé, cf. docstring du fichier).

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/app.py tests/test_webapp_smoke.py
git commit -m "feat: POST /runs accepte plusieurs cibles, enfile un job par cible"
```

---

### Task 6: `POST /runs/{run_id}/relaunch` — relancer un run passé

**Files:**
- Modify: `patrick/webapp/app.py`
- Modify: `tests/test_webapp_smoke.py`

**Interfaces:**
- Consumes: `run_manager.get_run_config(run_id)`, `run_manager.next_run_name(target_symbol)`, `run_manager.start_run(config)` (existants/Task 2)
- Produces: route `POST /runs/{run_id}/relaunch` -> `303 See Other` vers `/runs/{nouveau_run_id}`. Fonctionne pour un run soumis via le web (table `job`) ET pour un run lancé en CLI (repli sur `run.config_json`).

- [ ] **Step 1: Write the failing test**

Ajoute à `tests/test_webapp_smoke.py` :

```python
def test_relaunch_reuses_config_with_fresh_name(tmp_path):
    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path))
    run_id = resp.json()["runs"][0]["run_id"]
    _wait_for_status(client, run_id, not_in={"queued", "running"}, deadline_s=240)

    relaunch_resp = client.post(f"/runs/{run_id}/relaunch", follow_redirects=False)
    assert relaunch_resp.status_code == 303, relaunch_resp.text
    new_run_id = relaunch_resp.headers["location"].rsplit("/", 1)[-1]
    assert new_run_id != run_id

    old_config = run_manager.get_run_config(run_id)
    new_config = run_manager.get_run_config(new_run_id)
    assert new_config.objective.target_symbol == old_config.objective.target_symbol
    assert new_config.objective.horizons == old_config.objective.horizons
    assert new_config.name != old_config.name
    assert new_config.name.startswith(forms.slug_target(old_config.objective.target_symbol))


def test_relaunch_404_on_unknown_run():
    client = TestClient(app)
    resp = client.post("/runs/does-not-exist/relaunch")
    assert resp.status_code == 404
```

`forms`/`run_manager` sont déjà importés en tête du fichier depuis Task 5 (Step 1) — rien à ajouter ici.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webapp_smoke.py -v -m slow`
Expected: FAIL — `404 Not Found` (route inexistante) sur `test_relaunch_reuses_config_with_fresh_name` ; `test_relaunch_404_on_unknown_run` peut passer par accident (404 générique FastAPI) mais pour la mauvaise raison — vérifie que le premier test échoue avant de continuer.

- [ ] **Step 3: Write minimal implementation**

Dans `patrick/webapp/app.py`, ajoute cette route juste après le bloc `create_run` (après le `POST /runs` de Task 5, avant `GET /api/run-state`) :

```python
@app.post("/runs/{run_id}/relaunch")
def relaunch_run(run_id: str):
    """Relance un run passé à l'identique, sauf nom/dossier de sortie
    (nouveau numéro, cf. `run_manager.next_run_name`) -- une nouvelle
    tentative doit être distinguable dans l'historique, pas confondue avec
    l'originale. Fonctionne pour un run soumis via le web (config retrouvée
    dans la table `job`) et pour un run lancé en CLI (repli sur
    `run.config_json`, absent de `job`)."""
    config = run_manager.get_run_config(run_id)
    if config is None:
        conn = trackdb.connect()
        try:
            row = conn.execute(
                "SELECT config_json FROM run WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None or not row[0]:
            raise HTTPException(status_code=404, detail="Run introuvable (config indisponible)")
        config = RunConfig.model_validate_json(row[0])

    new_name = run_manager.next_run_name(config.objective.target_symbol)
    cfg_dict = config.model_dump()
    cfg_dict["name"] = new_name
    cfg_dict["output"]["dir"] = f"runs/{new_name}"
    new_config = RunConfig.model_validate(cfg_dict)

    job_view = run_manager.start_run(new_config)
    return RedirectResponse(f"/runs/{job_view['id']}", status_code=303)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webapp_smoke.py -v -m slow`
Expected: PASS (5 tests). Attendu ~4-5 min (deux pipelines complets : le run initial + son relaunch, tous deux jusqu'à `done`).

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/app.py tests/test_webapp_smoke.py
git commit -m "feat: POST /runs/{run_id}/relaunch pour relancer un run passe"
```

---

### Task 7: Frontend — sélection multi-cible + aperçu de nom (`index.html`, `app.js`, `i18n.py`)

**Files:**
- Modify: `patrick/webapp/templates/index.html:51-61` (sélecteur de cible), `:44-47` (champ nom)
- Modify: `patrick/webapp/static/app.js` (soumission, récap, quick-pick, aperçu de nom)
- Modify: `patrick/webapp/i18n.py`

**Interfaces:**
- Consumes: `POST /runs` répondant `{"runs": [...]}` (Task 5), `GET /api/next-run-names` (Task 4)
- Produces: aucune nouvelle interface Python — changements UI uniquement.

Pas de test automatisé pour cette tâche (JS/DOM, pas de suite de tests front dans ce projet) — vérification manuelle en Step 4.

- [ ] **Step 1: `i18n.py` — nouvelle clé + mise à jour du libellé du nom**

Dans `patrick/webapp/i18n.py`, remplace :

```python
    "section_run": {"fr": "Run", "en": "Run"},
    "field_run_name": {"fr": "Nom du run", "en": "Run name"},
```

par :

```python
    "section_run": {"fr": "Run", "en": "Run"},
    "field_run_name": {"fr": "Nom du run (généré automatiquement)", "en": "Run name (auto-generated)"},
```

Et remplace :

```python
    "section_objective": {"fr": "Objectif — que prédire ?", "en": "Objective — what to predict?"},
    "field_target": {"fr": "Cible", "en": "Target"},
```

par :

```python
    "section_objective": {"fr": "Objectif — que prédire ?", "en": "Objective — what to predict?"},
    "field_target": {"fr": "Cible(s)", "en": "Target(s)"},
    "target_multiselect_hint": {
        "fr": "Ctrl/Cmd + clic (ou glisser) pour sélectionner plusieurs cibles — un run est lancé par cible, à la suite.",
        "en": "Ctrl/Cmd + click (or drag) to pick multiple targets — one run launches per target, in sequence.",
    },
```

- [ ] **Step 2: `index.html` — champ nom en lecture seule, sélecteur multi-cible**

Remplace (lignes 44-47) :

```html
        <fieldset>
            <legend>{{ t('section_run') }}</legend>
            <label>{{ t('field_run_name') }}
                <input type="text" name="name" value="{{ view.name }}" required>
            </label>
        </fieldset>
```

par :

```html
        <fieldset>
            <legend>{{ t('section_run') }}</legend>
            <label>{{ t('field_run_name') }}
                <input type="text" id="run-name-preview" value="{{ view.name }}" readonly>
            </label>
        </fieldset>
```

Remplace (lignes 51-61) :

```html
            <label>{{ t('field_target') }}
                <select name="target_symbol" id="target_symbol" required>
                    {% for group, items in target_groups.items() %}
                    <optgroup label="{{ group_labels.get(group, group) }}">
                        {% for sym, sym_label in items %}
                        <option value="{{ sym }}" {% if view.target_symbol == sym %}selected{% endif %}>{{ sym }} — {{ sym_label }}</option>
                        {% endfor %}
                    </optgroup>
                    {% endfor %}
                </select>
            </label>
```

par :

```html
            <label>{{ t('field_target') }}
                <select name="target_symbols" id="target_symbols" multiple required size="8">
                    {% for group, items in target_groups.items() %}
                    <optgroup label="{{ group_labels.get(group, group) }}">
                        {% for sym, sym_label in items %}
                        <option value="{{ sym }}" {% if view.target_symbol == sym %}selected{% endif %}>{{ sym }} — {{ sym_label }}</option>
                        {% endfor %}
                    </optgroup>
                    {% endfor %}
                </select>
                <p class="hint">{{ t('target_multiselect_hint') }}</p>
            </label>
```

- [ ] **Step 3: `app.js` — soumission batch, récap, quick-pick additif, aperçu de nom**

Remplace (lignes 487-499, `refreshRecap`) :

```javascript
    const launchRecap = document.getElementById("launch-recap");
    function refreshRecap() {
        if (!launchRecap || !form) return;
        const target = form.querySelector("#target_symbol");
        const horizons = form.querySelector("[name=horizons]");
        const scheme = form.querySelector("[name=scheme]");
        const bits = [];
        if (target && target.value) bits.push("<b>" + target.value + "</b>");
        if (horizons && horizons.value) {
            bits.push(fmtStr(tr("recap_horizons", "horizons {h}"), { h: horizons.value }));
        }
        if (scheme && scheme.selectedIndex >= 0) bits.push(scheme.options[scheme.selectedIndex].textContent.trim());
        launchRecap.innerHTML = bits.join(" · ");
    }
```

par :

```javascript
    const launchRecap = document.getElementById("launch-recap");
    function refreshRecap() {
        if (!launchRecap || !form) return;
        const target = form.querySelector("#target_symbols");
        const horizons = form.querySelector("[name=horizons]");
        const scheme = form.querySelector("[name=scheme]");
        const bits = [];
        if (target) {
            const selected = Array.from(target.selectedOptions).map((o) => o.value);
            if (selected.length === 1) bits.push("<b>" + selected[0] + "</b>");
            else if (selected.length > 1) bits.push("<b>" + selected.length + " cibles</b>");
        }
        if (horizons && horizons.value) {
            bits.push(fmtStr(tr("recap_horizons", "horizons {h}"), { h: horizons.value }));
        }
        if (scheme && scheme.selectedIndex >= 0) bits.push(scheme.options[scheme.selectedIndex].textContent.trim());
        launchRecap.innerHTML = bits.join(" · ");
    }

    // --- aperçu (lecture seule) du nom que le serveur attribuera à chaque
    // cible sélectionnée -- appelle /api/next-run-names, ne réserve rien. ---
    const runNamePreview = document.getElementById("run-name-preview");
    async function refreshRunNamePreview() {
        if (!runNamePreview || !form) return;
        const select = form.querySelector("#target_symbols");
        if (!select) return;
        const selected = Array.from(select.selectedOptions).map((o) => o.value);
        if (!selected.length) {
            runNamePreview.value = "";
            return;
        }
        const params = new URLSearchParams();
        selected.forEach((s) => params.append("target", s));
        try {
            const res = await fetch(`/api/next-run-names?${params}`);
            const names = await res.json();
            runNamePreview.value = selected.map((s) => names[s]).filter(Boolean).join(", ");
        } catch (e) {
            // aperçu best-effort : une panne réseau ne doit pas bloquer le formulaire.
        }
    }
```

Remplace (lignes 501-509) :

```javascript
    if (advBlocks.length || launchRecap) {
        advBlocks.forEach((block) => advBaseline.set(block, advSignature(block)));
        refreshAdvStates();
        refreshRecap();
        if (form) {
            form.addEventListener("change", function () { refreshAdvStates(); refreshRecap(); });
            form.addEventListener("input", refreshRecap);
        }
    }
```

par :

```javascript
    if (advBlocks.length || launchRecap) {
        advBlocks.forEach((block) => advBaseline.set(block, advSignature(block)));
        refreshAdvStates();
        refreshRecap();
        if (form) {
            form.addEventListener("change", function () { refreshAdvStates(); refreshRecap(); });
            form.addEventListener("input", refreshRecap);
        }
    }

    const targetSymbolsSelect = document.getElementById("target_symbols");
    if (targetSymbolsSelect) {
        targetSymbolsSelect.addEventListener("change", refreshRunNamePreview);
        refreshRunNamePreview();
    }
```

Remplace (lignes 514-534, le handler `moversColumns`) :

```javascript
    const moversColumns = document.getElementById("movers-columns");
    if (moversColumns) {
        moversColumns.addEventListener("click", function (ev) {
            const btn = ev.target.closest(".movers-pick");
            if (!btn) return;
            const select = document.getElementById("target_symbol");
            if (!select) return;
            const symbol = btn.dataset.symbol;
            const match = Array.from(select.options).some((o) => o.value === symbol);
            if (!match) {
                btn.title = fmtStr(tr("movers_not_a_target", "{s} n'est pas une cible disponible."), { s: symbol });
                return;
            }
            select.value = symbol;
            // `change` déclenche le rechargement de l'aperçu marché (market.js)
            // et le rafraîchissement du récapitulatif : poser `.value` seul ne
            // notifie personne.
            select.dispatchEvent(new Event("change", { bubbles: true }));
            select.focus({ preventScroll: false });
        });
    }
```

par :

```javascript
    const moversColumns = document.getElementById("movers-columns");
    if (moversColumns) {
        moversColumns.addEventListener("click", function (ev) {
            const btn = ev.target.closest(".movers-pick");
            if (!btn) return;
            const select = document.getElementById("target_symbols");
            if (!select) return;
            const symbol = btn.dataset.symbol;
            const option = Array.from(select.options).find((o) => o.value === symbol);
            if (!option) {
                btn.title = fmtStr(tr("movers_not_a_target", "{s} n'est pas une cible disponible."), { s: symbol });
                return;
            }
            // Additif, pas remplacement : un clic sur une variation ajoute
            // cette cible à la sélection en cours au lieu de l'écraser --
            // c'est ainsi qu'on compose un batch depuis ce panneau.
            option.selected = true;
            // `change` déclenche le rechargement de l'aperçu marché (market.js)
            // et le rafraîchissement du récapitulatif/de l'aperçu de nom : poser
            // `.selected` seul ne notifie personne.
            select.dispatchEvent(new Event("change", { bubbles: true }));
            select.focus({ preventScroll: false });
        });
    }
```

Enfin, remplace le handler de soumission (lignes 373-399) :

```javascript
    if (form) {
        form.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            clearErrors();
            launchBtn.disabled = true;
            try {
                const res = await fetch("/runs", { method: "POST", body: new FormData(form) });
                const data = await res.json();
                if (!res.ok) {
                    showErrors(data.errors || [tr("run_launch_error", "Error launching the run.")]);
                    return;
                }
                if (data.status === "running") {
                    startTracking(data.run_id);
                } else {
                    // "queued" : le run affiché reste celui déjà actif ; on
                    // rafraîchit juste la file d'attente tout de suite plutôt
                    // que d'attendre le prochain tick de runStatePoll.
                    runStatePoll();
                }
            } catch (e) {
                showErrors([tr("run_launch_error", "Error launching the run.")]);
            } finally {
                launchBtn.disabled = false;
            }
        });
    }
```

par :

```javascript
    if (form) {
        form.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            clearErrors();
            launchBtn.disabled = true;
            try {
                const res = await fetch("/runs", { method: "POST", body: new FormData(form) });
                const data = await res.json();
                if (!res.ok) {
                    showErrors(data.errors || [tr("run_launch_error", "Error launching the run.")]);
                    return;
                }
                // Chaque job posé (un par cible sélectionnée) est 'queued' à cet
                // instant (cf. run_manager.start_run) : le passage à 'running' est
                // décidé par le worker séparé, repéré par le polling périodique de
                // l'état de la file (runStatePoll), jamais ici.
                runStatePoll();
            } catch (e) {
                showErrors([tr("run_launch_error", "Error launching the run.")]);
            } finally {
                launchBtn.disabled = false;
            }
        });
    }
```

- [ ] **Step 4: Vérification manuelle dans le navigateur**

```bash
python -m patrick.cli serve
```

Ouvre `http://127.0.0.1:8000/`, puis vérifie :
1. Le sélecteur "Cible(s)" affiche plusieurs lignes (multi-select natif) — sélectionner 2-3 cibles avec Ctrl/Cmd+clic.
2. Le champ "Nom du run" (lecture seule) se remplit tout seul avec les noms générés (ex. `VIX_1, AAPL_1`) après la sélection.
3. Le récapitulatif au-dessus du bouton "Lancer" affiche "N cibles" quand plusieurs sont sélectionnées.
4. Cliquer une ligne dans "Plus fortes variations" AJOUTE sa cible à la sélection existante (ne la remplace pas).
5. Soumettre avec 2 cibles sélectionnées : la file d'attente affiche 2 entrées (`#queue-panel`), qui s'enchaînent l'une après l'autre.
6. Aucune erreur dans la console navigateur (F12).

Arrête le serveur (`Ctrl+C`) une fois vérifié.

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/templates/index.html patrick/webapp/static/app.js patrick/webapp/i18n.py
git commit -m "feat: selection multi-cible + apercu de nom en lecture seule sur le formulaire de lancement"
```

---

### Task 8: Frontend — bouton "Relancer" (`run_detail.html`, `target.html`, `style.css`)

**Files:**
- Modify: `patrick/webapp/templates/run_detail.html:19-25`
- Modify: `patrick/webapp/templates/target.html:56-74`
- Modify: `patrick/webapp/static/style.css`

**Interfaces:**
- Consumes: `POST /runs/{run_id}/relaunch` (Task 6)
- Produces: aucune nouvelle interface Python — changements UI uniquement.

Pas de test automatisé (templates/CSS) — vérification manuelle en Step 4.

- [ ] **Step 1: `style.css` — utilitaire pour un `<form>` en ligne**

Ajoute, juste après la règle `button.primary:disabled { ... }` (repère : ligne ~536-538 dans `patrick/webapp/static/style.css`, cherche `button.primary:disabled`) :

```css
.inline-form { display: inline; }
```

- [ ] **Step 2: `run_detail.html` — bouton "Relancer ce run"**

Remplace (lignes 19-25) :

```html
<h1 class="page-title">{{ detail.config.name or run.run_id }}</h1>
<p class="page-subtitle">
    <a href="/targets/{{ run.target }}">{{ run.target }}</a> · horizon {{ run.horizon }}j ·
    {{ status_badge('CPCV' if detail.is_cpcv else 'walk-forward', 'neutral') }}
    {{ status_badge(run.status, state) }} ·
    lancé le {{ run.started_at or '—' }}{% if run.finished_at %}, terminé le {{ run.finished_at }}{% endif %}
</p>
```

par :

```html
<h1 class="page-title">{{ detail.config.name or run.run_id }}</h1>
<p class="page-subtitle">
    <a href="/targets/{{ run.target }}">{{ run.target }}</a> · horizon {{ run.horizon }}j ·
    {{ status_badge('CPCV' if detail.is_cpcv else 'walk-forward', 'neutral') }}
    {{ status_badge(run.status, state) }} ·
    lancé le {{ run.started_at or '—' }}{% if run.finished_at %}, terminé le {{ run.finished_at }}{% endif %}
</p>
<form method="post" action="/runs/{{ run.run_id }}/relaunch" class="inline-form">
    <button type="submit" class="primary">Relancer ce run</button>
</form>
```

- [ ] **Step 3: `target.html` — colonne "Relancer" dans la table des runs**

Remplace (lignes 56-74) :

```html
<section class="card">
<h2>Runs</h2>
{% set rows = [] %}
{% for r in detail.runs %}
{% set state = 'ok' if r.status == 'done' else ('pending' if r.status in ('running', 'queued') else ('error' if r.status in ('failed', 'error') else 'neutral')) %}
{% set dm_cell = ("%.4f" | format(r.dm_result.p_value)) if r.dm_result else '<span class="na">—</span>' %}
{% set _ = rows.append([
    '<a href="/runs/' ~ r.run_id ~ '">' ~ (r.name or r.run_id) ~ '</a>',
    r.horizon ~ 'j',
    ('CPCV' if r.scheme == 'cpcv' else 'walk-forward'),
    status_badge(r.status, state),
    r.started_at or '—',
    r.n_trials if r.n_trials is not none else '<span class="na">—</span>',
    ('%.4f' | format(r.best_f1_dir) if r.best_f1_dir is not none else '<span class="na">—</span>'),
    dm_cell,
]) %}
{% endfor %}
{{ data_table(["Run", "Horizon", "Schéma", "Statut", "Démarré", "Essais", "F1_dir (meilleur essai)", "DM p-value"],
              rows, num_cols=[1, 5, 6, 7],
              footer=(detail.runs | length) ~ " run(s) · F1_dir = meilleur essai sur n, non déflaté ; p-value DM brute — la version corrigée du test multiple (BH entre cibles) est le bloc de mesure en haut de cette page.") }}
</section>
```

par :

```html
<section class="card">
<h2>Runs</h2>
{% set rows = [] %}
{% for r in detail.runs %}
{% set state = 'ok' if r.status == 'done' else ('pending' if r.status in ('running', 'queued') else ('error' if r.status in ('failed', 'error') else 'neutral')) %}
{% set dm_cell = ("%.4f" | format(r.dm_result.p_value)) if r.dm_result else '<span class="na">—</span>' %}
{% set relaunch_cell = '<form method="post" action="/runs/' ~ r.run_id ~ '/relaunch" class="inline-form"><button type="submit" class="primary">Relancer</button></form>' %}
{% set _ = rows.append([
    '<a href="/runs/' ~ r.run_id ~ '">' ~ (r.name or r.run_id) ~ '</a>',
    r.horizon ~ 'j',
    ('CPCV' if r.scheme == 'cpcv' else 'walk-forward'),
    status_badge(r.status, state),
    r.started_at or '—',
    r.n_trials if r.n_trials is not none else '<span class="na">—</span>',
    ('%.4f' | format(r.best_f1_dir) if r.best_f1_dir is not none else '<span class="na">—</span>'),
    dm_cell,
    relaunch_cell,
]) %}
{% endfor %}
{{ data_table(["Run", "Horizon", "Schéma", "Statut", "Démarré", "Essais", "F1_dir (meilleur essai)", "DM p-value", "Relancer"],
              rows, num_cols=[1, 5, 6, 7],
              footer=(detail.runs | length) ~ " run(s) · F1_dir = meilleur essai sur n, non déflaté ; p-value DM brute — la version corrigée du test multiple (BH entre cibles) est le bloc de mesure en haut de cette page.") }}
</section>
```

- [ ] **Step 4: Vérification manuelle dans le navigateur**

```bash
python -m patrick.cli serve
```

Ouvre la page de détail d'un run passé (`/runs/<run_id>`, prends un `run_id` existant via `/runs`), puis :
1. Vérifie qu'un bouton "Relancer ce run" apparaît sous le sous-titre, et qu'il reste sur la même ligne (pas de saut de bloc).
2. Clique dessus : la page redirige vers `/runs/<nouveau_run_id>` et le suivi en direct démarre.
3. Sur `/targets/<un_target_avec_historique>`, vérifie la nouvelle colonne "Relancer" dans la table des runs et son fonctionnement identique.

Arrête le serveur (`Ctrl+C`) une fois vérifié.

- [ ] **Step 5: Commit**

```bash
git add patrick/webapp/templates/run_detail.html patrick/webapp/templates/target.html patrick/webapp/static/style.css
git commit -m "feat: bouton Relancer sur la page de detail d'un run et l'historique par cible"
```

---

### Task 9: Vérification finale

**Files:** aucun (validation seule)

**Interfaces:** aucune

- [ ] **Step 1: Suite rapide complète**

Run: `pytest`
Expected: PASS, tout le fichier `tests/` sauf les tests `slow` (≈2 min, cf. `pyproject.toml`)

- [ ] **Step 2: Suite lente touchée par ce plan**

Run: `pytest -m slow tests/test_webapp_smoke.py -v`
Expected: PASS (5 tests, ≈6-8 min : deux pipelines complets exécutés dans `test_relaunch_reuses_config_with_fresh_name` + un dans `test_run_via_web_form_end_to_end` + le batch de `test_batch_submit_queues_one_job_per_target`, qui n'attend pas la complétion)

- [ ] **Step 3: Vérification manuelle bout-en-bout**

Reprends les Steps 4 de Task 7 et Task 8 (`python -m patrick.cli serve`) une dernière fois, cette fois-ci du batch complet : sélectionner 2 cibles, lancer, laisser la première se terminer, observer la seconde démarrer automatiquement (queue FIFO), puis relancer l'une des deux depuis sa page de détail.

- [ ] **Step 4: `graphify update .`**

Run: `graphify update .` (si `graphify-out/graph.json` existe dans le repo — cf. CLAUDE.md du projet) pour garder le graphe de connaissance à jour après ces changements de code.

Pas de commit à cette tâche — vérification seule. Si un problème est détecté, revenir à la tâche concernée, corriger, et commit séparément.
