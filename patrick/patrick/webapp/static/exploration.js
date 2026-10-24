/* Page Exploration : sélection d'actifs, appels /api/exploration/<étude>, graphiques SVG sans dépendance.
   Les couleurs viennent des variables CSS (thème clair/sombre sans redessin). Chaque résultat est affiché avec son nombre
   d'observations ; les notes interprétatives sont des `.hint` repliées derrière un « ? » par help.js. */
(function () {
    "use strict";

    var C = window.PatrickCharts;
    var tr = C.tr, fmtStr = C.fmtStr, num = C.num, pct = C.pct, pval = C.pval, h = C.h, s = C.s, chip = C.chip, note = C.note;
    var table = C.table, numCell = C.numCell, lineChart = C.lineChart, barChart = C.barChart;
    function $(id) { return document.getElementById(id); }
    var PN = window.PatrickNames || { label: function (s) { return s; }, name: function (s) { return s; }, tip: function () { return ""; } };

    // Matrice carrée en cases colorées. `o.symbol` : grandeur affichée dans l'infobulle (ρ pour une corrélation) ; `o.title` : nom de l'étude.
    function heatmap(res, o) {
        o = o || {};
        var symbol = o.symbol || "ρ";
        var labels = res.labels.map(function (sym) { return PN.name(sym); }), n = labels.length;
        var cs = Math.max(18, Math.min(46, Math.floor(560 / n)));
        // axes : noms raccourcis (le nom complet reste dans l'infobulle de chaque case)
        var axis = labels.map(function (l) { return l.length > 22 ? l.slice(0, 21) + "…" : l; });
        var longest = axis.reduce(function (m, l) { return Math.max(m, l.length); }, 0);
        var ml = Math.min(150, longest * 6.4 + 12), mt = ml;
        var W = ml + n * cs + 8, H = mt + n * cs + 8;
        var svg = s("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "exp-heat", role: "img",
            "aria-label": fmtStr(tr("exp_chart_aria"), { t: o.title || tr("exp_tab_corr") }) });
        labels.forEach(function (lab, i) {
            svg.appendChild(s("text", { x: ml - 6, y: mt + i * cs + cs / 2 + 3.5, "text-anchor": "end", class: "exp-axis", text: axis[i] }));
            svg.appendChild(s("text", { x: 0, y: 0, class: "exp-axis", text: axis[i], transform: "translate(" + (ml + i * cs + cs / 2 + 3.5) + "," + (mt - 6) + ") rotate(-90)" }));
        });
        res.matrix.forEach(function (row, i) {
            row.forEach(function (rho, j) {
                var sig = res.significant ? res.significant[i][j] : true;
                var diag = i === j;
                var fill = diag ? "var(--surface-3)" : (rho >= 0 ? "var(--brand)" : "var(--neg)");
                var op = diag ? 1 : Math.min(1, Math.abs(rho) * 1.05) * (sig === false ? 0.28 : 1);
                var cell = s("rect", { x: ml + j * cs + 1, y: mt + i * cs + 1, width: cs - 2, height: cs - 2, rx: 3, fill: fill, "fill-opacity": op });
                cell.appendChild(s("title", { text: labels[i] + " × " + labels[j] + " : " + symbol + " = " + num(rho, 2) + (sig === false ? " (" + tr("exp_nonsig") + ")" : "") }));
                svg.appendChild(cell);
                if (!diag && cs >= 28) {
                    svg.appendChild(s("text", { x: ml + j * cs + cs / 2, y: mt + i * cs + cs / 2 + 3.5, "text-anchor": "middle", class: "exp-cell", text: num(rho, 2).replace("-", "−") }));
                }
            });
        });
        return h("div", { class: "exp-heat-wrap" }, [svg]);
    }

    // Matrice « qui mène qui » : ligne = cause, colonne = effet ; case pleine = lien significatif (plus foncée = p corrigée plus petite).
    function grangerHeat(res) {
        var labels = res.labels.map(function (sym) { return PN.name(sym); }), n = labels.length;
        var cs = Math.max(18, Math.min(46, Math.floor(560 / n)));
        var axis = labels.map(function (l) { return l.length > 22 ? l.slice(0, 21) + "…" : l; });
        var longest = axis.reduce(function (m, l) { return Math.max(m, l.length); }, 0);
        var ml = Math.min(150, longest * 6.4 + 12), mt = ml;
        var W = ml + n * cs + 8, H = mt + n * cs + 8;
        var svg = s("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "exp-heat", role: "img",
            "aria-label": fmtStr(tr("exp_chart_aria"), { t: tr("exp_gm_title") }) });
        labels.forEach(function (lab, i) {
            svg.appendChild(s("text", { x: ml - 6, y: mt + i * cs + cs / 2 + 3.5, "text-anchor": "end", class: "exp-axis", text: axis[i] }));
            svg.appendChild(s("text", { x: 0, y: 0, class: "exp-axis", text: axis[i], transform: "translate(" + (ml + i * cs + cs / 2 + 3.5) + "," + (mt - 6) + ") rotate(-90)" }));
        });
        res.p_adj.forEach(function (row, i) {
            row.forEach(function (q, j) {
                var diag = i === j, sig = res.significant[i][j] === true;
                var strength = sig ? 0.4 + 0.6 * Math.min(1, -Math.log10(Math.max(q === null ? 1 : q, 1e-12)) / 8) : 0;
                var cell = s("rect", { x: ml + j * cs + 1, y: mt + i * cs + 1, width: cs - 2, height: cs - 2, rx: 3,
                    fill: diag ? "var(--surface-3)" : (sig ? "var(--brand)" : "var(--surface-2)"), "fill-opacity": diag ? 1 : (sig ? strength : 0.8) });
                if (!diag) {
                    var g = res.gain[i][j];
                    cell.appendChild(s("title", { text: fmtStr(tr("exp_gm_cell"), { a: labels[i], b: labels[j], q: pval(q), g: g === null ? "—" : pct(g, 2) }) }));
                }
                svg.appendChild(cell);
            });
        });
        return h("div", { class: "exp-heat-wrap" }, [svg]);
    }

    // ------------------------------------------------------------------ état
    var assets = $("exp-assets");
    var runId = 0, loaded = {}, activePanel = "corr", lastMeta = null;

    function selected() { return Array.prototype.map.call(assets.selectedOptions, function (o) { return o.value; }); }

    function renderChips() {
        var box = $("exp-chips"), syms = selected();
        box.replaceChildren();
        syms.forEach(function (sym) {
            var b = h("button", { type: "button", class: "exp-chip-btn", title: sym, "aria-label": fmtStr(tr("exp_remove"), { s: PN.label(sym) }) }, [PN.label(sym) + " ×"]);
            b.addEventListener("click", function () {
                Array.prototype.forEach.call(assets.options, function (o) { if (o.value === sym) o.selected = false; });
                onSelectionChange();
            });
            box.appendChild(b);
        });
        $("exp-count").textContent = syms.length ? fmtStr(tr("exp_selected"), { n: syms.length }) : tr("exp_none_selected");
    }

    function refreshAssetSelects(only) {
        var syms = only || selected();
        document.querySelectorAll(".exp-asset-select").forEach(function (sel) {
            var previous = sel.value, role = sel.dataset.role;
            sel.replaceChildren();
            syms.forEach(function (sym) { sel.appendChild(h("option", { value: sym, text: PN.label(sym), title: sym })); });
            if (previous && syms.indexOf(previous) >= 0) sel.value = previous;
            else if (syms.length) sel.value = syms[role === "b" ? Math.min(1, syms.length - 1) : 0];
        });
    }

    function onSelectionChange() { renderChips(); refreshAssetSelects(); }

    // ------------------------------------------------------------------ API
    function baseParams() {
        var p = new URLSearchParams();
        p.set("symbols", selected().join(","));
        if ($("exp-start").value) p.set("start", $("exp-start").value);
        p.set("freq", $("exp-freq").value);
        p.set("transform", $("exp-transform").value);
        return p;
    }

    function api(study, extra) {
        var p = baseParams();
        Object.keys(extra || {}).forEach(function (k) { p.set(k, extra[k]); });
        return fetch("/api/exploration/" + study + "?" + p.toString(), { headers: { Accept: "application/json" } })
            .then(function (r) { return r.json().catch(function () { return { error: tr("exp_load_error") }; }).then(function (body) { return { ok: r.ok, body: body }; }); })
            .then(function (res) {
                if (!res.ok) throw new Error((res.body && (res.body.error || res.body.detail)) || tr("exp_load_error"));
                if (!lastMeta || lastMeta._run !== runId) { lastMeta = res.body.meta; lastMeta._run = runId; showMeta(lastMeta); }
                return res.body.result;
            });
    }

    function showMeta(meta) {
        $("exp-status").textContent = fmtStr(tr("exp_status"), { n: meta.n_obs, start: meta.start, end: meta.end, k: meta.n_assets });
        var ul = $("exp-warnings");
        ul.replaceChildren();
        (meta.warnings || []).forEach(function (w) { ul.appendChild(h("li", { text: w })); });
        // Les listes A / B ne proposent que les actifs réellement chargés (un actif exclu y fabriquerait une erreur).
        var available = Object.keys(meta.transforms || {});
        if (available.length && available.length < selected().length) refreshAssetSelects(available);
    }

    function paint(out, builder) {
        out.replaceChildren(h("p", { class: "exp-loading", text: tr("exp_running"), role: "status" }));
        return function (result) {
            out.replaceChildren(builder(result));
            if (window.PatrickHelp) window.PatrickHelp.scan(out);
        };
    }
    function fail(out) {
        return function (err) { out.replaceChildren(h("p", { class: "banner banner-error", role: "alert", text: fmtStr(tr("exp_error"), { e: err.message }) })); };
    }
    // Une réponse n'est affichée que si aucune demande plus récente n'a été lancée pour la même zone (deux « Appliquer » rapprochés : la
    // réponse arrivée en dernier ne doit pas écraser la dernière demande).
    function job(outId, study, extra, builder) {
        var out = $(outId), seq = (out._seq = (out._seq || 0) + 1), done = paint(out, builder), failed = fail(out);
        return api(study, extra)
            .then(function (result) { if (out._seq === seq) done(result); })
            .catch(function (err) { if (out._seq === seq) failed(err); });
    }
    function pair(prefix) {
        var a = $(prefix + "-a"), b = $(prefix + "-b");
        return { a: a ? a.value : "", b: b ? b.value : "" };
    }
    function needPair(outId, p) {
        if (!p.a || !p.b || p.a === p.b) {
            $(outId).replaceChildren(h("p", { class: "hint", "data-keep": "", text: tr("exp_pair_needs_two") }));
            return false;
        }
        return true;
    }

    // ------------------------------------------------------------------ rendus
    function pairList(title, rows) {
        if (!rows.length) return null;
        return h("div", { class: "exp-pairs" }, [h("h4", { text: title }), table(["", "ρ", "p"], rows.map(function (r) {
            return [PN.label(r.a) + " × " + PN.label(r.b), numCell(num(r.rho, 2), r.rho), { cell: pval(r.p_adj), cls: "num pk-mono" }];
        }))]);
    }

    function renderCorrelation(res) {
        var box = h("div", {});
        box.appendChild(heatmap(res));
        var legend = h("div", { class: "exp-legend" }, [chip(tr("exp_legend_pos"), "pos"), chip(tr("exp_legend_neg"), "neg"),
            res.significant ? chip(tr("exp_legend_faded"), "faded") : null]);
        box.appendChild(legend);
        var meta = [fmtStr(tr("exp_obs"), { n: res.n_obs }), tr("exp_corr_mean_abs") + " " + num(res.mean_abs_corr, 2)];
        meta.push(res.significant ? fmtStr(tr("exp_corr_tests"), { n: res.n_tests }) : tr("exp_corr_no_sig"));
        box.appendChild(h("p", { class: "exp-meta", text: meta.join(" · ") }));
        var grid = h("div", { class: "exp-two" }, [pairList(tr("exp_corr_most_pos"), res.most_positive), pairList(tr("exp_corr_most_neg"), res.most_negative)]);
        box.appendChild(grid);
        return box;
    }

    function renderRolling(res) {
        var box = h("div", {});
        box.appendChild(lineChart({
            dates: res.dates, series: [{ values: res.values }], yMin: -1, yMax: 1, title: PN.label(res.a) + " × " + PN.label(res.b),
            band: [res.full_sample - res.noise_band, res.full_sample + res.noise_band],
            hlines: [{ y: res.full_sample, dash: "2 3" }, { y: 0, color: "var(--line-strong)", dash: "0" }],
        }));
        box.appendChild(h("p", { class: "exp-meta", text: [
            tr("exp_roll_full") + " " + num(res.full_sample, 2), tr("exp_roll_last") + " " + num(res.last, 2),
            tr("exp_roll_min") + " " + num(res.min, 2), tr("exp_roll_max") + " " + num(res.max, 2),
            tr("exp_roll_halves") + " " + num(res.first_half_mean, 2) + " → " + num(res.second_half_mean, 2),
            fmtStr(tr("exp_obs"), { n: res.n_obs })].join(" · ") }));
        return box;
    }

    function renderDescribe(res) {
        var headers = [tr("exp_col_asset"), tr("exp_col_mean"), tr("exp_col_vol"), tr("exp_col_skew"), tr("exp_col_kurt"), tr("exp_col_normal"),
            { text: tr("exp_col_var"), term: "exp_var_es" }, { text: tr("exp_col_es"), term: "exp_var_es" }, tr("exp_col_worst"), tr("exp_col_best"), tr("exp_col_dd"), tr("exp_col_pos"), tr("exp_col_ac1")];
        var rows = res.rows.map(function (r) {
            return [{ cell: PN.label(r.symbol) }, numCell(pct(r.mean_ann), r.mean_ann), { cell: pct(r.vol_ann), cls: "num pk-mono" },
                numCell(num(r.skew, 2), r.skew), { cell: num(r.excess_kurtosis, 2), cls: "num pk-mono" },
                { cell: chip(r.normal_rejected ? tr("exp_normal_rejected") : tr("exp_normal_kept"), r.normal_rejected ? "warn" : "ok") },
                numCell(pct(r.var95, 2), r.var95), numCell(pct(r.es95, 2), r.es95),
                numCell(pct(r.worst, 1), r.worst), numCell(pct(r.best, 1), r.best),
                r.max_drawdown === null ? { cell: "—", cls: "num" } : numCell(pct(r.max_drawdown, 1), r.max_drawdown),
                { cell: pct(r.pct_positive, 0), cls: "num pk-mono" }, numCell(num(r.autocorr_1, 2), r.autocorr_1)];
        });
        var box = h("div", {}, [table(headers, rows)]);
        box.appendChild(h("p", { class: "exp-meta", text: fmtStr(tr("exp_obs"), { n: res.n_obs }) }));
        return box;
    }

    function renderStationarity(res) {
        var headers = [tr("exp_col_asset"), { text: tr("exp_col_adf"), term: "exp_adf" }, { text: tr("exp_col_kpss"), term: "exp_kpss" }, tr("exp_col_level"), tr("exp_col_ret_stat"), { text: tr("exp_col_hurst"), term: "exp_hurst" }];
        var rows = res.rows.map(function (r) {
            if (r.error) return [{ cell: PN.label(r.symbol) }, { cell: r.error }, "", "", "", ""];
            var level = r.level_stationary ? chip(tr("exp_v_stationary"), "ok") : (r.level_unit_root ? chip(tr("exp_v_unit_root"), "warn") : chip(tr("exp_v_ambiguous"), "neutral"));
            var hurstKind = r.hurst_label === "random_walk" ? "neutral" : (r.hurst_label === "trending" ? "pos" : "neg");
            return [{ cell: PN.label(r.symbol) }, { cell: pval(r.adf_level_p), cls: "num pk-mono" }, { cell: pval(r.kpss_level_p), cls: "num pk-mono" },
                { cell: level }, { cell: chip(r.return_stationary ? tr("exp_v_stationary") : tr("exp_v_ambiguous"), r.return_stationary ? "ok" : "neutral") },
                { cell: h("span", {}, [num(r.hurst, 2) + " ", r.hurst === null ? "" : chip(tr("exp_h_" + r.hurst_label), hurstKind)]) }];
        });
        return h("div", {}, [table(headers, rows), h("p", { class: "exp-meta", text: fmtStr(tr("exp_obs"), { n: res.n_obs }) }), note(res.note || "")]);
    }

    function renderMemory(res) {
        var box = h("div", {});
        var labels = res.lags.map(String);
        [["exp_acf_returns", res.acf], ["exp_pacf_returns", res.pacf], ["exp_acf_squared", res.acf_squared]].forEach(function (pair) {
            box.appendChild(h("h4", { text: tr(pair[0]) }));
            box.appendChild(barChart({ values: pair[1], labels: labels, band: res.band, yMin: -0.3, yMax: 0.3, title: tr(pair[0]),
                strong: pair[1].map(function (v) { return Math.abs(v) > res.band; }) }));
        });
        var lb = function (obj) { return Object.keys(obj).map(function (k) { return tr("exp_lag") + " " + k + " : " + pval(obj[k]); }).join(" · "); };
        box.appendChild(table(["", ""], [
            [tr("exp_lb_returns"), { cell: h("span", {}, [lb(res.ljung_box_returns_p) + " ", chip(res.returns_autocorrelated ? tr("exp_v_autocorr") : tr("exp_v_no_autocorr"), res.returns_autocorrelated ? "warn" : "ok")]) }],
            [tr("exp_lb_squared"), { cell: lb(res.ljung_box_squared_p) }],
            [tr("exp_arch_lm"), { cell: h("span", {}, [pval(res.arch_lm_p) + " ", chip(res.volatility_clustering ? tr("exp_v_clustering") : tr("exp_v_no_clustering"), res.volatility_clustering ? "warn" : "ok")]) }],
        ]));
        box.appendChild(h("p", { class: "exp-meta", text: fmtStr(tr("exp_obs"), { n: res.n_obs }) }));
        return box;
    }

    function renderVarianceRatio(res) {
        var box = h("div", {});
        // la barre part de 1 (marche aléatoire) : au-dessus, les mouvements se prolongent ; en dessous, ils se corrigent
        box.appendChild(barChart({ values: res.rows.map(function (r) { return r.vr - 1; }), labels: res.rows.map(function (r) { return String(r.q); }),
            yMin: -0.5, yMax: 0.5, yFmt: function (v) { return num(1 + v, 2); }, title: tr("exp_vr_title"),
            strong: res.rows.map(function (r) { return r.significant === true; }) }));
        box.appendChild(table([tr("exp_vr_horizon"), tr("exp_vr_ratio"), tr("exp_vr_z"), tr("exp_col_p"), tr("exp_col_padj"), ""],
            res.rows.map(function (r) {
                return [{ cell: r.q, cls: "num" }, { cell: num(r.vr, 2), cls: "num pk-mono" }, numCell(num(r.z_robust, 2), r.z_robust),
                    { cell: pval(r.p_robust), cls: "num pk-mono" }, { cell: pval(r.p_adj), cls: "num pk-mono" },
                    { cell: r.significant ? chip(tr("exp_sig"), "pos") : "" }];
            })));
        var kind = res.verdict === "momentum" ? "pos" : (res.verdict === "mean_reversion" ? "neg" : "neutral");
        box.appendChild(h("p", { class: "exp-meta" }, [tr("exp_vr_joint") + " " + pval(res.joint_p) + " ", chip(tr("exp_vr_v_" + res.verdict), kind),
            " · " + fmtStr(tr("exp_obs"), { n: res.n_obs })]));
        return box;
    }

    function renderXcorr(res) {
        var box = h("div", {});
        box.appendChild(barChart({ values: res.values, labels: res.lags.map(String), band: res.band, yMin: -0.3, yMax: 0.3,
            strong: res.significant, title: tr("exp_xcorr_title") }));
        var meta = [tr("exp_xcorr_best") + " " + res.best_lag + " (ρ = " + num(res.best_value, 2) + ")",
            tr("exp_xcorr_zero") + " ρ = " + num(res.contemporaneous, 2)];
        if (res.portmanteau_valid && res.b_leads_p !== null && res.a_leads_p !== null) {
            meta.push(fmtStr(tr("exp_ccf_b_leads"), { a: PN.name(res.a), b: PN.name(res.b), p: pval(res.b_leads_p) }));
            meta.push(fmtStr(tr("exp_ccf_a_leads"), { a: PN.name(res.a), b: PN.name(res.b), p: pval(res.a_leads_p) }));
        }
        meta.push(fmtStr(tr("exp_obs"), { n: res.n_obs }));
        box.appendChild(h("p", { class: "exp-meta", text: meta.join(" · ") }));
        if (res.prewhitened) {
            var ar = res.ar_orders || {};
            box.appendChild(h("p", { class: "exp-meta", text: fmtStr(tr("exp_ccf_ar"), { a: PN.name(res.a), pa: ar[res.a], b: PN.name(res.b), pb: ar[res.b] }) }));
        } else {
            box.appendChild(h("p", { class: "exp-meta" }, [chip(tr("exp_ccf_raw_warn"), "warn")]));
        }
        return box;
    }

    function renderGranger(res) {
        function row(d) {
            return [{ cell: fmtStr(tr("exp_granger_dir"), { a: PN.name(d.cause), b: PN.name(d.effect) }), cls: "pk-mono" },
                { cell: d.order, cls: "num" }, { cell: pval(d.p_order), cls: "num pk-mono" }, { cell: pct(d.gain_order, 2), cls: "num pk-mono" },
                { cell: pval(d.p_bonferroni), cls: "num pk-mono" },
                { cell: chip(d.predictive ? tr("exp_v_predictive") : tr("exp_v_not_predictive"), d.predictive ? "pos" : "neutral") }];
        }
        var box = h("div", {}, [table(["", tr("exp_gr_order"), tr("exp_gr_p"), tr("exp_gr_gain"), tr("exp_gr_bonf"), ""], [row(res.a_to_b), row(res.b_to_a)])]);
        var meta = [fmtStr(tr("exp_obs"), { n: res.n_obs })];
        if (res.on === "abs") meta.push(tr("exp_gr_on_abs"));
        box.appendChild(h("p", { class: "exp-meta", text: meta.join(" · ") }));
        if (res.nonstationary && res.nonstationary.length) {
            box.appendChild(h("p", { class: "exp-meta" }, [chip(fmtStr(tr("exp_gr_nonstat"), { s: res.nonstationary.map(PN.label).join(", ") }), "warn")]));
        }
        return box;
    }

    // Dépendance non linéaire d'un couple, décalage par décalage (corrélation de distance ou information mutuelle).
    function renderDepPair(res) {
        var box = h("div", {});
        var title = tr(res.measure === "mi" ? "exp_mi_title" : "exp_dcor_title");
        box.appendChild(barChart({ values: res.values, labels: res.lags.map(String), yMin: 0, yMax: 0.3, strong: res.significant, title: title,
            hlines: [{ y: res.band, dash: "4 4" }], color: function () { return "var(--brand)"; } }));
        var maxPearson = Math.max.apply(null, res.pearson_abs.filter(function (v) { return v !== null; }));
        var meta = [tr("exp_xcorr_best") + " " + res.best_lag + " (" + num(res.best_value, 2) + ")", tr("exp_xcorr_zero") + " " + num(res.contemporaneous, 2),
            tr("exp_depp_threshold") + " " + num(res.band, 2), tr("exp_depp_pearson") + " " + num(maxPearson, 2)];
        box.appendChild(h("p", { class: "exp-meta", text: meta.join(" · ") }));
        var verdict = res.nonlinear_only ? chip(tr("exp_v_nonlinear_only"), "warn")
            : (res.contemporaneous_significant ? chip(tr("exp_v_linear_too"), "pos") : chip(tr("exp_v_no_link"), "neutral"));
        var line = [verdict, " " + fmtStr(tr("exp_obs"), { n: res.n_used })];
        if (res.windowed) line.push(" · " + fmtStr(tr("exp_depp_window"), { n: res.n_used, total: res.n_obs }));
        box.appendChild(h("p", { class: "exp-meta" }, line));
        return box;
    }

    function pairLabel(a, b) { return PN.name(a) + " × " + PN.name(b); }

    // Matrice de dépendance non linéaire de toute la sélection + les couples que Pearson ne voit pas.
    function renderDependence(res) {
        var box = h("div", {});
        var symbol = res.measure === "mi" ? "IC" : "dCor";
        box.appendChild(heatmap(res, { symbol: symbol, title: tr(res.measure === "mi" ? "exp_m_mi" : "exp_m_dcor") }));
        box.appendChild(h("div", { class: "exp-legend" }, [res.significant ? chip(tr("exp_legend_faded"), "faded") : null]));
        var meta = [fmtStr(tr("exp_corr_tests"), { n: res.n_tests }),
            tr("exp_dep_mean") + " " + num(res.mean_dependence, 2) + " " + tr("exp_dep_mean_pearson") + " " + num(res.mean_abs_pearson, 2),
            fmtStr(tr("exp_obs"), { n: res.n_used })];
        if (res.windowed) meta.push(fmtStr(tr("exp_dep_window"), { n: res.n_used, total: res.n_obs }));
        box.appendChild(h("p", { class: "exp-meta", text: meta.join(" · ") }));
        function listing(title, rows, gap) {
            var headers = [tr("exp_dep_col_pair"), tr("exp_dep_col_value"), tr("exp_dep_col_pearson")];
            if (gap) headers.push(tr("exp_dep_col_gap"));
            headers.push(tr("exp_col_padj"));
            return h("div", { class: "exp-pairs" }, [h("h4", { text: title }), table(headers, rows.map(function (r) {
                var cells = [{ cell: pairLabel(r.a, r.b), cls: "pk-mono" }, { cell: num(r.value, 2), cls: "num pk-mono" }, { cell: num(Math.abs(r.pearson), 2), cls: "num pk-mono" }];
                if (gap) cells.push(numCell(num(r.gap, 2), r.gap));
                cells.push({ cell: pval(r.p_adj), cls: "num pk-mono" });
                return cells;
            }))]);
        }
        var hidden = res.hidden.length ? listing(tr("exp_dep_hidden"), res.hidden, true)
            : h("div", { class: "exp-pairs" }, [h("h4", { text: tr("exp_dep_hidden") }), h("p", { class: "hint", "data-keep": "", text: tr("exp_dep_no_hidden") })]);
        box.appendChild(h("div", { class: "exp-two exp-two-wide" }, [listing(tr("exp_dep_strongest"), res.strongest, false), hidden]));
        return box;
    }

    // « Qui mène qui » : matrice de causalité de Granger, meneurs et liens significatifs.
    function renderGrangerMatrix(res) {
        var box = h("div", {});
        box.appendChild(grangerHeat(res));
        box.appendChild(h("div", { class: "exp-legend" }, [chip(tr("exp_gm_legend"), "pos")]));
        var meta = [fmtStr(tr("exp_gm_summary"), { e: res.n_edges, t: res.n_tests }), fmtStr(tr("exp_obs"), { n: res.n_obs })];
        if (res.on === "abs") meta.push(tr("exp_gr_on_abs"));
        box.appendChild(h("p", { class: "exp-meta", text: meta.join(" · ") }));
        if (!res.n_edges) { box.appendChild(h("p", { class: "hint", "data-keep": "", text: tr("exp_gm_none") })); return box; }
        var leaders = h("div", { class: "exp-pairs" }, [h("h4", { text: tr("exp_gm_leaders") }),
            table(["", tr("exp_gm_out"), tr("exp_gm_in"), tr("exp_gm_net")], res.leaders.filter(function (r) { return r.out || r.in; }).slice(0, 8).map(function (r) {
                return [{ cell: PN.name(r.symbol), cls: "pk-mono" }, { cell: r.out, cls: "num" }, { cell: r.in, cls: "num" }, numCell(String(r.net), r.net)];
            }))]);
        var edges = h("div", { class: "exp-pairs" }, [h("h4", { text: tr("exp_gm_edges") }),
            table([tr("exp_gm_col_link"), tr("exp_gm_col_order"), tr("exp_gm_col_q"), tr("exp_gm_col_gain")], res.edges.slice(0, 12).map(function (e) {
                return [{ cell: fmtStr(tr("exp_granger_dir"), { a: PN.name(e.cause), b: PN.name(e.effect) }), cls: "pk-mono" }, { cell: e.order, cls: "num" },
                    { cell: pval(e.p_adj), cls: "num pk-mono" }, { cell: e.gain === null ? "—" : pct(e.gain, 2), cls: "num pk-mono" }];
            }))]);
        box.appendChild(h("div", { class: "exp-two exp-two-wide" }, [leaders, edges]));
        return box;
    }

    function renderCoint(res) {
        var box = h("div", {});
        box.appendChild(table(["", "", "", "", ""], [[
            { cell: chip(res.cointegrated ? tr("exp_v_cointegrated") : tr("exp_v_not_cointegrated"), res.cointegrated ? "pos" : "neutral") },
            tr("exp_coint_p") + " " + pval(res.p_value), tr("exp_coint_hedge") + " " + num(res.hedge_ratio, 2),
            tr("exp_coint_half") + " " + (res.half_life_periods === null ? "—" : num(res.half_life_periods, 1)),
            tr("exp_coint_z") + " " + num(res.last_zscore, 2)]]));
        box.appendChild(lineChart({ dates: res.dates, series: [{ values: res.zscore }], hlines: [{ y: 0, dash: "0", color: "var(--line-strong)" }, { y: 2 }, { y: -2 }],
            title: tr("exp_zscore"), yFmt: function (v) { return num(v, 1); } }));
        return box;
    }

    function renderTail(res) {
        function line(label, p, ratio, hits, n) {
            return [label, { cell: pct(p, 1), cls: "num pk-mono" }, { cell: num(ratio, 1) + " " + tr("exp_tail_ratio"), cls: "num pk-mono" }, { cell: hits + " / " + n, cls: "num pk-mono" }];
        }
        return h("div", {}, [table(["", "P(B | A)", "", ""], [
            line(tr("exp_tail_lower"), res.lower, res.lower_ratio, res.lower_hits, res.lower_n),
            line(tr("exp_tail_upper"), res.upper, res.upper_ratio, res.upper_hits, res.upper_n)]),
            h("p", { class: "exp-meta", text: [tr("exp_tail_q") + " " + pct(res.q, 0), tr("exp_tail_corr") + " " + num(res.pearson, 2), fmtStr(tr("exp_obs"), { n: res.n_obs })].join(" · ") }),
            note(res.note || "")]);
    }

    function renderPca(res) {
        var box = h("div", {});
        var labels = res.explained.map(function (_, i) { return "PC" + (i + 1); });
        box.appendChild(barChart({ values: res.explained, labels: labels, yMin: 0, yMax: 1, title: tr("exp_pca_explained"), yFmt: function (v) { return pct(v, 0); },
            color: function () { return "var(--brand)"; } }));
        box.appendChild(h("p", { class: "exp-meta", text: [tr("exp_pca_first") + " " + pct(res.first_factor_share, 0), tr("exp_pca_n80") + " " + res.n_for_80pct,
            fmtStr(tr("exp_obs"), { n: res.n_obs })].join(" · ") }));
        var parts = res.components.slice(0, 3).map(function (c) {
            return h("div", { class: "exp-comp" }, [h("h4", { text: fmtStr(tr("exp_pca_comp"), { k: c.component }) + " · " + pct(c.explained, 0) }),
                table(["", tr("exp_pca_loadings")], c.loadings.slice(0, 8).map(function (l) { return [{ cell: PN.label(l.symbol) }, numCell(num(l.loading, 2), l.loading)]; }))]);
        });
        box.appendChild(h("div", { class: "exp-three" }, parts));
        return box;
    }

    function renderBeta(res) {
        var box = h("div", {});
        box.appendChild(table(["", "", "", ""], [[
            tr("exp_beta") + " " + num(res.beta, 2) + " (p " + pval(res.beta_p) + ")",
            tr("exp_alpha_ann") + " " + pct(res.alpha_annualized, 1) + " (p " + pval(res.alpha_p) + ")", tr("exp_r2") + " " + num(res.r2, 2),
            fmtStr(tr("exp_obs"), { n: res.n_obs })]]));
        box.appendChild(h("h4", { text: tr("exp_rolling_beta") }));
        box.appendChild(lineChart({ dates: res.dates, series: [{ values: res.rolling_beta }], hlines: [{ y: res.beta }, { y: 1, dash: "1 3" }], title: tr("exp_rolling_beta") }));
        return box;
    }

    function renderSeason(res) {
        var box = h("div", {});
        [["wd", "exp_season_weekday"], ["mo", "exp_season_month"]].forEach(function (k) {
            var rows = res.rows.filter(function (r) { return r.kind === k[0]; });
            if (!rows.length) return;
            box.appendChild(h("h4", { text: tr(k[1]) + (res.omnibus_p && res.omnibus_p[k[0] === "wd" ? "weekday" : "month"] !== undefined
                ? " · " + tr("exp_season_omnibus") + " " + pval(res.omnibus_p[k[0] === "wd" ? "weekday" : "month"]) : "") }));
            box.appendChild(barChart({ values: rows.map(function (r) { return r.excess; }), labels: rows.map(function (r) { return r.group; }),
                strong: rows.map(function (r) { return r.significant === true; }), yFmt: function (v) { return pct(v, 2); }, title: tr(k[1]) }));
            box.appendChild(table([tr("exp_col_group"), tr("exp_col_n"), tr("exp_season_excess"), tr("exp_col_hit"), tr("exp_col_t"), tr("exp_col_p"), tr("exp_col_padj"), ""],
                rows.map(function (r) {
                    return [{ cell: r.group, cls: "pk-mono" }, { cell: r.n, cls: "num" }, numCell(pct(r.excess, 3), r.excess), { cell: pct(r.hit_rate, 0), cls: "num pk-mono" },
                        { cell: num(r.t, 2), cls: "num pk-mono" }, { cell: pval(r.p), cls: "num pk-mono" }, { cell: pval(r.p_adj), cls: "num pk-mono" },
                        { cell: r.significant ? chip(tr("exp_sig"), "pos") : "" }];
                })));
        });
        if (res.turn_of_month) {
            box.appendChild(h("p", { class: "exp-meta", text: tr("exp_season_tom") + " : " + fmtStr(tr("exp_season_tom_cmp"), {
                a: pct(res.turn_of_month.mean_turn, 3), b: pct(res.turn_of_month.mean_rest, 3) }) + " (" + res.turn_of_month.n_turn + ")" }));
        }
        box.appendChild(h("p", { class: "exp-meta", text: fmtStr(tr("exp_obs"), { n: res.n_obs }) }));
        return box;
    }

    // ------------------------------------------------------------------ onglets
    function loadPanel(key) {
        if (loaded[key] === runId) return;
        loaded[key] = runId;
        if (key === "corr") {
            loadCorrelation();
            loadRolling();
        } else if (key === "dep") {
            loadDependence();
            loadGrangerMatrix();
        } else if (key === "dist") {
            job("exp-dist-out", "describe", {}, renderDescribe);
        } else if (key === "memory") {
            job("exp-stat-out", "stationarity", {}, renderStationarity);
            loadMemory();
        } else if (key === "link") {
            loadLink();
        } else if (key === "struct") {
            job("exp-pca-out", "pca", {}, renderPca);
            loadBeta();
        } else if (key === "season") {
            loadSeason();
        }
    }
    function loadCorrelation() {
        var method = $("exp-corr-method").value;
        if (method === "partial") job("exp-corr-out", "partial", {}, renderCorrelation);
        else job("exp-corr-out", "correlation", { method: method }, renderCorrelation);
    }
    function loadDependence() { job("exp-dep-out", "dependence", { measure: $("exp-dep-measure").value }, renderDependence); }
    function loadGrangerMatrix() {
        job("exp-gm-out", "granger_matrix", { maxlag: $("exp-gm-lags").value, on: $("exp-gm-on").value, scope: $("exp-gm-scope").value }, renderGrangerMatrix);
    }
    function loadRolling() {
        var p = pair("exp-roll");
        if (needPair("exp-roll-out", p)) job("exp-roll-out", "rolling", { a: p.a, b: p.b, window: $("exp-roll-window").value }, renderRolling);
    }
    function loadMemory() {
        var p = pair("exp-mem");
        if (p.a) {
            job("exp-mem-out", "memory", { a: p.a, nlags: $("exp-mem-lags").value }, renderMemory);
            job("exp-vr-out", "variance_ratio", { a: p.a }, renderVarianceRatio);
        }
    }
    function loadLink() {
        var p = pair("exp-link");
        if (!p.a || !p.b || p.a === p.b) {
            ["exp-xcorr-out", "exp-granger-out", "exp-dcor-out", "exp-mi-out", "exp-coint-out", "exp-tail-out"].forEach(function (id) { needPair(id, p); });
            return;
        }
        var lags = $("exp-link-lags").value, basis = $("exp-link-basis").value;
        job("exp-xcorr-out", "leadlag", { a: p.a, b: p.b, maxlag: lags, basis: basis, prewhiten: $("exp-link-prewhiten").checked ? 1 : 0,
            method: $("exp-link-rank").checked ? "spearman" : "pearson" }, renderXcorr);
        job("exp-granger-out", "granger", { a: p.a, b: p.b, maxlag: Math.min(10, lags), on: basis === "abs" ? "abs" : "returns" }, renderGranger);
        ["dcor", "mi"].forEach(function (measure) {
            job("exp-" + measure + "-out", "dependence_pair", { a: p.a, b: p.b, measure: measure, maxlag: Math.min(20, lags) }, renderDepPair);
        });
        job("exp-coint-out", "cointegration", { a: p.a, b: p.b }, renderCoint);
        job("exp-tail-out", "tail", { a: p.a, b: p.b, q: $("exp-link-q").value }, renderTail);
    }
    function loadBeta() {
        var p = pair("exp-beta");
        if (needPair("exp-beta-out", p)) job("exp-beta-out", "beta", { a: p.a, b: p.b, window: $("exp-beta-window").value }, renderBeta);
    }
    function loadSeason() {
        var p = pair("exp-season");
        if (p.a) job("exp-season-out", "seasonality", { a: p.a }, renderSeason);
    }

    function showPanel(key) {
        activePanel = key;
        document.querySelectorAll(".exp-tabs [role=tab]").forEach(function (tab) {
            var on = tab.dataset.panel === key;
            tab.setAttribute("aria-selected", on ? "true" : "false");
            tab.tabIndex = on ? 0 : -1;
        });
        document.querySelectorAll(".exp-panel").forEach(function (panel) { panel.hidden = panel.id !== "exp-panel-" + key; });
        if (selected().length) loadPanel(key);
    }

    function runAll() {
        var syms = selected();
        if (!syms.length) { $("exp-status").textContent = tr("exp_pick_one"); return; }
        runId += 1; loaded = {}; lastMeta = null;
        $("exp-status").textContent = tr("exp_running");
        $("exp-warnings").replaceChildren();
        loadPanel(activePanel);
    }

    // ------------------------------------------------------------------ câblage
    assets.addEventListener("change", onSelectionChange);
    $("exp-filter").addEventListener("input", function () {
        var q = this.value.trim().toLowerCase();
        Array.prototype.forEach.call(assets.options, function (o) { o.hidden = q !== "" && o.dataset.text.indexOf(q) < 0; });
    });
    $("exp-clear").addEventListener("click", function () {
        Array.prototype.forEach.call(assets.options, function (o) { o.selected = false; });
        onSelectionChange();
    });
    document.querySelectorAll("#exp-presets button[data-symbols]").forEach(function (b) {
        b.addEventListener("click", function () {
            var wanted = b.dataset.symbols.split(",");
            Array.prototype.forEach.call(assets.options, function (o) { o.selected = wanted.indexOf(o.value) >= 0; });
            onSelectionChange();
        });
    });
    document.querySelectorAll(".exp-period-btns .range-btn").forEach(function (b) {
        b.addEventListener("click", function () {
            document.querySelectorAll(".exp-period-btns .range-btn").forEach(function (x) { x.classList.toggle("active", x === b); });
            var years = parseInt(b.dataset.years, 10);
            if (!years) { $("exp-start").value = ""; return; }
            var d = new Date(); d.setFullYear(d.getFullYear() - years);
            $("exp-start").value = d.toISOString().slice(0, 10);
        });
    });
    $("exp-start").addEventListener("change", function () {
        document.querySelectorAll(".exp-period-btns .range-btn").forEach(function (x) { x.classList.remove("active"); });
    });
    $("exp-run").addEventListener("click", runAll);
    $("exp-corr-method").addEventListener("change", function () { loaded.corr = undefined; if (selected().length) loadPanel("corr"); });
    $("exp-dep-measure").addEventListener("change", function () { if (selected().length) loadDependence(); });
    $("exp-gm-run").addEventListener("click", loadGrangerMatrix);
    $("exp-roll-run").addEventListener("click", loadRolling);
    $("exp-mem-run").addEventListener("click", loadMemory);
    $("exp-link-run").addEventListener("click", loadLink);
    $("exp-beta-run").addEventListener("click", loadBeta);
    $("exp-season-run").addEventListener("click", loadSeason);
    document.querySelectorAll(".exp-tabs [role=tab]").forEach(function (tab, i, all) {
        tab.addEventListener("click", function () { showPanel(tab.dataset.panel); });
        tab.addEventListener("keydown", function (ev) {
            var next = ev.key === "ArrowRight" ? 1 : (ev.key === "ArrowLeft" ? -1 : 0);
            if (!next) return;
            ev.preventDefault();
            var target = all[(i + next + all.length) % all.length];
            target.focus(); showPanel(target.dataset.panel);
        });
    });

    // Début par défaut : 5 ans.
    var d5 = new Date(); d5.setFullYear(d5.getFullYear() - 5);
    $("exp-start").value = d5.toISOString().slice(0, 10);
    onSelectionChange();
    $("exp-status").textContent = tr("exp_not_run");
})();
