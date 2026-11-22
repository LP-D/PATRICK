// Tests des fonctions pures du laboratoire de stratégies (static/strategies.js) : description des règles, grille, CSV, description d'étude.
// Lancé par tests/webapp/test_strategies_page.py ; sans DOM.
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const S = require(path.join(__dirname, "..", "..", "patrick", "webapp", "static", "strategies.js"));

// ---- description lisible des règles
assert.equal(S.operandText({ ind: "sma", n: 50 }), "sma(50)");
assert.equal(S.operandText({ ind: "price", symbol: "^VIX" }), "price [^VIX]");
assert.equal(S.operandText({ value: 25 }), "25");
assert.equal(S.operandText({ ind: "mom", n: 252, skip: 21, mult: 1.02, shift: 1 }), "1.02 × mom(252, 21) (t−1)");
const tr = (k) => ({ st_ind_sma: "MM", st_ind_price: "Cours", st_and: "et", st_or: "ou", st_op_between: "entre", st_op_crosses_above: "croise au-dessus de" }[k] || k);
assert.equal(S.conditionText({ left: { ind: "price" }, op: ">=", right: { ind: "sma", n: 200 } }, tr), "Cours ≥ MM(200)");
assert.equal(S.conditionText({ left: { ind: "price" }, op: "between", low: { value: 1 }, high: { value: 2 } }, tr), "Cours entre [1 ; 2]");
assert.equal(S.groupText({ all: [{ left: { ind: "price" }, op: ">", right: { value: 1 } }], any: [{ left: { ind: "price" }, op: "<", right: { value: 5 } }, { left: { ind: "price" }, op: "crosses_above", right: { value: 9 } }] }, tr),
    "Cours > 1 et (Cours < 5 ou Cours croise au-dessus de 9)");
assert.equal(S.groupText(null), "");

// ---- grille de sensibilité : lignes = paramètre 2, colonnes = paramètre 1, valeurs manquantes à null
const grid = { axes: [{ param: "fast", values: [10, 20] }, { param: "slow", values: [100, 200] }],
               cells: [{ params: { fast: 10, slow: 100 }, sharpe: 0.5 }, { params: { fast: 20, slow: 100 }, sharpe: -0.2 }, { params: { fast: 10, slow: 200 }, sharpe: 1.1 }] };
const mx = S.gridMatrix(grid, "sharpe");
assert.deepEqual(mx.rows, [[0.5, -0.2], [1.1, null]]);
assert.equal(mx.min, -0.2);
assert.equal(mx.max, 1.1);
assert.equal(S.gridMatrix({ axes: [] }, "sharpe"), null);
assert.equal(S.signedIntensity(0.55, -0.2, 1.1), 0.5);
assert.equal(S.signedIntensity(null, 0, 1), 0);

// ---- CSV des opérations (séparateur ;, guillemets échappés)
const csv = S.tradesCsv([{ symbol: "A;B", side: 1, entry: "2020-01-02", entry_price: 10, exit: null, exit_price: 11, days: 3, return: 0.1, pnl: 100, costs: 1, reason: "fin \"de\" période" }]);
assert.equal(csv.split("\r\n")[1], "\"A;B\";1;2020-01-02;10;;11;3;0.1;100;1;\"fin \"\"de\"\" période\"");

// ---- symboles saisis
assert.deepEqual(S.parseSymbols("spy, ^fchi ; btc-usd spy bad$"), ["SPY", "^FCHI", "BTC-USD"]);

// ---- description envoyée au serveur : grille sans paramètre 2 identique, poids seulement pour l'allocation fixe
const form = { name: "x", symbols: ["SPY"], benchmark: "", start: "2010-01-01", end: "2020-01-01", oos: "", capital: 1000, template: "sma_cross", params: { fast: 20 },
               weights: { SPY: 100 }, events: null, rules: null, sizing: { method: "", n: 60 }, decision: "", rebalance: "monthly", costs: {}, execution: { lag: 1, at: "close" },
               risk: {}, allow_yahoo: true, robustness: { random: true, bootstrap: false, grid: { x: { param: "fast", min: 10, max: 50, steps: 5 }, y: { param: "fast" } } } };
const spec = S.specOf(form);
assert.equal(spec.oos_start, null);
assert.deepEqual(spec.robustness.grid, { x: { param: "fast", min: 10, max: 50, steps: 5 } });
assert.equal(spec.weights, undefined);
assert.deepEqual(spec.sizing, { n: 60 });
assert.equal(spec.rebalance, "monthly");
assert.equal(spec.decision, undefined);

// ---- tons et courbes rebasées
assert.equal(S.verdictTone("robust"), "ok");
assert.equal(S.verdictTone("none"), "error");
assert.equal(S.checkTone(null), "disabled");
assert.deepEqual(S.rebase([null, 50, 75, null]), [null, 100, 150, null]);

console.log("strategies.test.js : ok");
