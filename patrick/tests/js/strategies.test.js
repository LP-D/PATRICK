// Tests des fonctions pures de la page Stratégies (static/strategies.js) : jours de sortie affichés, matrice de sensibilité, état du verdict.
// Lancé par tests/test_strategies_page.py ; sans DOM.
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const S = require(path.join(__dirname, "..", "..", "patrick", "webapp", "static", "strategies.js"));

// ---- jours de sortie montrés : des repères, le jour maximal et le meilleur jour, jamais au-delà du maximum, sans doublon, triés
assert.deepEqual(S.keyDays(20, 3), [1, 2, 3, 5, 10, 15, 20]);
assert.deepEqual(S.keyDays(20, 7), [1, 2, 3, 5, 7, 10, 15, 20]);
assert.deepEqual(S.keyDays(8, 4), [1, 2, 3, 4, 5, 8]);
assert.deepEqual(S.keyDays(1, 1), [1]);
assert.deepEqual(S.keyDays(60, 60), [1, 2, 3, 5, 10, 15, 20, 30, 45, 60]);

// ---- matrice de sensibilité : lignes = maturités, colonnes = ratios de sortie, croissants
const cells = [
    { maturity: 14, exit_ratio: 0.95, mean: 0.02, win: 0.5, n: 30 }, { maturity: 7, exit_ratio: 0.5, mean: -0.12, win: 0.2, n: 30 },
    { maturity: 7, exit_ratio: 0.95, mean: 0.01, win: 0.5, n: 30 }, { maturity: 14, exit_ratio: 0.5, mean: -0.08, win: 0.3, n: 30 },
];
const pv = S.pivot(cells);
assert.deepEqual(pv.maturities, [7, 14]);
assert.deepEqual(pv.ratios, [0.5, 0.95]);
assert.equal(pv.rows[7][0.5].mean, -0.12);
assert.equal(pv.rows[14][0.95].mean, 0.02);

// ---- intensité : proportionnelle à |moyenne| / plus grand |moyenne|, bornée à 1
assert.equal(S.maxAbs(cells), 0.12);
assert.equal(S.heat(-0.12, 0.12), 1);
assert.equal(S.heat(0.06, 0.12), 0.5);
assert.equal(S.heat(0.5, 0.12), 1);
assert.equal(S.heat(null, 0.12), 0);
assert.equal(S.heat(0.05, 0), 0);
assert.equal(S.maxAbs([]), 0);

// ---- état du verdict (couleur du badge)
assert.equal(S.verdictState("robust"), "ok");
assert.equal(S.verdictState("fragile"), "warning");
assert.equal(S.verdictState("none"), "error");

// ---- les drapeaux sont lus dans un ordre fixe (celui des tests statistiques)
assert.deepEqual(S.FLAG_ORDER, ["enough_events", "ci_above_zero", "oos_holds", "not_concentrated", "stable_best_day"]);

console.log("strategies.test.js : ok");
