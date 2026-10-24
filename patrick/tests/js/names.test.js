// Tests de static/names.js (noms d'affichage des instruments côté navigateur). Lancé par tests/test_instrument_names.py ;
// sans DOM : un faux `document` ne sait servir que le bloc JSON `instrument-names`.
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");

const NAMES = {
    AAPL: "Apple",
    "^GSPC": "Indice · S&P 500",
    "GC=F": "Future · Or",
    "BTC-USD": "Crypto · Bitcoin",
    DGS10: "Macro · Rendement du Trésor US 10 ans",
};
let present = false;                                    // le bloc JSON n'est dans la page qu'à partir d'un certain moment
globalThis.document = { getElementById: (id) => (id === "instrument-names" && present ? { textContent: JSON.stringify(NAMES) } : null) };
globalThis.I18N = { inst_kind_future: "Future", inst_kind_index: "Indice", inst_kind_fx: "Devise", inst_kind_crypto: "Crypto", inst_alpha_vs: "α vs {bench}" };
require(path.join(__dirname, "..", "..", "patrick", "webapp", "static", "names.js"));
const P = globalThis.PatrickNames;

// Un appel pendant le chargement de l'en-tête (avant le bloc) ne fige pas un cache vide : c'était la cause de symboles bruts dans les récapitulatifs.
assert.equal(P.label("AAPL"), "AAPL");
assert.equal(P.known("AAPL"), false);
present = true;
assert.equal(P.label("AAPL"), "Apple");
assert.equal(P.known("AAPL"), true);

// Société : le nom seul ; autres genres : « Genre · nom » déjà composé par le serveur.
assert.equal(P.label("^GSPC"), "Indice · S&P 500");
assert.equal(P.label("GC=F"), "Future · Or");

// Nom seul, sans genre.
assert.equal(P.name("^GSPC"), "S&P 500");
assert.equal(P.name("AAPL"), "Apple");
assert.equal(P.name("DGS10"), "Rendement du Trésor US 10 ans");

// Cible d'alpha : « nom · α vs référence ».
assert.equal(P.label("AAPL__alpha_^GSPC"), "Apple · α vs S&P 500");

// Symbole absent du registre : genre déduit de la forme, sinon le symbole tel quel.
assert.equal(P.label("FOO=F"), "Future · FOO=F");
assert.equal(P.label("EURGBP=X"), "Devise · EUR/GBP");
assert.equal(P.label("ZZZ-USD"), "Crypto · ZZZ");
assert.equal(P.label("^ZZZ"), "Indice · ^ZZZ");
assert.equal(P.label("ZZZ.UNKNOWN"), "ZZZ.UNKNOWN");
assert.equal(P.label(""), "");
assert.equal(P.label(null), "");

// Infobulle : le symbole, sauf si l'affichage EST le symbole.
assert.equal(P.tip("AAPL"), "AAPL");
assert.equal(P.tip("ZZZ.UNKNOWN"), "");

console.log("names.test.js ok");
