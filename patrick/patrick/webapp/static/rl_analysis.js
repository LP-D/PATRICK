/* Page /runs/{id}/analyse pour un run de reinforcement learning : plis, équité de l'agent contre acheter-garder / momentum / à plat,
   drawdowns, positions, rendements, statistiques de comparaison, graines, variables. Chargement par `analysis_loader.js`. */
(function () {
    "use strict";
    var PK = window.PK, RA = window.RA;
    if (!PK || !RA) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var titled = RA.helpers.titled, row2 = RA.helpers.row2, nearestIdx = RA.helpers.nearestIdx;
    var SERIES = [["agent", "ra_rl_agent", "var(--brand)"], ["buy_hold", "ra_rl_bh", "var(--text-3)"], ["momentum", "ra_rl_mom", "var(--ra-c2)"], ["flat", "ra_rl_flat", "var(--ra-c8)"]];

    function bars(items, o) {
        var max = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1e-12]));
        return h("div", { class: "ra-hbars" }, items.map(function (it) {
            return h("div", { class: "ra-hbar" }, [h("span", { class: "ra-hbar-label", title: it.label, text: it.label }),
                h("span", { class: "ra-hbar-track" }, [h("i", { style: { width: (Math.max(0, it.value) / (o.max || max) * 100).toFixed(1) + "%", background: o.color || "var(--brand)" } })]),
                h("span", { class: "ra-hbar-val pk-mono", text: o.fmt(it.value) })]);
        }));
    }
    function perfRow(label, s) {
        if (!s) return null;
        return [label, PK.spct(s.total_return, 1), PK.spct(s.cagr, 1), pct(s.vol, 1), num(s.sharpe, 2), num(s.sortino, 2), pct(s.max_drawdown, 1), int(s.max_drawdown_days),
            isNum(s.turnover) ? num(s.turnover, 1) : "—", pct(s.exposure, 0), pct(s.hit_rate, 0), int(s.n_trades), isNum(s.cost_drag) ? pct(s.cost_drag, 1) : "—"];
    }
    var PERF_HEAD = ["ra_rl_t_name", "ra_eq_t_total", "CAGR", "ra_eq_t_vol", "Sharpe", "Sortino", "ra_eq_t_maxdd", "ra_rl_t_dddays", "ra_rl_t_turn", "ra_rl_t_expo", "ra_rl_t_hit", "ra_rl_t_trades", "ra_rl_t_cost"];

    // ---------------------------------------------------------------- aperçu
    RA.render.overview = function (m, d) {
        var s = d.strategy || {}, bh = (d.baselines || {}).buy_hold || {}, st = d.stats || {}, grid = h("div", { class: "metric-grid ra-kpis" });
        grid.appendChild(PK.kpi(T("ra_rl_k_total"), PK.spct(s.total_return, 1), T("ra_rl_k_total_sub", { bh: PK.spct(bh.total_return, 1) }), isNum(s.total_return) && s.total_return > (bh.total_return || 0) ? "ok" : "warning"));
        grid.appendChild(PK.kpi("Sharpe", num(s.sharpe, 2), T("ra_rl_k_sharpe_sub", { bh: num(bh.sharpe, 2) }), isNum(s.sharpe) && s.sharpe > (bh.sharpe || 0) ? "ok" : "warning"));
        grid.appendChild(PK.kpi(T("ra_eq_t_maxdd"), pct(s.max_drawdown, 1), T("ra_rl_k_dd_sub", { bh: pct(bh.max_drawdown, 1) }), "neutral"));
        var dsr = st.dsr || {};
        grid.appendChild(PK.kpi(T("ra_rl_k_dsr"), isNum(dsr.dsr) ? pct(dsr.dsr, 0) : "—", T("ra_rl_k_dsr_sub", { n: st.n_trials || "—", psr: isNum(st.psr) ? pct(st.psr, 0) : "—" }), isNum(dsr.p_value) && dsr.p_value < 0.1 ? "ok" : "warning"));
        var vb = st.vs_buy_hold || {};
        grid.appendChild(PK.kpi(T("ra_rl_k_vs_bh"), isNum(vb.diff) ? PK.signed(vb.diff, 2) : "—", isNum(vb.ci_low) ? T("ra_rl_k_vs_sub", { lo: PK.signed(vb.ci_low, 2), hi: PK.signed(vb.ci_high, 2), p: PK.pval(vb.p_one_sided) }) : T("ra_rl_k_vs_none"), isNum(vb.ci_low) && vb.ci_low > 0 ? "ok" : "warning"));
        grid.appendChild(PK.kpi(T("ra_rl_k_folds"), int(d.n_folds), T("ra_rl_k_folds_sub", { s: (d.seeds || []).length }), "neutral"));
        m.appendChild(grid);
        (d.warnings || []).forEach(function (w) { m.appendChild(h("p", { class: "banner banner-warning", role: "status", text: w })); });
        if (d.run && d.run.error) m.appendChild(h("p", { class: "banner banner-error", role: "alert", text: d.run.error }));
        var rows = [perfRow(T("ra_rl_agent"), s), perfRow(T("ra_rl_bh"), bh), perfRow(T("ra_rl_mom"), (d.baselines || {}).momentum), perfRow(T("ra_rl_flat"), (d.baselines || {}).flat)].filter(Boolean);
        m.appendChild(titled(T("ra_rl_perf"), PK.table(PERF_HEAD.map(function (k) { return k.indexOf("ra_") === 0 ? T(k) : k; }), rows, { num: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }), T("ra_rl_perf_hint")));
        var r = d.run || {}, ident = [[T("ra_id_target"), r.target], [T("ra_id_algo"), r.algo], [T("ra_id_period"), (d.period || []).join(" → ")], [T("ra_rl_rows"), int(d.n_rows)], [T("ra_rl_pool"), int(d.n_pool)],
            [T("ra_rl_elapsed"), isNum(d.elapsed_s) ? num(d.elapsed_s / 60, 1) + " min" : "—"], [T("ra_rl_started"), r.started_at]];
        var settings = d.settings || {};
        Object.keys(settings).forEach(function (k) { if (settings[k] !== null && settings[k] !== undefined) ident.push([k, String(settings[k])]); });
        m.appendChild(titled(T("ra_ov_identity"), h("dl", { class: "rp-grid ra-ident" }, ident.map(function (p) { return h("div", {}, [h("dt", { text: p[0] }), h("dd", { class: "pk-mono", text: p[1] === undefined || p[1] === null ? "—" : String(p[1]) })]); }))));
    };

    // ---------------------------------------------------------------- plis
    RA.render.folds = function (m, d) {
        var fs = d.folds, lo = PK.dateMs(d.range[0]), hi = PK.dateMs(d.range[1]), rowH = 28, H = 20 + fs.length * rowH + 28;
        var P = PK.plot({ w: 780, h: H, m: { l: 74, t: 10, b: 26, r: 12 }, x: { type: "time", domain: [lo - (hi - lo) * 0.01, hi + (hi - lo) * 0.01] }, y: { domain: [0, 1], ticks: [], zero: false }, title: T("ra_pr_title") });
        fs.forEach(function (f, i) {
            var top = P.m.t + i * rowH + 5, hh = rowH - 10;
            P.add(PK.s("text", { x: P.m.l - 8, y: top + hh / 2 + 4, "text-anchor": "end", class: "ra-axis", text: T("ra_pr_fold", { n: f.fold }) }));
            if (f.train_start && f.train_end) {
                var a = P.X(PK.dateMs(f.train_start)), b = P.X(PK.dateMs(f.train_end));
                PK.hoverTip(P.add(PK.s("rect", { x: a, y: top, width: Math.max(1, b - a), height: hh, fill: "var(--line-strong)", "fill-opacity": 0.45, rx: 2 })), function () { return [T("ra_pr_train"), f.train_start + " → " + f.train_end, T("ra_pr_ntrain", { n: int(f.n_train), eff: int(f.n_train) })]; });
            }
            var x0 = P.X(PK.dateMs(f.test_start)), x1 = P.X(PK.dateMs(f.test_end)), good = f.strategy && f.buy_hold && isNum(f.strategy.sharpe) && f.strategy.sharpe > f.buy_hold.sharpe;
            PK.hoverTip(P.add(PK.s("rect", { x: x0, y: top, width: Math.max(2, x1 - x0), height: hh, fill: good ? "var(--pos)" : "var(--neg)", "fill-opacity": 0.8, rx: 2 })),
                function () { return [T("ra_pr_fold", { n: f.fold }), f.test_start + " → " + f.test_end, T("ra_rl_f_t", { s: num((f.strategy || {}).sharpe, 2), b: num((f.buy_hold || {}).sharpe, 2) })]; });
        });
        m.appendChild(P.node);
        m.appendChild(PK.legend([{ color: "var(--line-strong)", label: T("ra_pr_train") }, { color: "var(--pos)", label: T("ra_rl_f_lg_win") }, { color: "var(--neg)", label: T("ra_rl_f_lg_lose") }]));
        var X = fs.map(function (f) { return f.fold; }), ag = fs.map(function (f) { return (f.strategy || {}).sharpe; }), bhv = fs.map(function (f) { return (f.buy_hold || {}).sharpe; });
        var yr = PK.extent([ag, bhv, [0]], 0.12);
        var B = PK.plot({ w: 780, h: 240, x: { type: "linear", domain: [Math.min.apply(null, X) - 0.7, Math.max.apply(null, X) + 0.7], ticks: X, fmt: function (v) { return T("ra_pr_fold", { n: v }); } }, y: { domain: yr, fmt: function (v) { return num(v, 1); } }, title: T("ra_rl_f_bars") });
        var w = Math.min(34, 280 / fs.length);
        PK.bars(B, X.map(function (x) { return x - 0.18; }), ag, { color: "var(--brand)", width: w, title: function (i) { return T("ra_rl_agent") + " " + num(ag[i], 2); } });
        PK.bars(B, X.map(function (x) { return x + 0.18; }), bhv, { color: "var(--text-3)", width: w, title: function (i) { return T("ra_rl_bh") + " " + num(bhv[i], 2); } });
        m.appendChild(titled(T("ra_rl_f_bars"), B.node, T("ra_rl_f_bars_hint", { w: d.wins_vs_buy_hold, n: d.n })));
        m.appendChild(PK.legend([{ color: "var(--brand)", label: T("ra_rl_agent") }, { color: "var(--text-3)", label: T("ra_rl_bh") }]));
        m.appendChild(PK.table([T("ra_pr_h_fold"), T("ra_pr_h_test"), T("ra_pr_h_ntrain"), T("ra_rl_n_test"), T("ra_rl_agent") + " · " + T("ra_eq_t_total"), T("ra_rl_agent") + " Sharpe", T("ra_eq_t_maxdd"), T("ra_rl_bh") + " · " + T("ra_eq_t_total"), T("ra_rl_bh") + " Sharpe", T("ra_rl_nfeat_fold")],
            fs.map(function (f) { var s = f.strategy || {}, b = f.buy_hold || {}; return [f.fold, f.test_start + " → " + f.test_end, int(f.n_train), int(f.n_test), PK.spct(s.total_return, 1), num(s.sharpe, 2), pct(s.max_drawdown, 1), PK.spct(b.total_return, 1), num(b.sharpe, 2), f.n_features]; }), { num: [0, 2, 3, 4, 5, 6, 7, 8, 9] }));
    };

    // ---------------------------------------------------------------- équité
    RA.render.equity = function (m, d) {
        var ms = d.dates.map(PK.dateMs), N = ms.length, lo = ms[0], hi = ms[N - 1], pad = (hi - lo) * 0.01, off = {}, logScale = true, host = h("div", {});
        m.appendChild(PK.segmented([{ value: "log", label: T("ra_eq_log") }, { value: "lin", label: T("ra_eq_lin") }], "log", function (v) { logScale = v === "log"; draw(); }));
        (d.notes || []).forEach(function (n) { m.appendChild(PK.info(PK.noteText(n))); });
        m.appendChild(host);
        draw();
        function marks(P) { (d.folds || []).forEach(function (f) { if (f.start) PK.vline(P, PK.dateMs(f.start), { color: "var(--line-strong)", dash: "2 3" }); }); }
        function draw() {
            PK.clear(host);
            var vis = SERIES.filter(function (s) { return d.curves[s[0]] && !off[s[0]]; });
            var yv = PK.extent(vis.map(function (s) { return d.curves[s[0]]; }), 0.06), raw = PK.extent(vis.map(function (s) { return d.curves[s[0]]; }), 0), useLog = logScale && raw[0] > 0;
            function tr(v) { return v === null ? null : (useLog ? Math.log(Math.max(v, 1e-6)) : v); }
            var lo2 = useLog ? Math.log(raw[0]) - 0.06 : yv[0], hi2 = useLog ? Math.log(raw[1]) + 0.06 : yv[1];
            var ticks = useLog ? [0.1, 0.25, 0.5, 1, 2, 4, 8, 16].filter(function (v) { return Math.log(v) >= lo2 && Math.log(v) <= hi2; }).map(Math.log) : undefined;
            var P = PK.plot({ w: 780, h: 300, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: [lo2, hi2], ticks: ticks, fmt: function (v) { return num(useLog ? Math.exp(v) : v, 2); }, zero: false }, title: T("ra_rl_eq_title") });
            marks(P);
            vis.forEach(function (s) { PK.line(P, ms, d.curves[s[0]].map(tr), { color: s[2], width: s[0] === "agent" ? 1.9 : 1.3, dash: s[0] === "agent" ? null : "4 3" }); });
            PK.hover(P, function (xv) { var i = nearestIdx(ms, xv); return i < 0 ? null : [d.dates[i]].concat(vis.map(function (s) { return T(s[1]) + " : " + num(d.curves[s[0]][i], 3); })); }, function (xv) { return ms[nearestIdx(ms, xv)]; });
            var leg = h("div", { class: "ra-legend" });
            SERIES.forEach(function (s) {
                if (!d.curves[s[0]]) return;
                var b = h("button", { type: "button", class: "ra-legend-item ra-legend-btn" + (off[s[0]] ? " off" : ""), "aria-pressed": String(!off[s[0]]) }, [h("i", { class: "ra-swatch ra-swatch-line", style: { background: s[2] } }), T(s[1])]);
                b.addEventListener("click", function () { off[s[0]] = !off[s[0]]; draw(); });
                leg.appendChild(b);
            });
            host.appendChild(titled(T("ra_rl_eq_h"), P.node, T("ra_rl_eq_hint")));
            host.appendChild(leg);
            var dd = PK.plot({ w: 780, h: 170, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: PK.extent(vis.map(function (s) { return d.drawdown[s[0]]; }).concat([[0]]), 0.05), fmt: function (v) { return pct(v, 0); } }, title: T("ra_eq_dd") });
            marks(dd);
            vis.forEach(function (s) { PK.line(dd, ms, d.drawdown[s[0]], { color: s[2], width: 1.3, area: s[0] === "agent", areaOpacity: 0.12 }); });
            host.appendChild(titled(T("ra_eq_dd"), dd.node));
            var rsKeys = ["agent", "buy_hold"].filter(function (k) { return d.rolling_sharpe[k] && !off[k]; });
            if (rsKeys.length) {
                var rs = PK.plot({ w: 780, h: 170, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: PK.extent(rsKeys.map(function (k) { return d.rolling_sharpe[k]; }), 0.1), fmt: function (v) { return num(v, 1); } }, title: T("ra_eq_rs") });
                marks(rs);
                rsKeys.forEach(function (k) { PK.line(rs, ms, d.rolling_sharpe[k], { color: SERIES.filter(function (s) { return s[0] === k; })[0][2], width: 1.3 }); });
                host.appendChild(titled(T("ra_eq_rs"), rs.node, T("ra_eq_rs_hint")));
            }
            var ps = PK.plot({ w: 780, h: 150, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: [-1.15, 1.15], ticks: [-1, 0, 1], fmt: function (v) { return num(v, 0); } }, title: T("ra_rl_pos") });
            marks(ps);
            PK.line(ps, ms, d.position, { color: "var(--brand)", width: 1.2, step: true, area: true, areaOpacity: 0.15 });
            host.appendChild(titled(T("ra_rl_pos"), ps.node, T("ra_rl_pos_hint")));
            var rows = SERIES.filter(function (s) { return d.stats[s[0]]; }).map(function (s) { return perfRow(T(s[1]), d.stats[s[0]]); });
            host.appendChild(titled(T("ra_eq_stats"), PK.table(PERF_HEAD.map(function (k) { return k.indexOf("ra_") === 0 ? T(k) : k; }), rows, { num: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }), T("ra_rl_stats_hint")));
            var ex = d.exposure;
            host.appendChild(h("div", { class: "ra-chips" }, [PK.chip(T("ra_rl_c_expo", { l: pct(ex.share_long, 0), s: pct(ex.share_short, 0), f: pct(ex.share_flat, 0) })), PK.chip(T("ra_rl_c_turn", { t: num(ex.turnover_per_year, 1), c: int(ex.n_changes) })),
                ex.mean_holding ? PK.chip(T("ra_rl_c_hold", { d: num(ex.mean_holding, 1) })) : null, PK.chip(T("ra_rl_c_cost", { c: pct(ex.cost_total, 1) }))]));
            host.appendChild(titled(T("ra_rl_months"), monthHeat(d.months), T("ra_rl_months_hint")));
        }
        function monthHeat(months) {
            if (!months.length) return PK.empty(T("ra_reason_not_enough"));
            var years = Array.from(new Set(months.map(function (x) { return x.y; }))).sort(), map = {}, mx = 0;
            months.forEach(function (x) { map[x.y + "-" + x.m] = x.r; mx = Math.max(mx, Math.abs(x.r)); });
            return PK.heat(years.map(String), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(function (k) { return T("ra_mo_" + k); }), function (r, c) {
                var v = map[years[r] + "-" + (c + 1)];
                return v === undefined ? { text: "" } : { text: PK.spct(v, 1), intensity: Math.abs(v) / (mx || 1), base: v >= 0 ? "var(--pos)" : "var(--neg)" };
            });
        }
    };

    // ---------------------------------------------------------------- rendements
    RA.render.returns = function (m, d) {
        var e = d.hist.edges, c = d.hist.counts, mids = e.slice(0, -1).map(function (v, i) { return (v + e[i + 1]) / 2; }), ymax = Math.max.apply(null, c) * 1.1 || 1;
        var P = PK.plot({ w: 780, h: 230, x: { type: "linear", domain: [e[0], e[e.length - 1]], fmt: function (v) { return PK.spct(v, 1); }, label: T("ra_rl_r_x") }, y: { domain: [0, ymax], fmt: int }, title: T("ra_rl_r_h") });
        PK.bars(P, mids, c, { color: function (_, i) { return mids[i] >= 0 ? "var(--pos)" : "var(--neg)"; }, width: Math.max(2, (P.X(mids[1]) - P.X(mids[0])) * 0.9) });
        PK.vline(P, 0, { color: "var(--text-3)", dash: "" });
        m.appendChild(titled(T("ra_rl_r_h"), P.node, T("ra_rl_r_hint", { c: PK.spct(d.clip, 1) })));
        m.appendChild(h("div", { class: "ra-chips" }, [PK.chip(T("ra_rl_r_mean", { v: PK.spct(d.mean, 3) })), PK.chip(T("ra_rl_r_std", { v: pct(d.std, 2) })), PK.chip(T("ra_rl_r_skew", { s: num(d.skew, 2), k: num(d.kurtosis, 1) })),
            PK.chip(T("ra_rl_r_ext", { w: pct(d.worst, 1), b: pct(d.best, 1) })), PK.chip(T("ra_rl_r_win", { p: pct(d.p_win, 0), n: int(d.n) }))]));
        if (d.position_after) {
            m.appendChild(titled(T("ra_rl_r_follow"), h("div", { class: "ra-chips" }, [PK.chip(T("ra_rl_r_after_up", { p: num(d.position_after.up_day, 2) })), PK.chip(T("ra_rl_r_after_down", { p: num(d.position_after.down_day, 2) })),
                PK.chip(T("ra_rl_r_corr", { c: num(d.corr_position_asset, 2) }))]), T("ra_rl_r_follow_hint")));
        }
    };

    // ---------------------------------------------------------------- statistiques
    RA.render.stats = function (m, d) {
        var st = d.stats || {}, rows = [];
        [["vs_buy_hold", "ra_rl_bh"], ["vs_momentum", "ra_rl_mom"]].forEach(function (p) {
            var s = st[p[0]];
            if (s) rows.push([T("ra_rl_s_vs", { b: T(p[1]) }), PK.signed(s.diff, 2), isNum(s.ci_low) ? "[" + PK.signed(s.ci_low, 2) + " ; " + PK.signed(s.ci_high, 2) + "]" : "—", PK.pval(s.p_one_sided), int(s.n), s.block]);
        });
        if (rows.length) m.appendChild(titled(T("ra_rl_s_boot"), PK.table([T("ra_rl_s_cmp"), T("ra_rl_s_diff"), T("ra_rl_s_ci"), T("ra_rl_s_p"), "n", T("ra_rb_block")], rows, { num: [1, 3, 4, 5] }), T("ra_rl_s_boot_hint")));
        var dsr = st.dsr || {}, grid = h("div", { class: "metric-grid ra-kpis" });
        grid.appendChild(PK.kpi("PSR", isNum(st.psr) ? pct(st.psr, 1) : "—", T("ra_rl_s_psr_sub"), isNum(st.psr) && st.psr > 0.95 ? "ok" : "warning"));
        grid.appendChild(PK.kpi(T("ra_rl_k_dsr"), isNum(dsr.dsr) ? pct(dsr.dsr, 1) : "—", T("ra_rl_s_dsr_sub", { n: dsr.n_trials === undefined ? "—" : dsr.n_trials, b: isNum(dsr.benchmark_sr) ? num(dsr.benchmark_sr, 4) : "0" }), isNum(dsr.p_value) && dsr.p_value < 0.1 ? "ok" : "warning"));
        grid.appendChild(PK.kpi(T("ra_rl_s_sr"), isNum(dsr.sr_annualized) ? num(dsr.sr_annualized, 2) : "—", T("ra_rl_s_sr_sub", { n: int(dsr.n_obs) }), "neutral"));
        grid.appendChild(PK.kpi(T("ra_rl_s_moments"), isNum(dsr.kurtosis) ? num(dsr.kurtosis, 1) : "—", T("ra_rl_s_moments_sub", { s: num(dsr.skew, 2) }), "neutral"));
        m.appendChild(grid);
        m.appendChild(PK.note(T("ra_rl_s_dsr_hint")));
        if ((d.seeds || []).length) {
            m.appendChild(titled(T("ra_rl_s_seeds"), PK.table([T("ra_id_seed"), "Sharpe", T("ra_eq_t_total"), T("ra_rl_s_ruined")], d.seeds.map(function (s) { return [s.seed, num(s.sharpe, 2), PK.spct(s.total_return, 1), s.ruined ? T("ra_rl_yes") : T("ra_rl_no")]; }), { num: [0, 1, 2] }), T("ra_rl_s_seeds_hint")));
        }
    };

    // ---------------------------------------------------------------- variables
    RA.render.features = function (m, d) {
        var famCol = {}, i = 0;
        d.families.forEach(function (f) { famCol[f.family] = PK.CAT_COLORS[i++ % 8]; });
        m.appendChild(h("div", { class: "ra-chips" }, [PK.chip(T("ra_rl_fe_pool", { n: int(d.pool) })), PK.chip(T("ra_rl_fe_used", { n: d.n, k: d.n_folds }))]));
        m.appendChild(row2(titled(T("ra_rl_fe_usage"), bars(d.usage.slice(0, 25).map(function (u) { return { label: u.feature, value: u.folds / (d.n_folds || 1) }; }), { fmt: function (v) { return pct(v, 0); }, max: 1 }), T("ra_rl_fe_usage_hint")),
            titled(T("ra_fe_fam"), bars(d.families.map(function (f) { return { label: T("ra_fam_" + f.family), value: f.share }; }), { fmt: function (v) { return pct(v, 0); } }), T("ra_fe_fam_hint"))));
    };
})();
