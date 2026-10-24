/* Noms d'affichage des instruments côté navigateur : `window.PatrickNames`.
   Le symbole (`^GSPC`, `AAPL`, `GC=F`) reste l'identifiant ; la page montre le nom (cf. webapp/instruments.py, qui fournit les données
   dans `<script id="instrument-names">` et dont ce fichier reprend la règle).
     label(symbole)  -> « Apple », « Future · Or », « Indice · S&P 500 », « Apple · α vs S&P 500 » ; le symbole lui-même s'il est inconnu
     name(symbole)   -> le nom seul, sans genre
     tip(symbole)    -> le symbole, pour un attribut `title` (vide si le nom EST le symbole)
   Les données sont lues au premier appel qui trouve le bloc (le script est chargé dans l'en-tête, avant le corps de la page). */
(function (root) {
    "use strict";
    var ALPHA = "__alpha_";
    var cache = null;

    function data() {
        if (cache) return cache;
        var el = root.document && root.document.getElementById("instrument-names");
        // tant que le bloc n'est pas dans la page (appel pendant le chargement de l'en-tête), on ne mémorise rien
        if (!el) return {};
        try { cache = JSON.parse(el.textContent || "{}") || {}; } catch (e) { cache = {}; }
        return cache;
    }
    function tr(key, fallback) { return (root.I18N && root.I18N[key]) || fallback; }

    // Genre et nom déduits de la forme d'un symbole absent du registre (même règle que le serveur).
    function guess(symbol) {
        if (/=F$/.test(symbol)) return { kind: "future", name: symbol };
        var fx = /^([A-Z]{3})([A-Z]{3})=X$/.exec(symbol);
        if (fx) return { kind: "fx", name: fx[1] + "/" + fx[2] };
        var usd = /^([A-Z]{3})=X$/.exec(symbol);
        if (usd) return { kind: "fx", name: "USD/" + usd[1] };
        var crypto = /^([A-Za-z0-9]+)-USD$/.exec(symbol);
        if (crypto) return { kind: "crypto", name: crypto[1] };
        if (symbol.charAt(0) === "^") return { kind: "index", name: symbol };
        return null;
    }
    var KINDS = { future: "Future", cfd: "CFD", index: "Index", vol: "Volatility", fx: "FX", crypto: "Crypto", rate: "Rate", macro: "Macro" };

    function nameOf(symbol) {
        if (!symbol) return "";
        symbol = String(symbol);
        var i = symbol.indexOf(ALPHA);
        if (i >= 0) symbol = symbol.slice(0, i);
        var shown = data()[symbol];
        if (shown === undefined) { var g = guess(symbol); return g ? g.name : symbol; }
        // le registre donne l'affichage complet (« Future · Or ») : le nom seul est ce qui suit le premier « · »
        var cut = shown.indexOf(" · ");
        return cut >= 0 ? shown.slice(cut + 3) : shown;
    }
    function label(symbol) {
        if (!symbol) return "";
        symbol = String(symbol);
        var i = symbol.indexOf(ALPHA);
        if (i >= 0) {
            var bench = symbol.slice(i + ALPHA.length);
            return label(symbol.slice(0, i)) + " · " + tr("inst_alpha_vs", "α vs {bench}").replace("{bench}", nameOf(bench));
        }
        var shown = data()[symbol];
        if (shown !== undefined) return shown;
        var g = guess(symbol);
        return g ? tr("inst_kind_" + g.kind, KINDS[g.kind]) + " · " + g.name : symbol;
    }
    function tip(symbol) {
        var shown = label(symbol);
        return !symbol || shown === symbol ? "" : String(symbol);
    }

    root.PatrickNames = { label: label, name: nameOf, tip: tip, known: function (symbol) { return data()[symbol] !== undefined; } };
})(typeof window !== "undefined" ? window : globalThis);
