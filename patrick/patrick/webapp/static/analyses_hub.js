/* Vue « Analyses » de l'Historique (/runs?vue=analyses, ancienne page /analyses) : carte cible × horizon, distribution des scores par
   algorithme, nuage des runs RL. La liste des runs est l'autre vue de la page (runs.html) : elle porte un lien d'analyse par ligne.
   Données : /api/analyses/maps. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("ah-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, isNum = PK.isNum;
    // ---------------------------------------------------------------- carte cible × horizon
    // Panneau de métriques (ADR 0023) : `d.panel` = [{key, higher, chance, percent}] dans l'ordre AUC dir., Brier, MCC, bonne direction.
    var SPREAD = { AUC_dir: 0.12, Brier_up: 0.03, MCC_4cls: 0.10, Acc_dir_p: 0.08 };
    function pm(d, key) { return d.panel.filter(function (p) { return p.key === key; })[0]; }
    function fmtPm(d, key, v, digits) { return !isNum(v) ? "—" : (pm(d, key).percent ? pct(v, 1) : num(v, digits || 3)); }
    function value(cell, split, key) { var p = cell && cell["panel_" + split]; return p ? p[key] : null; }
    function better(d, key, a, b) { return pm(d, key).higher ? a > b : a < b; }
    function drawMap(d) {
        var host = document.getElementById("ah-map"), key = "AUC_dir", split = "holdout", query = "", per = 40;
        var cells = {};
        d.cells.forEach(function (c) { cells[c.target + "|" + c.horizon] = c; });
        function draw() {
            PK.clear(host);
            host.appendChild(PK.segmented(d.panel.map(function (p) { return { value: p.key, label: T("pm_" + p.key) }; }), key, function (v) { key = v; draw(); }));
            host.appendChild(PK.segmented([{ value: "holdout", label: T("ah_map_holdout") }, { value: "test", label: T("ah_map_test") }], split, function (v) { split = v; draw(); }));
            var search = h("input", { type: "search", class: "ra-num", style: { width: "180px", "margin-left": "12px" }, placeholder: T("ah_filter_q"), value: query });
            search.addEventListener("change", function () { query = search.value; draw(); });
            host.appendChild(search);
            var ts = d.targets.filter(function (t) { return !query || PK.instMatch(t, query.trim().toLowerCase()); });
            ts.sort(function (a, b) {
                function best(t) { var m = null; d.horizons.forEach(function (hz) { var v = value(cells[t + "|" + hz], split, key); if (isNum(v) && (m === null || better(d, key, v, m))) m = v; }); return m; }
                var ba = best(a), bb = best(b);
                if (ba === null || bb === null) return ba === null ? (bb === null ? 0 : 1) : -1;
                return better(d, key, bb, ba) ? 1 : (better(d, key, ba, bb) ? -1 : 0);
            });
            var shown = ts.slice(0, per);
            host.appendChild(PK.heat(shown.map(function (t) { return PK.inst(t); }), d.horizons.map(String), function (r, c) {
                var cell = cells[shown[r] + "|" + d.horizons[c]], v = value(cell, split, key);
                if (!isNum(v)) return { text: "" };
                var p = pm(d, key), dev = Math.min(1, Math.abs(v - p.chance) / SPREAD[key]), good = p.higher ? v >= p.chance : v <= p.chance;
                return { text: p.percent ? pct(v, 0) : num(v, 2), intensity: dev, base: good ? "var(--pos)" : "var(--neg)", href: "/runs/" + encodeURIComponent(cell.run_id) + "/analyse", title: cell.algo + (cell.suspect ? " ⚠" : "") };
            }, { corner: T("ah_map_corner") }));
            host.appendChild(PK.info(T("ah_map_shown", { n: shown.length, total: ts.length })));
            host.appendChild(PK.note(T("ah_map_hint")));
            host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
        }
        draw();
    }

    // ---------------------------------------------------------------- distribution par algorithme
    function drawAlgos(d) {
        var host = document.getElementById("ah-algos"), key = "AUC_dir";
        function draw() {
        PK.clear(host);
        host.appendChild(PK.segmented(d.panel.map(function (p) { return { value: p.key, label: T("pm_" + p.key) }; }), key, function (v) { key = v; draw(); }));
        var algos = d.algos.filter(function (a) { var m = a.metrics[key]; return m && (m.holdout || m.test); });
        if (!algos.length) { host.appendChild(PK.empty(T("ra_reason_not_enough"))); return; }
        var lo = Infinity, hi = -Infinity, p0 = pm(d, key);
        algos.forEach(function (a) { ["test", "holdout"].forEach(function (k) { var b = a.metrics[key][k]; if (b) { lo = Math.min(lo, b.min); hi = Math.max(hi, b.max); } }); });
        lo = Math.min(lo, p0.chance); hi = Math.max(hi, p0.chance);
        var pad = (hi - lo) * 0.05 || 0.02;
        var rowH = 34, H = 30 + algos.length * rowH + 24;
        var P = PK.plot({ w: 780, h: H, m: { l: 140, t: 10, b: 24, r: 14 }, x: { type: "linear", domain: [lo - pad, hi + pad], fmt: function (v) { return fmtPm(d, key, v, 3); }, label: T("pm_" + key) + " · " + T("ah_box_x") }, y: { domain: [0, 1], ticks: [], zero: false }, title: T("ah_s_algos") });
        PK.vline(P, p0.chance, { color: "var(--text-3)" });
        algos.forEach(function (a, i) {
            var y = P.m.t + i * rowH + 17, am = a.metrics[key];
            P.add(PK.s("text", { x: P.m.l - 8, y: y + 4, "text-anchor": "end", class: "ra-axis", text: a.algo + " (" + ((am.holdout || am.test).n) + ")" }));
            [["test", -6, "var(--brand)"], ["holdout", 6, "var(--warn)"]].forEach(function (p) {
                var b = am[p[0]];
                if (!b) return;
                var yy = y + p[1];
                P.add(PK.s("line", { x1: P.X(b.min), x2: P.X(b.max), y1: yy, y2: yy, stroke: p[2], "stroke-width": 1, "stroke-opacity": 0.7 }));
                PK.hoverTip(P.add(PK.s("rect", { x: P.X(b.q1), y: yy - 4, width: Math.max(1, P.X(b.q3) - P.X(b.q1)), height: 8, fill: p[2], "fill-opacity": 0.55, stroke: p[2] })),
                    function () { return [a.algo + " · " + T("ra_split_" + p[0]), T("ah_box_t", { med: fmtPm(d, key, b.median), q1: fmtPm(d, key, b.q1), q3: fmtPm(d, key, b.q3), mn: fmtPm(d, key, b.min), mx: fmtPm(d, key, b.max), n: b.n })]; });
                P.add(PK.s("line", { x1: P.X(b.median), x2: P.X(b.median), y1: yy - 5, y2: yy + 5, stroke: "var(--text)", "stroke-width": 2 }));
            });
        });
        host.appendChild(P.node);
        host.appendChild(PK.legend([{ color: "var(--brand)", label: T("ra_split_test") }, { color: "var(--warn)", label: T("ra_split_holdout") }]));
        host.appendChild(PK.note(T("ah_box_hint")));
        host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
        }
        draw();
    }

    // ---------------------------------------------------------------- nuage RL
    function drawRL(d) {
        var host = document.getElementById("ah-rl"), pts = d.rl.filter(function (p) { return isNum(p.sharpe) && isNum(p.sharpe_bh); });
        if (!pts.length) { host.appendChild(PK.empty(T("ah_rl_none"))); return; }
        var xs = pts.map(function (p) { return p.sharpe_bh; }), ys = pts.map(function (p) { return p.sharpe; });
        var dom = PK.extent([xs, ys], 0.08);
        var P = PK.plot({ w: 560, h: 380, x: { type: "linear", domain: dom, fmt: function (v) { return num(v, 1); }, label: T("ah_rl_x") }, y: { domain: dom, fmt: function (v) { return num(v, 1); }, label: T("ah_rl_y") }, title: T("ah_s_rl") });
        P.add(PK.s("line", { x1: P.X(dom[0]), y1: P.Y(dom[0]), x2: P.X(dom[1]), y2: P.Y(dom[1]), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
        // Une alerte (fuite probable, cible non négociable) = cercle vide : le point ne se lit pas comme une stratégie. Moteur 2 = carré.
        var ALERT = { leak: 1, untradable: 1 };
        pts.forEach(function (p) {
            var color = p.sharpe > p.sharpe_bh ? "var(--pos)" : "var(--neg)", alert = ALERT[p.verdict], x = P.X(p.sharpe_bh), y = P.Y(p.sharpe);
            var style = alert ? { fill: "none", stroke: "var(--text-3)", "stroke-width": 1.2 } : { fill: color, "fill-opacity": p.verdict === "beats" ? 0.95 : 0.55 };
            var c = p.engine >= 2 ? PK.s("rect", Object.assign({ x: x - 3.4, y: y - 3.4, width: 6.8, height: 6.8 }, style)) : PK.s("circle", Object.assign({ cx: x, cy: y, r: 3.6 }, style));
            c.style.cursor = "pointer";
            c.addEventListener("click", function () { window.location.href = "/runs/" + encodeURIComponent(p.id) + "/analyse"; });
            PK.hoverTip(P.add(c), function () {
                return [PK.inst(p.target) + " · " + p.algo + " · " + T("ra_rl_rd_engine", { n: p.engine || 1 }), T("ah_rl_t", { s: num(p.sharpe, 2), b: num(p.sharpe_bh, 2), d: isNum(p.dsr) ? pct(p.dsr, 0) : "—" })]
                    .concat(isNum(p.excess) ? [T("ah_rl_t_excess", { e: PK.spct(p.excess, 1) })] : []).concat(p.verdict ? [T("ra_rl_rd_" + p.verdict)] : []);
            });
        });
        var clean = pts.filter(function (p) { return !ALERT[p.verdict]; });
        var above = clean.filter(function (p) { return p.sharpe > p.sharpe_bh; }).length, beats = clean.filter(function (p) { return p.verdict === "beats"; }).length;
        host.appendChild(P.node);
        function shapeKey(kind, label) {
            var svg = PK.s("svg", { width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": "true" });
            svg.appendChild(kind === "square" ? PK.s("rect", { x: 2, y: 2, width: 8, height: 8, fill: "var(--text-2)" })
                : PK.s("circle", kind === "hollow" ? { cx: 6, cy: 6, r: 4, fill: "none", stroke: "var(--text-3)", "stroke-width": 1.2 } : { cx: 6, cy: 6, r: 4, fill: "var(--text-2)" }));
            return h("span", { class: "ra-legend-item" }, [svg, label]);
        }
        host.appendChild(h("div", { class: "ra-legend" }, [shapeKey("circle", T("ah_rl_lg_v1")), shapeKey("square", T("ah_rl_lg_v2")), shapeKey("hollow", T("ah_rl_lg_alert"))]));
        host.appendChild(PK.info(T("ah_rl_count2", { a: above, b: beats, n: clean.length, x: pts.length - clean.length })));
        host.appendChild(PK.note(T("ah_rl_hint")));
    }

    // ---------------------------------------------------------------- démarrage
    PK.fetchJSON("/api/analyses/maps").then(function (d) { drawMap(d); drawAlgos(d); drawRL(d); }).catch(function (e) {
        ["ah-map", "ah-algos", "ah-rl"].forEach(function (id) { PK.clear(document.getElementById(id)).appendChild(PK.empty(T("ra_error") + " " + e.message)); });
    });
})();
