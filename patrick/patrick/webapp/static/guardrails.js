/* Page /garde-fous : budget d'exploration consommé, significativité déflatée par couple cible × horizon, registre des lectures du holdout.
   Données : /api/garde-fous/summary (patrick/analysis/guardrails.py). */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("ag-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var SRC_COLORS = { scan: "var(--ra-c1)", optuna: "var(--ra-c2)", simulation: "var(--ra-c3)", category: "var(--ra-c4)", backfill_scan: "var(--ra-c6)", backfill_optuna: "var(--ra-c7)", backfill_simulation: "var(--ra-c8)" };
    var st = { q: "", verdict: "", minTrials: 0, sortKey: "trials", sortDir: -1, page: 0, per: 60, rows: [] };

    function verdictChip(r) {
        if (!r.verdict) return "—";
        var kind = r.verdict === "beyond_noise" ? "ok" : (r.verdict === "suspect" ? "warn" : "neutral");
        return PK.chip(T("ag_v_" + r.verdict), kind);
    }
    function kpis(d) {
        var box = document.getElementById("ag-kpis");
        PK.clear(box);
        var src = d.registry.by_source, top = Object.keys(src).sort(function (a, b) { return src[b].trials - src[a].trials; }).slice(0, 3).map(function (k) { return k + " " + int(src[k].trials); }).join(" · ");
        box.appendChild(PK.kpi(T("ag_k_trials"), int(d.registry.total), top, "neutral"));
        box.appendChild(PK.kpi(T("ag_k_runs"), int(d.runs.done), T("ag_k_runs_sub", { c: int(d.runs.configs), p: int(d.registry.pairs), t: int(d.registry.targets) }), "neutral"));
        box.appendChild(PK.kpi(T("ag_k_reads"), int(d.reads.recorded + d.reads.inferred), T("ag_k_reads_sub", { r: int(d.reads.recorded), i: int(d.reads.inferred), d: int(d.reads.duels) }), d.reads.pairs_read_more_than_once ? "warning" : "neutral"));
        box.appendChild(PK.kpi(T("ag_k_beyond"), int(d.verdicts.beyond_noise) + " / " + int(d.verdicts.tested), T("ag_k_beyond_sub"), "neutral"));
        box.appendChild(PK.kpi(T("ag_k_fdr"), int(d.fdr.n_bh_significant) + " / " + int(d.fdr.n_tested), T("ag_k_fdr_sub", { a: pct(d.fdr.alpha, 0), r: int(d.fdr.n_raw_significant) }), "neutral"));
    }

    function budget(d) {
        var host = PK.clear(document.getElementById("ag-budget")), months = Object.keys(d.registry.monthly).sort();
        if (!months.length) { host.appendChild(PK.empty(T("ra_reason_not_enough"))); return; }
        var sources = Object.keys(d.registry.by_source);
        var cum = {}, run = 0, totals = months.map(function (m) { var s = 0; sources.forEach(function (k) { s += d.registry.monthly[m][k] || 0; }); run += s; return run; });
        var X = months.map(function (_, i) { return i + 1; }), P = PK.plot({ w: 780, h: 260, x: { type: "linear", domain: [0.4, months.length + 0.6], ticks: X.filter(function (i) { return months.length < 14 || i % Math.ceil(months.length / 12) === 0; }), fmt: function (v) { return months[v - 1] || ""; } }, y: { domain: [0, Math.max.apply(null, months.map(function (m) { var s = 0; sources.forEach(function (k) { s += d.registry.monthly[m][k] || 0; }); return s; })) * 1.1 || 1], fmt: int, label: T("ag_b_y") }, title: T("ag_s_budget") });
        sources.forEach(function () { /* empilement : dessiné mois par mois ci-dessous */ });
        months.forEach(function (m, i) {
            var base = 0, w = Math.min(34, (P.W - P.m.l - P.m.r) / months.length * 0.7);
            sources.forEach(function (k) {
                var v = d.registry.monthly[m][k] || 0;
                if (!v) return;
                var y1 = P.Y(base + v), y0 = P.Y(base);
                PK.hoverTip(P.add(PK.s("rect", { x: P.X(i + 1) - w / 2, y: y1, width: w, height: Math.max(1, y0 - y1), fill: SRC_COLORS[k] || "var(--ra-c5)", "fill-opacity": 0.85 })), function () { return [m + " · " + k, int(v) + " " + T("ag_b_trials")]; });
                base += v;
            });
        });
        host.appendChild(P.node);
        host.appendChild(PK.legend(sources.map(function (k) { return { color: SRC_COLORS[k] || "var(--ra-c5)", label: k + " (" + int(d.registry.by_source[k].trials) + ")" }; })));
        host.appendChild(PK.note(T("ag_b_hint", { n: int(totals[totals.length - 1]) })));
    }

    function scatter(d) {
        var host = PK.clear(document.getElementById("ag-scatter")), pts = d.rows.filter(function (r) { return isNum(r.best_acc) && r.trials > 0; });
        if (!pts.length) return;
        var lx = pts.map(function (r) { return Math.log10(Math.max(1, r.trials)); }), xr = [0, Math.max.apply(null, lx) + 0.15];
        var ys = pts.map(function (r) { return Math.min(r.best_acc, 0.85); });
        var yr = [0.4, Math.max(0.7, Math.max.apply(null, ys) + 0.03)];
        var P = PK.plot({ w: 780, h: 300, x: { type: "linear", domain: xr, ticks: [0, 1, 2, 3, 4, 5].filter(function (t) { return t <= xr[1]; }), fmt: function (v) { return int(Math.pow(10, v)); }, label: T("ag_sc_x") }, y: { domain: yr, fmt: function (v) { return pct(v, 0); }, label: T("ag_sc_y") }, title: T("ag_sc_title") });
        // meilleur résultat attendu sur du hasard pur, effectif 280 jours à l'horizon 1 (repère)
        var curveX = [], curveY = [];
        for (var i = 1; i <= 60; i++) { var lg = xr[1] * i / 60, n = Math.pow(10, lg), z = zInv(1 - 1 / Math.max(2, n)); curveX.push(lg); curveY.push(0.5 + z * 0.5 / Math.sqrt(280)); }
        PK.line(P, curveX, curveY, { color: "var(--warn)", dash: "5 4", width: 1.4 });
        PK.hline(P, 0.5, { color: "var(--text-3)" });
        pts.forEach(function (r) {
            var c = r.verdict === "beyond_noise" ? "var(--pos)" : (r.verdict === "suspect" ? "var(--warn)" : "var(--text-3)");
            PK.hoverTip(P.add(PK.s("circle", { cx: P.X(Math.log10(Math.max(1, r.trials))), cy: P.Y(Math.min(r.best_acc, 0.85)), r: 3.2, fill: c, "fill-opacity": 0.6 })), function () { return [r.target + " · h" + r.horizon, T("ag_sc_t", { n: int(r.trials), a: pct(r.best_acc, 1), pd: PK.pval(r.p_deflated) })]; });
        });
        host.appendChild(P.node);
        host.appendChild(PK.legend([{ color: "var(--pos)", label: T("ag_v_beyond_noise") }, { color: "var(--text-3)", label: T("ag_v_within_noise") }, { color: "var(--warn)", label: T("ag_v_suspect") }, { color: "var(--warn)", label: T("ag_sc_curve"), line: true }]));
        host.appendChild(PK.note(T("ag_sc_hint")));
    }
    function zInv(p) {            // inverse de la loi normale (Acklam), précision suffisante pour un repère graphique
        var a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239],
            b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572],
            c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783], d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
        var q, r;
        if (p < 0.02425) { q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
        if (p > 1 - 0.02425) { q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
        q = p - 0.5; r = q * q;
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
    }

    var COLS = [
        { key: "target", label: "ag_c_target", cell: function (r) { return h("a", { class: "ra-cell-link", href: "/targets/" + encodeURIComponent(r.target), text: r.target }); }, sort: function (r) { return r.target.toLowerCase(); } },
        { key: "horizon", label: "ag_c_horizon", num: true, cell: function (r) { return r.horizon === null ? "—" : String(r.horizon); }, sort: function (r) { return r.horizon; } },
        { key: "runs", label: "ag_c_runs", num: true, cell: function (r) { return int(r.runs); }, sort: function (r) { return r.runs; } },
        { key: "configs", label: "ag_c_configs", num: true, cell: function (r) { return int(r.configs); }, sort: function (r) { return r.configs; } },
        { key: "trials", label: "ag_c_trials", num: true, cell: function (r) { return int(r.trials); }, sort: function (r) { return r.trials; } },
        { key: "best_acc", label: "ag_c_best", num: true, cell: function (r) { return isNum(r.best_acc) ? pct(r.best_acc, 1) : "—"; }, sort: function (r) { return r.best_acc; } },
        { key: "null_best", label: "ag_c_null", num: true, cell: function (r) { return isNum(r.null_best) ? pct(r.null_best, 1) : "—"; }, sort: function (r) { return r.null_best; } },
        { key: "margin", label: "ag_c_margin", num: true, cell: function (r) { return isNum(r.margin) ? { nodeText: PK.spct(r.margin, 1) } : "—"; }, sort: function (r) { return r.margin; } },
        { key: "p", label: "ag_c_p", num: true, cell: function (r) { return isNum(r.p) ? PK.pval(r.p) : "—"; }, sort: function (r) { return r.p; } },
        { key: "p_deflated", label: "ag_c_pdef", num: true, cell: function (r) { return isNum(r.p_deflated) ? PK.pval(r.p_deflated) : "—"; }, sort: function (r) { return r.p_deflated; } },
        { key: "reads", label: "ag_c_reads", num: true, cell: function (r) { return r.reads_recorded + " / " + r.reads_inferred + " / " + r.duels; }, sort: function (r) { return r.reads_recorded + r.reads_inferred; } },
        { key: "verdict", label: "ag_c_verdict", cell: verdictChip, sort: function (r) { return r.verdict || ""; } },
    ];
    function filtered() {
        var q = st.q.trim().toLowerCase();
        return st.rows.filter(function (r) {
            if (q && r.target.toLowerCase().indexOf(q) < 0) return false;
            if (st.verdict && r.verdict !== st.verdict) return false;
            return r.trials >= st.minTrials;
        });
    }
    function filters() {
        var box = PK.clear(document.getElementById("ag-filters"));
        var s = h("input", { type: "search", placeholder: T("ag_filter_q"), "aria-label": T("ag_filter_q"), value: st.q });
        s.addEventListener("input", function () { st.q = s.value; st.page = 0; table(); });
        box.appendChild(s);
        box.appendChild(PK.select([{ value: "", label: T("ah_all_status") }, { value: "beyond_noise", label: T("ag_v_beyond_noise") }, { value: "within_noise", label: T("ag_v_within_noise") }, { value: "suspect", label: T("ag_v_suspect") }], st.verdict, function (v) { st.verdict = v; st.page = 0; table(); }, T("ag_c_verdict")));
        box.appendChild(PK.select([{ value: "0", label: T("ah_all_status") }, { value: "100", label: "≥ 100" }, { value: "500", label: "≥ 500" }, { value: "2000", label: "≥ 2 000" }], String(st.minTrials), function (v) { st.minTrials = +v; st.page = 0; table(); }, T("ag_c_trials")));
    }
    function table() {
        var host = document.getElementById("ag-table"), rows = filtered();
        var col = COLS.filter(function (c) { return c.key === st.sortKey; })[0] || COLS[4];
        rows.sort(function (a, b) {
            var x = col.sort(a), y = col.sort(b), nx = x === null || x === undefined || (typeof x === "number" && !isFinite(x)), ny = y === null || y === undefined || (typeof y === "number" && !isFinite(y));
            if (nx && ny) return 0; if (nx) return 1; if (ny) return -1;
            return (x < y ? -1 : (x > y ? 1 : 0)) * st.sortDir;
        });
        var pages = Math.max(1, Math.ceil(rows.length / st.per)); st.page = Math.min(st.page, pages - 1);
        var slice = rows.slice(st.page * st.per, (st.page + 1) * st.per);
        var thead = h("tr", {}, COLS.map(function (c) {
            var th = h("th", { scope: "col", class: c.num ? "num pk-mono" : "", text: T(c.label), tabindex: "0", "aria-sort": c.key === st.sortKey ? (st.sortDir > 0 ? "ascending" : "descending") : "none" });
            function by() { if (st.sortKey === c.key) st.sortDir = -st.sortDir; else { st.sortKey = c.key; st.sortDir = c.num ? -1 : 1; } table(); }
            th.addEventListener("click", by); th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); by(); } });
            return th;
        }));
        var tbody = h("tbody", {}, slice.map(function (r) {
            return h("tr", {}, COLS.map(function (c) {
                var td = h("td", { class: c.num ? "num pk-mono" : "" }), v = c.cell(r);
                if (v && v.nodeType) td.appendChild(v); else if (v && v.nodeText !== undefined) { td.textContent = v.nodeText; td.classList.add(r.margin > 0 ? "pos" : "neg"); } else td.textContent = v;
                return td;
            }));
        }));
        PK.clear(host).appendChild(h("div", { class: "table-scroll" }, [h("table", { class: "data-table ra-sortable" }, [h("thead", {}, [thead]), tbody])]));
        host.appendChild(PK.info(T("ag_rows", { n: int(rows.length), total: int(st.rows.length) })));
        host.appendChild(PK.note(T("ag_t_hint")));
        var pager = PK.clear(document.getElementById("ag-pager"));
        if (pages > 1) {
            var prev = h("button", { type: "button", class: "btn-secondary", text: T("ah_prev") }), next = h("button", { type: "button", class: "btn-secondary", text: T("ah_next") });
            prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
            prev.addEventListener("click", function () { st.page--; table(); }); next.addEventListener("click", function () { st.page++; table(); });
            pager.appendChild(prev); pager.appendChild(h("span", { class: "pk-mono", text: (st.page + 1) + " / " + pages })); pager.appendChild(next);
        }
        host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }

    function holdout(d) {
        var host = PK.clear(document.getElementById("ag-holdout")), r = d.reads;
        host.appendChild(h("div", { class: "ra-chips" }, [PK.chip(T("ag_h_c_recorded", { n: int(r.recorded) }), r.recorded > 1 ? "warn" : "neutral"), PK.chip(T("ag_h_c_inferred", { n: int(r.inferred) }), "neutral"), PK.chip(T("ag_h_c_duels", { n: int(r.duels) }), r.duels ? "warn" : "neutral"),
            PK.chip(T("ag_h_c_pairs", { n: int(r.pairs_read_more_than_once) }), r.pairs_read_more_than_once ? "warn" : "neutral")]));
        host.appendChild(PK.note(r.first_at ? T("ag_h_since", { d: r.first_at }) : T("ag_h_empty")));
        if (r.pairs_read_more_than_once) host.appendChild(h("p", { class: "banner banner-warning", role: "note", text: T("ag_h_warn", { n: int(r.pairs_read_more_than_once) }) }));
        if (!d.log.length) { host.appendChild(PK.empty(T("ag_h_nolog"))); return; }
        host.appendChild(PK.table([T("ra_hl_a_when"), T("ag_c_target"), T("ag_c_horizon"), T("ra_hl_a_purpose"), T("ra_hl_a_run"), T("ra_hl_a_window"), T("ra_hl_a_rows")],
            d.log.map(function (x) { return [x.accessed_at, x.target, x.horizon, { cell: x.purpose, cls: x.purpose.indexOf("duel") >= 0 ? "neg" : "" }, x.run_id || "—", (x.holdout_start || "") + " → " + (x.holdout_end || ""), int(x.n_rows)]; }), { num: [2, 6] }));
    }

    PK.fetchJSON("/api/garde-fous/summary").then(function (d) {
        st.rows = d.rows;
        kpis(d); budget(d); scatter(d); filters(); table(); holdout(d);
        root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }).catch(function (e) {
        PK.clear(document.getElementById("ag-budget")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message }));
    });
})();
