/* Page /analyses/comparer : 2 à 4 runs ML / DL côte à côte (chiffres de tête, courbes superposées, plis, matrice de Diebold-Mariano,
   différences de configuration). Données : /api/analyses/compare. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("ac-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var IDS = (root.getAttribute("data-run-ids") || "").split(",").filter(Boolean);
    var COLORS = ["var(--ra-c1)", "var(--ra-c2)", "var(--ra-c3)", "var(--ra-c4)"];
    var state = { cost: 5, window: 120 }, data = null;

    function nearest(arr, v) {
        var lo = 0, hi = arr.length - 1;
        if (hi < 0) return -1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (arr[mid] < v) lo = mid; else hi = mid; }
        return Math.abs(arr[lo] - v) <= Math.abs(arr[hi] - v) ? lo : hi;
    }
    function request() {
        PK.fetchJSON("/api/analyses/compare?" + IDS.map(function (i) { return "run_ids=" + encodeURIComponent(i); }).join("&") + "&cost_bps=" + state.cost + "&window=" + state.window).then(function (d) { data = d; draw(); })
            .catch(function (e) { PK.clear(document.getElementById("ac-head")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); });
    }

    function controls() {
        var box = document.getElementById("ac-controls");
        var slider = h("input", { type: "range", min: 0, max: 50, step: 1, value: state.cost, class: "ra-range", "aria-label": T("ra_eq_cost") });
        var out = h("output", { class: "pk-mono", text: state.cost + " bps" });
        slider.addEventListener("input", function () { out.textContent = slider.value + " bps"; });
        slider.addEventListener("change", function () { state.cost = +slider.value; request(); });
        box.appendChild(h("label", { class: "ra-control" }, [h("span", { text: T("ra_eq_cost") }), slider, out]));
        box.appendChild(PK.segmented([60, 120, 250].map(function (w) { return { value: w, label: T("ra_ro_window", { n: w }) }; }), state.window, function (w) { state.window = +w; request(); }));
    }

    function draw() {
        var runs = data.runs;
        var chips = document.getElementById("ac-runs");
        PK.clear(chips);
        runs.forEach(function (r, i) {
            chips.appendChild(h("a", { class: "exp-chip-btn", href: "/runs/" + encodeURIComponent(r.run_id) + "/analyse", style: { "border-color": COLORS[i] } }, [h("i", { class: "ra-swatch", style: { background: COLORS[i] } }), " " + r.name + " · " + PK.inst(r.target) + " h" + r.horizon + " · " + r.algo]));
        });
        if (!data.same_target) chips.appendChild(PK.info(T("ac_mixed")));
        head(); curves(); folds(); dm(); diff();
        root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }

    function head() {
        var runs = data.runs;
        function hd(split, key) { return function (r) { var s = (r.headline || {})[split]; return s ? s[key] : null; }; }
        var table = [
            [T("ra_k_acc_test"), hd("test", "acc"), "max", function (v) { return pct(v, 1); }], [T("ra_k_acc_holdout"), hd("holdout", "acc"), "max", function (v) { return pct(v, 1); }],
            [T("ra_m_f1dir") + " · " + T("ra_split_test"), hd("test", "f1_dir"), "max", function (v) { return num(v, 3); }], [T("ra_m_f1dir") + " · " + T("ra_split_holdout"), hd("holdout", "f1_dir"), "max", function (v) { return num(v, 3); }],
            [T("ra_m_auc") + " · " + T("ra_split_test"), hd("test", "auc"), "max", function (v) { return num(v, 3); }], [T("ra_m_balacc") + " · " + T("ra_split_test"), hd("test", "bal_acc"), "max", function (v) { return num(v, 3); }],
            [T("ra_m_mcc") + " · " + T("ra_split_test"), hd("test", "mcc"), "max", function (v) { return num(v, 3); }], [T("ra_m_brier") + " · " + T("ra_split_test"), hd("test", "brier"), "min", function (v) { return num(v, 4); }],
            [T("ra_m_n") + " · " + T("ra_split_test"), hd("test", "n"), null, int], [T("ra_m_predup") + " · " + T("ra_split_test"), hd("test", "share_pred_up"), null, function (v) { return pct(v, 0); }],
            [T("ac_eq_total"), function (r) { return r.equity ? r.equity.stats.total : null; }, "max", function (v) { return PK.spct(v, 1); }], [T("ac_eq_sharpe"), function (r) { return r.equity ? r.equity.stats.sharpe : null; }, "max", function (v) { return num(v, 2); }],
            [T("ac_eq_dd"), function (r) { return r.equity ? r.equity.stats.max_dd : null; }, "max", function (v) { return pct(v, 1); }],
        ];
        var body = table.map(function (t) {
            var vals = runs.map(t[1]), nums = vals.filter(isNum), best = nums.length > 1 && t[2] ? (t[2] === "max" ? Math.max.apply(null, nums) : Math.min.apply(null, nums)) : null;
            return [t[0]].concat(vals.map(function (v) { return { cell: isNum(v) ? t[3](v) : "—", cls: best !== null && v === best ? "pos" : "" }; }));
        });
        PK.clear(document.getElementById("ac-head")).appendChild(PK.table([""].concat(runs.map(function (r) { return r.name; })), body, { num: runs.map(function (_, i) { return i + 1; }) }));
        document.getElementById("ac-head").appendChild(PK.note(T("ac_head_hint", { c: data.cost_bps })));
    }

    function overlay(title, ys, opts) {
        // ys : [{x:[ms], y:[...], color}] ; opts : {fmt, base, zero}
        var xs = [].concat.apply([], ys.map(function (s) { return s.x; })), lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs), pad = (hi - lo) * 0.01;
        var P = PK.plot({ w: 780, h: 250, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: PK.extent(ys.map(function (s) { return s.y; }).concat(opts.include ? [opts.include] : []), 0.06), fmt: opts.fmt, zero: opts.zero !== false }, title: title });
        if (opts.base !== undefined) PK.hline(P, opts.base, { color: "var(--text-3)" });
        ys.forEach(function (s) { PK.line(P, s.x, s.y, { color: s.color, width: s.width || 1.6, dash: s.dash || null }); });
        PK.hover(P, function (xv) {
            return [PK.dateStr(xv)].concat(ys.map(function (s, i) { var k = nearest(s.x, xv); return k < 0 ? null : (s.label || "") + " " + opts.fmt(s.y[k]); }).filter(Boolean));
        });
        return P.node;
    }
    function curves() {
        var runs = data.runs, host = PK.clear(document.getElementById("ac-curves"));
        var eq = [];
        runs.forEach(function (r, i) { if (r.equity) eq.push({ x: r.equity.dates.map(PK.dateMs), y: r.equity.long_short, color: COLORS[i], label: r.name }); });
        if (eq.length) {
            var bh = runs.filter(function (r) { return r.equity; })[0];
            host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ac_eq") }), overlay(T("ac_eq"), eq.concat(data.same_target ? [{ x: bh.equity.dates.map(PK.dateMs), y: bh.equity.buy_hold, color: "var(--text-3)", dash: "4 3", width: 1.2, label: T("ra_eq_bh") }] : []), { fmt: function (v) { return num(v, 2); }, zero: false }), PK.note(T("ac_eq_hint"))]));
        }
        var ro = [];
        runs.forEach(function (r, i) { if (r.rolling) ro.push({ x: r.rolling.t.map(PK.dateMs), y: r.rolling.acc, color: COLORS[i], label: r.name }); });
        if (ro.length) host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ra_ro_title") }), overlay(T("ra_ro_title"), ro, { fmt: function (v) { return pct(v, 1); }, base: 0.5, zero: false })]));
        var leg = PK.legend(runs.map(function (r, i) { return { color: COLORS[i], label: r.name, line: true }; }));
        host.appendChild(leg);
        // fiabilité et ROC
        var P = PK.plot({ w: 380, h: 300, x: { type: "linear", domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_ca_x") }, y: { domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_ca_y") }, title: T("ac_rel") });
        P.add(PK.s("line", { x1: P.X(0), y1: P.Y(0), x2: P.X(1), y2: P.Y(1), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
        runs.forEach(function (r, i) { if (r.reliability) PK.line(P, r.reliability.map(function (b) { return b.p_mean; }), r.reliability.map(function (b) { return b.freq; }), { color: COLORS[i], width: 1.6 }); });
        var Q = PK.plot({ w: 380, h: 300, x: { type: "linear", domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_cf_fpr") }, y: { domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_cf_tpr") }, title: "ROC" });
        Q.add(PK.s("line", { x1: Q.X(0), y1: Q.Y(0), x2: Q.X(1), y2: Q.Y(1), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
        runs.forEach(function (r, i) { if (r.roc) PK.line(Q, r.roc.fpr, r.roc.tpr, { color: COLORS[i], width: 1.6 }); });
        host.appendChild(h("div", { class: "ra-grid-2" }, [h("div", { class: "ra-block" }, [h("h3", { text: T("ac_rel") }), P.node]), h("div", { class: "ra-block" }, [h("h3", { text: "ROC" }), Q.node])]));
    }

    function folds() {
        var runs = data.runs, host = PK.clear(document.getElementById("ac-folds")), maxF = 0;
        runs.forEach(function (r) { r.folds.forEach(function (f) { maxF = Math.max(maxF, f.split === "holdout" ? 0 : f.fold); }); });
        var labels = []; for (var k = 1; k <= maxF; k++) labels.push(T("ra_pr_fold", { n: k })); labels.push(T("ra_pr_holdout"));
        var head = [T("ra_pr_h_fold")].concat(runs.map(function (r) { return r.name; }));
        var rows = labels.map(function (lab, idx) {
            var cells = runs.map(function (r) {
                var f = r.folds.filter(function (x) { return idx < maxF ? (x.split === "test" && x.fold === idx + 1) : x.split === "holdout"; })[0];
                if (!f) return "—";
                var maj = Math.max(f.base_up, 1 - f.base_up);
                return { cell: pct(f.acc, 1) + " (n=" + f.n + ")", cls: f.acc > maj ? "pos" : "neg" };
            });
            return [lab].concat(cells);
        });
        host.appendChild(PK.table(head, rows));
        host.appendChild(PK.note(T("ac_folds_hint")));
    }

    function dm() {
        var d = data.dm, n = d.names.length, host = PK.clear(document.getElementById("ac-dm"));
        var by = {};
        d.pairs.forEach(function (c) { by[c.i + "-" + c.j] = c; });
        host.appendChild(PK.heat(d.names, d.names, function (r, c) {
            if (r === c) return { text: "—" };
            var cell = by[Math.min(r, c) + "-" + Math.max(r, c)];
            if (!cell) return { text: "" };
            if (cell.p === null) return { text: "n/a", title: T("ac_dm_reason_" + (cell.reason || "unknown")), cls: "na" };
            var better = cell.better === r ? "▲" : (cell.better === c ? "▼" : "=");
            return { text: better + " " + PK.pval(cell.p_adj), intensity: Math.min(1, (1 - cell.p_adj) * 1.2), base: cell.better === r ? "var(--pos)" : "var(--neg)", title: T("ac_dm_cell", { p: PK.pval(cell.p), pa: PK.pval(cell.p_adj), n: cell.n, a: pct(cell.loss_i, 1), b: pct(cell.loss_j, 1) }) };
        }, { corner: T("ac_dm_corner") }));
        host.appendChild(PK.note(T("ac_dm_legend", { m: d.n_tested })));
    }

    function diff() {
        var host = PK.clear(document.getElementById("ac-diff")), rows = data.config_diff;
        if (!rows.length) { host.appendChild(PK.empty(T("ac_diff_none"))); return; }
        host.appendChild(PK.table([T("ac_diff_key")].concat(data.runs.map(function (r) { return r.name; })), rows.map(function (r) { return [{ cell: r.key, cls: "pk-mono" }].concat(r.values.map(function (v) { return v === null ? "—" : v; })); })));
        host.appendChild(PK.info(T("ac_diff_count", { n: rows.length })));
    }

    controls();
    request();
})();
