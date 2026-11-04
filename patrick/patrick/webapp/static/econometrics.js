/* Page Économétrie : une série à la fois, appels /api/econometrics/<étude>, graphiques sans dépendance (PatrickCharts).
   Chaque onglet calcule au clic (rien de lourd au chargement) ; un résultat identique est servi par le cache du serveur. Première ligne d'un résultat :
   le verdict, dit tel quel. Les couleurs viennent des variables CSS. */
(function () {
    "use strict";

    var C = window.PatrickCharts;
    var tr = C.tr, fmtStr = C.fmtStr, num = C.num, pval = C.pval, h = C.h, s = C.s, chip = C.chip, note = C.note;
    var table = C.table, numCell = C.numCell, lineChart = C.lineChart, barChart = C.barChart;
    function $(id) { return document.getElementById(id); }
    function pcell(p) { return { cell: pval(p), cls: "num pk-mono" }; }
    function ncell(v, d) { return { cell: num(v, d === undefined ? 3 : d), cls: "num pk-mono" }; }
    function yesNo(v) { return v ? chip(tr("eco_yes"), "pos") : chip(tr("eco_no"), "neutral"); }
    function verdict(kind, text) { return h("p", { class: "exp-meta eco-verdict" }, [chip(text, kind)]); }
    function line(parts) { return h("p", { class: "exp-meta", text: parts.filter(Boolean).join(" · ") }); }

    var seriesSel = $("eco-series");
    var meta = null, seq = 0;

    // ------------------------------------------------------------------ API
    function baseParams() {
        var p = new URLSearchParams();
        p.set("symbol", seriesSel.value);
        p.set("transform", $("eco-transform").value);
        if ($("eco-start").value) p.set("start", $("eco-start").value);
        if ($("eco-transform").value === "fracdiff") p.set("d_frac", $("eco-frac-d").value);
        return p;
    }
    function api(study, extra) {
        var p = baseParams();
        Object.keys(extra || {}).forEach(function (k) { p.set(k, extra[k]); });
        return fetch("/api/econometrics/" + study + "?" + p.toString(), { headers: { Accept: "application/json" } })
            .then(function (r) { return r.json().catch(function () { return { error: tr("eco_load_error") }; }).then(function (body) { return { ok: r.ok, body: body }; }); })
            .then(function (res) {
                if (!res.ok) throw new Error((res.body && (res.body.error || res.body.detail)) || tr("eco_load_error"));
                return res.body;
            });
    }
    function needSeries(out) {
        if (seriesSel.value) return true;
        out.replaceChildren(h("p", { class: "hint", "data-keep": "", text: tr("eco_pick_first") }));
        return false;
    }
    // Une réponse n'est affichée que si aucune demande plus récente n'a été lancée pour la même zone.
    function job(outId, study, extra, builder) {
        var out = $(outId);
        if (!needSeries(out)) return Promise.resolve();
        var mine = (out._seq = (out._seq || 0) + 1);
        out.replaceChildren(h("p", { class: "exp-loading", text: tr("eco_running"), role: "status" }));
        return api(study, extra).then(function (body) {
            if (out._seq !== mine) return;
            var node = builder(body.result, body);
            var box = h("div", {}, [node]);
            if (body.cached) box.appendChild(h("p", { class: "exp-meta", "data-keep": "", text: tr("eco_cached") }));
            out.replaceChildren(box);
            if (window.PatrickHelp) window.PatrickHelp.scan(out);
        }).catch(function (err) {
            if (out._seq === mine) out.replaceChildren(h("p", { class: "banner banner-error", role: "alert", text: fmtStr(tr("eco_error"), { e: err.message }) }));
        });
    }

    // ------------------------------------------------------------------ briques
    function qqPlot(q, title) {
        var W = 280, H = 280, m = 36, t = q.theoretical, y = q.sample;
        var all = t.concat(y), lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), pad = (hi - lo) * 0.05;
        lo -= pad; hi += pad;
        function X(v) { return m + (v - lo) / (hi - lo) * (W - m - 8); }
        function Y(v) { return H - m - (v - lo) / (hi - lo) * (H - m - 8); }
        var svg = s("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "exp-heat", role: "img", "aria-label": title });
        svg.appendChild(s("line", { x1: X(lo), y1: Y(lo), x2: X(hi), y2: Y(hi), stroke: "var(--line-strong)", "stroke-dasharray": "4 4" }));
        svg.appendChild(s("line", { x1: m, y1: H - m, x2: W - 8, y2: H - m, stroke: "var(--line-strong)" }));
        svg.appendChild(s("line", { x1: m, y1: 8, x2: m, y2: H - m, stroke: "var(--line-strong)" }));
        t.forEach(function (v, i) { svg.appendChild(s("circle", { cx: X(v), cy: Y(y[i]), r: 2.6, fill: "var(--brand)", "fill-opacity": 0.85 })); });
        return h("div", { class: "exp-heat-wrap" }, [h("h4", { text: title }), svg]);
    }

    function acfBars(values, band, labels, title) {
        var lim = Math.max(0.3, Math.max.apply(null, values.map(Math.abs)) * 1.15);
        return barChart({ values: values, labels: labels, band: band, yMin: -lim, yMax: lim, title: title,
            strong: values.map(function (v) { return Math.abs(v) > band; }) });
    }

    function convChip(row) {
        if (row.error) return chip(tr("eco_failed"), "neg");
        return row.converged ? chip(tr("eco_converged"), "pos") : chip(tr("eco_not_converged"), "neg");
    }

    function paramsTable(params) {
        var names = Object.keys(params);
        return table([tr("eco_col_param"), tr("eco_col_value"), tr("eco_col_se"), tr("eco_col_p")], names.map(function (k) {
            var p = params[k];
            return [{ cell: k, cls: "pk-mono" }, ncell(p.value, 4), ncell(p.se, 4), pcell(p.p)];
        }));
    }

    function modelLabel(row, res) {
        if (row.is_constant) return tr("eco_mean_const");
        var o = row.order, txt = "ARIMA(" + o[0] + "," + o[1] + "," + o[2] + ")";
        if (res && res.seasonal) txt += "(" + res.seasonal.join(",") + ")";
        return txt;
    }

    // ------------------------------------------------------------------ 1. stationnarité
    function renderVarianceRatio(vr) {
        if (!vr || vr.error || !vr.rows) return vr && vr.error ? note(vr.error) : null;
        var box = h("div", {}, [h("h3", { text: tr("eco_vr_title") })]);
        box.appendChild(table([tr("eco_vr_q"), tr("eco_vr_ratio"), tr("eco_vr_z"), tr("eco_col_p"), ""], vr.rows.map(function (r) {
            return [{ cell: r.q, cls: "num" }, ncell(r.vr, 2), numCell(num(r.z_robust, 2), r.z_robust), pcell(r.p_adj), { cell: r.significant ? chip(tr("exp_sig"), "pos") : "" }];
        })));
        var kind = vr.verdict === "momentum" ? "pos" : (vr.verdict === "mean_reversion" ? "neg" : "neutral");
        box.appendChild(h("p", { class: "exp-meta" }, [tr("exp_vr_joint") + " " + pval(vr.joint_p) + " ", chip(tr("exp_vr_v_" + vr.verdict), kind)]));
        return box;
    }

    function renderUnitroot(res) {
        var ur = res.unit_root, box = h("div", {});
        var kind = ur.verdict === "stationary" ? "pos" : (ur.verdict === "unit_root" ? "neg" : "neutral");
        box.appendChild(verdict(kind, tr("eco_v_" + ur.verdict)));
        var names = { adf: "ADF", kpss: "KPSS", pp: "Phillips-Perron", dfgls: "DF-GLS" };
        box.appendChild(table([tr("eco_col_stat"), "", tr("eco_col_p"), tr("eco_col_lags"), tr("eco_col_h0"), tr("eco_col_reject")].map(function (t, i) { return i === 0 ? "Test" : t; }),
            Object.keys(names).map(function (k) {
                var t = ur.tests[k];
                if (t.error) return [names[k], { cell: t.error }, "", "", tr("eco_h0_" + t.null), ""];
                return [names[k], numCell(num(t.stat, 3), t.stat), pcell(t.pvalue), { cell: t.lags, cls: "num" }, tr("eco_h0_" + t.null), yesNo(t.reject)];
            })));
        box.appendChild(h("h3", { text: tr("eco_za_title") }));
        box.appendChild(note(tr("eco_za_note")));
        var za = res.zivot_andrews;
        if (za && !za.error) {
            box.appendChild(line([fmtStr(tr("eco_za_result"), { date: za.break_date, pct: num(za.break_fraction * 100, 0) }), "p = " + pval(za.pvalue), za.reject ? tr("eco_yes") : tr("eco_no")]));
        } else if (za) { box.appendChild(note(za.error)); }
        var vr = renderVarianceRatio(res.variance_ratio);
        if (vr) box.appendChild(vr);
        if (res.hurst && res.hurst.value !== null) box.appendChild(line([fmtStr(tr("eco_hurst"), { h: num(res.hurst.value, 2) }), res.hurst.label ? tr("eco_hurst_" + res.hurst.label) : null]));
        box.appendChild(line([fmtStr(tr("eco_obs"), { n: ur.n_obs })]));
        return box;
    }

    // ------------------------------------------------------------------ 2. dépendance
    function renderDependence(res) {
        var box = h("div", {});
        var bds = res.bds && !res.bds.error ? res.bds : null;
        box.appendChild(verdict(res.returns_autocorrelated ? "pos" : "neutral", tr(res.returns_autocorrelated ? "eco_dep_v_mean_yes" : "eco_dep_v_mean_no")));
        box.appendChild(verdict(res.volatility_clustering ? "pos" : "neutral", tr(res.volatility_clustering ? "eco_dep_v_arch_yes" : "eco_dep_v_arch_no")));
        if (bds) box.appendChild(verdict(bds.rejects_iid ? "pos" : "neutral", tr(bds.rejects_iid ? "eco_dep_v_bds_yes" : "eco_dep_v_bds_no")));
        var labels = res.lags.map(String);
        box.appendChild(acfBars(res.acf, res.band, labels, tr("eco_dep_acf")));
        box.appendChild(acfBars(res.pacf, res.band, labels, tr("eco_dep_pacf")));
        box.appendChild(acfBars(res.acf_squared, res.band, labels, tr("eco_dep_acf2")));
        var lags = Object.keys(res.ljung_box_returns_p);
        box.appendChild(table([tr("eco_dep_lag"), tr("eco_dep_lb"), tr("eco_dep_lb2")], lags.map(function (k) {
            return [{ cell: k, cls: "num" }, pcell(res.ljung_box_returns_p[k]), pcell(res.ljung_box_squared_p[k])];
        })));
        box.appendChild(line([tr("eco_dep_arch") + " " + pval(res.arch_lm_p), fmtStr(tr("eco_obs"), { n: res.n_obs })]));
        if (bds) {
            box.appendChild(h("h3", { text: tr("eco_dep_bds") }));
            box.appendChild(table([tr("eco_dep_dim"), tr("eco_col_stat"), tr("eco_col_p")], bds.rows.map(function (r) { return [{ cell: r.dim, cls: "num" }, numCell(num(r.stat, 2), r.stat), pcell(r.pvalue)]; })));
        } else if (res.bds) { box.appendChild(note(res.bds.error)); }
        return box;
    }

    // ------------------------------------------------------------------ 3. moyenne
    function renderMean(res) {
        var box = h("div", {});
        var best = res.best;
        if (best) {
            var key = res.verdict === "better_than_constant" ? "eco_mean_v_better" : "eco_mean_v_none";
            box.appendChild(verdict(res.verdict === "better_than_constant" ? "pos" : "neutral", fmtStr(tr(key), { best: modelLabel(best, res), d: num(res.delta_bic, 1) })));
        }
        box.appendChild(line([fmtStr(tr("eco_mean_tried"), { n: res.n_specs, fail: res.n_failed, nc: res.n_not_converged, raw: res.fdr.n_raw_significant, bh: res.fdr.n_bh_significant }),
            fmtStr(tr("eco_obs"), { n: res.n_obs })]));
        var base = res.constant ? res.constant.bic : null;
        box.appendChild(table([tr("eco_fc_col_rank"), tr("eco_mean_col_model"), tr("eco_col_aic"), tr("eco_col_bic"), tr("eco_mean_col_dbic"), tr("eco_mean_col_lr"), tr("eco_mean_col_padj"),
            tr("eco_col_conv"), tr("eco_mean_col_lb"), tr("eco_mean_col_arch"), tr("eco_mean_col_jb")], res.rows.map(function (r) {
            var d = r.diagnostics || {};
            return [{ cell: r.rank, cls: "num" }, modelLabel(r, res), ncell(r.aic, 1), ncell(r.bic, 1), r.bic !== null && base !== null ? numCell(num(r.bic - base, 1), r.bic - base) : "—",
                pcell(r.lr_p), pcell(r.lr_p_adj), r.error ? { cell: r.error } : convChip(r), pcell(d.ljung_box_p), pcell(d.arch_lm_p), pcell(d.jarque_bera_p)];
        })));
        if (res.gph && !res.gph.error) box.appendChild(line([fmtStr(tr("eco_gph"), { d: num(res.gph.d, 2), se: num(res.gph.se, 2) })]));
        if (best) {
            box.appendChild(h("h3", { text: tr("eco_mean_best_params") + " : " + modelLabel(best, res) }));
            box.appendChild(paramsTable(best.params));
            if (best.diagnostics) box.appendChild(qqPlot(best.diagnostics.qq, tr("eco_qq")));
        }
        return box;
    }

    // ------------------------------------------------------------------ 4. variance
    function renderVariance(res) {
        var box = h("div", {});
        var title = tr("eco_m_" + res.model) + " · " + tr("eco_d_" + res.dist);
        box.appendChild(h("p", { class: "exp-meta" }, [title + " ", convChip(res)]));
        if (!res.converged && res.message) box.appendChild(note(res.message));
        if (res.near_integrated) box.appendChild(note(tr("eco_var_near_integrated")));
        if (res.se_missing) box.appendChild(note(tr("eco_var_se_missing")));
        var facts = [];
        if (res.persistence !== null) facts.push(fmtStr(tr("eco_var_persistence"), { p: num(res.persistence, 4) }));
        if (res.half_life !== null) facts.push(fmtStr(tr("eco_var_halflife"), { h: num(res.half_life, 1) }));
        facts.push(fmtStr(tr("eco_var_uncond"), { v: num(res.unconditional_vol_annual, 1) }));
        if (res.corr_with_realized !== undefined && res.corr_with_realized !== null) facts.push(fmtStr(tr("eco_var_corr"), { c: num(res.corr_with_realized, 2) }));
        facts.push(tr("eco_col_bic") + " " + num(res.bic, 1));
        box.appendChild(line(facts));
        box.appendChild(note(tr("eco_descriptive")));
        box.appendChild(paramsTable(res.params));
        var series = [{ name: tr("eco_var_cond"), values: res.conditional_vol.values, color: "--brand" }];
        if (res.realized_vol) series.push({ name: tr("eco_var_real"), values: res.realized_vol.values, color: "--text-3", width: 1 });
        box.appendChild(lineChart({ dates: res.conditional_vol.dates, series: series, title: tr("eco_var_chart"), yFmt: function (v) { return num(v, 0); } }));
        var d = res.diagnostics;
        box.appendChild(h("h3", { text: tr("eco_diag_title") }));
        var rows = [[tr("eco_diag_lb"), pcell(d.ljung_box_p)], [tr("eco_diag_lb2"), pcell(d.ljung_box_squared_p)], [tr("eco_diag_arch"), pcell(d.arch_lm_p)],
            [tr("eco_diag_jb"), pcell(d.jarque_bera_p)], [tr("eco_diag_kurt"), ncell(d.excess_kurtosis, 2)]];
        if (d.bds && !d.bds.error) rows.push([tr("eco_diag_bds"), pcell(d.bds.min_pvalue_adjusted)]);
        box.appendChild(table(["", ""], rows));
        box.appendChild(h("h3", { text: tr("eco_en_title") }));
        box.appendChild(note(tr("eco_en_note")));
        var en = res.engle_ng, enNames = { sign_bias: "eco_en_sign", negative_size_bias: "eco_en_neg", positive_size_bias: "eco_en_pos", joint: "eco_en_joint" };
        box.appendChild(table(["", tr("eco_col_stat"), tr("eco_col_p")], Object.keys(enNames).map(function (k) {
            return [tr(enNames[k]), numCell(num(en[k].stat, 2), en[k].stat), pcell(en[k].pvalue)];
        })));
        if (res.news_impact) {
            box.appendChild(lineChart({ dates: res.news_impact.shock.map(function (v) { return "ε " + num(v, 2); }), series: [{ name: "σ²", values: res.news_impact.variance, color: "--brand" }],
                title: tr("eco_nic"), yFmt: function (v) { return num(v, 2); } }));
        }
        box.appendChild(qqPlot(d.qq, tr("eco_qq")));
        return box;
    }

    function renderGrid(res) {
        var box = h("div", {});
        box.appendChild(line([fmtStr(tr("eco_grid_summary"), { n: res.n_specs, fail: res.n_failed, nc: res.n_not_converged }),
            res.delta_bic_vs_garch_normal !== null ? fmtStr(tr("eco_grid_dbic"), { d: num(res.delta_bic_vs_garch_normal, 1) }) : null]));
        box.appendChild(table([tr("eco_fc_col_rank"), tr("eco_model"), tr("eco_col_dist"), tr("eco_col_bic"), tr("eco_col_aic"), tr("eco_col_pers"), tr("eco_col_conv"), tr("eco_col_lb2"), tr("eco_col_archlm"), tr("eco_col_en")],
            res.rows.map(function (r) {
                return [{ cell: r.rank, cls: "num" }, tr("eco_m_" + r.model), tr("eco_d_" + r.dist), ncell(r.bic, 1), ncell(r.aic, 1), ncell(r.persistence, 3),
                    r.error ? { cell: r.error } : convChip(r), pcell(r.ljung_box_squared_p), pcell(r.arch_lm_p), pcell(r.engle_ng_joint_p)];
            })));
        box.appendChild(note(tr("eco_descriptive")));
        return box;
    }

    function renderHar(res) {
        var box = h("div", {});
        var names = { "const": "eco_har_const", daily: "eco_har_daily", weekly: "eco_har_weekly", monthly: "eco_har_monthly" };
        box.appendChild(table([tr("eco_col_param"), tr("eco_col_value"), tr("eco_col_se"), tr("eco_har_t"), tr("eco_col_p")], Object.keys(names).map(function (k) {
            var p = res.params[k];
            return [tr(names[k]), ncell(p.value, 6), ncell(p.se, 6), numCell(num(p.t, 2), p.t), pcell(p.p)];
        })));
        box.appendChild(line([fmtStr(tr("eco_har_r2"), { r: num(res.r2, 3), p: num(res.persistence, 3) }), fmtStr(tr("eco_obs"), { n: res.n_obs })]));
        box.appendChild(lineChart({ dates: res.fitted.dates, series: [{ name: tr("eco_var_real"), values: res.fitted.actual, color: "--text-3", width: 1 },
            { name: "HAR", values: res.fitted.values, color: "--brand" }], title: tr("eco_har_title"), yFmt: function (v) { return num(v, 6); } }));
        return box;
    }

    // ------------------------------------------------------------------ 6. régimes
    function renderRegimes(res) {
        var box = h("div", {});
        if (res.regimes) {
            var kind = res.verdict === "regimes_supported" ? "pos" : "neutral";
            var key = res.verdict === "not_converged" ? "eco_reg_v_not_converged" : (res.verdict === "regimes_supported" ? "eco_reg_v_supported" : "eco_reg_v_single");
            box.appendChild(verdict(kind, fmtStr(tr(key), { d: num(res.delta_bic, 1) })));
            box.appendChild(table([tr("eco_reg_col_regime"), tr("eco_reg_col_mean"), tr("eco_reg_col_vol"), tr("eco_reg_col_stay"), tr("eco_reg_col_dur"), tr("eco_reg_col_share")], res.regimes.map(function (r) {
                return [r.regime + (r.regime === res.stress_regime ? " · " + tr("eco_reg_stress") : ""), numCell(num(r.mean_pct, 3), r.mean_pct), ncell(r.vol_annual_pct, 1), ncell(r.p_stay, 3), ncell(r.expected_duration, 1), ncell(r.share * 100, 0)];
            })));
            box.appendChild(lineChart({ dates: res.dates, series: [{ name: tr("eco_reg_filtered"), values: res.filtered_stress, color: "--brand" },
                { name: tr("eco_reg_smoothed"), values: res.smoothed_stress, color: "--text-3", width: 1 }], yMin: 0, yMax: 1, title: tr("eco_reg_chart") }));
            box.appendChild(line([fmtStr(tr("eco_obs"), { n: res.n_obs }), tr("eco_col_bic") + " " + num(res.bic, 1) + " (1 : " + num(res.bic_single_regime, 1) + ")"]));
        } else {
            box.appendChild(line([fmtStr(tr("eco_reg_hmm_n"), { k: res.n_states }), fmtStr(tr("eco_obs"), { n: res.n_obs })]));
            box.appendChild(h("h3", { text: tr("eco_reg_bic") }));
            box.appendChild(table([tr("eco_reg_states"), tr("eco_col_bic"), tr("eco_col_aic")], res.bic.map(function (b) { return [{ cell: b.n_states, cls: "num" }, ncell(b.bic, 1), ncell(b.aic, 1)]; })));
            box.appendChild(table([tr("eco_reg_col_regime"), tr("eco_reg_col_mean"), tr("eco_reg_col_vol"), tr("eco_reg_col_stay"), tr("eco_reg_col_share")], res.states.map(function (r) {
                return [r.state + (r.state === res.stress_state ? " · " + tr("eco_reg_stress") : ""), numCell(num(r.mean_pct, 3), r.mean_pct), ncell(r.vol_annual_pct, 1), ncell(r.p_stay, 3), ncell(r.share * 100, 0)];
            })));
            box.appendChild(lineChart({ dates: res.dates, series: [{ name: tr("eco_reg_filtered"), values: res.stress_prob, color: "--brand" }], yMin: 0, yMax: 1, title: tr("eco_reg_chart") }));
        }
        box.appendChild(note(tr("eco_descriptive")));
        return box;
    }

    // ------------------------------------------------------------------ 7. prévision
    function specLabel(name) {
        if (name === "riskmetrics") return tr("eco_spec_riskmetrics");
        if (name === "rolling60") return tr("eco_spec_rolling60");
        if (name === "har") return tr("eco_spec_har");
        var p = name.split("|");
        return tr("eco_m_" + p[0]) + " · " + tr("eco_d_" + p[1]);
    }

    function renderForecast(res) {
        var box = h("div", {}), cmp = res.comparison;
        var proxyKey = "eco_fc_proxy_" + (res.proxy === "squared_return" ? "r2" : res.proxy);
        box.appendChild(line([fmtStr(tr("eco_fc_summary"), { n: cmp.n_models, obs: res.n_obs, proxy: tr(proxyKey), tests: cmp.n_dm_tests })]));
        box.appendChild(note(tr("eco_fc_snooping")));
        if (cmp.mcs_error) box.appendChild(note(cmp.mcs_error));
        box.appendChild(table([tr("eco_fc_col_rank"), tr("eco_model"), tr("eco_fc_col_qlike"), tr("eco_fc_col_mse"), tr("eco_fc_col_mz"), tr("eco_fc_col_mzp"), tr("eco_fc_col_dm"), tr("eco_fc_col_mcs"), tr("eco_fc_col_mcsp")],
            cmp.rows.map(function (r) {
                var dm = r.dm_p_adj === null ? { cell: "—", cls: "num" } : { cell: pval(r.dm_p_adj) + (r.dm_better ? " · " + tr("eco_fc_better") : ""), cls: "num pk-mono" };
                return [{ cell: r.rank, cls: "num" }, specLabel(r.name) + (r.name === cmp.benchmark ? " *" : ""), ncell(r.mean_qlike, 4), { cell: r.mean_mse.toExponential(2), cls: "num pk-mono" },
                    ncell(r.mz_slope, 2), pcell(r.mz_p), dm, r.in_mcs === null ? "" : yesNo(r.in_mcs), pcell(r.mcs_p)];
            })));
        box.appendChild(barChart({ values: cmp.rows.map(function (r) { return r.mean_qlike; }), labels: cmp.rows.map(function (r) { return specLabel(r.name); }), yMin: 0,
            title: tr("eco_fc_chart"), color: function () { return "var(--brand)"; } }));
        box.appendChild(h("h3", { text: tr("eco_fc_var_title") }));
        box.appendChild(note(tr("eco_fc_var_note")));
        var rows = [];
        Object.keys(res.var_backtest).forEach(function (name) {
            Object.keys(res.var_backtest[name]).forEach(function (lvl) {
                var t = res.var_backtest[name][lvl], uc = t.unconditional;
                rows.push([specLabel(name), { cell: num(parseFloat(lvl) * 100, 0) + " %", cls: "num" }, { cell: num(uc.rate * 100, 2) + " %", cls: "num pk-mono" }, { cell: uc.hits, cls: "num" },
                    pcell(uc.pvalue), pcell(t.independence.pvalue), pcell(t.conditional.pvalue)]);
            });
        });
        box.appendChild(table([tr("eco_model"), tr("eco_fc_col_level"), tr("eco_fc_col_rate"), tr("eco_fc_col_hits"), tr("eco_fc_col_kup"), tr("eco_fc_col_ind"), tr("eco_fc_col_cc")], rows));
        var info = Object.keys(res.refit).filter(function (k) { return res.refit[k].n_refits !== undefined; }).map(function (k) {
            var r = res.refit[k];
            return specLabel(k) + " — " + fmtStr(tr("eco_fc_refit_info"), { n: r.n_refits, f: r.n_failed_refits, nc: r.n_not_converged });
        });
        info.forEach(function (t) { box.appendChild(h("p", { class: "exp-meta", text: t })); });
        return box;
    }

    // ------------------------------------------------------------------ série
    function renderSeriesHeader(body) {
        meta = body.meta;
        $("eco-status").textContent = fmtStr(tr("eco_status"), { n: meta.n_obs, start: meta.start, end: meta.end, freq: tr("eco_freq_" + meta.periodicity), tr: tr("eco_tr_" + meta.transform.kind) });
        var ul = $("eco-warnings");
        ul.replaceChildren();
        if (meta.transform.fallback) ul.appendChild(h("li", { text: tr("eco_tr_fallback") }));
        $("eco-seasonal-wrap").hidden = !meta.seasonal_period;
        if (!meta.seasonal_period) $("eco-mean-seasonal").checked = false;
        document.querySelectorAll("#eco-transform option[value=parkinson], #eco-transform option[value=garman_klass], .eco-ohlc-opt").forEach(function (o) { o.disabled = !meta.ohlc_possible; });
        document.querySelectorAll("#eco-var-proxy option, #eco-har-proxy option, #eco-fc-proxy option").forEach(function (o) {
            if (o.value === "parkinson" || o.value === "garman_klass") o.disabled = !meta.ohlc_possible;
        });
        return lineChart({ dates: body.result.dates, series: [{ values: body.result.values, color: "--brand" }], title: tr("eco_series_chart"), yFmt: function (v) { return num(v, 4); } });
    }

    function loadSeries() {
        var out = $("eco-series-out");
        if (!needSeries(out)) return Promise.resolve();
        var mine = (out._seq = (out._seq || 0) + 1);
        out.replaceChildren(h("p", { class: "exp-loading", text: tr("eco_running"), role: "status" }));
        $("eco-status").textContent = "";
        return api("series", {}).then(function (body) {
            if (out._seq !== mine) return;
            out.replaceChildren(renderSeriesHeader(body));
            ["eco-ur-out", "eco-dep-out", "eco-mean-out", "eco-var-out", "eco-grid-out", "eco-har-out", "eco-reg-out", "eco-fc-out"].forEach(function (id) { $(id).replaceChildren(); });
            runUnitroot();
        }).catch(function (err) {
            if (out._seq === mine) out.replaceChildren(h("p", { class: "banner banner-error", role: "alert", text: fmtStr(tr("eco_error"), { e: err.message }) }));
        });
    }

    // ------------------------------------------------------------------ actions des onglets
    function runUnitroot() { return job("eco-ur-out", "unitroot", { trend: $("eco-ur-trend").value }, renderUnitroot); }
    function runDependence() { return job("eco-dep-out", "dependence", { nlags: $("eco-dep-lags").value }, renderDependence); }
    function runMean() {
        var extra = { max_p: $("eco-mean-p").value, max_q: $("eco-mean-q").value, d: $("eco-mean-d").value };
        if ($("eco-mean-seasonal").checked) extra.seasonal = "1";
        if ($("eco-mean-reg").value) extra.regressor = $("eco-mean-reg").value;
        return job("eco-mean-out", "mean", extra, renderMean);
    }
    function runVariance() {
        return job("eco-var-out", "variance", { model: $("eco-var-model").value, dist: $("eco-var-dist").value, mean: $("eco-var-mean").value, proxy: $("eco-var-proxy").value }, renderVariance);
    }
    function checked(sel) { return Array.prototype.map.call(document.querySelectorAll(sel + ":checked"), function (e) { return e.value; }); }
    function runGrid() {
        var models = checked(".eco-grid-model"), dists = checked(".eco-grid-dist");
        if (!models.length || !dists.length) return Promise.resolve();
        return job("eco-grid-out", "variance_grid", { models: models.join(","), dists: dists.join(","), mean: $("eco-var-mean").value }, renderGrid);
    }
    function runHar() { return job("eco-har-out", "har", { proxy: $("eco-har-proxy").value, log: $("eco-har-log").checked ? "1" : "0" }, renderHar); }
    function runRegimes() {
        var extra = { method: $("eco-reg-method").value, k: $("eco-reg-k").value, max_states: $("eco-reg-states").value,
            switching_mean: $("eco-reg-sw-mean").checked ? "1" : "0", switching_variance: $("eco-reg-sw-var").checked ? "1" : "0" };
        return job("eco-reg-out", "regimes", extra, renderRegimes);
    }
    function runForecast() {
        var specs = checked("#eco-fc-specs input");
        if (!specs.length) return Promise.resolve();
        var extra = { specs: specs.join(","), proxy: $("eco-fc-proxy").value, min_train: $("eco-fc-min").value, refit_every: $("eco-fc-refit").value, window: $("eco-fc-window").value };
        return job("eco-fc-out", "forecast", extra, renderForecast);
    }

    // ------------------------------------------------------------------ onglets, période, filtre
    function showPanel(key) {
        document.querySelectorAll(".exp-tabs [role=tab]").forEach(function (tab) {
            var on = tab.dataset.panel === key;
            tab.setAttribute("aria-selected", on ? "true" : "false");
            tab.tabIndex = on ? 0 : -1;
        });
        document.querySelectorAll(".exp-panel").forEach(function (p) { p.hidden = p.id !== "eco-panel-" + key; });
    }
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".exp-tabs [role=tab]"));
    tabs.forEach(function (tab, i) {
        tab.addEventListener("click", function () { showPanel(tab.dataset.panel); });
        tab.addEventListener("keydown", function (ev) {
            var d = ev.key === "ArrowRight" ? 1 : (ev.key === "ArrowLeft" ? -1 : 0);
            if (!d) return;
            var target = tabs[(i + d + tabs.length) % tabs.length];
            target.focus(); showPanel(target.dataset.panel);
        });
    });

    function setYears(years) {
        if (!years) { $("eco-start").value = ""; return; }
        var d = new Date(); d.setFullYear(d.getFullYear() - years);
        $("eco-start").value = d.toISOString().slice(0, 10);
    }
    document.querySelectorAll(".exp-period-btns .range-btn").forEach(function (b) {
        b.addEventListener("click", function () {
            document.querySelectorAll(".exp-period-btns .range-btn").forEach(function (x) { x.classList.toggle("active", x === b); });
            setYears(parseInt(b.dataset.years, 10));
            if (seriesSel.value) loadSeries();
        });
    });
    $("eco-start").addEventListener("change", function () {
        document.querySelectorAll(".exp-period-btns .range-btn").forEach(function (x) { x.classList.remove("active"); });
        if (seriesSel.value) loadSeries();
    });
    setYears(10);

    $("eco-filter").addEventListener("input", function () {
        var q = this.value.trim().toLowerCase();
        Array.prototype.forEach.call(seriesSel.querySelectorAll("option"), function (o) { o.hidden = !!q && (o.dataset.text || "").indexOf(q) < 0; });
        Array.prototype.forEach.call(seriesSel.querySelectorAll("optgroup"), function (g) {
            g.hidden = Array.prototype.every.call(g.querySelectorAll("option"), function (o) { return o.hidden; });
        });
    });
    $("eco-transform").addEventListener("change", function () {
        $("eco-frac-wrap").hidden = this.value !== "fracdiff";
        if (seriesSel.value) loadSeries();
    });
    $("eco-frac-d").addEventListener("change", function () { if (seriesSel.value) loadSeries(); });
    seriesSel.addEventListener("change", loadSeries);
    $("eco-load").addEventListener("click", loadSeries);
    $("eco-ur-run").addEventListener("click", runUnitroot);
    $("eco-dep-run").addEventListener("click", runDependence);
    $("eco-mean-run").addEventListener("click", runMean);
    $("eco-var-run").addEventListener("click", runVariance);
    $("eco-grid-run").addEventListener("click", runGrid);
    $("eco-har-run").addEventListener("click", runHar);
    $("eco-reg-run").addEventListener("click", runRegimes);
    $("eco-fc-run").addEventListener("click", runForecast);
})();
