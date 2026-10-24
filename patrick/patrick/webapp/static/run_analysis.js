/* Page /runs/{id}/analyse (run ML / DL) : rendus des sections prédit-contre-réel (graphiques SVG de `analysis_kit.js`), le chargement
   étant fait par `analysis_loader.js`. Suite des rendus : `run_analysis_more.js`. */
(function () {
    "use strict";
    var PK = window.PK, RA = window.RA;
    if (!PK || !RA) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var splitLabel = RA.helpers.splitLabel, stateFor = RA.helpers.stateFor, majority = RA.helpers.majority, foldBands = RA.helpers.foldBands;
    var row2 = RA.helpers.row2, titled = RA.helpers.titled, nearestIdx = RA.helpers.nearestIdx;

    // ---------------------------------------------------------------- aperçu
    RA.render.overview = function (m, d) {
        var hd = d.headline || {}, t = hd.test, ho = hd.holdout, lv = hd.live;
        var grid = h("div", { class: "metric-grid ra-kpis" });
        function accTile(label, s) {
            if (!s || s.acc === null) return null;
            var maj = majority(s.base_up), edge = maj === null ? null : s.acc - maj;
            return PK.kpi(label, pct(s.acc), T("ra_k_acc_sub", { lo: pct(s.acc_lo, 1), hi: pct(s.acc_hi, 1), maj: pct(maj, 1), n: int(s.n) }),
                s.acc_lo !== null && maj !== null && s.acc_lo > maj ? "ok" : stateFor(edge));
        }
        grid.appendChild(accTile(T("ra_k_acc_test"), t));
        grid.appendChild(accTile(T("ra_k_acc_holdout"), ho));
        if (t) {
            grid.appendChild(PK.kpi(T("ra_k_auc"), num(t.auc, 3), T("ra_k_auc_sub"), isNum(t.auc) ? (t.auc >= 0.55 ? "ok" : (t.auc < 0.52 ? "warning" : "neutral")) : "disabled"));
            grid.appendChild(PK.kpi(T("ra_k_f1dir"), num(t.f1_dir, 3), T("ra_k_f1dir_sub"), "neutral"));
            grid.appendChild(PK.kpi(T("ra_k_balacc"), num(t.bal_acc, 3), T("ra_k_balacc_sub"), "neutral"));
            grid.appendChild(PK.kpi(T("ra_k_mcc"), num(t.mcc, 3), T("ra_k_mcc_sub"), isNum(t.mcc) && t.mcc > 0.05 ? "ok" : "neutral"));
            grid.appendChild(PK.kpi(T("ra_k_brier"), num(t.brier, 4), T("ra_k_brier_sub", { base: num(t.base_up * (1 - t.base_up), 4) }), isNum(t.brier) && t.brier < t.base_up * (1 - t.base_up) ? "ok" : "warning"));
            grid.appendChild(PK.kpi(T("ra_k_predup"), pct(t.share_pred_up, 0), T("ra_k_predup_sub", { base: pct(t.base_up, 0) }), isNum(t.share_pred_up) && (t.share_pred_up > 0.7 || t.share_pred_up < 0.3) ? "warning" : "neutral"));
        }
        m.appendChild(grid);
        (d.notes || []).forEach(function (n) { m.appendChild(h("p", { class: "banner banner-info", role: "status", text: PK.noteText(n) })); });

        var cols = [["test", t], ["holdout", ho], ["live", lv]].filter(function (c) { return c[1]; });
        var metrics = [["n", "ra_m_n", int], ["acc", "ra_m_acc", function (v) { return pct(v, 1); }], ["bal_acc", "ra_m_balacc", function (v) { return num(v, 3); }],
            ["f1_dir", "ra_m_f1dir", function (v) { return num(v, 3); }], ["mcc", "ra_m_mcc", function (v) { return num(v, 3); }], ["auc", "ra_m_auc", function (v) { return num(v, 3); }],
            ["brier", "ra_m_brier", function (v) { return num(v, 4); }], ["precision", "ra_m_prec", function (v) { return pct(v, 1); }], ["recall", "ra_m_rec", function (v) { return pct(v, 1); }],
            ["base_up", "ra_m_baseup", function (v) { return pct(v, 1); }], ["share_pred_up", "ra_m_predup", function (v) { return pct(v, 1); }]];
        var rows = metrics.map(function (mm) { return [T(mm[1])].concat(cols.map(function (c) { return mm[2](c[1][mm[0]]); })); });
        var sp = d.splits || {};
        m.appendChild(titled(T("ra_ov_numbers"), PK.table([""].concat(cols.map(function (c) { return splitLabel(c[0]); })), rows, { num: cols.map(function (c, i) { return i + 1; }) })));

        var tr = d.trial || {}, run = d.run || {};
        var ident = [
            [T("ra_id_target"), PK.inst(run.target) + " · " + T("ra_id_horizon", { h: run.horizon })], [T("ra_id_algo"), tr.algo], [T("ra_id_sampler"), tr.sampler],
            [T("ra_id_nfeat"), tr.n_features], [T("ra_id_selector"), tr.selector], [T("ra_id_regime"), tr.regime + (tr.category ? " · " + tr.category : "")],
            [T("ra_id_trial"), "#" + tr.trial_id], [T("ra_id_scheme"), d.scheme === "cpcv" ? "CPCV" : "walk-forward"],
            [T("ra_id_period"), (sp.test ? sp.test.start + " → " : "") + (sp.holdout ? sp.holdout.end : (sp.test ? sp.test.end : "—"))],
            [T("ra_id_snapshot"), run.snapshot_id], [T("ra_id_config"), run.config_hash], [T("ra_id_git"), run.git_sha ? String(run.git_sha).slice(0, 10) : "—"],
            [T("ra_id_seed"), run.seed], [T("ra_id_trials"), T("ra_id_trials_v", { run: run.n_trials, cum: int(d.cumulative_trials) })],
            [T("ra_id_holdout_reads"), d.holdout_reads && d.holdout_reads.total ? T("ra_id_reads_v", { n: d.holdout_reads.total, sel: d.holdout_reads.selecting }) : T("ra_id_none")],
        ];
        var dl = h("dl", { class: "rp-grid ra-ident" }, ident.map(function (p) { return h("div", {}, [h("dt", { text: p[0] }), h("dd", { class: "pk-mono", text: p[1] === undefined || p[1] === null ? "—" : String(p[1]) })]); }));
        m.appendChild(titled(T("ra_ov_identity"), dl));
        if ((d.siblings || []).length) {
            var sib = h("div", { class: "ra-chips" }, d.siblings.map(function (s) {
                return h("a", { class: "exp-chip-btn", href: "/runs/" + encodeURIComponent(s.run_id) + "/analyse", text: (s.name || s.run_id) + " · " + (s.started_at || "").slice(0, 10) });
            }));
            m.appendChild(titled(T("ra_ov_siblings"), sib, T("ra_ov_siblings_hint")));
        }
    };

    // ---------------------------------------------------------------- protocole
    RA.render.protocol = function (m, d) {
        var folds = d.folds, cfg = d.config || {};
        var lo = PK.dateMs(d.range[0]), hi = PK.dateMs(d.range[1]), rowH = 28, n = folds.length, H = 20 + n * rowH + 28;
        var P = PK.plot({ w: 780, h: H, m: { l: 74, t: 10, b: 26, r: 12 }, x: { type: "time", domain: [lo - (hi - lo) * 0.01, hi + (hi - lo) * 0.01] }, y: { domain: [0, 1], ticks: [], zero: false }, title: T("ra_pr_title") });
        folds.forEach(function (f, i) {
            var top = P.m.t + i * rowH + 5, hh = rowH - 10, isH = f.split === "holdout";
            P.add(PK.s("text", { x: P.m.l - 8, y: top + hh / 2 + 4, "text-anchor": "end", class: "ra-axis", text: isH ? T("ra_pr_holdout") : T("ra_pr_fold", { n: f.fold }) }));
            if (f.train_start && f.train_end && f.train_end > f.train_start) {
                var a = P.X(PK.dateMs(f.train_start)), b = P.X(PK.dateMs(f.train_end));
                PK.hoverTip(P.add(PK.s("rect", { x: a, y: top, width: Math.max(1, b - a), height: hh, fill: "var(--line-strong)", "fill-opacity": 0.45, rx: 2 })),
                    function () { return [T("ra_pr_train"), f.train_start + " → " + f.train_end + " (" + T("ra_pr_estimated") + ")", f.n_train ? T("ra_pr_ntrain", { n: int(f.n_train), eff: int(f.effective_n_train) }) : ""]; });
            }
            var x0 = P.X(PK.dateMs(f.test_start)), x1 = P.X(PK.dateMs(f.test_end));
            var r = PK.hoverTip(P.add(PK.s("rect", { x: x0, y: top, width: Math.max(2, x1 - x0), height: hh, fill: isH ? "var(--warn)" : "var(--brand)", "fill-opacity": 0.9, rx: 2 })),
                function () { return [isH ? T("ra_pr_holdout") : T("ra_pr_fold", { n: f.fold }), f.test_start + " → " + f.test_end, T("ra_pr_npred", { n: int(f.n_pred) })]; });
            if (r && x1 - x0 > 60) P.add(PK.s("text", { x: (x0 + x1) / 2, y: top + hh / 2 + 4, "text-anchor": "middle", class: "ra-axis ra-on-bar", text: int(f.n_pred) }));
        });
        m.appendChild(P.node);
        m.appendChild(PK.legend([{ color: "var(--line-strong)", label: T("ra_pr_train") }, { color: "var(--brand)", label: T("ra_pr_test") }, { color: "var(--warn)", label: T("ra_pr_holdout") }]));
        var chips = h("div", { class: "ra-chips" });
        [["ra_pr_c_scheme", d.scheme === "cpcv" ? "CPCV" : "walk-forward"], ["ra_pr_c_folds", cfg.n_wf_folds], ["ra_pr_c_minfrac", cfg.min_train_frac], ["ra_pr_c_purge", cfg.purge ? T("ra_on") + " (" + cfg.purge_bars + ")" : T("ra_off")],
            ["ra_pr_c_embargo", cfg.embargo_enabled ? T("ra_on") + (cfg.embargo_bars ? " (" + cfg.embargo_bars + ")" : "") : T("ra_off")], ["ra_pr_c_holdout", cfg.holdout_months ? cfg.holdout_months + " " + T("ra_months") : "—"],
            ["ra_pr_c_horizon", cfg.horizon], ["ra_pr_c_mintrain", cfg.min_train_rows], ["ra_pr_c_mintest", cfg.min_test_rows]].forEach(function (c) {
            if (c[1] !== undefined && c[1] !== null) chips.appendChild(PK.chip(T(c[0]) + " : " + c[1]));
        });
        if (d.cpcv) chips.appendChild(PK.chip(T("ra_pr_c_cpcv", { g: d.cpcv.n_groups, k: d.cpcv.k_test_groups, p: d.cpcv.n_paths })));
        m.appendChild(chips);
        var rows = folds.map(function (f) {
            return [f.split === "holdout" ? T("ra_pr_holdout") : T("ra_pr_fold", { n: f.fold }), (f.train_start || "—") + " → " + (f.train_end || "—"), f.test_start + " → " + f.test_end, int(f.n_pred), f.n_train ? int(f.n_train) : "—", f.effective_n_train ? int(f.effective_n_train) : "—"];
        });
        m.appendChild(PK.table([T("ra_pr_h_fold"), T("ra_pr_h_train"), T("ra_pr_h_test"), T("ra_pr_h_npred"), T("ra_pr_h_ntrain"), T("ra_pr_h_neff")], rows, { num: [3, 4, 5] }));
        m.appendChild(PK.note(T("ra_pr_note")));
    };

    // ---------------------------------------------------------------- prédit contre réel dans le temps
    var tl = { start: null, end: null, base: null };
    RA.render.timeline = function (m, d) {
        tl.base = tl.base || { range: d.range, folds: d.folds };
        var controls = h("div", { class: "ra-controls" });
        var body = h("div", { class: "ra-tl-body" });
        function request(start, end) {
            tl.start = start; tl.end = end;
            body.classList.add("ra-busy");
            RA.api("timeline", { start: start, end: end }).then(function (nd) { drawBody(nd); body.classList.remove("ra-busy"); }).catch(function (e) { body.classList.remove("ra-busy"); PK.clear(body).appendChild(PK.empty(e.message)); });
        }
        var foldBtns = [{ value: "all", label: T("ra_tl_all") }].concat(tl.base.folds.map(function (f, i) { return { value: String(i), label: f.split === "holdout" ? T("ra_pr_holdout") : T("ra_pr_fold", { n: f.fold }) }; }));
        controls.appendChild(PK.segmented(foldBtns, tl.start ? "" : "all", function (v) {
            if (v === "all") request(null, null);
            else { var f = tl.base.folds[+v]; request(f.start, f.end); }
        }));
        var inFrom = h("input", { type: "date", class: "ra-date", "aria-label": T("ra_tl_from"), value: d.window[0] });
        var inTo = h("input", { type: "date", class: "ra-date", "aria-label": T("ra_tl_to"), value: d.window[1] });
        var go = h("button", { type: "button", class: "btn-secondary", text: T("ra_tl_apply") });
        go.addEventListener("click", function () { request(inFrom.value || null, inTo.value || null); });
        controls.appendChild(h("span", { class: "ra-inline" }, [inFrom, "→", inTo, go]));
        m.appendChild(controls);
        m.appendChild(PK.note(T("ra_tl_hint")));
        m.appendChild(body);
        drawBody(d);

        function drawBody(nd) {
            PK.clear(body);
            if (nd.available === false) { body.appendChild(PK.empty(T("ra_reason_" + (nd.reason || "unknown")))); return; }
            inFrom.value = nd.window[0]; inTo.value = nd.window[1];
            var pts = nd.points, days = nd.mode === "days", W = 780, laneH = 14, lanes = 3, mb = 30 + lanes * (laneH + 3);
            var withPrice = !!(nd.price && nd.price.t.length > 1), H = (withPrice ? 250 : 40) + mb;
            var lo = PK.dateMs(nd.window[0]), hi = PK.dateMs(nd.window[1]);
            if (hi <= lo) hi = lo + 864e5;
            var pad = (hi - lo) * 0.01;
            var py = withPrice ? PK.extent([nd.price.v], 0.05) : [0, 1];
            var P = PK.plot({ w: W, h: H, m: { l: 60, t: 10, b: mb, r: 12 }, x: { type: "time", domain: [lo - pad, hi + pad], axisY: H - 7 }, y: { domain: py, ticks: withPrice ? undefined : [], fmt: function (v) { return num(v, Math.abs(v) >= 100 ? 0 : 2); }, zero: false }, title: T("ra_tl_title") });
            nd.folds.forEach(function (f, i) {
                if (f.split === "holdout") PK.xband(P, PK.dateMs(f.start), PK.dateMs(f.end), { color: "var(--warn-soft)" });
                else if (i % 2 === 0) PK.xband(P, PK.dateMs(f.start), PK.dateMs(f.end), { color: "var(--neutral-soft)" });
            });
            if (withPrice) PK.line(P, nd.price.t.map(PK.dateMs), nd.price.v, { color: "var(--text-2)", width: 1.3 });
            var laneTop = H - mb + 6;
            ["ra_tl_lane_pred", "ra_tl_lane_true", "ra_tl_lane_ok"].forEach(function (k, i) {
                P.add(PK.s("text", { x: P.m.l - 6, y: laneTop + i * (laneH + 3) + laneH - 3, "text-anchor": "end", class: "ra-axis", text: T(k) }));
            });
            function shareColor(sv) {
                var p = Math.round(25 + 75 * Math.min(1, Math.abs(2 * sv - 1)));
                return "color-mix(in srgb, " + (sv >= 0.5 ? "var(--pos)" : "var(--neg)") + " " + p + "%, transparent)";
            }
            var xs = pts.map(function (p) { return PK.dateMs(days ? p.t : p.t0); });
            var plotW = W - P.m.l - P.m.r;
            pts.forEach(function (p, i) {
                var x0 = P.X(xs[i]), x1 = i + 1 < pts.length ? P.X(xs[i + 1]) : P.X(PK.dateMs(days ? p.t : p.t1)) + (days ? plotW / pts.length : 2);
                var w = days ? Math.max(1.2, plotW / pts.length) : Math.max(1, x1 - x0), x = days ? x0 - w / 2 : x0;
                var c1, c2, c3;
                if (days) { c1 = PK.CLASS_COLORS[p.yp]; c2 = p.yt === null ? (p.ut ? PK.CLASS_COLORS[3] : PK.CLASS_COLORS[0]) : PK.CLASS_COLORS[p.yt]; c3 = p.ok ? "var(--pos)" : "var(--neg)"; }
                else { c1 = shareColor(p.up_pred); c2 = shareColor(p.up_true); c3 = shareColor(p.acc); }
                [c1, c2, c3].forEach(function (c, k) { P.add(PK.s("rect", { x: x.toFixed(1), y: laneTop + k * (laneH + 3), width: w.toFixed(1), height: laneH, fill: c })); });
                if (days && withPrice && pts.length <= 260) {
                    var lvIdx = nearestIdx(nd.price.t.map(PK.dateMs), xs[i]);
                    P.add(PK.s("circle", { cx: P.X(xs[i]).toFixed(1), cy: P.Y(nd.price.v[lvIdx]).toFixed(1), r: 2.6, fill: p.ok ? "var(--pos)" : "var(--neg)" }));
                }
            });
            PK.hover(P, function (xv) {
                var i = nearestIdx(xs, xv);
                if (i < 0) return null;
                var p = pts[i];
                if (days) return [p.t + " · " + T("ra_split_" + p.split), T("ra_tl_t_pred", { c: T("ra_cls" + p.yp), p: isNum(p.p) ? num(p.p, 3) : "—" }), T("ra_tl_t_true", { c: p.yt === null ? T(p.ut ? "ra_up" : "ra_down") : T("ra_cls" + p.yt), r: isNum(p.ret) ? PK.spct(p.ret, 2) : "—" }), p.ok ? T("ra_tl_t_ok") : T("ra_tl_t_ko")];
                return [p.t0 + " → " + p.t1 + " (" + T("ra_tl_t_n", { n: p.n }) + ")", T("ra_tl_t_bin", { pred: pct(p.up_pred, 0), real: pct(p.up_true, 0), acc: pct(p.acc, 0) })];
            }, function (xv) { var i = nearestIdx(xs, xv); return i < 0 ? xv : xs[i]; });
            PK.brush(P, function (a, b) { request(PK.dateStr(a), PK.dateStr(b)); });
            body.appendChild(P.node);
            body.appendChild(PK.legend(days
                ? [{ color: PK.CLASS_COLORS[0], label: T("ra_cls0") }, { color: PK.CLASS_COLORS[1], label: T("ra_cls1") }, { color: PK.CLASS_COLORS[2], label: T("ra_cls2") }, { color: PK.CLASS_COLORS[3], label: T("ra_cls3") }, { color: "var(--neutral-soft)", label: T("ra_lg_fold_band") }, { color: "var(--warn-soft)", label: T("ra_lg_holdout_band") }]
                : [{ color: "var(--pos)", label: T("ra_tl_lg_up") }, { color: "var(--neg)", label: T("ra_tl_lg_down") }, { color: "var(--neutral-soft)", label: T("ra_lg_fold_band") }, { color: "var(--warn-soft)", label: T("ra_lg_holdout_band") }]));
            body.appendChild(PK.note(T(days ? "ra_tl_mode_days" : "ra_tl_mode_bins", { n: int(nd.n) }) + (nd.is_alpha ? " " + T("ra_tl_alpha") : "")));
        }
    };

    // ---------------------------------------------------------------- taux de réussite glissant
    RA.render.rolling = function (m, d) {
        var box = h("div", {});
        m.appendChild(PK.segmented([60, 120, 250, 500].map(function (w) { return { value: w, label: T("ra_ro_window", { n: w }) }; }), d.window, function (w) {
            box.classList.add("ra-busy");
            RA.api("rolling", { window: w }).then(function (nd) { draw(nd); box.classList.remove("ra-busy"); });
        }));
        m.appendChild(box);
        draw(d);
        function draw(nd) {
            PK.clear(box);
            if (nd.available === false) { box.appendChild(PK.empty(T("ra_reason_" + (nd.reason || "unknown")))); return; }
            var xs = nd.t.map(PK.dateMs), lo = xs[0], hi = xs[xs.length - 1], pad = (hi - lo) * 0.01;
            var yr = PK.extent([nd.lo, nd.hi, nd.base, [0.5]], 0.05);
            var P = PK.plot({ w: 780, h: 250, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: yr, fmt: function (v) { return pct(v, 0); }, zero: false }, title: T("ra_ro_title") });
            foldBands(P, nd.folds);
            PK.band(P, xs, nd.lo, nd.hi, { color: "var(--brand)", opacity: 0.18 });
            PK.hline(P, 0.5, { color: "var(--text-3)", label: "50 %" });
            PK.line(P, xs, nd.base, { color: "var(--warn)", dash: "5 4", width: 1.3 });
            PK.line(P, xs, nd.acc, { color: "var(--brand)", width: 1.8 });
            PK.hover(P, function (xv) {
                var i = nearestIdx(xs, xv);
                return i < 0 ? null : [nd.t[i], T("ra_ro_t", { acc: pct(nd.acc[i], 1), lo: pct(nd.lo[i], 1), hi: pct(nd.hi[i], 1), base: pct(nd.base[i], 1) })];
            }, function (xv) { return xs[nearestIdx(xs, xv)]; });
            box.appendChild(P.node);
            box.appendChild(PK.legend([{ color: "var(--brand)", label: T("ra_ro_lg_acc"), line: true }, { color: "var(--warn)", label: T("ra_ro_lg_base"), line: true }, { color: "var(--brand-soft)", label: T("ra_ro_lg_ci") }]));
            var ey = PK.extent([nd.cum_edge, nd.cum_flip], 0.08);
            var Q = PK.plot({ w: 780, h: 200, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: ey, fmt: function (v) { return int(v); } }, title: T("ra_ro_cum_title") });
            foldBands(Q, nd.folds);
            PK.line(Q, xs, nd.cum_edge, { color: "var(--pos)", width: 1.7 });
            PK.line(Q, xs, nd.cum_flip, { color: "var(--text-3)", width: 1.3, dash: "4 4" });
            PK.hover(Q, function (xv) { var i = nearestIdx(xs, xv); return i < 0 ? null : [nd.t[i], T("ra_ro_cum_t", { e: num(nd.cum_edge[i], 1), f: num(nd.cum_flip[i], 1) })]; }, function (xv) { return xs[nearestIdx(xs, xv)]; });
            box.appendChild(titled(T("ra_ro_cum_h"), Q.node, T("ra_ro_cum_hint", { m: pct(nd.majority_global, 1) })));
            box.appendChild(PK.legend([{ color: "var(--pos)", label: T("ra_ro_cum_lg_edge"), line: true }, { color: "var(--text-3)", label: T("ra_ro_cum_lg_flip"), line: true }]));
            var chips = h("div", { class: "ra-chips" });
            chips.appendChild(PK.chip(T("ra_ro_c_below", { p: pct(nd.share_below_half, 0) }), nd.share_below_half > 0.3 ? "warn" : "neutral"));
            if (nd.worst && nd.worst.at) chips.appendChild(PK.chip(T("ra_ro_c_worst", { a: pct(nd.worst.acc, 1), d: nd.worst.at })));
            if (nd.best && nd.best.at) chips.appendChild(PK.chip(T("ra_ro_c_best", { a: pct(nd.best.acc, 1), d: nd.best.at })));
            box.appendChild(chips);
        }
    };

    // ---------------------------------------------------------------- nuage P(hausse) × rendement
    RA.render.scatter = function (m, d) {
        var ic = d.ic || {}, grid = h("div", { class: "metric-grid ra-kpis" });
        grid.appendChild(PK.kpi(T("ra_sc_ic"), isNum(ic.rho) ? num(ic.rho, 3) : "—", T("ra_sc_ic_sub", { p: PK.pval(ic.p), n: int(ic.n) }), isNum(ic.p) && ic.p < 0.05 && ic.rho > 0 ? "ok" : "neutral"));
        grid.appendChild(PK.kpi(T("ra_sc_spread"), isNum(d.spread_top_bottom) ? PK.spct(d.spread_top_bottom, 2) : "—", T("ra_sc_spread_sub", { h: d.horizon }), isNum(d.spread_top_bottom) && d.spread_top_bottom > 0 ? "ok" : "warning"));
        ["test", "holdout"].forEach(function (k) { var s = (d.ic_by_split || {})[k]; if (s) grid.appendChild(PK.kpi(T("ra_sc_ic_split", { s: splitLabel(k) }), isNum(s.rho) ? num(s.rho, 3) : "—", T("ra_sc_ic_sub", { p: PK.pval(s.p), n: int(s.n) }), isNum(s.p) && s.p < 0.05 && s.rho > 0 ? "ok" : "neutral")); });
        m.appendChild(grid);
        var pts = d.points, ry = [-d.clip * 1.05, d.clip * 1.05];
        var P = PK.plot({ w: 520, h: 300, x: { type: "linear", domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_sc_x") }, y: { domain: ry, fmt: function (v) { return PK.spct(v, 0); }, label: T("ra_sc_y", { h: d.horizon }) }, title: T("ra_sc_title") });
        PK.vline(P, 0.5, { color: "var(--text-3)" });
        PK.points(P, pts.p, pts.ret, { color: function (i) { return pts.split[i] === "holdout" ? "var(--warn)" : "var(--brand)"; }, r: 2.1, opacity: 0.5 });
        var dec = d.deciles, X = dec.map(function (_, i) { return i + 1; });
        var yr = PK.extent([dec.map(function (q) { return q.mean_ret + (q.sem || 0); }), dec.map(function (q) { return q.mean_ret - (q.sem || 0); })], 0.15);
        var B = PK.plot({ w: 520, h: 300, x: { type: "linear", domain: [0.4, dec.length + 0.6], ticks: X, fmt: function (v) { return "D" + v; }, label: T("ra_sc_deciles_x") }, y: { domain: yr, fmt: function (v) { return PK.spct(v, 2); }, label: T("ra_sc_deciles_y") }, title: T("ra_sc_deciles_title") });
        PK.bars(B, X, dec.map(function (q) { return q.mean_ret; }), { title: function (i) { return "D" + (i + 1) + " · " + PK.spct(dec[i].mean_ret, 3) + " · n=" + dec[i].n; } });
        dec.forEach(function (q, i) { if (isNum(q.sem)) B.add(PK.s("line", { x1: B.X(i + 1), x2: B.X(i + 1), y1: B.Y(q.mean_ret - q.sem), y2: B.Y(q.mean_ret + q.sem), stroke: "var(--text-2)", "stroke-width": 1.2 })); });
        m.appendChild(row2(titled(T("ra_sc_h"), P.node, T("ra_sc_hint")), titled(T("ra_sc_deciles_h"), B.node, T("ra_sc_deciles_hint"))));
        m.appendChild(PK.legend([{ color: "var(--brand)", label: splitLabel("test") }, { color: "var(--warn)", label: splitLabel("holdout") }]));
        m.appendChild(PK.table([T("ra_sc_t_dec"), T("ra_sc_t_prange"), T("ra_sc_t_n"), T("ra_sc_t_mean"), T("ra_sc_t_median"), T("ra_sc_t_up")],
            dec.map(function (q, i) { return ["D" + (i + 1), num(q.p_lo, 2) + " – " + num(q.p_hi, 2), int(q.n), PK.spct(q.mean_ret, 3), PK.spct(q.median_ret, 3), pct(q.share_up, 1)]; }), { num: [2, 3, 4, 5] }));
        var f = (d.ic_by_fold || []);
        if (f.length) m.appendChild(titled(T("ra_sc_ic_folds"), PK.table([T("ra_pr_h_fold"), T("ra_sc_ic"), T("ra_sc_t_n")], f.map(function (x) { return [x.split === "holdout" ? T("ra_pr_holdout") : T("ra_pr_fold", { n: x.fold }), isNum(x.rho) ? num(x.rho, 3) : "—", int(x.n)]; }), { num: [1, 2] })));
        if (d.is_alpha) m.appendChild(PK.note(T("ra_tl_alpha")));
    };

    // ---------------------------------------------------------------- matrices de confusion
    RA.render.confusion = function (m, d) {
        var names = Object.keys(d.splits);
        var norm = "row", host = h("div", {});
        m.appendChild(PK.segmented([{ value: "row", label: T("ra_cf_row") }, { value: "col", label: T("ra_cf_col") }, { value: "n", label: T("ra_cf_count") }], norm, function (v) { norm = v; draw(); }));
        m.appendChild(host);
        draw();
        function cm4(sp) {
            var labels = [0, 1, 2, 3].map(function (c) { return T("ra_cls" + c); });
            var mat = sp.cm, rowSum = mat.map(function (r) { return r.reduce(function (a, b) { return a + b; }, 0); });
            var maxN = Math.max.apply(null, [].concat.apply([], mat));
            return PK.heat(labels, labels, function (r, c) {
                var v = mat[r][c], rn = sp.cm_row[r][c], cn = sp.cm_col[r][c];
                var shown = norm === "row" ? pct(rn, 0) : (norm === "col" ? pct(cn, 0) : int(v));
                var inten = norm === "row" ? rn : (norm === "col" ? cn : v / (maxN || 1));
                return { text: shown, intensity: inten, base: r === c ? "var(--pos)" : "var(--neg)", cls: r === c ? "ra-diag" : "", title: T("ra_cf_cell", { n: v, r: pct(rn, 1), c: pct(cn, 1), tc: labels[r], pc: labels[c] }) };
            }, { corner: T("ra_cf_corner") });
        }
        function bin2(sp) {
            var lab = [T("ra_down"), T("ra_up")], b = sp.bin_cm, tot = b[0][0] + b[0][1] + b[1][0] + b[1][1];
            return PK.heat(lab, lab, function (r, c) {
                var rs = b[r][0] + b[r][1], v = b[r][c];
                return { text: int(v) + " (" + pct(rs ? v / rs : null, 0) + ")", intensity: tot ? v / tot * 2 : 0, base: r === c ? "var(--pos)" : "var(--neg)", cls: r === c ? "ra-diag" : "" };
            }, { corner: T("ra_cf_corner") });
        }
        function draw() {
            PK.clear(host);
            names.forEach(function (name) {
                var sp = d.splits[name], b = sp.binary, card = h("div", { class: "ra-subcard" });
                card.appendChild(h("h3", { text: splitLabel(name) + " · n=" + int(sp.n) }));
                card.appendChild(titled(T("ra_cf_4"), cm4(sp)));
                card.appendChild(row2(titled(T("ra_cf_class"), PK.table([T("ra_cf_class"), T("ra_m_prec"), T("ra_m_rec"), "F1", T("ra_cf_support"), T("ra_cf_predicted")],
                    sp.classes.map(function (c) { return [T("ra_cls" + c["class"]), pct(c.precision, 1), pct(c.recall, 1), num(c.f1, 3), int(c.support), int(c.predicted)]; }), { num: [1, 2, 3, 4, 5] })), titled(T("ra_cf_2"), bin2(sp))));
                var chips = h("div", { class: "ra-chips" });
                chips.appendChild(PK.chip("AUC " + num(sp.roc.auc, 3) + (sp.auc_ci && sp.auc_ci.lo !== null ? " [" + num(sp.auc_ci.lo, 3) + " ; " + num(sp.auc_ci.hi, 3) + "]" : "")));
                chips.appendChild(PK.chip(T("ra_cf_ap", { v: num(sp.pr.ap, 3), b: pct(sp.pr.base_rate, 1) })));
                chips.appendChild(PK.chip(T("ra_cf_mcc", { v: num(b.mcc, 3) })));
                card.appendChild(chips);
                var R = PK.plot({ w: 380, h: 300, x: { type: "linear", domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_cf_fpr") }, y: { domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_cf_tpr") }, title: "ROC" });
                R.add(PK.s("line", { x1: R.X(0), y1: R.Y(0), x2: R.X(1), y2: R.Y(1), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
                PK.line(R, sp.roc.fpr, sp.roc.tpr, { color: "var(--brand)", width: 1.8, area: true });
                var Q = PK.plot({ w: 380, h: 300, x: { type: "linear", domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_cf_recall") }, y: { domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_cf_precision") }, title: "PR" });
                if (isNum(sp.pr.base_rate)) PK.hline(Q, sp.pr.base_rate, { color: "var(--text-3)", label: T("ra_cf_base") });
                PK.line(Q, sp.pr.recall, sp.pr.precision, { color: "var(--pos)", width: 1.8 });
                card.appendChild(row2(titled("ROC", R.node), titled(T("ra_cf_pr"), Q.node)));
                host.appendChild(card);
            });
            host.appendChild(titled(T("ra_cf_byfold"), foldTable(d.by_fold), T("ra_cf_byfold_hint")));
        }
        function foldTable(rows) {
            return PK.table([T("ra_pr_h_fold"), T("ra_pr_h_test"), T("ra_sc_t_n"), T("ra_m_acc"), T("ra_m_f1dir"), T("ra_m_balacc"), T("ra_m_auc"), T("ra_m_baseup"), T("ra_m_predup")],
                rows.map(function (f) {
                    var maj = majority(f.base_up);
                    return [f.split === "holdout" ? T("ra_pr_holdout") : T("ra_pr_fold", { n: f.fold }), f.start + " → " + f.end, int(f.n), { cell: pct(f.acc, 1), cls: isNum(f.acc) && maj !== null ? (f.acc > maj ? "pos" : "neg") : "" },
                        num(f.f1_dir, 3), num(f.bal_acc, 3), num(f.auc, 3), pct(f.base_up, 1), pct(f.share_pred_up, 1)];
                }), { num: [2, 3, 4, 5, 6, 7, 8] });
        }
    };

    // ---------------------------------------------------------------- calibration
    RA.render.calibration = function (m, d) {
        var names = Object.keys(d.splits), cur = names[0], host = h("div", {});
        if (names.length > 1) m.appendChild(PK.segmented(names.map(function (n) { return { value: n, label: splitLabel(n) }; }), cur, function (v) { cur = v; draw(); }));
        m.appendChild(host);
        draw();
        function reliabilityChart(rel, title, small) {
            var P = PK.plot({ w: small ? 380 : 500, h: small ? 280 : 340, x: { type: "linear", domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_ca_x") }, y: { domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_ca_y") }, title: title });
            P.add(PK.s("line", { x1: P.X(0), y1: P.Y(0), x2: P.X(1), y2: P.Y(1), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
            var bins = rel.bins, maxN = Math.max.apply(null, bins.map(function (b) { return b.n; }));
            PK.line(P, bins.map(function (b) { return b.p_mean; }), bins.map(function (b) { return b.freq; }), { color: "var(--brand)", width: 1.4, opacity: 0.7 });
            bins.forEach(function (b) {
                if (isNum(b.ci_lo)) P.add(PK.s("line", { x1: P.X(b.p_mean), x2: P.X(b.p_mean), y1: P.Y(b.ci_lo), y2: P.Y(b.ci_hi), stroke: "var(--brand)", "stroke-width": 1.2, "stroke-opacity": 0.6 }));
                PK.hoverTip(P.add(PK.s("circle", { cx: P.X(b.p_mean), cy: P.Y(b.freq), r: 3 + 5 * Math.sqrt(b.n / maxN), fill: "var(--brand)", "fill-opacity": 0.55, stroke: "var(--brand)" })),
                    function () { return [T("ra_ca_bin", { lo: num(b.lo, 2), hi: num(b.hi, 2) }), T("ra_ca_bin_v", { p: num(b.p_mean, 3), f: num(b.freq, 3), n: int(b.n) })]; });
            });
            return P.node;
        }
        function draw() {
            PK.clear(host);
            var sp = d.splits[cur], q = sp.quantile, u = sp.uniform, grid = h("div", { class: "metric-grid ra-kpis" });
            grid.appendChild(PK.kpi("Brier", num(q.brier, 4), T("ra_ca_brier_sub", { base: num(q.uncertainty, 4) }), q.brier < q.uncertainty ? "ok" : "warning"));
            grid.appendChild(PK.kpi("ECE", num(q.ece, 3), T("ra_ca_ece_sub"), q.ece > 0.08 ? "warning" : "ok"));
            grid.appendChild(PK.kpi(T("ra_ca_rel"), num(q.reliability, 4), T("ra_ca_rel_sub"), "neutral"));
            grid.appendChild(PK.kpi(T("ra_ca_res"), num(q.resolution, 4), T("ra_ca_res_sub"), "neutral"));
            grid.appendChild(PK.kpi(T("ra_ca_meanp"), pct(sp.mean_p, 1), T("ra_ca_meanp_sub", { b: pct(sp.base_rate, 1) }), "neutral"));
            host.appendChild(grid);
            host.appendChild(row2(titled(T("ra_ca_h_q"), reliabilityChart(q, T("ra_ca_h_q"), true), T("ra_ca_hint_q")), titled(T("ra_ca_h_u"), reliabilityChart(u, T("ra_ca_h_u"), true), T("ra_ca_hint_u"))));
            var hu = sp.hist_up, hd = sp.hist_down, mids = hu.edges.slice(0, -1).map(function (e, i) { return (e + hu.edges[i + 1]) / 2; });
            var ymax = Math.max.apply(null, hu.counts.concat(hd.counts)) * 1.08 || 1;
            var H = PK.plot({ w: 780, h: 200, x: { type: "linear", domain: [0, 1], fmt: function (v) { return num(v, 1); }, label: T("ra_ca_x") }, y: { domain: [0, ymax], fmt: int }, title: T("ra_ca_h_hist") });
            var w = (H.X(mids[1]) - H.X(mids[0])) * 0.42;
            PK.bars(H, mids.map(function (x) { return x - (mids[1] - mids[0]) * 0.22; }), hd.counts, { color: "var(--neg)", width: w, opacity: 0.8 });
            PK.bars(H, mids.map(function (x) { return x + (mids[1] - mids[0]) * 0.22; }), hu.counts, { color: "var(--pos)", width: w, opacity: 0.8 });
            host.appendChild(titled(T("ra_ca_h_hist"), H.node, T("ra_ca_hint_hist")));
            host.appendChild(PK.legend([{ color: "var(--pos)", label: T("ra_ca_lg_up") }, { color: "var(--neg)", label: T("ra_ca_lg_down") }]));
            if (d.by_fold.length) host.appendChild(titled(T("ra_ca_byfold"), PK.table([T("ra_pr_h_fold"), T("ra_sc_t_n"), "Brier", "ECE", T("ra_ca_meanp"), T("ra_m_baseup")],
                d.by_fold.map(function (f) { return [f.split === "holdout" ? T("ra_pr_holdout") : T("ra_pr_fold", { n: f.fold }), int(f.n), num(f.brier, 4), num(f.ece, 3), pct(f.mean_p, 1), pct(f.base_rate, 1)]; }), { num: [1, 2, 3, 4, 5] })));
            if (d.live) host.appendChild(titled(T("ra_ca_live", { n: d.live.n }), reliabilityChart(d.live.reliability, T("ra_ca_live", { n: d.live.n }), true), T("ra_ca_live_hint")));
        }
    };

})();
