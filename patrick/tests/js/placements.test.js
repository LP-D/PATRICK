// Tests des fonctions pures de la page Placements (static/placements.js) : choix de la meilleure allocation, CSV, couleurs de corrélation.
// Lancé par tests/test_placements_page.py ; sans DOM.
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const P = require(path.join(__dirname, "..", "..", "patrick", "webapp", "static", "placements.js"));

const pf = (id, window, vol, cagr, sharpe, wf) => ({ id, window, metrics: { vol, cagr, sharpe }, walk_forward: { sharpe: wf } });
const list = [
    pf("a", "w1", 0.02, 0.025, 0.9, 1.4),      // quasi monétaire : meilleur Sharpe hors échantillon, rendement faible
    pf("b", "w1", 0.06, 0.054, 0.8, 0.67),
    pf("c", "w1", 0.15, 0.11, 0.7, 0.5),
    pf("d", "w1", 0.08, 0.06, 1.1, null),      // pas de walk-forward : jamais retenu sur ce critère
    pf("e", "w2", 0.10, 0.07, 0.6, 0.9),
];

// ---- critère par critère, dans une fenêtre
assert.equal(P.pickBest(list, "w1", "wf_sharpe", null).id, "a");
assert.equal(P.pickBest(list, "w1", "sharpe", null).id, "d");
assert.equal(P.pickBest(list, "w1", "cagr", null).id, "c");
assert.equal(P.pickBest(list, "w1", "vol", null).id, "a");
assert.equal(P.pickBest(list, "w2", "cagr", null).id, "e");

// ---- la limite de volatilité écarte les portefeuilles trop risqués
assert.equal(P.pickBest(list, "w1", "cagr", 0.10).id, "d");        // c (15 %) écarté
assert.equal(P.pickBest(list, "w1", "cagr", 0.06).id, "b");        // la limite est incluse
assert.equal(P.pickBest(list, "w1", "cagr", 0.01), null);          // aucun ne passe
assert.equal(P.pickBest(list, "inconnue", "cagr", null), null);

// ---- sans walk-forward, un portefeuille n'est retenu sur ce critère que s'il est seul
assert.equal(P.pickBest([pf("x", "w", 0.1, 0.1, 1, null)], "w", "wf_sharpe", null).id, "x");
assert.equal(P.pickBest([pf("x", "w", 0.1, 0.1, 1, null), pf("y", "w", 0.1, 0.1, 1, 0.1)], "w", "wf_sharpe", null).id, "y");

// ---- un walk-forward peu fiable (< 36 mois) ne l'emporte pas sur un test fiable, mais reste utilisable s'il est seul
const weak = (id, wf) => ({ id, window: "w", metrics: { vol: 0.1, cagr: 0.1, sharpe: 1 }, walk_forward: { sharpe: wf, peu_fiable: true } });
const solid = (id, wf) => ({ id, window: "w", metrics: { vol: 0.1, cagr: 0.1, sharpe: 1 }, walk_forward: { sharpe: wf, peu_fiable: false } });
assert.equal(P.pickBest([weak("w1", 5), solid("s1", 0.6), solid("s2", 0.4)], "w", "wf_sharpe", null).id, "s1");
assert.equal(P.pickBest([weak("w1", 5), weak("w2", 3)], "w", "wf_sharpe", null).id, "w1");
assert.equal(P.pickBest([weak("w1", 5), solid("s1", 0.6)], "w", "sharpe", null).id, "w1");      // les autres critères ne sont pas concernés

assert.equal(P.maxVolOf(list, "w1"), 0.15);
assert.equal(P.maxVolOf(list, "w2"), 0.10);

// ---- CSV : séparateur « ; », guillemets doublés, cellules vides
assert.equal(P.toCsv([["a", "b"], [1, null], ["x;y", "dit \"oui\""]]), "a;b\r\n1;\r\n\"x;y\";\"dit \"\"oui\"\"\"");

// ---- intensité de corrélation : bornée à [0, 1], insensible au signe
assert.equal(P.corrIntensity(0.4), 0.4);
assert.equal(P.corrIntensity(-0.4), 0.4);
assert.equal(P.corrIntensity(1.2), 1);
assert.equal(P.corrIntensity(null), 0);
assert.equal(P.corrIntensity(NaN), 0);

console.log("placements.test.js : ok");
