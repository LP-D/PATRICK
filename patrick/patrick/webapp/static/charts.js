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
    function niceTicks(lo, hi, n) {
        if (lo === hi) { lo -= 1; hi += 1; }
        var span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / n)));
        [1, 2, 5, 10].some(function (m) { if (span / (step * m) <= n) { step *= m; return true; } return false; });
        var start = Math.ceil(lo / step) * step, out = [];
        for (var v = start; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
        return out;
    }

    function lineChart(o) {
        var W = o.width || 720, H = o.height || 220, ml = 46, mr = 12, mt = 10, mb = 26;
        var series = o.series, n = o.dates.length;
        var all = [];
        series.forEach(function (sr) { sr.values.forEach(function (v) { if (v !== null) all.push(v); }); });
        (o.hlines || []).forEach(function (l) { all.push(l.y); });
        if (o.band) { all.push(o.band[0], o.band[1]); }
        var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
        if (o.yMin !== undefined) lo = Math.min(lo, o.yMin);
        if (o.yMax !== undefined) hi = Math.max(hi, o.yMax);
        var pad = (hi - lo) * 0.06 || 0.5; lo -= pad; hi += pad;
        function X(i) { return ml + (W - ml - mr) * (n <= 1 ? 0 : i / (n - 1)); }
        function Y(v) { return mt + (H - mt - mb) * (1 - (v - lo) / (hi - lo)); }
        var svg = s("svg", { viewBox: "0 0 " + W + " " + H, class: "exp-chart", role: "img", "aria-label": fmtStr(tr("exp_chart_aria"), { t: o.title || "" }) });
        niceTicks(lo, hi, 5).forEach(function (t) {
            svg.appendChild(s("line", { x1: ml, x2: W - mr, y1: Y(t), y2: Y(t), stroke: "var(--chart-grid)" }));
            svg.appendChild(s("text", { x: ml - 6, y: Y(t) + 3.5, "text-anchor": "end", class: "exp-axis", text: (o.yFmt || function (v) { return num(v, 2); })(t) }));
        });
        var every = Math.max(1, Math.floor(n / 6));
        for (var i = 0; i < n; i += every) {
            svg.appendChild(s("text", { x: X(i), y: H - 8, "text-anchor": "middle", class: "exp-axis", text: o.dates[i].slice(0, o.dates[i].length > 7 ? 7 : 10) }));
        }
        if (o.band) {
            svg.appendChild(s("rect", { x: ml, width: W - ml - mr, y: Y(o.band[1]), height: Math.max(0, Y(o.band[0]) - Y(o.band[1])), fill: "var(--neutral-soft)" }));
        }
        (o.hlines || []).forEach(function (l) {
            svg.appendChild(s("line", { x1: ml, x2: W - mr, y1: Y(l.y), y2: Y(l.y), stroke: l.color || "var(--text-3)", "stroke-dasharray": l.dash || "4 4", "stroke-width": 1 }));
        });
        series.forEach(function (sr) {
            var d = "";
            sr.values.forEach(function (v, k) { if (v !== null) d += (d ? "L" : "M") + X(k).toFixed(1) + " " + Y(v).toFixed(1); });
            svg.appendChild(s("path", { d: d, fill: "none", stroke: sr.color || "var(--brand)", "stroke-width": 1.6, "stroke-linejoin": "round" }));
        });
        var cursor = s("line", { x1: 0, x2: 0, y1: mt, y2: H - mb, stroke: "var(--text-3)", "stroke-width": 1, visibility: "hidden" });
        var label = s("text", { x: ml + 4, y: mt + 11, class: "exp-axis exp-tip", text: "" });
        svg.appendChild(cursor); svg.appendChild(label);
        svg.addEventListener("mousemove", function (ev) {
            var r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width * W;
            var k = Math.max(0, Math.min(n - 1, Math.round((x - ml) / (W - ml - mr) * (n - 1))));
            cursor.setAttribute("x1", X(k)); cursor.setAttribute("x2", X(k)); cursor.setAttribute("visibility", "visible");
            label.textContent = o.dates[k] + " · " + series.map(function (sr) { return sr.values[k] === null ? "—" : (o.yFmt || num)(sr.values[k]); }).join(" · ");
        });
        svg.addEventListener("mouseleave", function () { cursor.setAttribute("visibility", "hidden"); label.textContent = ""; });
        return h("div", { class: "exp-chart-wrap" }, [svg]);
    }

    function barChart(o) {
        var n = o.values.length, W = o.width || 720, H = o.height || 190, ml = 46, mr = 10, mt = 10, mb = o.labelRows ? 34 : 24;
        var all = o.values.filter(function (v) { return v !== null; }).concat([0]);
        if (o.band) all.push(o.band, -o.band);
        var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
        if (o.yMin !== undefined) lo = Math.min(lo, o.yMin);
        if (o.yMax !== undefined) hi = Math.max(hi, o.yMax);
        var pad = (hi - lo) * 0.08 || 0.1; lo -= (lo < 0 ? pad : 0); hi += pad;
        function Y(v) { return mt + (H - mt - mb) * (1 - (v - lo) / (hi - lo)); }
        var slot = (W - ml - mr) / n, bw = Math.max(2, Math.min(34, slot * 0.7));
        var svg = s("svg", { viewBox: "0 0 " + W + " " + H, class: "exp-chart", role: "img", "aria-label": fmtStr(tr("exp_chart_aria"), { t: o.title || "" }) });
        niceTicks(lo, hi, 4).forEach(function (t) {
            svg.appendChild(s("line", { x1: ml, x2: W - mr, y1: Y(t), y2: Y(t), stroke: "var(--chart-grid)" }));
            svg.appendChild(s("text", { x: ml - 6, y: Y(t) + 3.5, "text-anchor": "end", class: "exp-axis", text: (o.yFmt || function (v) { return num(v, 2); })(t) }));
        });
        if (o.band) {
            [o.band, -o.band].forEach(function (b) {
                svg.appendChild(s("line", { x1: ml, x2: W - mr, y1: Y(b), y2: Y(b), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
            });
        }
        svg.appendChild(s("line", { x1: ml, x2: W - mr, y1: Y(0), y2: Y(0), stroke: "var(--line-strong)" }));
        var every = Math.max(1, Math.ceil(n / 20));
        o.values.forEach(function (v, i) {
            if (v === null) return;
            var x = ml + slot * i + (slot - bw) / 2, y0 = Y(0), y1 = Y(v);
            var strong = o.strong ? o.strong[i] : true;
            var color = o.color ? o.color(v, i) : (v >= 0 ? "var(--brand)" : "var(--neg)");
            var bar = s("rect", { x: x, y: Math.min(y0, y1), width: bw, height: Math.max(1, Math.abs(y1 - y0)), fill: color, "fill-opacity": strong ? 0.95 : 0.4 });
            bar.appendChild(s("title", { text: (o.labels ? o.labels[i] + " : " : "") + (o.yFmt || num)(v) }));
            svg.appendChild(bar);
            if (o.labels && i % every === 0) {
                svg.appendChild(s("text", { x: x + bw / 2, y: H - mb + 13, "text-anchor": "middle", class: "exp-axis", text: o.labels[i] }));
            }
        });
        return h("div", { class: "exp-chart-wrap" }, [svg]);
    }


    window.PatrickCharts = {
        tr: tr, fmtStr: fmtStr, num: num, pct: pct, pval: pval, h: h, s: s, chip: chip, note: note, table: table, numCell: numCell,
        niceTicks: niceTicks, lineChart: lineChart, barChart: barChart,
    };
})();
