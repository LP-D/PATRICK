// Tests des fonctions pures du moteur de graphiques (static/chart_kit.js) : échelles, graduations, décimation, bornes de zoom.
// Lancé par tests/test_chart_kit_js.py (`node tests/js/chart_kit.test.js`) ; sans DOM : seul `create` en a besoin.
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const kit = require(path.join(__dirname, "..", "..", "patrick", "webapp", "static", "chart_kit.js"));
const K = kit._internals;
const DAY = 86400000;

// ---- recherche dichotomique
assert.equal(K.lowerBound([1, 3, 5, 7], 5), 2);
assert.equal(K.lowerBound([1, 3, 5, 7], 4), 2);
assert.equal(K.lowerBound([1, 3, 5, 7], 0), 0);
assert.equal(K.lowerBound([1, 3, 5, 7], 99), 4);
assert.equal(K.nearestIndex([1, 3, 5, 7], 3.9), 1);
assert.equal(K.nearestIndex([1, 3, 5, 7], 4.1), 2);
assert.equal(K.nearestIndex([1, 3, 5, 7], -10), 0);
assert.equal(K.nearestIndex([1, 3, 5, 7], 10), 3);

// ---- graduations « rondes » et décimales cohérentes
let t = K.niceTicks(0, 9, 5);
assert.deepEqual(Array.from(t), [0, 2, 4, 6, 8]);
assert.equal(t.step, 2);
t = K.niceTicks(-0.3, 0.3, 4);
assert.ok(t.includes(0) && t.every((v) => v >= -0.3 - 1e-9 && v <= 0.3 + 1e-9));
assert.ok(t.length >= 3 && t.length <= 6);
t = K.niceTicks(1, 1, 5);                       // plage nulle : jamais de division par zéro
assert.ok(t.length >= 2);
t = K.niceTicks(98.43, 103.61, 5);
assert.ok(t.length >= 3 && t.every((v) => Number.isFinite(v)));
assert.equal(K.decimalsFor(1), 0);
assert.equal(K.decimalsFor(50), 0);
assert.equal(K.decimalsFor(0.5), 1);
assert.equal(K.decimalsFor(0.02), 2);
assert.equal(K.decimalsFor(0.005), 3);

// ---- dates
assert.equal(kit.parseDate("2024-03-15"), Date.UTC(2024, 2, 15));
assert.equal(kit.parseDate("2024-03"), Date.UTC(2024, 2, 1));
assert.ok(Number.isFinite(kit.parseDate("2024-03-15T10:30:00")));
assert.ok(Number.isNaN(kit.parseDate("pas une date")));
assert.ok(Number.isNaN(kit.parseDate(null)));

// ---- graduations du temps : alignées sur le calendrier, bornées en nombre, plus fines quand on zoome
const y5 = K.timeTicks(Date.UTC(2020, 0, 1), Date.UTC(2025, 0, 1), 8);
assert.equal(y5.unit, "y");
assert.ok(y5.ticks.length <= 8 && y5.ticks.every((x) => new Date(x).getUTCMonth() === 0 && new Date(x).getUTCDate() === 1));
const m6 = K.timeTicks(Date.UTC(2024, 0, 10), Date.UTC(2024, 6, 20), 8);
assert.equal(m6.unit, "m");
assert.ok(m6.ticks.every((x) => new Date(x).getUTCDate() === 1));
const w2 = K.timeTicks(Date.UTC(2024, 4, 1), Date.UTC(2024, 4, 20), 8);
assert.equal(w2.unit, "d");
assert.ok(w2.ticks.length >= 2 && w2.ticks.length <= 8);
const mon = K.timeTicks(Date.UTC(2024, 4, 1), Date.UTC(2024, 5, 30), 6);         // pas de 7 jours : lundis
if (mon.unit === "d" && mon.n === 7) assert.ok(mon.ticks.every((x) => new Date(x).getUTCDay() === 1));
assert.ok(K.timeTicks(0, 3 * DAY, 2).ticks.length >= 1);

