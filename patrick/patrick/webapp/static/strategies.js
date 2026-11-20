/* Page Stratégies (/strategies) : formulaire, étude en tâche de fond, résultats. Les textes viennent du bloc JSON `#st-i18n` (clés `st_*`) ; aucun calcul
   dans le navigateur : l'étude, son verdict et ses courbes arrivent de /api/strategies/*. Fonctions pures (mise en forme, drapeaux) testées sous Node. */
(function (root) {
    "use strict";

    // ------------------------------------------------------------------ fonctions pures
    var FLAG_ORDER = ["enough_events", "ci_above_zero", "oos_holds", "not_concentrated", "stable_best_day"];

    // Les jours de sortie montrés dans le tableau de la courbe : quelques repères, plus le meilleur jour, jamais au-delà du jour maximal.
    function keyDays(maxExit, best) {
        var days = [1, 2, 3, 5, 10, 15, 20, 30, 45, 60].filter(function (d) { return d <= maxExit; });
        if (maxExit > 0 && days.indexOf(maxExit) < 0) days.push(maxExit);
        if (best && days.indexOf(best) < 0) days.push(best);
        return days.sort(function (a, b) { return a - b; });
    }

    // Couleur de cellule de la matrice de sensibilité : intensité = |moyenne| / plus grand |moyenne| (0..1) ; le signe donne la teinte (CSS).
    function heat(value, maxAbs) {
        if (value === null || value === undefined || !isFinite(value) || !maxAbs) return 0;
        return Math.min(1, Math.abs(value) / maxAbs);
    }

    function maxAbs(cells) {
        return cells.reduce(function (m, c) { return c.mean === null || c.mean === undefined ? m : Math.max(m, Math.abs(c.mean)); }, 0);
    }

    // `{maturité: {ratio: cellule}}` à partir de la liste plate du serveur ; ordre des lignes et colonnes croissant.
    function pivot(cells) {
        var rows = {}, ratios = [];
        cells.forEach(function (c) {
            (rows[c.maturity] = rows[c.maturity] || {})[c.exit_ratio] = c;
            if (ratios.indexOf(c.exit_ratio) < 0) ratios.push(c.exit_ratio);
        });
        ratios.sort(function (a, b) { return a - b; });
        return { maturities: Object.keys(rows).map(Number).sort(function (a, b) { return a - b; }), ratios: ratios, rows: rows };
    }

    function verdictState(label) { return label === "robust" ? "ok" : (label === "fragile" ? "warning" : "error"); }

    var api = { FLAG_ORDER: FLAG_ORDER, keyDays: keyDays, heat: heat, maxAbs: maxAbs, pivot: pivot, verdictState: verdictState };
    if (typeof module === "object" && module.exports) module.exports = api;
    root.PatrickStrategies = api;

    // ------------------------------------------------------------------ interface
    var doc = root.document;
    if (!doc || !doc.getElementById("st-app")) return;

    var T = {};
    try { T = JSON.parse(doc.getElementById("st-i18n").textContent || "{}"); } catch (e) { T = {}; }
    var PRESETS = [];
    try { PRESETS = JSON.parse(doc.getElementById("st-presets").textContent || "[]"); } catch (e) { PRESETS = []; }
    var lang = doc.documentElement.lang || "fr";
    function t(key, params) {
        var s = T[key] || key;
        if (params) Object.keys(params).forEach(function (k) { s = s.split("{" + k + "}").join(params[k]); });
        return s;
    }
    function fmt(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : x.toLocaleString(lang, { minimumFractionDigits: d, maximumFractionDigits: d }); }
    function pct(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : fmt(x * 100, d === undefined ? 1 : d) + " %"; }
    function spct(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + pct(x, d); }
    function money(x) { return x === null || x === undefined || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + Math.round(x).toLocaleString(lang) + " €"; }
    function plain(x) { return x === null || x === undefined || !isFinite(x) ? "—" : Math.round(x).toLocaleString(lang) + " €"; }

    function h(tag, attrs, children) {
        var el = doc.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === null || v === undefined || v === false) return;
            if (k === "text") el.textContent = v;
            else if (k === "class") el.className = v;
            else if (k.indexOf("on") === 0) el.addEventListener(k.slice(2), v);
            else if (v === true) el.setAttribute(k, "");
            else el.setAttribute(k, v);
        });
        (children || []).forEach(function (c) { if (c) el.appendChild(typeof c === "string" ? doc.createTextNode(c) : c); });
        return el;
    }
    function hint(text) { return h("p", { class: "hint", "data-keep": "", text: text }); }
    function clear(el) { el.textContent = ""; return el; }
    function badge(text, state) { return h("span", { class: "status-badge status-" + state, text: text }); }

    function call(method, url, body) {
        var opt = { method: method, credentials: "same-origin" };
        if (body) opt.body = body;
        return root.fetch(url, opt).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
                return j;
            });
        });
    }

    var els = { tabs: doc.getElementById("st-tabs"), form: doc.getElementById("st-form-body"), result: doc.getElementById("st-result"), body: doc.getElementById("st-result-body") };
    var kind = (root.location.hash || "").replace("#", "") === "straddle" ? "straddle" : "event";
    var results = { event: null, straddle: null };
    var timer = null;
    var form = { source: "file", entry: "close_prev" };

    function setKind(next) {
        kind = next;
        try { root.history.replaceState(null, "", "#" + kind); } catch (e) { /* aperçu intégré */ }
        render();
        if (results[kind] === null) loadLast(kind);
    }
    function loadLast(k) {
        return call("GET", "/api/strategies/last/" + k).then(function (r) { results[k] = r.result || false; if (k === kind) renderResult(); }).catch(function () { results[k] = false; });
    }

    // ---- formulaire
    function field(label, input, extra) { return h("label", { class: "pl-label" }, [label, input, extra]); }
    function numInput(name, value, attrs) { return h("input", Object.assign({ type: "number", class: "pl-input pl-narrow", name: name, value: String(value) }, attrs || {})); }

    function renderForm() {
        var box = clear(els.form);
        var radios = ["file", "yahoo", "preset"].map(function (s) {
            return h("label", { class: "checkbox" }, [h("input", { type: "radio", name: "source", value: s, checked: form.source === s, onchange: function () { form.source = s; renderForm(); } }), " " + t("st_src_" + s)]);
        });
        box.appendChild(h("div", { class: "pl-row" }, radios));
        var inputs = {};
        if (form.source === "file") {
            inputs.events = h("input", { type: "file", class: "pl-file", accept: ".csv,.txt", "aria-label": t("st_src_file") });
            inputs.prices = h("input", { type: "file", class: "pl-file", accept: ".csv,.txt", "aria-label": t("st_prices_label") });
            inputs.fallback = h("input", { type: "checkbox", name: "fallback" });
            box.appendChild(h("div", { class: "pl-grid" }, [h("div", {}, [field(t("st_src_file"), inputs.events), hint(t("st_src_file_hint"))]),
                h("div", {}, [field(t("st_prices_label"), inputs.prices), h("label", { class: "checkbox" }, [inputs.fallback, " " + t("st_fallback")]), hint(t("st_prices_hint"))])]));
        } else if (form.source === "yahoo") {
            inputs.tickers = h("input", { type: "text", class: "pl-input", name: "tickers", placeholder: "AAPL, MSFT, NVDA", value: form.tickers || "", "aria-label": t("st_tickers") });
            inputs.quarters = numInput("quarters", 40, { min: "4", max: "80" });
            box.appendChild(h("div", { class: "pl-row" }, [field(t("st_tickers"), inputs.tickers), field(t("st_quarters"), inputs.quarters)]));
        } else {
            inputs.preset = h("select", { class: "pl-input", name: "preset", "aria-label": t("st_src_preset") }, PRESETS.map(function (p) { return h("option", { value: p, text: t("st_preset_" + p) }); }));
            box.appendChild(h("div", { class: "pl-row" }, [field(t("st_src_preset"), inputs.preset)]));
        }
        var p = {};
        box.appendChild(h("h3", { text: t("st_rule_h") }));
        if (kind === "event") {
            p.entry = h("select", { class: "pl-input", name: "entry", "aria-label": t("st_entry"), onchange: function (e) { form.entry = e.target.value; } },
                ["close_prev", "open_day0", "close_day0", "price"].map(function (v) { return h("option", { value: v, selected: form.entry === v, text: t("st_entry_" + v) }); }));
            p.max_exit = numInput("max_exit", 20, { min: "1", max: "60" });
            p.cost_bps = numInput("cost_bps", 10, { min: "0", max: "500", step: "1" });
            p.split = numInput("split", 70, { min: "30", max: "90", step: "5" });
            p.stake = numInput("stake", 10000, { min: "1", step: "100" });
            p.n_boot = numInput("n_boot", 2000, { min: "200", max: "20000", step: "200" });
            box.appendChild(h("div", { class: "pl-row" }, [field(t("st_entry"), p.entry), field(t("st_max_exit"), p.max_exit), field(t("st_cost"), p.cost_bps), field(t("st_split") + " (%)", p.split), field(t("st_stake"), p.stake), field(t("st_boot"), p.n_boot)]));
        } else {
            box.appendChild(hint(t("st_strad_note")));
            p.maturity_days = numInput("maturity_days", 7, { min: "1", max: "365" });
            p.strike = numInput("strike", 100, { min: "70", max: "130", step: "1" });
            p.entry_iv_mult = numInput("entry_iv_mult", 1.25, { min: "0.5", max: "3", step: "0.05" });
            p.exit_iv_ratio = numInput("exit_iv_ratio", 0.85, { min: "0.2", max: "2", step: "0.05" });
            p.lookback = numInput("lookback", 60, { min: "20", max: "250" });
            p.rate = numInput("rate", 4, { min: "0", max: "20", step: "0.25" });
            p.commission = numInput("commission", 0.65, { min: "0", step: "0.05" });
            p.half_spread = numInput("half_spread", 0.025, { min: "0", step: "0.005" });
            p.slippage = numInput("slippage", 0.005, { min: "0", step: "0.005" });
            p.stake = numInput("stake", 10000, { min: "1", step: "100" });
            p.split = numInput("split", 70, { min: "30", max: "90", step: "5" });
            box.appendChild(h("div", { class: "pl-row" }, [field(t("st_maturity"), p.maturity_days), field(t("st_strike"), p.strike), field(t("st_iv_in"), p.entry_iv_mult), field(t("st_iv_out"), p.exit_iv_ratio), field(t("st_lookback"), p.lookback)]));
            box.appendChild(h("div", { class: "pl-row" }, [field(t("st_rate"), p.rate), field(t("st_commission"), p.commission), field(t("st_spread"), p.half_spread), field(t("st_slippage"), p.slippage), field(t("st_stake"), p.stake), field(t("st_split") + " (%)", p.split)]));
        }
        var status = h("p", { class: "hint pl-status", "data-keep": "", role: "status" });
        var bar = h("progress", { class: "pl-progress", max: "100", value: "0", hidden: true });
        var button = h("button", { type: "button", class: "btn", text: t("st_run") });
        button.addEventListener("click", function () {
            var body = new root.FormData();
            body.append("kind", kind); body.append("source", form.source);
            var n = function (el) { return parseFloat(el.value); };
            var params = kind === "event"
                ? { entry: p.entry.value, max_exit: parseInt(p.max_exit.value, 10), cost_bps: n(p.cost_bps), split_frac: n(p.split) / 100, stake: n(p.stake), n_boot: parseInt(p.n_boot.value, 10) }
                : { maturity_days: parseInt(p.maturity_days.value, 10), strike_factor: n(p.strike) / 100, entry_iv_mult: n(p.entry_iv_mult), exit_iv_ratio: n(p.exit_iv_ratio),
                    lookback: parseInt(p.lookback.value, 10), rate: n(p.rate) / 100, commission: n(p.commission), half_spread: n(p.half_spread), slippage: n(p.slippage), stake: n(p.stake), split_frac: n(p.split) / 100 };
            body.append("params", JSON.stringify(params));
            if (form.source === "file") {
                if (!inputs.events.files.length) { status.textContent = t("st_need_events"); return; }
                body.append("events_file", inputs.events.files[0], inputs.events.files[0].name);
                if (inputs.prices.files.length) body.append("prices_file", inputs.prices.files[0], inputs.prices.files[0].name);
                if (inputs.fallback.checked) body.append("fallback", "true");
            } else if (form.source === "yahoo") {
                if (!inputs.tickers.value.trim()) { status.textContent = t("st_need_events"); return; }
                form.tickers = inputs.tickers.value; body.append("tickers", inputs.tickers.value); body.append("quarters", inputs.quarters.value);
            } else body.append("preset", inputs.preset.value);
            button.disabled = true; bar.hidden = false; bar.value = 0; status.textContent = t("st_running");
            call("POST", "/api/strategies/run", body).then(function (job) { poll(job.id, kind, bar, status, button); })
                .catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("st_failed", { e: e.message }); });
        });
        box.appendChild(h("div", { class: "pl-row" }, [button, bar, status]));
    }

    function poll(jobId, k, bar, status, button) {
        root.clearTimeout(timer);
        call("GET", "/api/strategies/jobs/" + jobId).then(function (job) {
            bar.value = Math.round(job.fraction * 100);
            status.textContent = job.status === "running" ? t("st_running") + " " + Math.round(job.fraction * 100) + " % · " + job.message : "";
            if (job.status === "running") { timer = root.setTimeout(function () { poll(jobId, k, bar, status, button); }, 1000); return; }
            button.disabled = false; bar.hidden = true;
            if (job.status === "error") { status.textContent = t("st_failed", { e: job.error }); return; }
            return loadLast(k);
        }).catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("st_failed", { e: e.message }); });
    }

    // ---- résultats
    function table(headers, rows, cls) {
        return h("div", { class: "table-scroll" }, [h("table", { class: "data-table " + (cls || "") }, [
            h("thead", {}, [h("tr", {}, headers.map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]), h("tbody", {}, rows)])]);
    }
    function row(cells, cls) { return h("tr", { class: cls || "" }, cells.map(function (c, i) { return h("td", { class: i ? "n" : "", text: c }); })); }

    function verdictCard(r) {
        var v = r.verdict, state = verdictState(v.label);
        var flags = FLAG_ORDER.filter(function (f) { return f in v.flags; }).map(function (f) {
            if (f === "oos_holds" && !v.oos_available) return h("li", { class: "st-flag is-na" }, ["– " + t("st_split_na")]);
            return h("li", { class: "st-flag " + (v.flags[f] ? "is-ok" : "is-ko") }, [(v.flags[f] ? "✓ " : "✗ ") + t("st_flag_" + f)]);
        });
        return h("div", { class: "card pl-card st-verdict st-" + state }, [
            h("div", { class: "pl-row pl-row-end" }, [badge(t("st_verdict_" + v.label), state), h("span", { class: "hint", "data-keep": "", text: t("st_generated", { d: r.generated_at.replace("T", " ").slice(0, 16), n: r.n_events, s: r.n_symbols, a: r.first_date, b: r.last_date }) })]),
            h("p", { text: t("st_verdict_" + v.label + "_txt") }), h("ul", { class: "st-flags" }, flags),
            Object.keys(r.skipped || {}).length ? hint(t("st_skipped", { list: Object.keys(r.skipped).map(function (k) { return r.skipped[k] + " " + k; }).join(", ") })) : null,
            (r.failed_symbols || []).length ? hint(t("st_failed_symbols", { list: r.failed_symbols.join(", ") })) : null]);
    }

    function curveSection(r) {
        var K = r.params.max_exit, best = r.best.k, b = r.bootstrap;
        var xs = r.curve.map(function (c) { return c.k; });
        var host = h("div", { class: "pl-chart", role: "img", "aria-label": t("st_curve_h") });
        function ser(key) { return r.curve.map(function (c) { return c[key] === undefined || c[key] === null ? null : c[key] * 100; }); }
        root.setTimeout(function () {
            if (!root.PatrickPlot) return;
            root.PatrickPlot.create(host, { type: "line", xKind: "index", xs: xs, xLabel: function (i) { return "J+" + xs[i]; }, height: 260, legend: true, markers: false, finance: false, zoomable: false,
                series: [{ name: t("st_col_mean"), color: "--brand", width: 2.6, values: ser("mean") }, { name: t("st_col_median"), color: "--text-3", width: 1.6, values: ser("median") },
                         { name: "IC95 ↑", color: "--pos", width: 1, dash: "4 3", values: b.ci_high.map(function (v) { return v * 100; }) }, { name: "IC95 ↓", color: "--neg", width: 1, dash: "4 3", values: b.ci_low.map(function (v) { return v * 100; }) }],
                yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        }, 0);
        var rows = keyDays(K, best).map(function (d) {
            var c = r.curve[d - 1];
            return row(["J+" + d, c.n, spct(c.mean), spct(c.median), pct(c.win, 0), spct(c.p05), spct(c.p95), pct(b.best_freq[d - 1], 0)], d === best ? "pl-pick is-on" : "");
        });
        return h("div", { class: "card pl-card" }, [h("h3", { text: t("st_curve_h") }), host, hint(t("st_curve_note")),
            table([t("st_col_day"), t("st_col_n"), t("st_col_mean"), t("st_col_median"), t("st_col_win"), t("st_col_p5"), t("st_col_p95"), t("st_col_stability")], rows)]);
    }

    function bestLine(r) {
        var b = r.best;
        return hint(t("st_best_line", { m: spct(b.mean), lo: spct(b.ci_low), hi: spct(b.ci_high), md: spct(b.median), w: pct(b.win, 0), n: b.n_complete }));
    }

    function splitBlock(r) {
        var s = r.split;
        if (!s.available) return hint(t("st_split_na"));
        return h("div", {}, [h("p", { class: "pl-wf" + (s.holds ? "" : " is-weak"), "data-keep": "", text: t("st_split_line", { k: s.k || 1, a: s.n_train, b: s.n_test, tm: spct(s.train_mean), tw: pct(s.train_win, 0), om: spct(s.test_mean), lo: spct(s.test_ci_low), hi: spct(s.test_ci_high), ow: pct(s.test_win, 0) }) }),
            hint(s.holds ? t("st_split_holds") : t("st_split_fails"))]);
    }

    function metricsBlock(r) {
        var m = r.metrics;
        var rows = [["st_m_win", pct(m.win_rate)], ["st_m_mean", spct(m.mean, 2)], ["st_m_median", spct(m.median, 2)], ["st_m_pf", m.profit_factor === null ? "—" : fmt(m.profit_factor, 2)],
                    ["st_m_payoff", m.payoff === null ? "—" : fmt(m.payoff, 2)], ["st_m_sharpe", m.sharpe_trade === null ? "—" : fmt(m.sharpe_trade, 2)], ["st_m_var", pct(m.var95)],
                    ["st_m_cvar", pct(m.cvar95)], ["st_m_dd", money(m.max_drawdown)], ["st_m_streak", String(m.max_losing_streak)], ["st_m_total", money(m.total_pnl)], ["st_m_best", spct(m.best, 0) + " / " + spct(m.worst, 0)]];
        return h("dl", { class: "pl-metrics" }, rows.reduce(function (acc, x) { return acc.concat([h("dt", { text: t(x[0]) }), h("dd", { text: x[1] })]); }, []));
    }

    function equityChart(r) {
        var host = h("div", { class: "pl-chart", role: "img", "aria-label": t("st_equity_h") });
        var xs = r.equity.dates.map(function (d) { return Date.parse(d); });
        root.setTimeout(function () {
            if (!root.PatrickPlot || !xs.length) return;
            root.PatrickPlot.create(host, { type: "line", xKind: "time", xs: xs, height: 220, legend: false, markers: false, finance: false, series: [{ name: t("st_m_total"), color: "--brand", width: 2.2, values: r.equity.pnl }],
                yFmt: function (v, d) { return fmt(v, 0) + " €"; }, tipFmt: function (v) { return money(v); } });
        }, 0);
        return h("div", {}, [h("h4", { text: t("st_equity_h") }), host, hint(t("st_equity_note"))]);
    }

    function concentrationBlock(r) {
        var c = r.concentration;
        return h("div", {}, [hint(t("st_conc_trim", { n: c.n_trimmed, m: spct(c.trimmed_mean) })), c.top5_share_of_gains === null ? null : hint(t("st_conc_top5", { p: pct(c.top5_share_of_gains, 0) })),
            table([t("st_col_year"), t("st_col_n"), t("st_col_mean"), t("st_col_win")], c.by_year.map(function (y) { return row([String(y.year), y.n, spct(y.mean), pct(y.win, 0)]); }))]);
    }

    function groupsBlock(r) {
        if (!r.groups || r.groups.length < 2) return null;
        return h("div", {}, [h("h4", { text: t("st_groups_h") }), table([t("st_col_group"), t("st_col_n"), t("st_col_mean"), t("st_col_median"), t("st_col_win")],
            r.groups.map(function (g) { return row([g.group, g.n, spct(g.mean), spct(g.median), pct(g.win, 0)]); }))]);
    }

    function extremesBlock(r) {
        function list(name, items) {
            return h("div", {}, [h("h4", { text: name }), table([t("st_col_symbol"), t("st_col_date"), t("st_col_ret")], items.map(function (e) { return row([e.symbol, e.date, spct(e.ret)]); }))]);
        }
        return h("div", { class: "pl-grid pl-grid-2" }, [list(t("st_ext_best"), r.extremes.best), list(t("st_ext_worst"), r.extremes.worst)]);
    }

    function sensitivityBlock(r) {
        var pv = pivot(r.sensitivity), top = maxAbs(r.sensitivity);
        var head = h("tr", {}, [h("th", {})].concat(pv.ratios.map(function (x) { return h("th", { class: "n", text: t("st_sens_col", { r: fmt(x, 2) }) }); })));
        var body = pv.maturities.map(function (m) {
            return h("tr", {}, [h("th", { class: "pl-corr-row", text: t("st_sens_row", { d: m }) })].concat(pv.ratios.map(function (x) {
                var c = pv.rows[m][x];
                return h("td", { class: "pl-corr " + (c && c.mean < 0 ? "is-neg" : "is-pos"), style: "--v:" + heat(c && c.mean, top).toFixed(2), title: c ? pct(c.win, 0) + " · n=" + c.n : "", text: c ? spct(c.mean) : "—" });
            })));
        });
        return h("div", { class: "card pl-card" }, [h("h3", { text: t("st_sens_h") }), hint(t("st_sens_note")), h("div", { class: "table-scroll" }, [h("table", { class: "pl-corrtable" }, [h("thead", {}, [head]), h("tbody", {}, body)])])]);
    }

    function renderResult() {
        var r = results[kind];
        els.result.hidden = !r;
        if (!r) return;
        var box = clear(els.body);
        box.appendChild(verdictCard(r));
        if (kind === "event") {
            box.appendChild(h("div", { class: "card pl-card" }, [h("h3", { text: t("st_best_h", { k: r.best.k }) }), bestLine(r), h("h4", { text: t("st_split_h") }), splitBlock(r)]));
            box.appendChild(curveSection(r));
        } else {
            box.appendChild(h("div", { class: "card pl-card" }, [h("h3", { text: t("st_strad_result_h") }), bestLine(r), hint(t("st_strad_line", { p: plain(r.mean_premium), mv: pct(r.mean_move), c: plain(r.cost_per_contract) })), h("h4", { text: t("st_split_h") }), splitBlock(r)]));
            box.appendChild(sensitivityBlock(r));
        }
        var tail = [h("h3", { text: t("st_metrics_h", { stake: plain(r.params.stake) }) }), metricsBlock(r), equityChart(r)];
        if (kind === "event" && r.last_metrics) tail.push(hint(t("st_last_h", { k: r.params.max_exit }) + " — " + t("st_last_line", { m: spct(r.last_metrics.mean), w: pct(r.last_metrics.win_rate, 0), dd: money(r.last_metrics.max_drawdown) })));
        tail.push(h("h4", { text: t("st_conc_h") }), concentrationBlock(r));
        var groups = groupsBlock(r);
        if (groups) tail.push(groups);
        tail.push(h("h4", { text: t("st_mc_h", { n: r.campaign.n_trades }) }), hint(t("st_mc_line", { p5: money(r.campaign.p05), p50: money(r.campaign.p50), p95: money(r.campaign.p95), pl: pct(r.campaign.proba_loss, 0) })));
        box.appendChild(h("div", { class: "card pl-card" }, tail));
        box.appendChild(h("div", { class: "card pl-card" }, [h("h3", { text: t("st_ext_h") }), extremesBlock(r)]));
    }

    function render() {
        Array.prototype.forEach.call(els.tabs.querySelectorAll(".kind-tab"), function (a) {
            a.classList.toggle("active", a.dataset.kind === kind);
            a.onclick = function (e) { e.preventDefault(); setKind(a.dataset.kind); };
        });
        renderForm();
        renderResult();
    }
    render();
    loadLast(kind);
})(typeof window !== "undefined" ? window : globalThis);
