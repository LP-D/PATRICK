/* Vue « Analyses » de l'Historique (/runs?vue=analyses, ancienne page /analyses) : carte cible × horizon, distribution des scores par
   algorithme, nuage des runs RL. La liste des runs est l'autre vue de la page (runs.html) : elle porte un lien d'analyse par ligne.
   Données : /api/analyses/maps. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("ah-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, isNum = PK.isNum;
    // ---------------------------------------------------------------- carte cible × horizon
    function drawMap(d) {
        var host = document.getElementById("ah-map"), metric = "f1_holdout", query = "", per = 40;
        var cells = {};
        d.cells.forEach(function (c) { cells[c.target + "|" + c.horizon] = c; });
        function draw() {
            PK.clear(host);
            host.appendChild(PK.segmented([{ value: "f1_holdout", label: T("ah_map_holdout") }, { value: "f1_test", label: T("ah_map_test") }], metric, function (v) { metric = v; draw(); }));
            var search = h("input", { type: "search", class: "ra-num", style: { width: "180px", "margin-left": "12px" }, placeholder: T("ah_filter_q"), value: query });
            search.addEventListener("change", function () { query = search.value; draw(); });
            host.appendChild(search);
            var ts = d.targets.filter(function (t) { return !query || t.toLowerCase().indexOf(query.trim().toLowerCase()) >= 0; });
            ts.sort(function (a, b) {
                function best(t) { var m = -1; d.horizons.forEach(function (hz) { var c = cells[t + "|" + hz]; if (c && isNum(c[metric]) && c[metric] > m) m = c[metric]; }); return m; }
                return best(b) - best(a);
            });
            var shown = ts.slice(0, per);
            host.appendChild(PK.heat(shown, d.horizons.map(String), function (r, c) {
                var cell = cells[shown[r] + "|" + d.horizons[c]];
                if (!cell || !isNum(cell[metric])) return { text: "" };
                var v = cell[metric], dev = Math.min(1, Math.abs(v - 0.5) / 0.12);
                return { text: num(v, 2), intensity: dev, base: v >= 0.5 ? "var(--pos)" : "var(--neg)", href: "/runs/" + encodeURIComponent(cell.run_id) + "/analyse", title: cell.algo + (cell.suspect ? " ⚠" : "") };
            }, { corner: T("ah_map_corner") }));
            host.appendChild(PK.info(T("ah_map_shown", { n: shown.length, total: ts.length })));
            host.appendChild(PK.note(T("ah_map_hint")));
            host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
        }
        draw();
    }

    // ---------------------------------------------------------------- distribution par algorithme
    function drawAlgos(d) {
        var host = document.getElementById("ah-algos");
        var algos = d.algos.filter(function (a) { return a.holdout || a.test; });
        if (!algos.length) { host.appendChild(PK.empty(T("ra_reason_not_enough"))); return; }
        var lo = 1, hi = 0;
        algos.forEach(function (a) { ["test", "holdout"].forEach(function (k) { if (a[k]) { lo = Math.min(lo, a[k].min); hi = Math.max(hi, a[k].max); } }); });
        var rowH = 34, H = 30 + algos.length * rowH + 24;
        var P = PK.plot({ w: 780, h: H, m: { l: 100, t: 10, b: 24, r: 14 }, x: { type: "linear", domain: [Math.max(0, lo - 0.02), Math.min(1, hi + 0.02)], fmt: function (v) { return num(v, 2); }, label: T("ah_box_x") }, y: { domain: [0, 1], ticks: [], zero: false }, title: T("ah_s_algos") });
        PK.vline(P, 0.5, { color: "var(--text-3)" });
        algos.forEach(function (a, i) {
            var y = P.m.t + i * rowH + 17;
            P.add(PK.s("text", { x: P.m.l - 8, y: y + 4, "text-anchor": "end", class: "ra-axis", text: a.algo + " (" + ((a.holdout || a.test).n) + ")" }));
            [["test", -6, "var(--brand)"], ["holdout", 6, "var(--warn)"]].forEach(function (p) {
                var b = a[p[0]];
                if (!b) return;
                var yy = y + p[1];
                P.add(PK.s("line", { x1: P.X(b.min), x2: P.X(b.max), y1: yy, y2: yy, stroke: p[2], "stroke-width": 1, "stroke-opacity": 0.7 }));
                PK.hoverTip(P.add(PK.s("rect", { x: P.X(b.q1), y: yy - 4, width: Math.max(1, P.X(b.q3) - P.X(b.q1)), height: 8, fill: p[2], "fill-opacity": 0.55, stroke: p[2] })),
                    function () { return [a.algo + " · " + T("ra_split_" + p[0]), T("ah_box_t", { med: num(b.median, 3), q1: num(b.q1, 3), q3: num(b.q3, 3), mn: num(b.min, 3), mx: num(b.max, 3), n: b.n })]; });
                P.add(PK.s("line", { x1: P.X(b.median), x2: P.X(b.median), y1: yy - 5, y2: yy + 5, stroke: "var(--text)", "stroke-width": 2 }));
            });
        });
        host.appendChild(P.node);
        host.appendChild(PK.legend([{ color: "var(--brand)", label: T("ra_split_test") }, { color: "var(--warn)", label: T("ra_split_holdout") }]));
        host.appendChild(PK.note(T("ah_box_hint")));
    }

    // ---------------------------------------------------------------- nuage RL
    function drawRL(d) {
        var host = document.getElementById("ah-rl"), pts = d.rl.filter(function (p) { return isNum(p.sharpe) && isNum(p.sharpe_bh); });
        if (!pts.length) { host.appendChild(PK.empty(T("ah_rl_none"))); return; }
        var xs = pts.map(function (p) { return p.sharpe_bh; }), ys = pts.map(function (p) { return p.sharpe; });
        var dom = PK.extent([xs, ys], 0.08);
        var P = PK.plot({ w: 560, h: 380, x: { type: "linear", domain: dom, fmt: function (v) { return num(v, 1); }, label: T("ah_rl_x") }, y: { domain: dom, fmt: function (v) { return num(v, 1); }, label: T("ah_rl_y") }, title: T("ah_s_rl") });
        P.add(PK.s("line", { x1: P.X(dom[0]), y1: P.Y(dom[0]), x2: P.X(dom[1]), y2: P.Y(dom[1]), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
        pts.forEach(function (p) {
            var c = PK.s("circle", { cx: P.X(p.sharpe_bh), cy: P.Y(p.sharpe), r: 3.6, fill: p.sharpe > p.sharpe_bh ? "var(--pos)" : "var(--neg)", "fill-opacity": 0.6 });
            c.style.cursor = "pointer";
            c.addEventListener("click", function () { window.location.href = "/runs/" + encodeURIComponent(p.id) + "/analyse"; });
            PK.hoverTip(P.add(c), function () { return [p.target + " · " + p.algo, T("ah_rl_t", { s: num(p.sharpe, 2), b: num(p.sharpe_bh, 2), d: isNum(p.dsr) ? pct(p.dsr, 0) : "—" })]; });
        });
        var above = pts.filter(function (p) { return p.sharpe > p.sharpe_bh; }).length;
        host.appendChild(P.node);
        host.appendChild(PK.info(T("ah_rl_count", { a: above, n: pts.length })));
        host.appendChild(PK.note(T("ah_rl_hint")));
    }

    // ---------------------------------------------------------------- démarrage
    PK.fetchJSON("/api/analyses/maps").then(function (d) { drawMap(d); drawAlgos(d); drawRL(d); }).catch(function (e) {
        ["ah-map", "ah-algos", "ah-rl"].forEach(function (id) { PK.clear(document.getElementById(id)).appendChild(PK.empty(T("ra_error") + " " + e.message)); });
    });
})();
