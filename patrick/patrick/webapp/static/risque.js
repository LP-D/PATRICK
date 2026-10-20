/* Page /risque : VaR et ES, valeur et baisses, contributions au risque, corrélations, scénarios de crise, chocs uniformes,
   simulation marche avant par règle d'allocation, attribution par ligne, écarts à une cible. Lecture seule.
   Données : /api/risque/sources, /api/risque/report, /api/risque/backtest, /api/risque/rebalance. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("rk-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, spct = PK.spct, int = PK.int, isNum = PK.isNum;
    var COLORS = ["var(--ra-c1)", "var(--ra-c2)", "var(--ra-c3)", "var(--ra-c4)", "var(--ra-c5)", "var(--ra-c6)", "var(--ra-c7)", "var(--ra-c8)"];
    var METHODS = ["equal", "inv_vol", "hrp", "current"];
    var st = { source: "real", lookback: 504, bt: { lookback: 252, rebalance: 21, cost: 10 }, gap: { method: "hrp", tol: 0.05, cost: 10 }, rule: "hrp", sources: [], report: null, bt_data: null };
    var seq = { report: 0, bt: 0, gap: 0 };

    function eur(v) { return isNum(v) ? int(v) + " €" : "—"; }
    function nearest(arr, v) {
        var lo = 0, hi = arr.length - 1;
        if (hi < 0) return -1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (arr[mid] < v) lo = mid; else hi = mid; }
        return Math.abs(arr[lo] - v) <= Math.abs(arr[hi] - v) ? lo : hi;
    }
    function box(id) { return PK.clear(document.getElementById(id)); }
    function loading(id) { box(id).appendChild(h("div", { class: "ra-skeleton", role: "status", "aria-label": T("rk_load") }, [h("div", { class: "skeleton-line", style: { width: "70%" } })])); }
    function fail(id, e) { box(id).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("rk_error") + " " + e.message })); }
    function done() { root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true })); }
    function methodLabel(m) { return T("rk_m_" + m); }

    function overlay(title, series, fmt, opts) {
        opts = opts || {};
        var xs = [].concat.apply([], series.map(function (s) { return s.x; })), lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs), pad = (hi - lo) * 0.01;
        var P = PK.plot({ w: 780, h: opts.h || 250, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: PK.extent(series.map(function (s) { return s.y; }), 0.06), fmt: fmt, zero: opts.zero !== false }, title: title });
        if (opts.base !== undefined) PK.hline(P, opts.base, { color: "var(--text-3)" });
        series.forEach(function (s) { PK.line(P, s.x, s.y, { color: s.color, width: s.width || 1.6, area: s.area, areaBase: s.areaBase }); });
        PK.hover(P, function (xv) {
            return [PK.dateStr(xv)].concat(series.map(function (s) { var k = nearest(s.x, xv); return k < 0 ? null : (s.label ? s.label + " " : "") + fmt(s.y[k]); }).filter(Boolean));
        });
        return P.node;
    }

    // ------------------------------------------------------------------------------------------ contrôles
    function controls() {
        var c = box("rk-controls");
        var opts = [{ value: "real", label: T("rk_src_real") }, { value: "fictive", label: T("rk_src_fictive") }].concat(st.sources.map(function (a) { return { value: a.account_id, label: a.name + " (" + a.kind + (a.mode === "fictive" ? ", fictif" : "") + ")" }; }));
        c.appendChild(PK.select(opts, st.source, function (v) { st.source = v; reload(); }, T("rk_f_source")));
        c.appendChild(PK.select([252, 504, 756, 1008, 0].map(function (n) { return { value: n, label: n ? T("rk_lb_n", { n: n }) : T("rk_lb_all") }; }), st.lookback, function (v) { st.lookback = +v; loadReport(); }, T("rk_f_lookback")));
    }
    function numInput(label, value, min, max, step, onChange) {
        var inp = h("input", { type: "number", class: "ra-num", value: value, min: min, max: max, step: step, style: { width: "90px" } });
        inp.addEventListener("change", function () { var v = parseFloat(inp.value); if (isFinite(v)) onChange(Math.max(min, Math.min(max, v))); });
        return h("label", { class: "ra-control" }, [h("span", { text: label }), inp]);
    }
    function btControls() {
        var c = box("rk-bt-controls");
        c.appendChild(numInput(T("rk_f_est"), st.bt.lookback, 60, 1000, 10, function (v) { st.bt.lookback = v; }));
        c.appendChild(numInput(T("rk_f_reb"), st.bt.rebalance, 1, 252, 1, function (v) { st.bt.rebalance = v; }));
        c.appendChild(numInput(T("rk_f_cost"), st.bt.cost, 0, 500, 1, function (v) { st.bt.cost = v; }));
        var b = h("button", { type: "button", class: "btn-secondary", text: T("rk_run") });
        b.addEventListener("click", loadBacktest);
        c.appendChild(b);
    }
    function gapControls() {
        var c = box("rk-gap-controls");
        c.appendChild(PK.select(METHODS.map(function (m) { return { value: m, label: methodLabel(m) }; }), st.gap.method, function (v) { st.gap.method = v; loadGaps(); }, T("rk_f_rule")));
        c.appendChild(numInput(T("rk_f_tol"), st.gap.tol * 100, 0, 50, 1, function (v) { st.gap.tol = v / 100; loadGaps(); }));
        c.appendChild(numInput(T("rk_f_cost"), st.gap.cost, 0, 500, 1, function (v) { st.gap.cost = v; loadGaps(); }));
    }

    // ----------------------------------------------------------------------------------------- rapport
    function excludedNote(list) {
        if (!list || !list.length) return null;
        return PK.info(T("rk_excluded") + " " + list.map(function (e) { return e.symbol + " (" + T("rk_ex_" + e.reason, { n: e.n }) + ")"; }).join(", "), "warn");
    }
    function renderReport(r) {
        st.report = r;
        var status = box("rk-status");
        ["rk-kpis", "rk-var", "rk-equity", "rk-contrib", "rk-corr", "rk-stress", "rk-shocks"].forEach(box);
        (r.warnings || []).forEach(function (w) { status.appendChild(PK.info(T("rk_warn_" + w), "warn")); });
        var ex = excludedNote(r.excluded);
        if (ex) status.appendChild(ex);
        if (!r.available) {
            status.appendChild(PK.empty(r.risky_share > 0 ? T("rk_unavailable") : T("rk_empty")));
            done();
            return;
        }
        var v95 = r.var.filter(function (x) { return x.level === 0.95 && x.horizon === 1; })[0] || {};
        var k = document.getElementById("rk-kpis");
        k.appendChild(PK.kpi(T("rk_k_total"), eur(r.total), null, "neutral"));
        k.appendChild(PK.kpi(T("rk_k_risky"), pct(r.risky_share, 0), T("rk_k_risky_sub"), "neutral"));
        k.appendChild(PK.kpi(T("rk_k_vol"), pct(r.volatility, 1), T("rk_k_vol_sub", { s: isNum(r.shrinkage) ? num(r.shrinkage, 2) : "—" }), "neutral"));
        k.appendChild(PK.kpi(T("rk_k_var"), pct(v95.hist, 2), T("rk_k_var_sub", { e: pct(v95.es_hist, 2) }), "neutral"));
        k.appendChild(PK.kpi(T("rk_k_dd"), pct(r.perf.max_dd, 1), T("rk_k_dd_sub", { n: r.n_days, a: r.start, b: r.end }), r.perf.max_dd < -0.3 ? "warning" : "neutral"));
        k.appendChild(PK.kpi(T("rk_k_cov"), pct(r.covered_weight, 0), T("rk_k_cov_sub"), r.covered_weight < r.risky_share - 1e-9 ? "warning" : "ok"));
        renderVar(r, v95);
        renderEquity(r);
        renderContrib(r);
        renderCorr(r);
        renderStress(r);
        renderShocks(r);
        done();
    }
    function renderVar(r, v95) {
        var rows = r.var.map(function (x) {
            var kp = x.kupiec;
            return [pct(x.level, 0), T("rk_days", { n: x.horizon }), { cell: pct(x.hist, 2), cls: "neg" }, pct(x.gauss, 2), pct(x.cf, 2), pct(x.es_hist, 2), pct(x.es_gauss, 2),
                kp && isNum(kp.breaches) ? int(kp.breaches) + " / " + num(kp.expected, 1) : "—", kp && isNum(kp.p) ? PK.pval(kp.p) : "—"];
        });
        var host = box("rk-var");
        host.appendChild(PK.table([T("rk_c_level"), T("rk_c_horizon"), T("rk_c_hist"), T("rk_c_gauss"), T("rk_c_cf"), T("rk_c_es_hist"), T("rk_c_es_gauss"), T("rk_c_kupiec"), T("rk_c_kp")], rows, { num: [2, 3, 4, 5, 6, 7, 8] }));
        host.appendChild(PK.info(T("rk_var_note", { n: int(v95.n), s: num(v95.skew, 2), k: num(v95.kurt, 2) })));
        host.appendChild(PK.note(T("rk_kupiec_hint")));
    }
    function renderEquity(r) {
        var xs = r.dates.map(PK.dateMs), host = box("rk-equity");
        var p = r.perf;
        host.appendChild(PK.info([T("rk_perf_total") + " " + spct(p.total, 1), T("rk_perf_cagr") + " " + spct(p.cagr, 1), T("rk_perf_vol") + " " + pct(p.vol, 1), T("rk_perf_sharpe") + " " + num(p.sharpe, 2), T("rk_perf_dd") + " " + pct(p.max_dd, 1)].join(" · ")));
        host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("rk_equity") }), overlay(T("rk_equity"), [{ x: xs, y: r.equity, color: "var(--ra-c1)", area: true, areaBase: 1 }], function (v) { return num(v, 2); }, { zero: false })]));
        host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("rk_drawdown") }), overlay(T("rk_drawdown"), [{ x: xs, y: r.drawdown, color: "var(--neg)", area: true }], function (v) { return pct(v, 0); }, { h: 190 })]));
        host.appendChild(h("h3", { text: T("rk_worst_days") }));
        host.appendChild(PK.table([T("rk_c_date"), T("rk_c_return")], r.worst_days.map(function (d) { return [d.date, { cell: spct(d.return, 2), cls: "neg" }]; }), { num: [1] }));
    }
    function renderContrib(r) {
        var host = box("rk-contrib"), mx = Math.max.apply(null, r.contributions.map(function (c) { return Math.max(c.share, c.weight / (r.covered_weight || 1)); }).concat([0.01]));
        host.appendChild(h("div", { class: "ra-hbars" }, r.contributions.map(function (c) {
            return h("div", { class: "ra-hbar" }, [h("span", { class: "ra-hbar-label", title: c.symbol, text: c.symbol }),
                h("span", { class: "ra-hbar-track", title: T("rk_c_share") + " " + pct(c.share, 1) }, [h("i", { style: { width: (c.share / mx * 100).toFixed(1) + "%", background: "var(--ra-c1)" } })]),
                h("span", { class: "ra-hbar-val pk-mono", text: pct(c.share, 0) })]);
        })));
        host.appendChild(PK.table([T("rk_c_symbol"), T("rk_c_weight"), T("rk_c_vol"), T("rk_c_share"), T("rk_c_contrib")],
            r.contributions.map(function (c) { return [c.symbol, pct(c.weight, 1), pct(c.vol, 1), pct(c.share, 1), pct(c.contribution, 2)]; }), { num: [1, 2, 3, 4] }));
    }
    function renderCorr(r) {
        var c = r.correlation, host = box("rk-corr");
        host.appendChild(PK.heat(c.symbols, c.symbols, function (i, j) {
            var v = c.values[i][j];
            return { text: num(v, 2), intensity: Math.abs(v), base: v < 0 ? "var(--ra-c2)" : "var(--ra-c1)", title: c.symbols[i] + " / " + c.symbols[j] };
        }));
    }
    function renderStress(r) {
        var rows = r.stress.map(function (w) {
            var worst = w.legs.length ? w.legs[0] : null;
            return [T("rk_w_" + w.key), w.start + " → " + w.end, pct(w.coverage, 0), w.sufficient ? { cell: spct(w.return_risky, 1), cls: "neg" } : { cell: T("rk_insufficient"), cls: "hint" },
                w.sufficient ? { cell: spct(w.return_total, 1), cls: "neg" } : "—", worst && w.sufficient ? worst.symbol + " " + spct(worst.return, 0) : "—"];
        });
        box("rk-stress").appendChild(PK.table([T("rk_c_window"), T("rk_c_period"), T("rk_c_cover"), T("rk_c_ret_risky"), T("rk_c_ret_total"), T("rk_c_worst")], rows, { num: [2, 3, 4] }));
    }
    function renderShocks(r) {
        box("rk-shocks").appendChild(PK.table([T("rk_c_shock"), T("rk_c_loss"), T("rk_c_amount")], r.shocks.map(function (s) { return [spct(s.shock, 0), { cell: spct(s.loss_total, 1), cls: "neg" }, eur(s.loss_total * r.total)]; }), { num: [0, 1, 2] }));
    }
    function loadReport() {
        var n = ++seq.report;
        box("rk-status"); box("rk-kpis");
        ["rk-var", "rk-equity", "rk-contrib", "rk-corr", "rk-stress", "rk-shocks"].forEach(loading);
        PK.fetchJSON("/api/risque/report?" + PK.qs({ source: st.source, lookback: st.lookback })).then(function (r) { if (n === seq.report) renderReport(r); })
            .catch(function (e) { if (n === seq.report) { ["rk-var", "rk-equity", "rk-contrib", "rk-corr", "rk-stress", "rk-shocks"].forEach(function (id) { fail(id, e); }); } });
    }

    // ------------------------------------------------------------------------------------ simulation
    function renderBacktest(d) {
        st.bt_data = d;
        var host = box("rk-bt");
        var ex = excludedNote(d.excluded);
        if (ex) host.appendChild(ex);
        if (!d.available) {
            host.appendChild(PK.empty(T("rk_bt_reason_" + (d.reason || "need_two_assets"), { n: d.n_common || 0 })));
            box("rk-attr");
            done();
            return;
        }
        var xs = d.dates.map(PK.dateMs);
        host.appendChild(PK.info(T("rk_bt_head", { a: d.start, b: d.end, n: int(d.n_days), s: d.limiting_asset, c: d.common_start })));
        var series = d.methods.map(function (m, i) { return { x: xs, y: m.equity, color: COLORS[i], label: methodLabel(m.method) }; });
        var dd = d.methods.map(function (m, i) { return { x: xs, y: m.drawdown, color: COLORS[i], label: methodLabel(m.method) }; });
        host.appendChild(PK.legend(d.methods.map(function (m, i) { return { color: COLORS[i], label: methodLabel(m.method), line: true }; })));
        host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("rk_bt_curves") }), overlay(T("rk_bt_curves"), series, function (v) { return num(v, 2); }, { zero: false })]));
        host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("rk_bt_dd") }), overlay(T("rk_bt_dd"), dd, function (v) { return pct(v, 0); }, { h: 190 })]));
        var best = Math.max.apply(null, d.methods.map(function (m) { return isNum(m.perf.sharpe) ? m.perf.sharpe : -Infinity; }));
        var rows = d.methods.map(function (m) {
            var ci = m.sharpe_ci;
            return [methodLabel(m.method), spct(m.perf.total, 1), spct(m.perf.cagr, 1), pct(m.perf.vol, 1), { cell: num(m.perf.sharpe, 2), cls: m.perf.sharpe === best ? "pos" : "" },
                isNum(ci.lo) ? "[" + num(ci.lo, 2) + " ; " + num(ci.hi, 2) + "]" : "—", { cell: pct(m.perf.max_dd, 1), cls: "neg" }, num(m.turnover_annual, 2) + " ×", pct(m.cost_annual, 2)];
        });
        host.appendChild(PK.table([T("rk_c_rule"), T("rk_c_total"), T("rk_c_cagr"), T("rk_perf_vol"), T("rk_c_sharpe"), T("rk_c_sharpe_ci"), T("rk_c_maxdd"), T("rk_c_turn"), T("rk_c_cost")], rows, { num: [1, 2, 3, 4, 5, 6, 7, 8] }));
        host.appendChild(PK.note(T("rk_bt_note")));
        renderAttribution(d);
        done();
    }
    function renderAttribution(d) {
        var host = box("rk-attr");
        var ruleSel = PK.select(d.methods.map(function (m) { return { value: m.method, label: methodLabel(m.method) }; }), st.rule, function (v) { st.rule = v; renderAttribution(d); }, T("rk_f_rule"));
        host.appendChild(h("div", { class: "ra-controls" }, [ruleSel]));
        var m = d.methods.filter(function (x) { return x.method === st.rule; })[0] || d.methods[0];
        var mx = Math.max.apply(null, m.attribution.map(function (a) { return Math.abs(a.contribution); }).concat([1e-9]));
        host.appendChild(h("div", { class: "ra-hbars" }, m.attribution.map(function (a) {
            return h("div", { class: "ra-hbar" }, [h("span", { class: "ra-hbar-label", title: a.symbol, text: a.symbol }),
                h("span", { class: "ra-hbar-track" }, [h("i", { style: { width: (Math.abs(a.contribution) / mx * 100).toFixed(1) + "%", background: a.contribution >= 0 ? "var(--pos)" : "var(--neg)" } })]),
                h("span", { class: "ra-hbar-val pk-mono", text: spct(a.contribution, 1) })]);
        })));
        var w = m.weights, wx = w.dates.map(PK.dateMs), lo = Math.min.apply(null, wx), hi = Math.max.apply(null, wx), pad = Math.max((hi - lo) * 0.01, 86400000);
        var P = PK.plot({ w: 780, h: 230, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: [0, Math.max(0.1, PK.extent(w.values, 0.05)[1])], fmt: function (v) { return pct(v, 0); } }, title: T("rk_weights_over_time") });
        w.symbols.forEach(function (s, j) { PK.line(P, wx, w.values.map(function (row) { return row[j]; }), { color: COLORS[j % COLORS.length], width: 1.5, step: true }); });
        PK.hover(P, function (xv) { var k = nearest(wx, xv); return k < 0 ? null : [w.dates[k]].concat(w.symbols.map(function (s, j) { return s + " " + pct(w.values[k][j], 1); })); });
        host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("rk_weights_over_time") }), PK.legend(w.symbols.map(function (s, j) { return { color: COLORS[j % COLORS.length], label: s, line: true }; })), P.node]));
        done();
    }
    function loadBacktest() {
        var n = ++seq.bt;
        loading("rk-bt"); box("rk-attr");
        PK.fetchJSON("/api/risque/backtest?" + PK.qs({ source: st.source, lookback: st.bt.lookback, rebalance: st.bt.rebalance, cost: st.bt.cost })).then(function (d) { if (n === seq.bt) renderBacktest(d); })
            .catch(function (e) { if (n === seq.bt) fail("rk-bt", e); });
    }

    // ------------------------------------------------------------------------------------------ écarts
    function renderGaps(d) {
        var host = box("rk-gaps");
        var ex = excludedNote(d.excluded);
        if (ex) host.appendChild(ex);
        if (!d.available) { host.appendChild(PK.empty(T("rk_bt_reason_" + (d.reason || "need_two_assets"), { n: 0 }))); done(); return; }
        var rows = d.rows.map(function (r) {
            return [r.symbol, pct(r.current, 1), pct(r.target, 1), { cell: (r.gap > 0 ? "+" : "") + num(r.gap * 100, 1) + " pts", cls: r.outside_band ? (r.gap > 0 ? "pos" : "neg") : "" }, { cell: eur(r.amount), cls: r.outside_band ? "" : "hint" }, r.outside_band ? PK.chip(T("rk_yes"), "warn") : T("rk_no")];
        });
        host.appendChild(PK.table([T("rk_c_symbol"), T("rk_c_current"), T("rk_c_target"), T("rk_c_gap"), T("rk_c_gap_amount"), T("rk_c_band")], rows, { num: [1, 2, 3, 4] }));
        host.appendChild(PK.info(T("rk_gaps_note", { t: eur(d.turnover_amount), b: num(d.cost_bps, 0), c: eur(d.cost_estimate), n: d.n_outside, d: d.as_of })));
        done();
    }
    function loadGaps() {
        var n = ++seq.gap;
        loading("rk-gaps");
        PK.fetchJSON("/api/risque/rebalance?" + PK.qs({ source: st.source, method: st.gap.method, tolerance: st.gap.tol, cost: st.gap.cost })).then(function (d) { if (n === seq.gap) renderGaps(d); })
            .catch(function (e) { if (n === seq.gap) fail("rk-gaps", e); });
    }

    function reload() { controls(); loadReport(); loadBacktest(); loadGaps(); }
    btControls(); gapControls();
    PK.fetchJSON("/api/risque/sources").then(function (s) { st.sources = s; controls(); }).catch(function () { /* la liste des comptes est facultative */ });
    reload();
})();
