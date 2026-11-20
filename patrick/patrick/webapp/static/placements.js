/* Page Placements (/placements) : import de VL, simulation en tâche de fond, résultats.
   Deux parties : des fonctions PURES (choix de la meilleure allocation, CSV, couleurs) testées sous Node (tests/js/placements.test.js),
   puis l'interface, lancée seulement si la page est là. Tout texte vient du bloc JSON `#pl-i18n` (clés `pl_*`). Le serveur ne fait aucun
   calcul à l'affichage : les jeux de données, le dernier résultat et l'avancement arrivent par /api/placements/*. */
(function (root) {
    "use strict";

    // ------------------------------------------------------------------ fonctions pures
    var CRITERIA = ["wf_sharpe", "sharpe", "cagr", "vol"];

    function criterionValue(pf, crit) {
        var wf = pf.walk_forward && pf.walk_forward.sharpe;
        if (crit === "wf_sharpe") return (wf === null || wf === undefined) ? -Infinity : wf;
        if (crit === "sharpe") return pf.metrics.sharpe;
        if (crit === "cagr") return pf.metrics.cagr;
        if (crit === "vol") return -pf.metrics.vol;
        return -Infinity;
    }

    // La meilleure allocation d'une fenêtre selon un critère, parmi celles dont la volatilité ne dépasse pas `maxVol` (null = sans limite).
    // `null` si aucune ne respecte la limite. Les égalités sont départagées par l'ordre du résultat (stable).
    function pickBest(portfolios, windowId, crit, maxVol) {
        var pool = portfolios.filter(function (pf) {
            return pf.window === windowId && !(maxVol !== null && maxVol !== undefined && pf.metrics.vol > maxVol + 1e-12);
        });
        // Un walk-forward sur moins de 36 mois hors échantillon est du bruit (un fonds quasi monétaire y obtient un Sharpe énorme) : sur ce
        // critère, les portefeuilles au test fiable passent d'abord ; s'il n'y en a aucun dans la fenêtre, on garde les autres.
        if (crit === "wf_sharpe") {
            var reliable = pool.filter(function (pf) { return !(pf.walk_forward && pf.walk_forward.peu_fiable); });
            if (reliable.length) pool = reliable;
        }
        var best = null, bestValue = -Infinity;
        pool.forEach(function (pf) {
            var v = criterionValue(pf, crit);
            if (best === null || v > bestValue) { best = pf; bestValue = v; }
        });
        return best;
    }

    function csvCell(v) {
        var s = v === null || v === undefined ? "" : String(v);
        return /[";\n\r]/.test(s) ? "\"" + s.replace(/"/g, "\"\"") + "\"" : s;
    }
    // CSV (séparateur « ; », ouvrable tel quel dans un Excel français) : lignes = tableaux de valeurs.
    function toCsv(rows) {
        return rows.map(function (r) { return r.map(csvCell).join(";"); }).join("\r\n");
    }

    // Couleur d'une corrélation : intensité = |valeur|, teinte = signe. Retourne une valeur de 0 à 1 pour la variable CSS --v.
    function corrIntensity(v) {
        if (v === null || v === undefined || !isFinite(v)) return 0;
        return Math.min(1, Math.abs(v));
    }

    function maxVolOf(portfolios, windowId) {
        var m = 0;
        portfolios.forEach(function (pf) { if (pf.window === windowId && pf.metrics.vol > m) m = pf.metrics.vol; });
        return m;
    }

    var api = { CRITERIA: CRITERIA, criterionValue: criterionValue, pickBest: pickBest, toCsv: toCsv, corrIntensity: corrIntensity, maxVolOf: maxVolOf };
    if (typeof module === "object" && module.exports) module.exports = api;
    root.PatrickPlacements = api;

    // ------------------------------------------------------------------ interface
    var doc = root.document;
    if (!doc || !doc.getElementById("pl-app")) return;

    var T = {};
    try { T = JSON.parse(doc.getElementById("pl-i18n").textContent || "{}"); } catch (e) { T = {}; }
    var lang = doc.documentElement.lang || "fr";
    function t(key, params) {
        var s = T[key] || key;
        if (params) Object.keys(params).forEach(function (k) { s = s.split("{" + k + "}").join(params[k]); });
        return s;
    }
    function fmt(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : x.toLocaleString(lang, { minimumFractionDigits: d, maximumFractionDigits: d }); }
    function pct(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : fmt(x * 100, d === undefined ? 1 : d) + " %"; }
    function eur(x) { return x === null || x === undefined || !isFinite(x) ? "—" : Math.round(x).toLocaleString(lang) + " €"; }
    function num(x, d) { return fmt(x, d === undefined ? 2 : d); }

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

    function call(method, url, body, isForm) {
        var opt = { method: method, credentials: "same-origin", headers: {} };
        if (body && !isForm) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
        else if (body) opt.body = body;
        return root.fetch(url, opt).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
                return j;
            });
        });
    }

    var STORE_KEY = "patrick.placements.v1";
    var els = { data: doc.getElementById("pl-data-body"), run: doc.getElementById("pl-run"), runBody: doc.getElementById("pl-run-body"),
                result: doc.getElementById("pl-result"), resultBody: doc.getElementById("pl-result-body") };
    var state = { datasets: [], id: null, ds: null, result: null, creating: false, timer: null, busy: false, notice: null,
                  sel: { window: null, crit: "wf_sharpe", maxVol: null, pid: null, centering: "prudent", unit: "ann", statWindow: null } };
    try { state.id = (JSON.parse(root.localStorage.getItem(STORE_KEY) || "{}") || {}).id || null; } catch (e) { state.id = null; }
    function remember() { try { root.localStorage.setItem(STORE_KEY, JSON.stringify({ id: state.id })); } catch (e) { /* stockage indisponible */ } }

    var OBJ_KEYS = ["max_return", "max_sharpe", "min_vol", "max_sortino"];
    var METHOD_KEYS = ["bootstrap blocs 6 mois", "bootstrap i.i.d.", "bootstrap stationnaire", "GARCH résidus", "Monte Carlo μ incertain"];
    var CAPS = [1, 0.5, 0.4, 0.3];
    var PALETTE = ["--ra-c1", "--ra-c2", "--ra-c3", "--ra-c4", "--ra-c5", "--ra-c6", "--ra-c7", "--ra-c8"];

    function objectiveName(o) { return t("pl_obj_" + o); }
    function capName(cap) { return cap === null || cap === undefined || cap >= 1 ? t("pl_cap_none") : Math.round(cap * 100) + " %"; }
    function windowName(w) { return t("pl_window_value", { d: w.start, m: w.months }); }

    // ---- 1. données
    function loadAll() {
        return call("GET", "/api/placements/datasets").then(function (list) {
            state.datasets = list;
            if (!state.id || !list.some(function (d) { return d.id === state.id; })) state.id = list.length ? list[0].id : null;
            return state.id ? selectDataset(state.id) : (render(), null);
        }).catch(function (e) { clear(els.data).appendChild(hint(e.message)); });
    }

    function selectDataset(id) {
        state.id = id; state.creating = false; remember();
        return Promise.all([call("GET", "/api/placements/datasets/" + id), call("GET", "/api/placements/datasets/" + id + "/result")]).then(function (r) {
            state.ds = r[0]; state.result = r[1].result;
            state.sel.window = null; state.sel.pid = null;
            render();
        }).catch(function (e) { state.notice = e.message; render(); });
    }

    function importForm(dataset) {
        var name = h("input", { type: "text", class: "pl-input", maxlength: "80", placeholder: t("pl_name_ph"), "aria-label": t("pl_dataset") });
        var files = h("input", { type: "file", multiple: true, accept: ".csv,.txt,.xlsx,.xlsm", class: "pl-file", "aria-label": t("pl_import_h") });
        var status = h("p", { class: "hint", "data-keep": "", role: "status" });
        var button = h("button", { type: "submit", class: "btn", text: dataset ? t("pl_add_files") : t("pl_import_btn") });
        var form = h("form", { class: "pl-import", onsubmit: function (e) {
            e.preventDefault();
            if (!files.files.length) return;
            var body = new FormData();
            if (!dataset) body.append("name", name.value);
            Array.prototype.forEach.call(files.files, function (f) { body.append("files", f, f.name); });
            button.disabled = true; status.textContent = t("pl_importing");
            call("POST", dataset ? "/api/placements/datasets/" + dataset.id + "/files" : "/api/placements/datasets", body, true).then(function (res) {
                var ok = res.report.filter(function (r) { return r.ok; }).length, bad = res.report.filter(function (r) { return !r.ok; });
                state.notice = t("pl_import_done", { n: ok }) + (bad.length ? " · " + t("pl_import_failed", { n: bad.length }) + " : " + bad.map(function (b) { return b.error; }).join(" ") : "");
                state.id = res.dataset.id; remember(); return loadAll();
            }).catch(function (err) { status.textContent = err.message; button.disabled = false; });
        } }, [dataset ? null : name, files, button, status]);
        return form;
    }

    function saveSettings(patch) {
        return call("POST", "/api/placements/datasets/" + state.id + "/settings", patch).then(function (ds) { state.ds = ds; render(); })
            .catch(function (e) { state.notice = e.message; render(); });
    }

    function fundsTable(ds) {
        var keys = Object.keys(ds.funds);
        var head = h("tr", {}, [t("pl_col_use"), t("pl_col_fund"), t("pl_col_start"), t("pl_col_end"), t("pl_col_points"), t("pl_col_check"), ""].map(function (c) { return h("th", { text: c }); }));
        var rows = keys.map(function (k) {
            var f = ds.funds[k], isCash = ds.cash === k;
            var check = f.checks && f.checks.length ? f.checks[f.checks.length - 1] : null;
            var checkText = check ? (check.points_communs ? t("pl_check_value", { n: check.points_communs, gap: num(check.ecart_max, 4) }) : t("pl_check_new", { n: check.nouveaux_points })) : "";
            var useBox = h("input", { type: "checkbox", "aria-label": t("pl_col_use") + " " + f.label, checked: !f.excluded || isCash, disabled: isCash, onchange: function (e) {
                var ex = {}; ex[k] = !e.target.checked; saveSettings({ excluded: ex });
            } });
            var del = h("button", { type: "button", class: "btn-secondary pl-small", title: t("pl_remove_fund"), "aria-label": t("pl_remove_fund") + " " + f.label, text: "✕", onclick: function () {
                if (!root.confirm(t("pl_remove_confirm", { name: f.label }))) return;
                call("DELETE", "/api/placements/datasets/" + ds.id + "/funds/" + encodeURIComponent(k)).then(function (d) { state.ds = d; render(); }).catch(function (e) { state.notice = e.message; render(); });
            } });
            return h("tr", { class: f.excluded && !isCash ? "pl-off" : "" }, [
                h("td", {}, [useBox]),
                h("td", {}, [f.label, isCash ? h("span", { class: "status-badge status-neutral pl-badge", text: t("pl_cash_badge") }) : null]),
                h("td", { text: f.start }), h("td", { text: f.end }), h("td", { class: "n", text: f.points.toLocaleString(lang) }),
                h("td", {}, [h("span", { class: "hint", "data-keep": "", text: checkText })]), h("td", {}, [del])]);
        });
        return h("div", { class: "table-scroll" }, [h("table", { class: "data-table pl-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]);
    }

    function dataPanel() {
        var box = clear(els.data);
        if (state.notice) { box.appendChild(h("p", { class: "banner banner-info", role: "status", text: state.notice })); state.notice = null; }
        var ds = state.creating ? null : state.ds;
        if (state.datasets.length) {
            var select = h("select", { class: "pl-input", "aria-label": t("pl_dataset"), onchange: function (e) { if (e.target.value === "__new__") { state.creating = true; state.ds = null; render(); } else selectDataset(e.target.value); } },
                state.datasets.map(function (d) { return h("option", { value: d.id, selected: !state.creating && d.id === state.id, text: d.name + " (" + d.n_funds + ")" }); })
                    .concat([h("option", { value: "__new__", selected: state.creating, text: "+ " + t("pl_import_h") })]));
            box.appendChild(h("div", { class: "pl-row" }, [h("label", { class: "pl-label" }, [t("pl_dataset"), select])]));
        } else {
            box.appendChild(hint(t("pl_no_dataset")));
        }
        if (!ds) {
            box.appendChild(h("h3", { text: t("pl_import_h") }));
            box.appendChild(hint(t("pl_import_hint")));
            box.appendChild(importForm(null));
            return;
        }
        var amount = h("input", { type: "number", class: "pl-input", min: "1", step: "100", value: String(ds.amount), "aria-label": t("pl_amount_label"), onchange: function (e) { saveSettings({ amount: parseFloat(e.target.value) }); } });
        var cashSel = h("select", { class: "pl-input", "aria-label": t("pl_cash_label"), onchange: function (e) { saveSettings({ set_cash: true, cash: e.target.value === "" ? null : e.target.value }); } },
            [h("option", { value: "", selected: !ds.cash, text: t("pl_cash_none") })].concat(Object.keys(ds.funds).map(function (k) { return h("option", { value: k, selected: ds.cash === k, text: ds.funds[k].label }); })));
        var rf = h("input", { type: "number", class: "pl-input", step: "0.1", min: "-5", max: "30", value: String(Math.round((ds.rf_annual || 0) * 1000) / 10), disabled: !!ds.cash, "aria-label": t("pl_rf_label"),
                              onchange: function (e) { saveSettings({ rf_annual: parseFloat(e.target.value) / 100 }); } });
        box.appendChild(h("div", { class: "pl-row" }, [
            h("label", { class: "pl-label" }, [t("pl_amount_label"), amount]), h("label", { class: "pl-label" }, [t("pl_cash_label"), cashSel]),
            h("label", { class: "pl-label" }, [t("pl_rf_label") + " (%)", rf])]));
        box.appendChild(fundsTable(ds));
        box.appendChild(h("div", { class: "pl-row pl-row-end" }, [importForm(ds), h("button", { type: "button", class: "btn-secondary", text: t("pl_delete_dataset"), onclick: function () {
            if (!root.confirm(t("pl_delete_confirm", { name: ds.name }))) return;
            call("DELETE", "/api/placements/datasets/" + ds.id).then(function () { state.id = null; state.ds = null; state.result = null; return loadAll(); }).catch(function (e) { state.notice = e.message; render(); });
        } })]));
    }

    // ---- 2. simulation
    function checkboxes(name, items, label, isChecked) {
        return h("fieldset", { class: "pl-fieldset" }, [h("legend", { text: name })].concat(items.map(function (it) {
            return h("label", { class: "checkbox" }, [h("input", { type: "checkbox", name: label, value: String(it.value), checked: isChecked(it.value) }), " " + it.label]);
        })));
    }

    function runPanel() {
        var ds = state.creating ? null : state.ds;
        var risky = ds ? Object.keys(ds.funds).filter(function (k) { return !ds.funds[k].excluded && k !== ds.cash; }).length : 0;
        els.run.hidden = !ds;
        if (!ds) return;
        var box = clear(els.runBody);
        if (risky < 2) { box.appendChild(hint(t("pl_need_funds"))); return; }
        var horizon = h("input", { type: "number", class: "pl-input pl-narrow", name: "horizon", min: "1", max: "10", value: "5", "aria-label": t("pl_horizon") });
        var sims = h("select", { class: "pl-input", name: "sims", "aria-label": t("pl_sims") }, [5000, 20000, 50000].map(function (n) { return h("option", { value: String(n), selected: n === 20000, text: n.toLocaleString(lang) }); }));
        var windows = h("fieldset", { class: "pl-fieldset" }, [h("legend", { text: t("pl_windows") }), hint(t("pl_windows_auto"))].concat((ds.windows || []).map(function (w) {
            return h("label", { class: "checkbox" }, [h("input", { type: "checkbox", name: "window", value: w.start }), " " + t("pl_window_row", { d: w.start, m: w.months, n: w.funds })]);
        })));
        var advanced = h("details", { class: "adv" }, [h("summary", { class: "adv-summary", text: t("pl_advanced") }),
            h("div", { class: "pl-grid" }, [
                checkboxes(t("pl_methods"), METHOD_KEYS.map(function (m) { return { value: m, label: m }; }), "method", function () { return true; }),
                h("label", { class: "pl-label" }, [t("pl_sims"), sims]), windows])]);
        var status = h("p", { class: "hint pl-status", "data-keep": "", role: "status" });
        var bar = h("progress", { class: "pl-progress", max: "100", value: "0", hidden: true });
        var button = h("button", { type: "button", class: "btn", id: "pl-go", text: t("pl_run") });
        function values(name) { return Array.prototype.map.call(box.querySelectorAll("input[name=" + name + "]:checked"), function (i) { return i.value; }); }
        button.addEventListener("click", function () {
            var body = { horizon_years: parseInt(horizon.value, 10) || 5, objectives: values("objective"), caps: values("cap").map(parseFloat),
                         methods: values("method"), n_sims: parseInt(sims.value, 10), windows: values("window") };
            button.disabled = true; bar.hidden = false; bar.value = 0; status.textContent = t("pl_running");
            call("POST", "/api/placements/datasets/" + ds.id + "/analyse", body).then(function (job) { poll(job.id, bar, status, button); })
                .catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("pl_failed", { e: e.message }); });
        });
        box.appendChild(h("div", { class: "pl-grid" }, [
            h("label", { class: "pl-label" }, [t("pl_horizon"), horizon]),
            checkboxes(t("pl_objectives"), OBJ_KEYS.map(function (o) { return { value: o, label: objectiveName(o) }; }), "objective", function () { return true; }),
            checkboxes(t("pl_caps"), CAPS.map(function (c) { return { value: c, label: capName(c) }; }), "cap", function (v) { return v === 1 || v === 0.4; })]));
        box.appendChild(advanced);
        box.appendChild(h("div", { class: "pl-row" }, [button, bar, status]));
    }

    function poll(jobId, bar, status, button) {
        root.clearTimeout(state.timer);
        call("GET", "/api/placements/jobs/" + jobId).then(function (job) {
            bar.value = Math.round(job.fraction * 100);
            status.textContent = job.status === "running" ? t("pl_running") + " " + Math.round(job.fraction * 100) + " % · " + job.message : "";
            if (job.status === "running") { state.timer = root.setTimeout(function () { poll(jobId, bar, status, button); }, 1000); return; }
            button.disabled = false; bar.hidden = true;
            if (job.status === "error") { status.textContent = t("pl_failed", { e: job.error }); return; }
            return call("GET", "/api/placements/datasets/" + state.id + "/result").then(function (r) { state.result = r.result; state.sel.window = null; state.sel.pid = null; renderResult(); });
        }).catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("pl_failed", { e: e.message }); });
    }

    // ---- 3. résultats
    function metricsGrid(pf) {
        var m = pf.metrics;
        var rows = [["pl_m_cagr", pct(m.cagr)], ["pl_m_vol", pct(m.vol)], ["pl_m_sharpe", num(m.sharpe)], ["pl_m_sortino", num(m.sortino)],
                    ["pl_m_mdd", pct(m.max_dd_daily)], ["pl_m_worst12", pct(m.worst_12m)], ["pl_m_var5", pct(m.var5)]];
        return h("dl", { class: "pl-metrics" }, rows.reduce(function (acc, r) { return acc.concat([h("dt", { text: t(r[0]) }), h("dd", { text: r[1] })]); }, []));
    }

    function weightsBlock(pf) {
        return h("table", { class: "data-table pl-weights" }, [h("thead", {}, [h("tr", {}, [h("th", { text: t("pl_col_fund") }), h("th", { text: t("pl_col_weight") }), h("th", { class: "n", text: t("pl_col_amount") })]) ]),
            h("tbody", {}, pf.weights.map(function (w) {
                return h("tr", {}, [h("td", { text: w.label }), h("td", {}, [h("span", { class: "pl-bar", style: "--w:" + (w.weight * 100).toFixed(1) + "%" }), " " + pct(w.weight)]), h("td", { class: "n", text: eur(w.amount) })]);
            }))]);
    }

    function walkForwardBlock(pf) {
        var wf = pf.walk_forward;
        if (!wf || wf.sharpe === null || wf.sharpe === undefined) return h("p", { class: "hint", "data-keep": "", text: t("pl_wf_none") });
        var parts = [t("pl_wf_line", { s: num(wf.sharpe), b: num(wf.sharpe_1n), m: wf.mois_hors_echantillon }), wf.significatif ? t("pl_wf_sig") : t("pl_wf_nosig")];
        if (wf.peu_fiable) parts.push(t("pl_wf_unreliable"));
        return h("p", { class: "pl-wf" + (wf.peu_fiable ? " is-weak" : ""), "data-keep": "", text: parts.join(" ") });
    }

    function scenarioBlock(pf, amount, years) {
        var sel = state.sel;
        function seg(name, options, key) {
            return h("span", { class: "pl-seg", role: "group" }, options.map(function (o) {
                return h("button", { type: "button", class: "pl-seg-btn", "aria-pressed": sel[key] === o[0] ? "true" : "false", text: o[1], onclick: function () { sel[key] = o[0]; renderResult(); } });
            }));
        }
        var qs = ["05", "25", "50", "75", "95"];
        var head = h("tr", {}, [t("pl_col_method")].concat(qs.map(function (q) { return "P" + parseInt(q, 10); })).concat([t("pl_col_loss")]).map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }));
        var rows = Object.keys(pf.scenarios || {}).map(function (name) {
            var s = pf.scenarios[name][sel.centering];
            if (!s) return h("tr", { class: "pl-off" }, [h("td", { text: name }), h("td", { colspan: "6" }, [h("span", { class: "hint", "data-keep": "", text: t("pl_garch_off", { m: pf.garch ? pf.garch.motif : "" }) })])]);
            return h("tr", {}, [h("td", { text: name })].concat(qs.map(function (q) {
                return h("td", { class: "n", text: sel.unit === "ann" ? pct(s["ann_p" + q]) : eur(amount * (1 + s["cum_p" + q])) });
            })).concat([h("td", { class: "n", text: pct(s.proba_perte) })]));
        });
        var hist = pf.history;
        return h("div", { class: "pl-scn" }, [
            h("h4", { text: t("pl_scn_h", { y: years }) }),
            h("div", { class: "pl-row" }, [seg("c", [["historique", t("pl_cen_hist")], ["prudent", t("pl_cen_prudent")]], "centering"), seg("u", [["ann", t("pl_unit_ann")], ["final", t("pl_unit_final")]], "unit")]),
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]),
            hint(t("pl_scn_note")),
            hist ? hint(t("pl_hist_line", { y: years, w: pct(hist.pire), a: pct(hist.moyen), b: pct(hist.meilleur), n: num(hist.blocs_indep, 1) })) : null]);
    }

    function paintChart(host, opts) {
        if (!root.PatrickPlot) { host.textContent = ""; return; }
        root.PatrickPlot.create(host, opts);
    }

    function fanChart(pf, years) {
        var fan = pf.fan && pf.fan[state.sel.centering];
        var host = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_fan_h") });
        if (!fan) return host;
        var xs = [0].concat(fan.annees);
        function vals(k) { return [0].concat(fan[k].map(function (v) { return v * 100; })); }
        root.setTimeout(function () {
            paintChart(host, { type: "line", xKind: "index", xs: xs, xLabel: function (i) { return i === 0 ? "0" : t("pl_fan_year", { n: i }); }, height: 240, legend: true, markers: false, finance: false, zoomable: false,
                series: [{ name: "P5", color: "--neg", width: 1.6, values: vals("p05") }, { name: "P25", color: "--text-3", width: 1.2, dash: "4 3", values: vals("p25") },
                         { name: "P50", color: "--brand", width: 2.6, values: vals("p50") }, { name: "P75", color: "--text-3", width: 1.2, dash: "4 3", values: vals("p75") },
                         { name: "P95", color: "--pos", width: 1.6, values: vals("p95") }],
                yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        }, 0);
        return host;
    }

    function portfolioDetail(pf, r) {
        var years = r.params.horizon_years;
        return h("div", { class: "pl-detail" }, [
            h("div", { class: "pl-detail-head" }, [h("h3", { text: objectiveName(pf.objective) + " · " + t("pl_col_cap") + " " + capName(pf.cap) })]),
            h("div", { class: "pl-grid pl-grid-2" }, [h("div", {}, [weightsBlock(pf)]), h("div", {}, [metricsGrid(pf), h("h4", { text: t("pl_wf_h") }), walkForwardBlock(pf)])]),
            scenarioBlock(pf, r.params.amount, years),
            h("h4", { text: t("pl_fan_h") }), fanChart(pf, years)]);
    }

    function bestSection(r) {
        var sel = state.sel;
        var winSel = h("select", { class: "pl-input", "aria-label": t("pl_window"), onchange: function (e) { sel.window = e.target.value; sel.pid = null; sel.maxVol = null; renderResult(); } },
            r.windows.map(function (w) { return h("option", { value: w.id, selected: w.id === sel.window, text: windowName(w) }); }));
        var critSel = h("select", { class: "pl-input", "aria-label": t("pl_criterion"), onchange: function (e) { sel.crit = e.target.value; sel.pid = null; renderResult(); } },
            CRITERIA.map(function (c) { return h("option", { value: c, selected: c === sel.crit, text: t("pl_crit_" + c) }); }));
        var top = maxVolOf(r.portfolios, sel.window);
        var volValue = sel.maxVol === null ? top : sel.maxVol;
        var volLabel = h("output", { class: "pl-out", text: sel.maxVol === null ? t("pl_maxvol_any") : pct(sel.maxVol) });
        var vol = h("input", { type: "range", class: "pl-range", min: "0", max: String(Math.ceil(top * 1000) / 1000), step: "0.001", value: String(volValue), "aria-label": t("pl_maxvol"),
            oninput: function (e) { var v = parseFloat(e.target.value); sel.maxVol = v >= top - 1e-9 ? null : v; sel.pid = null; volLabel.textContent = sel.maxVol === null ? t("pl_maxvol_any") : pct(sel.maxVol); },
            onchange: function () { renderResult(); } });
        var picked = pickBest(r.portfolios, sel.window, sel.crit, sel.maxVol);
        var chosen = sel.pid ? r.portfolios.filter(function (p) { return p.id === sel.pid; })[0] : picked;
        return h("div", { class: "card pl-card" }, [
            h("h3", { text: t("pl_best_h") }),
            h("div", { class: "pl-row" }, [h("label", { class: "pl-label" }, [t("pl_window"), winSel]), h("label", { class: "pl-label" }, [t("pl_criterion"), critSel]),
                h("label", { class: "pl-label" }, [t("pl_maxvol"), h("span", { class: "pl-range-row" }, [vol, volLabel])])]),
            picked ? portfolioDetail(chosen || picked, r) : hint(t("pl_no_match"))]);
    }

    function allocationsTable(r) {
        var head = h("tr", {}, [t("pl_window"), t("pl_col_obj"), t("pl_col_cap"), t("pl_col_alloc"), t("pl_m_cagr"), t("pl_m_vol"), t("pl_m_sharpe"), t("pl_col_wf"), t("pl_col_1n")].map(function (c, i) { return h("th", { class: i > 3 ? "n" : "", text: c }); }));
        var rows = r.portfolios.map(function (pf) {
            var wf = pf.walk_forward || {};
            return h("tr", { class: "pl-pick" + (pf.id === state.sel.pid ? " is-on" : ""), tabindex: "0", onclick: function () { state.sel.pid = pf.id; state.sel.window = pf.window; renderResult(); root.scrollTo({ top: els.resultBody.offsetTop, behavior: "smooth" }); } }, [
                h("td", { text: pf.window }), h("td", { text: objectiveName(pf.objective) }), h("td", { text: capName(pf.cap) }),
                h("td", { text: pf.weights.slice(0, 3).map(function (w) { return w.label + " " + Math.round(w.weight * 100) + " %"; }).join(" / ") }),
                h("td", { class: "n", text: pct(pf.metrics.cagr) }), h("td", { class: "n", text: pct(pf.metrics.vol) }), h("td", { class: "n", text: num(pf.metrics.sharpe) }),
                h("td", { class: "n", text: wf.sharpe === null || wf.sharpe === undefined ? "—" : num(wf.sharpe) }), h("td", { class: "n", text: wf.sharpe_1n === null || wf.sharpe_1n === undefined ? "—" : num(wf.sharpe_1n) })]);
        });
        var exportBtn = h("button", { type: "button", class: "btn-secondary", text: t("pl_export"), onclick: function () {
            var csv = toCsv([["window", "objective", "cap", "allocation", "cagr", "vol", "sharpe", "wf_sharpe", "sharpe_1n"]].concat(r.portfolios.map(function (pf) {
                var wf = pf.walk_forward || {};
                return [pf.window, pf.objective, pf.cap === null ? "" : pf.cap, pf.weights.map(function (w) { return w.label + " " + (w.weight * 100).toFixed(1) + "%"; }).join(" / "),
                        pf.metrics.cagr, pf.metrics.vol, pf.metrics.sharpe, wf.sharpe, wf.sharpe_1n];
            })));
            var a = h("a", { href: root.URL.createObjectURL(new root.Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" })), download: "placements.csv" });
            doc.body.appendChild(a); a.click(); a.remove();
        } });
        return h("div", { class: "card pl-card" }, [h("div", { class: "pl-row pl-row-between" }, [h("h3", { text: t("pl_all_h") }), exportBtn]),
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table pl-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])])]);
    }

    function growthSection(r, pf) {
        var ch = r.charts[state.sel.window];
        if (!ch) return null;
        var xs = ch.dates.map(function (d) { return Date.parse(d); });
        var inAlloc = pf ? pf.weights.map(function (w) { return w.key; }) : [];
        var series = [];
        if (pf && ch.portfolios[pf.id]) series.push({ name: t("pl_portfolio"), color: "--brand", width: 2.8, values: ch.portfolios[pf.id] });
        series.push({ name: t("pl_one_n"), color: "--text-3", width: 1.6, dash: "4 3", values: ch.one_over_n });
        inAlloc.forEach(function (k, i) { if (ch.funds[k]) series.push({ name: (r.funds.filter(function (f) { return f.key === k; })[0] || { label: k }).label, color: PALETTE[i % PALETTE.length], width: 1.3, values: ch.funds[k] }); });
        var growth = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_growth_h") });
        var drawdown = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_dd_h") });
        function dd(values) { var peak = -Infinity; return values.map(function (v) { peak = Math.max(peak, v); return (v / peak - 1) * 100; }); }
        root.setTimeout(function () {
            paintChart(growth, { type: "line", xKind: "time", xs: xs, series: series, height: 280, legend: true, markers: false, finance: false, yFmt: function (v, d) { return fmt(v, d); }, tipFmt: function (v) { return fmt(v, 1); } });
            paintChart(drawdown, { type: "line", xKind: "time", xs: xs, height: 200, legend: false, markers: false, finance: false, zoomable: true, sync: "pl-dd",
                series: series.map(function (s) { return { name: s.name, color: s.color, width: s.width, dash: s.dash, values: dd(s.values) }; }),
                yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        }, 0);
        return h("div", {}, [h("h4", { text: t("pl_growth_h") }), growth, h("h4", { text: t("pl_dd_h") }), drawdown]);
    }

    function statsSection(r) {
        var sel = state.sel;
        var windows = r.stat_windows;
        if (!sel.statWindow || windows.indexOf(sel.statWindow) < 0) sel.statWindow = windows[windows.length - 1];
        var pick = h("select", { class: "pl-input", "aria-label": t("pl_stats_window"), onchange: function (e) { sel.statWindow = e.target.value; renderResult(); } },
            windows.map(function (w) { return h("option", { value: w, selected: w === sel.statWindow, text: w }); }));
        var head = h("tr", {}, [t("pl_col_fund"), t("pl_col_start"), t("pl_col_cagr"), t("pl_col_vol"), t("pl_col_sharpe"), t("pl_col_mdd"), t("pl_col_w12")].map(function (c, i) { return h("th", { class: i > 1 ? "n" : "", text: c }); }));
        var rows = r.fund_stats.filter(function (f) { return f.windows[sel.statWindow]; }).sort(function (a, b) { return (b.windows[sel.statWindow].sharpe || -99) - (a.windows[sel.statWindow].sharpe || -99); }).map(function (f) {
            var s = f.windows[sel.statWindow];
            return h("tr", {}, [h("td", { text: f.label }), h("td", { text: s.start }), h("td", { class: "n", text: pct(s.cagr) }), h("td", { class: "n", text: pct(s.vol) }), h("td", { class: "n", text: num(s.sharpe) }), h("td", { class: "n", text: pct(s.max_dd) }), h("td", { class: "n", text: pct(s.worst_12m) })]);
        });
        var corr = r.correlation;
        var labelOf = function (k) { return (r.funds.filter(function (f) { return f.key === k; })[0] || { label: k }).label; };
        var cHead = h("tr", {}, [h("th", {})].concat(corr.keys.map(function (k, i) { return h("th", { class: "pl-corr-h", title: labelOf(k), text: String(i + 1) }); })));
        var cRows = corr.keys.map(function (k, i) {
            return h("tr", {}, [h("th", { class: "pl-corr-row", text: (i + 1) + " · " + labelOf(k) })].concat(corr.matrix[i].map(function (v, j) {
                return h("td", { class: "pl-corr " + (v < 0 ? "is-neg" : "is-pos"), style: "--v:" + corrIntensity(v).toFixed(2), title: labelOf(k) + " × " + labelOf(corr.keys[j]), text: v === null ? "—" : fmt(v, 2) });
            })));
        });
        var fs = r.fund_scenarios.map(function (f) {
            var s = f.scenarios["bootstrap blocs 6 mois"] && f.scenarios["bootstrap blocs 6 mois"][state.sel.centering];
            return s ? h("tr", {}, [h("td", { text: f.label }), h("td", { class: "n", text: pct(f.expected) }), h("td", { class: "n", text: pct(s.ann_p05) }), h("td", { class: "n", text: pct(s.ann_p50) }), h("td", { class: "n", text: pct(s.ann_p95) }), h("td", { class: "n", text: pct(s.proba_perte) })]) : null;
        });
        return h("div", { class: "card pl-card" }, [
            h("h3", { text: t("pl_funds_h") }), h("label", { class: "pl-label" }, [t("pl_stats_window"), pick]),
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table pl-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]),
            h("h4", { text: t("pl_corr_h") }), h("div", { class: "table-scroll" }, [h("table", { class: "pl-corrtable" }, [h("thead", {}, [cHead]), h("tbody", {}, cRows)])]),
            fs.filter(Boolean).length ? h("div", {}, [h("h4", { text: t("pl_fscn_h") }),
                h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, [t("pl_col_fund"), "E", "P5", "P50", "P95", t("pl_col_loss")].map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]), h("tbody", {}, fs.filter(Boolean))])])]) : null]);
    }

    function renderResult() {
        var r = state.result;
        els.result.hidden = !r || state.creating;
        if (!r || state.creating) return;
        var sel = state.sel;
        if (!sel.window || !r.windows.some(function (w) { return w.id === sel.window; })) sel.window = r.windows[r.windows.length - 1].id;
        var picked = pickBest(r.portfolios, sel.window, sel.crit, sel.maxVol);
        var chosen = sel.pid ? r.portfolios.filter(function (p) { return p.id === sel.pid; })[0] : picked;
        var box = clear(els.resultBody);
        box.appendChild(hint(t("pl_generated", { d: r.generated_at.replace("T", " ").slice(0, 16), c: r.last_common })));
        if (r.warnings && r.warnings.length) box.appendChild(h("ul", { class: "pl-warnings" }, r.warnings.map(function (w) { return h("li", { text: w }); })));
        box.appendChild(bestSection(r));
        var growth = growthSection(r, chosen || picked);
        if (growth) box.appendChild(h("div", { class: "card pl-card" }, [growth]));
        box.appendChild(allocationsTable(r));
        box.appendChild(statsSection(r));
    }

    function render() { dataPanel(); runPanel(); renderResult(); }
    loadAll();
})(typeof window !== "undefined" ? window : globalThis);