// ---- décimation : le tracé reste borné et garde les extrêmes de chaque colonne
const N = 20000, xs = [], ys = [];
for (let i = 0; i < N; i++) { xs.push(i); ys.push(Math.sin(i / 300) * 10 + (i === 12345 ? 500 : 0) + (i === 777 ? -400 : 0)); }
const W = 200, X = (x) => x / N * W;
const idx = K.decimate(xs, ys, 0, N - 1, X, W);
assert.ok(idx.length <= W * 4 + 8, `trop de points : ${idx.length}`);
assert.ok(idx.includes(12345) && idx.includes(777), "les pics doivent survivre à la décimation");
assert.deepEqual(idx, idx.slice().sort((a, b) => a - b), "ordre croissant conservé");
const few = K.decimate([0, 1, 2], [1, 2, 3], 0, 2, (x) => x * 50, 300);
assert.deepEqual(few, [0, 1, 2]);
const withGap = K.decimate(xs, ys.map((v, i) => (i === 5000 ? null : v)), 0, N - 1, X, W);
assert.ok(withGap.includes(5000), "un trou doit rester visible pour couper le trait");

// ---- bornes verticales : seuls les points visibles comptent ; un repère lointain ne gêne pas le recalcul
const series = [{ xs: [0, 1, 2, 3, 4, 5], ys: [10, 11, 12, 100, 101, 102], hidden: false }];
assert.deepEqual(K.yExtent(series, 0, 2, [], []), [10, 12]);
assert.deepEqual(K.yExtent(series, 3, 5, [], []), [100, 102]);
assert.deepEqual(K.yExtent(series, 0, 2, [500], []), [10, 12], "repère lointain ignoré");
assert.deepEqual(K.yExtent(series, 0, 2, [12.5], []), [10, 12.5], "repère proche pris en compte");
assert.deepEqual(K.yExtent(series, 0, 2, [], [0]), [0, 12], "plancher imposé toujours inclus");
assert.equal(K.yExtent(series, 10, 20, [], []), null, "aucun point visible");
series[0].hidden = true;
assert.equal(K.yExtent(series, 0, 5, [], []), null, "série masquée ignorée");
const withNulls = [{ xs: [0, 1, 2], ys: [null, 4, NaN], hidden: false }];
assert.deepEqual(K.yExtent(withNulls, 0, 2, [], []), [4, 4]);

// ---- rendu « cotation » : couleurs, variation de la fenêtre, bougies, YTD
assert.equal(K.withAlpha("#5B8DEF", 0.3), "rgba(91,141,239,0.3)");
assert.equal(K.withAlpha("#fff", 0.5), "rgba(255,255,255,0.5)");
assert.equal(K.withAlpha("rgb(10, 20, 30)", 0.2), "rgba(10,20,30,0.2)");
assert.equal(K.withAlpha("rgba(10,20,30,0.9)", 0.2), "rgba(10,20,30,0.2)");
assert.equal(K.withAlpha("red", 0.5), "red", "forme inconnue rendue telle quelle");

const wx = [0, 1, 2, 3, 4, 5], wy = [null, 10, 12, NaN, 15, null];
let wc = K.windowChange(wx, wy, 0, 5);
assert.deepEqual([wc.i0, wc.i1, wc.first, wc.last, wc.abs], [1, 4, 10, 15, 5], "trous ignorés aux deux bouts");
assert.equal(Math.round(wc.pct), 50);
wc = K.windowChange(wx, wy, 2, 5);
assert.deepEqual([wc.first, wc.last], [12, 15], "seule la fenêtre compte");
assert.equal(K.windowChange(wx, wy, 20, 30), null, "aucun point visible");
assert.equal(K.windowChange([0, 1], [0, 5], 0, 1).pct, null, "départ nul : pas de pourcentage");
assert.ok(K.windowChange([0, 1], [10, 8], 0, 1).abs < 0, "baisse : variation négative");

assert.deepEqual(K.candleExtent([0, 1, 2, 3], [5, 9, 7, 12], [4, 3, 6, 2], 0, 2), [3, 9], "bornes des bougies visibles");
assert.deepEqual(K.candleExtent([0, 1, 2], [null, 9, NaN], [null, 3, NaN], 0, 2), [3, 9], "cases vides ignorées");
assert.equal(K.candleExtent([0, 1], [5, 6], [4, 3], 10, 20), null);

assert.equal(K.yearStart(Date.UTC(2026, 9, 22)), Date.UTC(2026, 0, 1));
assert.equal(K.yearStart(Date.UTC(2024, 0, 1)), Date.UTC(2024, 0, 1));

console.log("chart_kit : tous les tests passent");
