/* Page /runs/{id}/analyse : plis, stratégie simulée, erreurs, variables, essais, robustesse, holdout et live, chemins CPCV, lecture
   guidée. Suite de `run_analysis.js` (même objet `window.RA`, boîte à outils `window.PK`). */
(function () {
    "use strict";
    var PK = window.PK, RA = window.RA;
    if (!PK || !RA) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var H = RA.helpers, titled = H.titled, row2 = H.row2, splitLabel = H.splitLabel, nearestIdx = H.nearestIdx;

    function foldName(f) { return f.split === "holdout" || f.fold === 0 && f.split !== "test" ? T("ra_pr_holdout") : T("ra_pr_fold", { n: f.fold }); }
    function hbars(items, o) {
        var max = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1e-12]));
        return h("div", { class: "ra-hbars" }, items.map(function (it) {
            return h("div", { class: "ra-hbar" }, [
                h("span", { class: "ra-hbar-label", title: it.label, text: it.label }),
                h("span", { class: "ra-hbar-track" }, [h("i", { style: { width: (Math.max(0, it.value) / (o.max || max) * 100).toFixed(1) + "%", background: it.color || o.color || "var(--brand)" } })]),
                h("span", { class: "ra-hbar-val pk-mono", text: o.fmt(it.value) })]);
        }));
    }

    // ---------------------------------------------------------------- plis
    RA.render.folds = function (m, d) {
        var all = {};
        d.blocks.forEach(function (b) { b.metrics.forEach(function (x) { all[x] = 1; }); });
        var metrics = d.metric_order.filter(function (x) { return all[x]; }).concat(Object.keys(all).filter(function (x) { return d.metric_order.indexOf(x) < 0 && x !== "n_train" && x !== "effective_n_train" && x !== "n_test"; }));
        var cur = metrics.indexOf("F1_dir") >= 0 ? "F1_dir" : metrics[0], host = h("div", {});
        m.appendChild(PK.select(metrics.map(function (x) { return { value: x, label: x }; }), cur, function (v) { cur = v; draw(); }, T("ra_fo_metric")));
        m.appendChild(host);
        draw();
        function draw() {
            PK.clear(host);
            var cats = [], vals = [], cols = [];
            d.blocks.forEach(function (b) {
                if (b.split === "valid") return;
                b.folds.forEach(function (f) {
                    if (f.vals[cur] === undefined) return;
                    cats.push((b.split === "holdout" ? T("ra_pr_holdout") : (b.split === "test_path" ? T("ra_pa_path", { n: f.fold }) : T("ra_pr_fold", { n: f.fold }))));
                    vals.push(f.vals[cur]);
                    cols.push(b.split === "holdout" ? "var(--warn)" : "var(--brand)");
                });
            });
            if (!vals.length) { host.appendChild(PK.empty(T("ra_reason_not_enough"))); return; }
            var base = {};
            Object.keys(d.baselines || {}).forEach(function (b) { var t = (d.baselines[b] || {}).test; if (t && isNum(t[cur])) base[b] = t[cur]; });
            var yr = PK.extent([vals, Object.keys(base).map(function (k) { return base[k]; }), [0]], 0.12);
            if (cur.indexOf("F1") === 0 || cur.indexOf("Acc") === 0 || cur.indexOf("AUC") === 0) yr[0] = Math.min(yr[0], 0.3);
            var X = vals.map(function (_, i) { return i + 1; });
            var P = PK.plot({ w: 780, h: 280, x: { type: "linear", domain: [0.4, vals.length + 0.6], ticks: X, fmt: function (v) { return cats[v - 1] || ""; } }, y: { domain: yr, fmt: function (v) { return num(v, 2); } }, title: cur });
            PK.hline(P, 0.5, { color: "var(--text-3)" });
            PK.bars(P, X, vals, { base: yr[0], color: function (v, i) { return cols[i]; }, title: function (i) { return cats[i] + " · " + num(vals[i], 4); }, width: Math.min(60, 520 / vals.length) });
            var mean = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
            PK.hline(P, mean, { color: "var(--brand)", dash: "2 3", label: T("ra_fo_mean", { v: num(mean, 3) }) });
            var bnames = Object.keys(base);
            function bcolor(i) { return "var(--ra-c" + (2 + (i % 7)) + ")"; }
            bnames.forEach(function (k, i) { PK.hline(P, base[k], { color: bcolor(i), dash: "6 3", width: 1.1 }); });
            host.appendChild(P.node);
            host.appendChild(PK.legend([{ color: "var(--brand)", label: T("ra_pr_test") }, { color: "var(--warn)", label: T("ra_pr_holdout") }].concat(bnames.map(function (k, i) { return { color: bcolor(i), label: T("ra_fo_baseline", { b: k.replace(/^BASELINE_/, "") }) + " " + num(base[k], 3), line: true }; }))));
            host.appendChild(PK.note(T("ra_fo_note")));
            d.blocks.forEach(function (b) {
                var rows = [[T("ra_fo_mean_row")].concat(b.metrics.map(function (x) { return num(b.mean[x], 4); }))];
                b.folds.forEach(function (f) { rows.push([b.split === "holdout" ? T("ra_pr_holdout") : String(f.fold)].concat(b.metrics.map(function (x) { return num(f.vals[x], 4); }))); });
                host.appendChild(titled(splitLabel(b.split === "test_path" ? "test" : b.split) + (b.split === "valid" ? " (" + T("ra_fo_valid") + ")" : ""),
                    PK.table([T("ra_pr_h_fold")].concat(b.metrics), rows, { num: b.metrics.map(function (_, i) { return i + 1; }), rowClass: function (i) { return i === 0 ? "fold-mean" : ""; } })));
            });
            if ((d.dm || []).length) host.appendChild(titled(T("ra_fo_dm"), PK.table([T("ra_fo_baseline_h"), T("ra_fo_dm_kind"), "DM", "p", T("ra_fo_dm_sample"), "n"],
                d.dm.map(function (x) { return [x.baseline, x.kind, num(x.dm_stat, 3), PK.pval(x.p_value), x.sample, int(x.n_obs)]; }), { num: [2, 3, 5] }), T("ra_fo_dm_hint")));
        }
    };

    // ---------------------------------------------------------------- stratégie simulée
    var STRAT = [["long_short", "ra_eq_ls", "var(--brand)"], ["long_flat", "ra_eq_lf", "var(--pos)"], ["buy_hold", "ra_eq_bh", "var(--text-3)"]];
    function perf(r) {
        var n = r.length;
        if (!n) return {};
        var eq = 1, peak = 1, dd = 0, sum = 0, sq = 0, dsq = 0, wins = 0;
        for (var i = 0; i < n; i++) {
            eq *= 1 + r[i]; peak = Math.max(peak, eq); dd = Math.min(dd, eq / peak - 1);
            sum += r[i]; sq += r[i] * r[i]; if (r[i] < 0) dsq += r[i] * r[i]; if (r[i] > 0) wins++;
        }
        var mean = sum / n, sd = n > 1 ? Math.sqrt(Math.max(0, (sq - n * mean * mean) / (n - 1))) : 0, down = Math.sqrt(dsq / n), yrs = n / 252;
        return { total: eq - 1, cagr: eq > 0 && yrs > 0 ? Math.pow(eq, 1 / yrs) - 1 : null, vol: sd * Math.sqrt(252), sharpe: sd > 1e-12 ? mean / sd * Math.sqrt(252) : null,
            sortino: down > 1e-12 ? mean / down * Math.sqrt(252) : null, maxdd: dd, win: wins / n };
    }
    RA.render.equity = function (m, d) {
        var ms = d.dates.map(PK.dateMs), N = ms.length, st = { cost: Math.round(d.cost_bps), off: {}, log: true };
        var iHold = d.holdout_start ? nearestIdx(ms, PK.dateMs(d.holdout_start)) : N, iLive = d.live_start ? nearestIdx(ms, PK.dateMs(d.live_start)) : N;
        var host = h("div", {});
        var slider = h("input", { type: "range", min: 0, max: 50, step: 1, value: st.cost, class: "ra-range", "aria-label": T("ra_eq_cost") });
        var out = h("output", { class: "pk-mono", text: st.cost + " bps" });
        slider.addEventListener("input", function () { st.cost = +slider.value; out.textContent = st.cost + " bps"; draw(); });
        var ctl = h("div", { class: "ra-controls" }, [h("label", { class: "ra-control" }, [h("span", { text: T("ra_eq_cost") }), slider, out])]);
        ctl.appendChild(PK.segmented([{ value: "log", label: T("ra_eq_log") }, { value: "lin", label: T("ra_eq_lin") }], "log", function (v) { st.log = v === "log"; draw(); }));
        m.appendChild(ctl);
        m.appendChild(PK.note(T("ra_eq_note", { h: d.horizon })));
        m.appendChild(host);
        draw();
        function net(k) {
            var s = d.series[k], c = st.cost * 1e-4, r = new Array(N);
            for (var i = 0; i < N; i++) r[i] = s.gross[i] - c * s.turn[i];
            return r;
        }
        function curve(r) { var e = 1, o = new Array(r.length); for (var i = 0; i < r.length; i++) { e *= 1 + r[i]; o[i] = e; } return o; }
        function draw() {
            PK.clear(host);
            var lo = ms[0], hi = ms[N - 1], pad = (hi - lo) * 0.01, curves = {}, rets = {}, dds = {}, rsh = {};
            STRAT.forEach(function (s) {
                var r = net(s[0]); rets[s[0]] = r; curves[s[0]] = curve(r);
                var peak = 1; dds[s[0]] = curves[s[0]].map(function (v) { peak = Math.max(peak, v); return v / peak - 1; });
                rsh[s[0]] = r.map(function (_, i) {
                    if (i < 125) return null;
                    var a = Math.max(0, i - 251), w = r.slice(a, i + 1), mu = w.reduce(function (x, y) { return x + y; }, 0) / w.length;
                    var sd = Math.sqrt(w.reduce(function (x, y) { return x + (y - mu) * (y - mu); }, 0) / Math.max(1, w.length - 1));
                    return sd > 1e-12 ? mu / sd * Math.sqrt(252) : null;
                });
            });
            function mark(P) {
                (d.folds || []).forEach(function (f) { if (f.split !== "holdout") PK.vline(P, PK.dateMs(f.start), { color: "var(--line-strong)", dash: "2 3" }); });
                if (d.holdout_start) PK.vline(P, PK.dateMs(d.holdout_start), { color: "var(--warn)", label: T("ra_pr_holdout") });
                if (d.live_start) PK.vline(P, PK.dateMs(d.live_start), { color: "var(--pos)", label: T("ra_split_live"), anchor: "end", row: 1 });
            }
            var vis = STRAT.filter(function (s) { return !st.off[s[0]]; });
            var yv = PK.extent(vis.map(function (s) { return curves[s[0]]; }), 0.06), raw = PK.extent(vis.map(function (s) { return curves[s[0]]; }), 0);
            var useLog = st.log && raw[0] > 0;
            function tr(v) { return useLog ? Math.log(v) : v; }
            var ylo = useLog ? Math.log(raw[0]) - 0.06 : yv[0], yhi = useLog ? Math.log(raw[1]) + 0.06 : yv[1];
            var ticks = useLog ? [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64].filter(function (v) { return Math.log(v) >= ylo && Math.log(v) <= yhi; }).map(Math.log) : undefined;
            var P = PK.plot({ w: 780, h: 290, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: [ylo, yhi], ticks: ticks, fmt: function (v) { return num(useLog ? Math.exp(v) : v, 2); }, zero: false }, title: T("ra_eq_title") });
            mark(P);
            vis.forEach(function (s) { PK.line(P, ms, curves[s[0]].map(tr), { color: s[2], width: s[0] === "buy_hold" ? 1.3 : 1.8, dash: s[0] === "buy_hold" ? "4 3" : null }); });
            PK.hover(P, function (xv) {
                var i = nearestIdx(ms, xv);
                return i < 0 ? null : [d.dates[i]].concat(STRAT.filter(function (s) { return !st.off[s[0]]; }).map(function (s) { return T(s[1]) + " : " + num(curves[s[0]][i], 3) + " (" + PK.spct(curves[s[0]][i] - 1, 1) + ")"; }));
            }, function (xv) { return ms[nearestIdx(ms, xv)]; });
            var leg = h("div", { class: "ra-legend" });
            STRAT.forEach(function (s) {
                var b = h("button", { type: "button", class: "ra-legend-item ra-legend-btn" + (st.off[s[0]] ? " off" : ""), "aria-pressed": String(!st.off[s[0]]) }, [h("i", { class: "ra-swatch ra-swatch-line", style: { background: s[2] } }), T(s[1])]);
                b.addEventListener("click", function () { st.off[s[0]] = !st.off[s[0]]; draw(); });
                leg.appendChild(b);
            });
            host.appendChild(titled(T("ra_eq_h"), P.node));
            host.appendChild(leg);
            var dd = PK.plot({ w: 780, h: 170, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: PK.extent(vis.map(function (s) { return dds[s[0]]; }).concat([[0]]), 0.05), fmt: function (v) { return pct(v, 0); } }, title: T("ra_eq_dd") });
            mark(dd);
            vis.forEach(function (s) { PK.line(dd, ms, dds[s[0]], { color: s[2], width: 1.3, area: s[0] === "long_short", areaOpacity: 0.12 }); });
            host.appendChild(titled(T("ra_eq_dd"), dd.node));
            var rs = PK.plot({ w: 780, h: 170, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: PK.extent(vis.map(function (s) { return rsh[s[0]]; }), 0.1), fmt: function (v) { return num(v, 1); } }, title: T("ra_eq_rs") });
            mark(rs);
            vis.forEach(function (s) { PK.line(rs, ms, rsh[s[0]], { color: s[2], width: 1.3 }); });
            host.appendChild(titled(T("ra_eq_rs"), rs.node, T("ra_eq_rs_hint")));
            var periods = [["all", 0, N], ["test", 0, Math.min(iHold, N)], ["holdout", iHold, Math.min(iLive, N)]].filter(function (p) { return p[2] - p[1] > 20; });
            var rows = [];
            STRAT.forEach(function (s) {
                periods.forEach(function (p) {
                    var q = perf(rets[s[0]].slice(p[1], p[2]));
                    rows.push([T(s[1]), p[0] === "all" ? T("ra_eq_p_all") : splitLabel(p[0]), PK.spct(q.total, 1), PK.spct(q.cagr, 1), pct(q.vol, 1), num(q.sharpe, 2), num(q.sortino, 2), pct(q.maxdd, 1), pct(q.win, 1)]);
                });
            });
            host.appendChild(titled(T("ra_eq_stats"), PK.table([T("ra_eq_t_strat"), T("ra_eq_t_period"), T("ra_eq_t_total"), "CAGR", T("ra_eq_t_vol"), "Sharpe", "Sortino", T("ra_eq_t_maxdd"), T("ra_eq_t_win")], rows, { num: [2, 3, 4, 5, 6, 7, 8] })));
            var ex = d.stats.long_short.exposure, ex2 = d.stats.long_flat.exposure, chips = h("div", { class: "ra-chips" });
            chips.appendChild(PK.chip(T("ra_eq_c_exp", { l: pct(ex.share_long, 0), s: pct(ex.share_short, 0), t: num(ex.turnover_per_year, 1) })));
            chips.appendChild(PK.chip(T("ra_eq_c_exp_lf", { l: pct(ex2.share_long, 0), t: num(ex2.turnover_per_year, 1) })));
            if (d.dsr && isNum(d.dsr.dsr)) chips.appendChild(PK.chip(T("ra_eq_c_dsr", { d: pct(d.dsr.dsr, 0), n: int(d.n_trials) }), d.dsr.p_value < 0.1 ? "ok" : "warn"));
            host.appendChild(chips);
            host.appendChild(titled(T("ra_eq_months"), monthHeat(d.months), T("ra_eq_months_hint", { c: Math.round(d.cost_bps) })));
        }
        function monthHeat(months) {
            if (!months.length) return PK.empty(T("ra_reason_not_enough"));
            var years = Array.from(new Set(months.map(function (x) { return x.y; }))).sort(), map = {}, mx = 0;
            months.forEach(function (x) { map[x.y + "-" + x.m] = x.r; mx = Math.max(mx, Math.abs(x.r)); });
            var labels = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(function (k) { return T("ra_mo_" + k); });
            return PK.heat(years.map(String), labels, function (r, c) {
                var v = map[years[r] + "-" + (c + 1)];
                if (v === undefined) return { text: "" };
                return { text: PK.spct(v, 1), intensity: Math.abs(v) / (mx || 1), base: v >= 0 ? "var(--pos)" : "var(--neg)" };
            });
        }
    };

    // ---------------------------------------------------------------- erreurs
    var ERR_KEYS = ["fold", "year", "month", "weekday", "vol", "trend", "dd", "mom", "conf", "pup", "pred_class", "true_class"];
    RA.render.errors = function (m, d) {
        var keys = ERR_KEYS.filter(function (k) { return d.tables[k] && d.tables[k].length; }), cur = keys[0], host = h("div", {});
        m.appendChild(PK.select(keys.map(function (k) { return { value: k, label: T("ra_er_by_" + k) }; }), cur, function (v) { cur = v; draw(); }, T("ra_er_group")));
        m.appendChild(PK.note(T("ra_er_hint" + (d.has_regimes ? "" : "_noreg"))));
        m.appendChild(host);
        m.appendChild(row2(titled(T("ra_er_streaks"), PK.table([T("ra_er_s_from"), T("ra_er_s_to"), T("ra_er_s_len")], d.streaks.map(function (s) { return [s.start, s.end, s.length]; }), { num: [2] }), T("ra_er_streaks_hint")),
            titled(T("ra_er_months"), PK.table([T("ra_er_month"), T("ra_sc_t_n"), T("ra_m_acc")],
                d.worst_months.map(function (x) { return [x.ym, x.n, { cell: pct(x.acc, 0), cls: "neg" }]; }).concat(d.best_months.map(function (x) { return [x.ym, x.n, { cell: pct(x.acc, 0), cls: "pos" }]; })), { num: [1, 2] }), T("ra_er_months_hint"))));
        draw();
        function label(k, key) {
            if (k === "fold") { var p = String(key).split(":"); return (p[0] === "holdout" ? T("ra_pr_holdout") : T("ra_pr_fold", { n: p[1] })); }
            if (k === "month") return T("ra_mo_" + key);
            if (k === "weekday") return T("ra_wd_" + key);
            if (k === "vol" || k === "trend" || k === "dd" || k === "mom") return T("ra_rg_" + key);
            if (k === "pred_class" || k === "true_class") return T("ra_cls" + key);
            return String(key);
        }
        function miniBar(r) {
            var lo = 0.3, hi = 0.7, W = 150, x = function (v) { return (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * W; };
            var svg = PK.s("svg", { viewBox: "0 0 " + W + " 16", class: "ra-mini", width: W, height: 16, role: "img", "aria-label": pct(r.acc, 1) });
            svg.appendChild(PK.s("line", { x1: x(0.5), x2: x(0.5), y1: 0, y2: 16, stroke: "var(--text-3)", "stroke-dasharray": "2 2" }));
            svg.appendChild(PK.s("line", { x1: x(r.lo), x2: x(r.hi), y1: 8, y2: 8, stroke: "var(--text-2)", "stroke-width": 1.4 }));
            svg.appendChild(PK.s("circle", { cx: x(r.acc), cy: 8, r: 3.5, fill: r.acc > r.base ? "var(--pos)" : "var(--neg)" }));
            svg.appendChild(PK.s("rect", { x: x(r.base) - 1, y: 3, width: 2, height: 10, fill: "var(--warn)" }));
            return svg;
        }
        function draw() {
            PK.clear(host);
            var rows = d.tables[cur].map(function (r) {
                return [label(cur, r.key), int(r.n), pct(r.acc, 1), { cell: miniBar(r) }, pct(r.base, 1), { cell: PK.spct(r.edge, 1), cls: r.edge > 0 ? "pos" : "neg" }, num(r.f1_dir, 3), pct(r.share_pred_up, 0), pct(r.share_true_up, 0), PK.spct(r.ret_if_up, 2), PK.spct(r.ret_if_down, 2)];
            });
            host.appendChild(PK.table([T("ra_er_group"), T("ra_sc_t_n"), T("ra_m_acc"), T("ra_er_ci"), T("ra_er_base"), T("ra_er_edge"), T("ra_m_f1dir"), T("ra_m_predup"), T("ra_m_baseup"), T("ra_er_ret_up"), T("ra_er_ret_down")], rows, { num: [1, 2, 4, 5, 6, 7, 8, 9, 10] }));
            host.appendChild(PK.legend([{ color: "var(--pos)", label: T("ra_er_lg_above") }, { color: "var(--neg)", label: T("ra_er_lg_below") }, { color: "var(--warn)", label: T("ra_er_lg_base") }]));
        }
    };

    // ---------------------------------------------------------------- variables
    RA.render.features = function (m, d) {
        var famCol = {}, i = 0;
        d.families.forEach(function (f) { famCol[f.family] = PK.CAT_COLORS[i++ % 8]; });
        var chips = h("div", { class: "ra-chips" });
        if (d.stability && isNum(d.stability.mean_jaccard)) chips.appendChild(PK.chip(T("ra_fe_jaccard", { j: num(d.stability.mean_jaccard, 3), n: d.stability.n_folds }), d.stability.mean_jaccard >= 0.5 ? "ok" : "warn"));
        chips.appendChild(PK.chip(T("ra_fe_nfeat", { n: d.n_features })));
        m.appendChild(chips);
        var blocks = [];
        if (d.importance) blocks.push(titled(T("ra_fe_imp", { k: d.importance_kind }), hbars(d.importance.slice(0, 25).map(function (x) { return { label: x.feature, value: x.value, color: famCol[x.family] }; }), { fmt: function (v) { return pct(v, 1); } }), T("ra_fe_imp_hint")));
        if (d.selection && d.selection.length) blocks.push(titled(T("ra_fe_sel"), hbars(d.selection.slice(0, 25).map(function (x) { return { label: x.feature, value: x.freq, color: famCol[x.family] }; }), { fmt: function (v) { return pct(v, 0); }, max: 1 }), T("ra_fe_sel_hint", { n: d.n_selection })));
        if (blocks.length === 2) m.appendChild(row2(blocks[0], blocks[1])); else blocks.forEach(function (b) { m.appendChild(b); });
        if (d.families.length) {
            m.appendChild(titled(T("ra_fe_fam"), hbars(d.families.map(function (f) { return { label: T("ra_fam_" + f.family), value: f.share, color: famCol[f.family] }; }), { fmt: function (v) { return pct(v, 0); } }), T("ra_fe_fam_hint")));
        }
    };

    // ---------------------------------------------------------------- essais
    RA.render.trials = function (m, d) {
        var algos = Array.from(new Set(d.trials.map(function (t) { return t.algo; }))), col = {};
        algos.forEach(function (a, i) { col[a] = PK.CAT_COLORS[i % 8]; });
        var pts = d.trials.filter(function (t) { return isNum(t.f1_dir); });
        if (pts.length) {
            var xs = pts.map(function (t) { return t.n_features; }), ys = pts.map(function (t) { return t.f1_dir; });
            var xr = PK.extent([xs], 0.08), yr = PK.extent([ys, [0.5]], 0.1);
            var P = PK.plot({ w: 780, h: 280, x: { type: "linear", domain: xr, fmt: function (v) { return int(v); }, label: T("ra_tr_x") }, y: { domain: yr, fmt: function (v) { return num(v, 2); }, label: T("ra_tr_y") }, title: T("ra_tr_title") });
            PK.hline(P, 0.5, { color: "var(--text-3)" });
            pts.forEach(function (t) {
                var c = PK.hoverTip(P.add(PK.s("circle", { cx: P.X(t.n_features), cy: P.Y(t.f1_dir), r: t.is_best ? 6.5 : 4.2, fill: col[t.algo], "fill-opacity": 0.7, stroke: t.is_best ? "var(--text)" : col[t.algo], "stroke-width": t.is_best ? 2 : 1 })),
                    function () { return ["#" + t.trial_id + " · " + t.algo + " · " + t.sampler, T("ra_tr_t", { n: t.n_features, f: num(t.f1_dir, 4), a: num(t.acc_dir, 4), h: num(t.holdout_f1, 4) })]; });
                return c;
            });
            m.appendChild(P.node);
            m.appendChild(PK.legend(algos.map(function (a) { return { color: col[a], label: a }; })));
            m.appendChild(PK.note(T("ra_tr_hint")));
        }
        var rows = d.trials.map(function (t) { return [{ cell: "#" + t.trial_id + (t.is_best ? " ★" : ""), cls: t.is_best ? "pos" : "" }, t.algo, t.sampler, t.n_features, t.selector, t.regime, num(t.f1_dir, 4), num(t.acc_dir, 4), num(t.auc, 3), num(t.holdout_f1, 4)]; });
        m.appendChild(titled(T("ra_tr_table", { n: d.n_in_run }), PK.table(["#", "Algo", "Sampler", "N", T("ra_tr_selector"), T("ra_tr_regime"), "F1_dir", "Acc_dir", "AUC", "F1_dir " + T("ra_pr_holdout")], rows, { num: [3, 6, 7, 8, 9] })));
        if (d.registry && d.registry.length) {
            var ch = h("div", { class: "ra-chips" }, d.registry.map(function (r) { return PK.chip(r.source + " : " + int(r.n)); }));
            m.appendChild(titled(T("ra_tr_registry"), ch, T("ra_tr_registry_hint")));
        }
        if (d.screening && d.screening.length) {
            m.appendChild(titled(T("ra_tr_screen"), PK.table([T("ra_tr_regime"), "N", "Sampler", "Algo", T("ra_tr_score"), T("ra_tr_rank"), T("ra_tr_decision"), T("ra_tr_reason")],
                d.screening.map(function (c) { return [c.regime, c.n_features, c.sampler, c.algo, isNum(c.score) ? num(c.score, 4) : "—", c.rank === null ? "—" : c.rank, c.decision === "finalist" ? T("ra_tr_finalist") : T("ra_tr_dropped"), c.reason]; }), { num: [1, 4, 5] })));
        }
    };

    // ---------------------------------------------------------------- robustesse
    RA.render.robustness = function (m, d) {
        var pr = d.params, inputs = {}, host = h("div", {});
        var ctl = h("div", { class: "ra-controls" });
        [["n_perm", "ra_rb_nperm", pr.n_perm, 50, 2000], ["n_boot", "ra_rb_nboot", pr.n_boot, 50, 1000], ["block", "ra_rb_block", pr.block, 1, 250]].forEach(function (f) {
            inputs[f[0]] = h("input", { type: "number", class: "ra-num", min: f[3], max: f[4], value: f[2], "aria-label": T(f[1]) });
            ctl.appendChild(h("label", { class: "ra-control" }, [h("span", { text: T(f[1]) }), inputs[f[0]]]));
        });
        var go = h("button", { type: "button", class: "btn-secondary", text: T("ra_rb_run") });
        go.addEventListener("click", function () {
            host.classList.add("ra-busy");
            RA.api("robustness", { n_perm: inputs.n_perm.value, n_boot: inputs.n_boot.value, block: inputs.block.value }).then(function (nd) { host.classList.remove("ra-busy"); if (nd.available !== false) draw(nd); });
        });
        ctl.appendChild(go);
        m.appendChild(ctl);
        m.appendChild(PK.note(T("ra_rb_hint")));
        m.appendChild(host);
        draw(d);
        function nullChart(s) {
            var pn = s.perm_acc;
            if (!pn || !pn.null_hist) return PK.empty(T("ra_reason_not_enough"));
            var e = pn.null_hist.edges, c = pn.null_hist.counts, mids = e.slice(0, -1).map(function (v, i) { return (v + e[i + 1]) / 2; });
            var xr = PK.extent([mids, [pn.observed]], 0.08), ymax = Math.max.apply(null, c) * 1.1 || 1;
            var P = PK.plot({ w: 380, h: 240, x: { type: "linear", domain: xr, fmt: function (v) { return pct(v, 0); }, label: T("ra_rb_null_x") }, y: { domain: [0, ymax], fmt: int }, title: T("ra_rb_null") });
            PK.bars(P, mids, c, { color: "var(--text-3)", width: Math.max(2, (P.X(mids[1]) - P.X(mids[0])) * 0.9), opacity: 0.6 });
            PK.vline(P, pn.observed, { color: "var(--brand)", dash: "", width: 2, label: T("ra_rb_obs", { v: pct(pn.observed, 1) }) });
            PK.vline(P, s.chance, { color: "var(--text-2)", label: T("ra_rb_chance_l") });
            return P.node;
        }
        function forest(s) {
            var rows = [[T("ra_m_acc"), s.boot_acc], [T("ra_m_balacc"), s.boot_bal], ["AUC", s.boot_auc]].filter(function (r) { return r[1] && isNum(r[1].lo); });
            if (!rows.length) return PK.empty(T("ra_reason_not_enough"));
            var all = []; rows.forEach(function (r) { all.push(r[1].lo, r[1].hi, r[1].point); }); all.push(0.5);
            var xr = PK.extent([all], 0.1), H = 40 + rows.length * 38;
            var P = PK.plot({ w: 380, h: H, m: { l: 130 }, x: { type: "linear", domain: xr, fmt: function (v) { return num(v, 2); } }, y: { domain: [0, 1], ticks: [], zero: false }, title: T("ra_rb_boot") });
            PK.vline(P, 0.5, { color: "var(--text-3)" });
            rows.forEach(function (r, i) {
                var y = P.m.t + 20 + i * 38, b = r[1];
                P.add(PK.s("text", { x: P.m.l - 8, y: y + 4, "text-anchor": "end", class: "ra-axis", text: r[0] }));
                P.add(PK.s("line", { x1: P.X(b.lo), x2: P.X(b.hi), y1: y, y2: y, stroke: "var(--brand)", "stroke-width": 2 }));
                PK.hoverTip(P.add(PK.s("circle", { cx: P.X(b.point), cy: y, r: 4.5, fill: "var(--brand)" })), function () { return [r[0], num(b.point, 3) + " [" + num(b.lo, 3) + " ; " + num(b.hi, 3) + "]", T("ra_rb_boot_t", { n: b.n_boot, b: b.block })]; });
            });
            return P.node;
        }
        function shiftChart(s) {
            var sh = s.shift.filter(function (x) { return isNum(x.acc); });
            if (!sh.length) return PK.empty(T("ra_reason_not_enough"));
            var yr = PK.extent([sh.map(function (x) { return x.acc; }), [0.5, s.majority]], 0.15);
            var P = PK.plot({ w: 380, h: 240, x: { type: "linear", domain: [sh[0].lag - 0.5, sh[sh.length - 1].lag + 0.5], fmt: function (v) { return int(v); }, label: T("ra_rb_lag") }, y: { domain: yr, fmt: function (v) { return pct(v, 0); } }, title: T("ra_rb_shift") });
            PK.vline(P, 0, { color: "var(--text-3)" });
            PK.hline(P, s.majority, { color: "var(--warn)", dash: "5 4", label: T("ra_rb_maj") });
            PK.hline(P, 0.5, { color: "var(--text-3)" });
            PK.line(P, sh.map(function (x) { return x.lag; }), sh.map(function (x) { return x.acc; }), { color: "var(--brand)", width: 1.8 });
            PK.points(P, sh.map(function (x) { return x.lag; }), sh.map(function (x) { return x.acc; }), { r: 3, color: "var(--brand)", opacity: 0.9 });
            return P.node;
        }
        function draw(nd) {
            PK.clear(host);
            Object.keys(nd.samples).forEach(function (name) {
                var s = nd.samples[name], card = h("div", { class: "ra-subcard" });
                card.appendChild(h("h3", { text: splitLabel(name) + " · n=" + int(s.n) }));
                var g = h("div", { class: "metric-grid ra-kpis" });
                g.appendChild(PK.kpi(T("ra_m_acc"), pct(s.acc, 1), T("ra_rb_k_acc_sub", { maj: pct(s.majority, 1), ch: pct(s.chance, 1) }), s.acc > s.majority ? "ok" : "warning"));
                g.appendChild(PK.kpi(T("ra_rb_perm_p"), PK.pval(s.perm_acc.p_value), T("ra_rb_perm_sub", { n: s.perm_acc.n_perm, b: s.perm_acc.block }), isNum(s.perm_acc.p_value) && s.perm_acc.p_value < 0.05 ? "ok" : "warning"));
                g.appendChild(PK.kpi(T("ra_rb_perm_bal"), PK.pval(s.perm_bal.p_value), T("ra_rb_perm_bal_sub"), isNum(s.perm_bal.p_value) && s.perm_bal.p_value < 0.05 ? "ok" : "warning"));
                g.appendChild(PK.kpi(T("ra_rb_binom"), PK.pval(s.binom_p_blocks), T("ra_rb_binom_sub", { naive: PK.pval(s.binom_p_naive), h: nd.params.horizon }), isNum(s.binom_p_blocks) && s.binom_p_blocks < 0.05 ? "ok" : "warning"));
                card.appendChild(g);
                card.appendChild(h("div", { class: "ra-grid-3" }, [titled(T("ra_rb_null"), nullChart(s), T("ra_rb_null_hint")), titled(T("ra_rb_boot"), forest(s), T("ra_rb_boot_hint")), titled(T("ra_rb_shift"), shiftChart(s), T("ra_rb_shift_hint"))]));
                host.appendChild(card);
            });
            var st = nd.stability || {};
            if (st.leave_one_fold_out && st.leave_one_fold_out.length) {
                var items = st.leave_one_fold_out.map(function (x) { return { label: T("ra_rb_without", { n: x.fold }), value: x.acc }; });
                host.appendChild(titled(T("ra_rb_loo"), hbars(items, { fmt: function (v) { return pct(v, 1); }, max: 1 }), T("ra_rb_loo_hint", { v: pct(st.full_acc, 1) })));
            }
            if (st.halves && st.halves.length) host.appendChild(titled(T("ra_rb_halves"), PK.table([T("ra_rb_half"), T("ra_sc_t_n"), T("ra_m_acc"), T("ra_er_base")], st.halves.map(function (x) { return [T("ra_rb_half_" + x.half), int(x.n), pct(x.acc, 1), pct(x.majority, 1)]; }), { num: [1, 2, 3] })));
            if (st.years && st.years.length) {
                host.appendChild(titled(T("ra_rb_years"), PK.table([T("ra_er_by_year"), T("ra_sc_t_n"), T("ra_m_acc"), T("ra_er_base"), T("ra_er_edge")],
                    st.years.map(function (x) { return [x.year, int(x.n), pct(x.acc, 1), pct(x.majority, 1), { cell: PK.spct(x.acc - x.majority, 1), cls: x.acc > x.majority ? "pos" : "neg" }]; }), { num: [1, 2, 3, 4] }),
                    T("ra_rb_years_hint", { s: pct(st.share_years_beating, 0) })));
            }
            host.appendChild(PK.note(T("ra_rb_retrain")));
        }
    };

    // ---------------------------------------------------------------- holdout et live
    RA.render.holdout_live = function (m, d) {
        var t = d.compare.test, ho = d.compare.holdout, cols = [["test", t], ["holdout", ho]].filter(function (c) { return c[1]; });
        if (cols.length) {
            var rows = [["ra_m_n", "n", int], ["ra_m_acc", "acc", function (v) { return pct(v, 1); }], ["ra_m_balacc", "bal_acc", function (v) { return num(v, 3); }], ["ra_m_f1dir", "f1_dir", function (v) { return num(v, 3); }], ["ra_m_auc", "auc", function (v) { return num(v, 3); }], ["ra_m_baseup", "base_up", function (v) { return pct(v, 1); }], ["ra_m_predup", "share_pred_up", function (v) { return pct(v, 1); }]]
                .map(function (r) { return [T(r[0])].concat(cols.map(function (c) { return r[2](c[1][r[1]]); })); });
            m.appendChild(PK.table([""].concat(cols.map(function (c) { return splitLabel(c[0]); })), rows, { num: cols.map(function (_, i) { return i + 1; }) }));
        }
        if (isNum(d.acc_drop)) m.appendChild(h("div", { class: "ra-chips" }, [PK.chip(T("ra_hl_drop", { v: PK.spct(d.acc_drop, 1) }), d.acc_drop < -0.05 ? "warn" : "ok")]));
        var r = d.reads || {};
        m.appendChild(titled(T("ra_hl_reads"), h("div", { class: "ra-chips" }, [
            PK.chip(T("ra_hl_reads_total", { n: r.total || 0 }), r.total > 1 ? "warn" : "neutral"), PK.chip(T("ra_hl_reads_sel", { n: r.selecting || 0 }), r.selecting ? "warn" : "neutral"),
            PK.chip(T("ra_hl_reads_runs", { n: r.n_runs || 0 }))]), T("ra_hl_reads_hint")));
        if ((d.access || []).length) m.appendChild(PK.table([T("ra_hl_a_when"), T("ra_hl_a_purpose"), T("ra_hl_a_run"), T("ra_hl_a_window"), T("ra_hl_a_rows")],
            d.access.map(function (a) { return [a.accessed_at, a.purpose, a.run_id, a.holdout_start + " → " + a.holdout_end, int(a.n_rows)]; }), { num: [4] }));
        var lv = d.live;
        var head = h("div", { class: "ra-chips" }, [PK.chip(T("ra_hl_live_n", { n: lv.n, r: lv.resolved }))]);
        if (isNum(lv.hit_rate)) head.appendChild(PK.chip(T("ra_hl_live_hit", { h: pct(lv.hit_rate, 0), lo: pct(lv.lo, 0), hi: pct(lv.hi, 0) }), lv.hit_rate > 0.5 ? "ok" : "warn"));
        m.appendChild(titled(T("ra_hl_live"), head, T("ra_hl_live_hint")));
        if (lv.items.length) m.appendChild(PK.table([T("ra_hl_l_date"), T("ra_hl_l_pred"), "P(up)", T("ra_hl_l_real"), T("ra_hl_l_ok")],
            lv.items.slice().reverse().map(function (x) { return [x.t, T("ra_cls" + x.yp), isNum(x.p) ? num(x.p, 3) + (x.calibrated ? " ✓" : "") : "—", x.ut === null ? T("ra_hl_pending") : T(x.ut ? "ra_up" : "ra_down"), x.ok === null ? "" : { cell: x.ok ? "✓" : "✗", cls: x.ok ? "pos" : "neg" }]; }), { num: [2] }));
    };

    // ---------------------------------------------------------------- chemins CPCV
    RA.render.paths = function (m, d) {
        var metrics = d.metrics, cur = metrics.indexOf("F1_dir") >= 0 ? "F1_dir" : metrics[0], host = h("div", {});
        m.appendChild(PK.select(metrics.map(function (x) { return { value: x, label: x }; }), cur, function (v) { cur = v; draw(); }, T("ra_fo_metric")));
        m.appendChild(host);
        draw();
        function draw() {
            PK.clear(host);
            var s = d.summary[cur], vals = d.paths.map(function (p) { return p[cur]; }).filter(isNum);
            var X = vals.map(function (_, i) { return i + 1; }), yr = PK.extent([vals, [0.5]], 0.15);
            var P = PK.plot({ w: 780, h: 240, x: { type: "linear", domain: [0.4, vals.length + 0.6], ticks: vals.length > 30 ? undefined : X, fmt: function (v) { return int(v); }, label: T("ra_pa_x") }, y: { domain: yr, fmt: function (v) { return num(v, 3); } }, title: cur });
            if (s) { PK.yband(P, s.q05, s.q95, { color: "var(--brand-soft)" }); PK.hline(P, s.median, { color: "var(--brand)", dash: "", label: T("ra_pa_median", { v: num(s.median, 3) }) }); }
            PK.hline(P, 0.5, { color: "var(--text-3)" });
            PK.points(P, X, vals, { r: 3.5, color: "var(--brand)", opacity: 0.85 });
            host.appendChild(P.node);
            if (s) host.appendChild(PK.table([T("ra_pa_n"), T("ra_pa_mean"), T("ra_pa_std"), "q05", T("ra_pa_median_h"), "q95", "min", "max"], [[s.n, num(s.mean, 4), num(s.std, 4), num(s.q05, 4), num(s.median, 4), num(s.q95, 4), num(s.min, 4), num(s.max, 4)]], { num: [0, 1, 2, 3, 4, 5, 6, 7] }));
            host.appendChild(PK.note(T("ra_pa_note")));
        }
    };

    // ---------------------------------------------------------------- lecture guidée
    var PCT = { acc: 1, maj: 1, lo: 1, hi: 1, test: 1, holdout: 1, share: 1, base: 1, worst: 1, max_dd: 1, bh_dd: 1, ret: 1, bh_ret: 1, dsr: 1 }, SPCT = { edge: 1, drop: 1, spread: 1 };
    var NUM3 = { auc: 1, rho: 1, ece: 1, brier: 1, base_brier: 1, sharpe: 1, bh_sharpe: 1 };
    function fmtParams(p) {
        var o = {};
        Object.keys(p).forEach(function (k) {
            var v = p[k];
            if (v === null || v === undefined) { o[k] = "—"; return; }
            if (typeof v === "string") { o[k] = v; return; }
            if (k === "p") o[k] = PK.pval(v);
            else if (PCT[k]) o[k] = pct(v, 1);
            else if (SPCT[k]) o[k] = PK.spct(v, 1);
            else if (NUM3[k]) o[k] = num(v, 3);
            else o[k] = int(v);
        });
        return o;
    }
    RA.render.guide = function (m, d) {
        var ul = h("ul", { class: "ra-guide" });
        d.items.forEach(function (it) {
            var icon = it.level === "ok" ? "✓" : (it.level === "warn" ? "!" : "i");
            ul.appendChild(h("li", { class: "ra-guide-" + it.level }, [h("span", { class: "ra-guide-icon", "aria-hidden": "true", text: icon }), h("span", { text: it.key === "note" ? PK.noteText(it.params.text || "") : T("ra_g_" + it.key, fmtParams(it.params)) })]));
        });
        m.appendChild(ul);
        m.appendChild(PK.note(T("ra_g_disclaimer")));
    };
})();
