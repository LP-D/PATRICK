/* Briques communes des pages à graphiques (Exploration, Reinforcement learning) : formats de nombres, construction DOM / SVG sans
   dépendance, courbes et barres. Les couleurs viennent des variables CSS (thème clair/sombre sans redessin). Exposé : `window.PatrickCharts`. */
(function () {
    "use strict";

    var I18N = window.I18N || {};
    var LANG = document.documentElement.lang || "fr";
    var NS = "http://www.w3.org/2000/svg";

    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(text, params) { return text.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; }); }

    // ------------------------------------------------------------------ formats
    function num(v, d) {
        if (v === null || v === undefined || !isFinite(v)) return "—";
        d = d === undefined ? 2 : d;
        return v.toLocaleString(LANG, { minimumFractionDigits: d, maximumFractionDigits: d });
    }
    function pct(v, d) { return v === null || v === undefined ? "—" : num(v * 100, d === undefined ? 1 : d) + " %"; }
    function pval(p) { return p === null || p === undefined ? "—" : (p < 0.001 ? "<" + num(0.001, 3) : num(p, 3)); }

    // ------------------------------------------------------------------ DOM
    function h(tag, attrs, children) {
        var el = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === "class") el.className = attrs[k];
            else if (k === "text") el.textContent = attrs[k];
            else el.setAttribute(k, attrs[k]);
        });
        [].concat(children || []).forEach(function (c) {
            if (c === null || c === undefined) return;
            el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
        });
        return el;
    }
    function s(tag, attrs, children) {
        var el = document.createElementNS(NS, tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === "text") el.textContent = attrs[k];
            else if (k === "fill" || k === "stroke") el.style[k] = attrs[k];
            else el.setAttribute(k, attrs[k]);
        });
        [].concat(children || []).forEach(function (c) { if (c) el.appendChild(c); });
        return el;
    }
    function chip(text, kind) { return h("span", { class: "exp-chip exp-chip-" + (kind || "neutral"), text: text }); }
    function note(text) { return h("p", { class: "hint", text: text }); }
    function table(headers, rows, cls) {
        var head = h("tr", {}, headers.map(function (t) {
            if (t && t.term) {          // en-tête avec définition du glossaire (bouton « ? » ouvert par glossary.js)
                return h("th", { scope: "col" }, [t.text, h("button", { type: "button", class: "info-icon", "data-term": t.term, "data-term-label": t.text,
                    "aria-label": fmtStr(tr("glossary_open_aria", "Définition : {term}"), { term: t.text }) })]);
            }
            return h("th", { scope: "col", text: t });
        }));
        var body = rows.map(function (r) {
            return h("tr", {}, r.map(function (c) {
                var cell = c && c.cell !== undefined ? c : { cell: c };
                var td = h("td", { class: (cell.cls || "") }, [typeof cell.cell === "string" || typeof cell.cell === "number" ? String(cell.cell) : cell.cell]);
                return td;
            }));
        });
        return h("div", { class: "table-scroll" }, [h("table", { class: "data-table " + (cls || "") }, [h("thead", {}, [head]), h("tbody", {}, body)])]);
    }
    function numCell(text, v) { return { cell: text, cls: "num pk-mono" + (v < 0 ? " neg" : (v > 0 ? " pos" : "")) }; }

    // ------------------------------------------------------------------ graphiques
    // Courbes et barres : enveloppes minces du moteur commun `PatrickPlot` (chart_kit.js) — zoom, déplacement, échelle recalculée sur la
    // fenêtre visible, infobulle et légende y vivent. Les appelants gardent la même signature (dates, series, hlines, band, yMin/yMax…).
    function niceTicks(lo, hi, n) { return window.PatrickPlot._internals.niceTicks(lo, hi, n); }

    function lineChart(o) {
        var P = window.PatrickPlot, host = h("div", { class: "exp-chart-wrap" });
        var xs = o.dates.map(P.parseDate), timed = xs.every(function (x) { return isFinite(x); });
        if (!timed) xs = o.dates.map(function (_, i) { return i; });
        P.create(host, {
            type: "line", xKind: timed ? "time" : "index", xs: xs, xLabel: function (i) { return o.dates[i]; },
            series: o.series, hlines: o.hlines, band: o.band, yMin: o.yMin, yMax: o.yMax, yFmt: o.yFmt,
            title: o.title || "", height: o.height || 240, ranges: timed, markers: false,
        });
        return host;
    }

    function barChart(o) {
        var P = window.PatrickPlot, host = h("div", { class: "exp-chart-wrap" });
        P.create(host, {
            type: "bar", values: o.values, labels: o.labels, xLabel: function (i) { return o.labels ? o.labels[i] : String(i); },
            band: o.band, yMin: o.yMin, yMax: o.yMax, yFmt: o.yFmt, color: o.color, strong: o.strong, title: o.title || "", height: o.height || 200,
        });
        return host;
    }


    window.PatrickCharts = {
        tr: tr, fmtStr: fmtStr, num: num, pct: pct, pval: pval, h: h, s: s, chip: chip, note: note, table: table, numCell: numCell,
        niceTicks: niceTicks, lineChart: lineChart, barChart: barChart,
    };
})();
