// Tests des fonctions pures de la page « Écrans côte à côte » (static/split.js) : géométrie des dispositions, bornes des séparateurs,
// état <-> fragment d'adresse, filtrage des adresses. Lancé par tests/webapp/test_split_page.py ; sans DOM.
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const S = require(path.join(__dirname, "..", "..", "patrick", "webapp", "static", "split.js"));

const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);

// ---- chaque disposition : le bon nombre de volets, qui couvrent exactement la scène sans se recouvrir
Object.keys(S.LAYOUTS).forEach((layout) => {
    const g = S.geometry(layout, {});
    assert.equal(g.panes.length, S.LAYOUTS[layout].n, layout);
    const area = g.panes.reduce((s, p) => s + p.w * p.h, 0);
    near(area, 1);
    g.panes.forEach((p) => {
        assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.w <= 1 + 1e-9 && p.y + p.h <= 1 + 1e-9, `${layout} dépasse la scène`);
        assert.ok(p.w >= S.MIN - 1e-9 && p.h >= S.MIN - 1e-9, `${layout} volet trop étroit`);
    });
    // aucun recouvrement : l'aire d'intersection de chaque paire est nulle
    for (let i = 0; i < g.panes.length; i++) {
        for (let j = i + 1; j < g.panes.length; j++) {
            const a = g.panes[i], b = g.panes[j];
            const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
            const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
            assert.ok(!(w > 1e-9 && h > 1e-9), `${layout} : volets ${i} et ${j} se recouvrent`);
        }
    }
});

// ---- séparateurs : ils suivent les réglages
let g = S.geometry("c2", { x: 0.3 });
near(g.panes[0].w, 0.3);
near(g.panes[1].x, 0.3);
assert.deepEqual(g.gutters, [{ key: "x", axis: "x", pos: 0.3, from: 0, to: 1 }]);
g = S.geometry("l12", { x: 0.7, y: 0.4 });
near(g.panes[1].h, 0.4);
near(g.panes[2].y, 0.4);
assert.equal(g.gutters.length, 2);
assert.deepEqual(g.gutters.find((s) => s.key === "y"), { key: "y", axis: "y", pos: 0.4, from: 0.7, to: 1 });   // le trait horizontal ne traverse que la colonne de droite
assert.equal(S.geometry("s1", {}).gutters.length, 0);

// ---- bornes : jamais de volet plus étroit que le minimum, x2 reste à droite de x
near(S.clampRatio("c2", "x", 0.01, {}), S.MIN);
near(S.clampRatio("c2", "x", 0.99, {}), 1 - S.MIN);
near(S.clampRatio("c3", "x", 0.9, { x: 0.3, x2: 0.7 }), 0.7 - S.MIN);
near(S.clampRatio("c3", "x2", 0.1, { x: 0.3, x2: 0.7 }), 0.3 + S.MIN);

// ---- état <-> fragment d'adresse
let st = S.normalize({ layout: "g4", ratios: { x: 0.4, y: 0.55 }, panes: ["/predictions?view=horizon", "/targets/%5EGSPC", "", "/universe"] });
let text = S.encodeState(st);
let back = S.decodeState("#" + text);
assert.equal(back.layout, "g4");
near(back.ratios.x, 0.4);
near(back.ratios.y, 0.55);
assert.deepEqual(back.panes, ["/predictions?view=horizon", "/targets/%5EGSPC", "", "/universe"]);

// les volets vides en fin de liste ne laissent pas de virgules dans le lien ; un volet vide au milieu garde sa place
assert.ok(!/,$/.test(S.encodeState(S.normalize({ layout: "c2", ratios: {}, panes: ["/runs", "", "", ""] }))));
assert.deepEqual(S.decodeState("#" + S.encodeState(S.normalize({ layout: "c3", ratios: {}, panes: ["", "/runs", "/universe", ""] }))).panes.slice(0, 3), ["", "/runs", "/universe"]);

// une valeur hors bornes ou absente retombe sur une valeur valide
back = S.decodeState("#l=c3&x=0.9&x2=0.2&p=");
assert.ok(back.ratios.x < back.ratios.x2);
assert.equal(S.decodeState("#l=inconnue&p=/x"), null);
assert.equal(S.decodeState(""), null);
assert.equal(S.decodeState("#l=c2").panes.length, S.MAX_PANES);

// ---- adresses : uniquement des pages de l'application
assert.equal(S.sanitizeUrl("/predictions?view=horizon"), "/predictions?view=horizon");
assert.equal(S.sanitizeUrl("/targets/AAPL"), "/targets/AAPL");
["https://evil.example/", "//evil.example/x", "/\\evil.example", "javascript:alert(1)", "/split", "/split#l=c2", "/api/asset-index", "/static/x.js",
 "/fragments/predictions", "predictions", "", null, 12].forEach((bad) => assert.equal(S.sanitizeUrl(bad), "", String(bad)));
// une adresse dangereuse glissée dans le lien de partage est neutralisée au décodage
back = S.decodeState("#l=c2&p=" + encodeURIComponent("https://evil.example/") + "," + encodeURIComponent("/runs"));
assert.deepEqual(back.panes.slice(0, 2), ["", "/runs"]);

// ---- titre : le préfixe de l'application est retiré
assert.equal(S.titleOf("PATRICK — Prédictions"), "Prédictions");
assert.equal(S.titleOf("PATRICK - Univers"), "Univers");
assert.equal(S.titleOf(""), "");

console.log("split.test.js : ok");
