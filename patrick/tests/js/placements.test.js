// Tests des fonctions pures de la page Placements (static/placements.js) : choix de la meilleure allocation, CSV, couleurs de corrélation.
// Lancé par tests/webapp/test_placements_page.py ; sans DOM.
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

// ---- page générale : nuage risque / rendement (SVG échappé), saisie des taux
{
    const svg = P.scatterSvg({ funds: [{ label: "A<script>", vol: 0.1, ret: 0.05 }], line: [{ vol: 0.02, ret: 0.01 }, { vol: 0.1, ret: 0.06 }],
                               marks: [{ label: "retenue", vol: 0.05, ret: 0.03, kind: "chosen" }] }, 400, 300);
    assert.ok(svg.startsWith("<svg") && svg.endsWith("</svg>"));
    assert.ok(svg.includes("A&lt;script&gt;") && !svg.includes("<script>"));
    assert.ok(svg.includes("pl-sc-chosen") && svg.includes("<polyline"));
    assert.equal(P.scatterSvg({ funds: [], line: [], marks: [] }, 400, 300), "");
    assert.equal(P.esc("a\"b&"), "a&quot;b&amp;");
    assert.equal(P.countRateLines("2023 2,6\n2024;2.7 %\nnotes\n24 1"), 2);
}

// ---- 2026-11-23 : classement de toutes les ventilations, statistiques des rendements mensuels, SVG
const rk = [
    { id: "m1", window: "w1", cap: null, objective: "mv_prudent", metrics: { vol: 0.03, cagr: 0.03, sharpe: 0.9, div_ratio: 1.4, max_dd_daily: -0.04 }, walk_forward: { sharpe: 0.8, peu_fiable: false } },
    { id: "m2", window: "w1", cap: null, objective: "mv_dynamic", metrics: { vol: 0.12, cagr: 0.08, sharpe: 0.6, div_ratio: 1.1, max_dd_daily: -0.2 }, walk_forward: { sharpe: 1.5, peu_fiable: true } },
    { id: "m3", window: "w1", cap: 0.4, objective: "mv_dynamic", metrics: { vol: 0.10, cagr: 0.07, sharpe: 0.7, div_ratio: 1.3, max_dd_daily: -0.15 }, walk_forward: { sharpe: 0.5, peu_fiable: false } },
];
assert.deepEqual(P.rankBy(rk, "w1", 1, "cagr").map((p) => p.id), ["m2", "m1"]);          // plafond « aucun » seulement
assert.deepEqual(P.rankBy(rk, "w1", 1, "wf_sharpe").map((p) => p.id), ["m1", "m2"]);     // walk-forward peu fiable relégué
assert.deepEqual(P.rankBy(rk, "w1", 1, "mdd").map((p) => p.id), ["m1", "m2"]);           // la baisse la moins profonde d'abord
assert.deepEqual(P.rankBy(rk, "w1", 0.4, "div_ratio").map((p) => p.id), ["m3"]);

assert.deepEqual(P.returnsFromGrowth([100, 110, 99]).map((x) => +x.toFixed(4)), [0.1, -0.1]);
assert.equal(P.quantile([1, 2, 3, 4], 0.5), 2.5);
assert.equal(P.quantile([1, 2, 3, 4], 0), 1);
const sym = P.moments([-2, -1, 0, 1, 2]);
assert.equal(sym.mean, 0);
assert.ok(Math.abs(sym.skew) < 1e-12);
assert.ok(Math.abs(sym.sd - Math.sqrt(2.5)) < 1e-12);
assert.ok(sym.jb_p > 0 && sym.jb_p <= 1);
assert.ok(Math.abs(P.normInv(0.975) - 1.959964) < 1e-5);
assert.ok(Math.abs(P.normInv(0.05) + 1.644854) < 1e-5);
assert.equal(P.normInv(0.5), 0);
assert.ok(Math.abs(P.normPdf(0, 0, 1) - 0.398942) < 1e-6);

const hist = P.histogram([0, 0.1, 0.2, 0.3, 0.4], 4);
assert.equal(hist.counts.length, 4);
assert.equal(hist.counts.reduce((a, b) => a + b, 0), 5);
assert.equal(hist.edges.length, 5);

const cal = P.monthlyTable(["2023-11-30", "2023-12-31", "2024-01-31", "2024-02-29"], [0.01, 0.02, -0.01]);
assert.deepEqual(cal.map((r) => r.year), [2023, 2024]);
assert.equal(cal[0].months[11], 0.01);
assert.equal(cal[1].months[0], 0.02);
assert.ok(cal[1].partial && Math.abs(cal[1].total - (1.02 * 0.99 - 1)) < 1e-12);

const roll = P.rolling([0.01, 0.01, 0.01, 0.01], 3);
assert.equal(roll.ret[1], null);
assert.ok(Math.abs(roll.ret[2] - (Math.pow(1.01, 12) - 1)) < 1e-12);
assert.ok(Math.abs(roll.vol[3]) < 1e-12);

const svg = P.distSvg({ edges: hist.edges, counts: hist.counts, mean: 0.2, sd: 0.15, quantiles: [{ q: 0.5, v: 0.2 }, { q: 0.05, v: 0.02 }], marks: [{ v: 0.1, label: "<b>", kind: "goal" }] });
assert.ok(svg.startsWith("<svg") && svg.includes("pl-dist-normal") && svg.includes("is-median") && svg.includes(">P5<"));
assert.ok(!svg.includes("<b>") && svg.includes("&lt;b&gt;"));                                  // libellés échappés
assert.ok(P.qqSvg([0.01, -0.02, 0.03, 0.0, 0.015, -0.01]).includes("pl-qq-ref"));
assert.equal(P.qqSvg([0.01]), "");
assert.ok(P.barsSvg([{ label: "2024", a: 0.05, b: 0.03 }, { label: "2025", a: -0.02, b: 0.01 }], 400, 200, 0.015).includes("pl-bars-mean"));
console.log("placements.test.js : nouveaux cas OK");
