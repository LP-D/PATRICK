/* Page Reinforcement learning : formulaire (vue simplifiée / experte, profils du navigateur), lancement d'un run par cible dans la file
   commune, suivi (`/runs/<id>/status`), résultats (`/runs/<id>/results`) et liste des runs RL (`/api/rl/runs`). Tout texte vient de
   `window.I18N` ; les graphiques viennent de `charts.js`. */
(function () {
    "use strict";

    var C = window.PatrickCharts;
    var tr = C.tr, fmtStr = C.fmtStr, num = C.num, pct = C.pct, pval = C.pval, h = C.h, chip = C.chip, note = C.note;
    var table = C.table, numCell = C.numCell, lineChart = C.lineChart;
    function $(id) { return document.getElementById(id); }

    var form = $("rl-form");
    if (!form) return;
    var algoSel = $("rl-algo"), spaceSel = $("rl-action-space");
    var MODE_KEY = "patrick-rl-settings-mode", PROFILE_KEY = "patrick-rl-profiles";
    var currentRun = null, pollTimer = null, lastLog = "";

    function fmtDuration(seconds) {
        seconds = Math.max(0, Math.round(seconds));
        var m = Math.floor(seconds / 60), s = seconds % 60;
        return m ? m + " min " + (s < 10 ? "0" : "") + s + " s" : s + " s";
    }

    // ------------------------------------------------------------------ vue simplifiée / experte
    function setMode(mode, persist) {
        var expert = mode === "expert";
        form.dataset.mode = expert ? "expert" : "simple";
        var toggle = $("settings-mode-toggle");
        toggle.setAttribute("aria-pressed", String(expert));
        toggle.textContent = tr(expert ? "settings_mode_hide_expert" : "settings_mode_show_expert");
        $("settings-mode-hint").textContent = tr(expert ? "settings_mode_expert_hint" : "settings_mode_simple_hint");
        if (persist) { try { localStorage.setItem(MODE_KEY, expert ? "expert" : "simple"); } catch (e) { /* stockage indisponible */ } }
    }
    var saved = "simple";
    try { saved = localStorage.getItem(MODE_KEY) === "expert" ? "expert" : "simple"; } catch (e) { /* idem */ }
    setMode(saved, false);
    $("settings-mode-toggle").addEventListener("click", function () { setMode(form.dataset.mode === "expert" ? "simple" : "expert", true); });

    // ------------------------------------------------------------------ cohérence algorithme / actions, champs propres à un algorithme
    function syncAlgo() {
        var algo = algoSel.value;
        Array.prototype.forEach.call(spaceSel.options, function (o) {
            o.disabled = (algo === "DQN" && o.value === "continuous") || (algo === "SAC" && o.value === "discrete");
        });
        if (algo === "DQN") spaceSel.value = "discrete";
        if (algo === "SAC") spaceSel.value = "continuous";
        form.querySelectorAll("[data-algos]").forEach(function (el) { el.hidden = el.dataset.algos.split(",").indexOf(algo) < 0; });
        form.querySelectorAll("[data-actions]").forEach(function (el) { el.hidden = el.dataset.actions !== spaceSel.value; });
        recap();
    }

    function selectedTargets() {
        return Array.prototype.map.call($("rl-targets").selectedOptions, function (o) { return o.value; });
    }
    function recap() {
        var targets = selectedTargets();
        var label = targets.length > 3 ? targets.slice(0, 3).join(", ") + " +" + (targets.length - 3) : (targets.join(", ") || "—");
        $("rl-recap").textContent = fmtStr(tr("rlp_recap"), {
            targets: label, algo: algoSel.value, steps: Number(form.elements.rl_total_timesteps.value || 0).toLocaleString(document.documentElement.lang || "fr"),
            folds: form.elements.rl_n_folds.value });
    }
    algoSel.addEventListener("change", syncAlgo);
    spaceSel.addEventListener("change", syncAlgo);
    form.addEventListener("input", recap);
    form.addEventListener("change", recap);
    syncAlgo();

    // ------------------------------------------------------------------ profils enregistrés dans le navigateur
    var pName = $("rl-profile-name"), pList = $("rl-profile-list"), pStatus = $("rl-profile-status");
    function profileMessage(text, bad) { pStatus.textContent = text; pStatus.dataset.error = bad ? "true" : "false"; }
    function readProfiles() {
        try {
            var list = JSON.parse(localStorage.getItem(PROFILE_KEY) || "[]");
            return Array.isArray(list) ? list.filter(function (p) { return p && typeof p.name === "string" && p.fields; }) : [];
        } catch (e) { return []; }
    }
    function refreshProfiles() {
        var previous = pList.value, list = readProfiles();
        pList.replaceChildren(new Option(tr("profile_choose"), ""));
        list.forEach(function (p) { pList.add(new Option(p.name, p.name)); });
        if (list.some(function (p) { return p.name === previous; })) pList.value = previous;
        $("rl-profile-load").disabled = !pList.value;
        $("rl-profile-delete").disabled = !pList.value;
    }
    function serialize() {
        var out = {};
        Array.prototype.forEach.call(form.elements, function (el) {
            if (!el.name || el.disabled || ["button", "submit", "reset"].indexOf(el.type) >= 0 || out[el.name] !== undefined) return;
            var same = Array.prototype.filter.call(form.elements, function (c) { return c.name === el.name; });
            if (el.type === "checkbox") out[el.name] = same.filter(function (c) { return c.checked; }).map(function (c) { return c.value; });
            else if (el.multiple) out[el.name] = Array.prototype.map.call(el.selectedOptions, function (o) { return o.value; });
            else out[el.name] = [el.value];
        });
        return out;
    }
    function apply(fields) {
        Object.keys(fields).forEach(function (name) {
            var values = fields[name];
            Array.prototype.filter.call(form.elements, function (el) { return el.name === name; }).forEach(function (el) {
                if (el.type === "checkbox") el.checked = values.indexOf(el.value) >= 0 || (el.value === "on" && values.indexOf("on") >= 0);
                else if (el.multiple) Array.prototype.forEach.call(el.options, function (o) { o.selected = values.indexOf(o.value) >= 0; });
                else if (values.length) el.value = values[0];
            });
        });
        syncAlgo();
    }
    $("rl-profile-save").addEventListener("click", function () {
        var name = pName.value.trim();
        if (!name) { profileMessage(tr("rlp_profile_name_required"), true); pName.focus(); return; }
        var list = readProfiles().filter(function (p) { return p.name !== name; });
        list.push({ name: name, fields: serialize() });
        try { localStorage.setItem(PROFILE_KEY, JSON.stringify(list)); } catch (e) { profileMessage(tr("profile_save_error"), true); return; }
        refreshProfiles(); pList.value = name; refreshProfiles();
        profileMessage(tr("rlp_profile_saved"), false);
    });
    $("rl-profile-load").addEventListener("click", function () {
        var p = readProfiles().filter(function (x) { return x.name === pList.value; })[0];
        if (!p) { profileMessage(tr("profile_missing"), true); refreshProfiles(); return; }
        apply(p.fields); pName.value = p.name; profileMessage(tr("rlp_profile_loaded"), false);
    });
    $("rl-profile-delete").addEventListener("click", function () {
        var list = readProfiles().filter(function (x) { return x.name !== pList.value; });
        try { localStorage.setItem(PROFILE_KEY, JSON.stringify(list)); } catch (e) { profileMessage(tr("profile_delete_error"), true); return; }
        refreshProfiles(); profileMessage(tr("rlp_profile_deleted"), false);
    });
    pList.addEventListener("change", refreshProfiles);
    pName.addEventListener("keydown", function (ev) { if (ev.key === "Enter") ev.preventDefault(); });
    refreshProfiles();

    // ------------------------------------------------------------------ erreurs et lancement
    function showErrors(errors) {
        var ul = $("rl-errors-list");
        ul.replaceChildren();
        errors.forEach(function (e) { ul.appendChild(h("li", { text: e })); });
        $("rl-errors").classList.toggle("hidden", !errors.length);
        if (errors.length) $("rl-errors").scrollIntoView({ block: "nearest" });
    }
    form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        if (!selectedTargets().length) { showErrors([tr("rlp_pick_target")]); return; }
        var btn = $("rl-launch");
        btn.disabled = true;
        btn.textContent = tr("rlp_launching");
        fetch("/api/rl/runs", { method: "POST", body: new FormData(form) })
            .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
            .then(function (res) {
                if (!res.ok) { showErrors(res.body.errors || [tr("run_launch_error")]); return; }
                showErrors([]);
                var first = res.body.runs[0];
                if (!currentRun || currentRun.status === "done" || currentRun.status === "error") track(first.run_id);
                refreshRuns();
            })
            .catch(function () { showErrors([tr("run_launch_error")]); })
            .finally(function () { btn.disabled = false; btn.textContent = tr("rlp_launch"); });
    });

    // ------------------------------------------------------------------ suivi d'un run
    function track(runId) {
        clearTimeout(pollTimer);
        currentRun = { id: runId, status: "queued" };
        $("rl-idle").classList.add("hidden");
        $("rl-status-panel").classList.remove("hidden");
        $("rl-results-panel").hidden = true;
        lastLog = "";
        poll();
    }
    function poll() {
        if (!currentRun) return;
        var id = currentRun.id;
        fetch("/runs/" + encodeURIComponent(id) + "/status")
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (job) {
                if (!currentRun || currentRun.id !== id) return;
                currentRun.status = job.status;
                $("rl-run-name").textContent = job.name || id;
                var total = (job.progress && job.progress.total) || 0, done = (job.progress && job.progress.done) || 0;
                $("rl-progress-fill").style.width = (job.status === "done" ? 100 : (total ? Math.min(100, done / total * 100) : 3)) + "%";
                var log = (job.log_tail || []).join("\n");
                if (log !== lastLog) { $("rl-log").textContent = log; lastLog = log; }
                var stop = $("rl-stop");
                stop.hidden = job.status !== "running";
                var line = $("rl-status-line");
                if (job.status === "queued") line.textContent = fmtStr(tr("rlp_status_queued"), { n: job.queue_position || 1 });
                else if (job.status === "running" || job.status === "paused") {
                    line.textContent = fmtStr(tr("rlp_status_running"), { phase: tr("rlp_phase_" + job.phase, job.phase || ""), done: done, total: total || "?" });
                } else if (job.status === "error") line.textContent = fmtStr(tr("rlp_status_error"), { e: job.error || "" });
                else if (job.status === "done") { line.textContent = tr("rlp_status_done") + " · " + fmtStr(tr("rlp_elapsed"), { t: fmtDuration(job.elapsed_s) }); }
                if (job.status === "done") { loadResult(id); refreshRuns(); return; }
                if (job.status === "error") { refreshRuns(); return; }
                pollTimer = setTimeout(poll, 2000);
            })
            .catch(function () {
                $("rl-status-line").textContent = tr("rlp_status_lost");
                pollTimer = setTimeout(poll, 4000);
            });
    }
    $("rl-stop").addEventListener("click", function () {
        if (!currentRun) return;
        var id = currentRun.id;
        var ask = window.patrickDialog ? window.patrickDialog.confirm(tr("rlp_stop") + " ?", tr("rlp_stop"), true) : Promise.resolve(true);
        ask.then(function (yes) { if (yes) fetch("/api/jobs/" + encodeURIComponent(id) + "/stop", { method: "POST" }).then(function () { setTimeout(poll, 800); }); });
    });

    // ------------------------------------------------------------------ résultats
    function loadResult(runId) {
        fetch("/runs/" + encodeURIComponent(runId) + "/results")
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (result) {
                var box = $("rl-results");
                box.replaceChildren(renderResults(result, runId));
                $("rl-results-panel").hidden = false;
                if (window.PatrickHelp) window.PatrickHelp.scan($("rl-results-panel"));
            })
            .catch(function () { $("rl-results").replaceChildren(h("p", { class: "banner banner-error", role: "alert", text: tr("rlp_status_lost") })); $("rl-results-panel").hidden = false; });
    }

    var LEGS = [["strategy", "rlp_leg_strategy"], ["buy_hold", "rlp_leg_buy_hold"], ["momentum", "rlp_leg_momentum"], ["flat", "rlp_leg_flat"]];
    var KPIS = [
        ["total_return", "rlp_k_total", function (v) { return pct(v, 1); }], ["cagr", "rlp_k_cagr", function (v) { return pct(v, 1); }],
        ["vol", "rlp_k_vol", function (v) { return pct(v, 1); }], ["sharpe", "rlp_k_sharpe", function (v) { return num(v, 2); }],
        ["sortino", "rlp_k_sortino", function (v) { return num(v, 2); }], ["max_drawdown", "rlp_k_maxdd", function (v) { return pct(v, 1); }],
        ["turnover", "rlp_k_turnover", function (v) { return num(v, 1); }], ["exposure", "rlp_k_exposure", function (v) { return pct(v, 0); }],
        ["hit_rate", "rlp_k_hit", function (v) { return pct(v, 0); }], ["n_trades", "rlp_k_trades", function (v) { return num(v, 0); }],
        ["cost_drag", "rlp_k_costs", function (v) { return pct(v, 1); }],
    ];

    function verdict(stat) {
        if (!stat || stat.ci_low === null || stat.ci_high === null) return chip("—", "neutral");
        if (stat.ci_low > 0) return chip(tr("rlp_v_beats"), "pos");
        if (stat.ci_high < 0) return chip(tr("rlp_v_loses"), "neg");
        return chip(tr("rlp_v_uncertain"), "warn");
    }
    function gapRow(label, stat) {
        return [label, { cell: num(stat.diff, 2), cls: "num pk-mono" },
            fmtStr(tr("rlp_stat_ci"), { lo: num(stat.ci_low, 2), hi: num(stat.ci_high, 2) }) + " · " + fmtStr(tr("rlp_stat_p"), { p: pval(stat.p_one_sided) }),
            { cell: verdict(stat) }];
    }
    function legend(items) {
        return h("div", { class: "exp-legend" }, items.map(function (it) {
            var dot = h("span", { class: "rl-dot" });
            dot.style.background = it[1];
            return h("span", { class: "exp-chip" }, [dot, it[0]]);
        }));
    }

    function renderResults(r, runId) {
        var box = h("div", { class: "rl-results" });
        box.appendChild(h("p", { class: "exp-meta", text: [r.name + " · " + r.target + " · " + r.algo,
            fmtStr(tr("rlp_n_obs"), { n: r.strategy.n, start: r.curves.dates[0], end: r.curves.dates[r.curves.dates.length - 1] }),
            fmtStr(tr("rlp_elapsed"), { t: fmtDuration(r.elapsed_s) })].join(" · ") }));
        (r.warnings || []).forEach(function (w) { box.appendChild(h("p", { class: "banner banner-warning", role: "status", text: w })); });

        // chiffres clés : une colonne par ligne de base
        var legs = LEGS.filter(function (l) { return l[0] === "strategy" || r.baselines[l[0]]; });
        var rows = KPIS.map(function (k) {
            return [k[1] === undefined ? "" : tr(k[1])].concat(legs.map(function (l) {
                var m = l[0] === "strategy" ? r.strategy : r.baselines[l[0]];
                var v = m[k[0]];
                return { cell: v === null || v === undefined ? "—" : k[2](v), cls: "num pk-mono" + (l[0] === "strategy" ? " rl-agent-col" : "") };
            }));
        });
        box.appendChild(table([""].concat(legs.map(function (l) { return tr(l[1]); })), rows));

        // l'agent bat-il vraiment la référence ?
        box.appendChild(h("h3", { text: tr("rlp_stats_title") }));
        var st = r.stats;
        box.appendChild(table(["", "Δ Sharpe", "", ""], [gapRow(tr("rlp_stat_vs_bh"), st.vs_buy_hold), gapRow(tr("rlp_stat_vs_mom"), st.vs_momentum)]));
        box.appendChild(table(["", "", ""], [
            [tr("rlp_stat_psr"), { cell: pct(st.psr, 0), cls: "num pk-mono" }, ""],
            [tr("rlp_stat_dsr"), { cell: st.dsr && st.dsr.dsr !== null ? pct(st.dsr.dsr, 0) : "—", cls: "num pk-mono" },
                fmtStr(tr("rlp_stat_dsr_detail"), { n: st.n_trials, bench: st.dsr && st.dsr.benchmark_sr !== null ? num(st.dsr.benchmark_sr, 3) : "—" })],
        ]));

        // courbes
        box.appendChild(h("h3", { text: tr("rlp_c_equity") }));
        box.appendChild(lineChart({
            dates: r.curves.dates, title: tr("rlp_c_equity"),
            series: [{ values: r.curves.buy_hold, color: "var(--text-3)" }, { values: r.curves.momentum, color: "var(--warn)" },
                     { values: r.curves.strategy, color: "var(--brand)" }],
            hlines: [{ y: 1, dash: "2 4" }], yFmt: function (v) { return num(v, 2); } }));
        box.appendChild(legend([[tr("rlp_leg_strategy"), "var(--brand)"], [tr("rlp_leg_buy_hold"), "var(--text-3)"], [tr("rlp_leg_momentum"), "var(--warn)"]]));
        box.appendChild(h("h3", { text: tr("rlp_c_position") }));
        box.appendChild(lineChart({ dates: r.curves.dates, series: [{ values: r.curves.position, color: "var(--pos)" }], title: tr("rlp_c_position"),
            yMin: -1, yMax: 1, hlines: [{ y: 0, dash: "0", color: "var(--line-strong)" }], yFmt: function (v) { return num(v, 1); }, height: 150 }));

        // plis
        box.appendChild(h("h3", { text: tr("rlp_folds_title") }));
        box.appendChild(table([tr("rlp_col_fold"), tr("rlp_col_train"), tr("rlp_col_test"), tr("rlp_col_n"), tr("rlp_col_agent") + " · Sharpe", tr("rlp_col_bh") + " · Sharpe"],
            r.folds.map(function (f) {
                return [{ cell: String(f.fold), cls: "num" }, f.train_start + " → " + f.train_end, f.test_start + " → " + f.test_end,
                    { cell: String(f.n_test), cls: "num" }, numCell(num(f.strategy.sharpe, 2), f.strategy.sharpe), numCell(num(f.buy_hold.sharpe, 2), f.buy_hold.sharpe)];
            })));

        if (r.seeds && r.seeds.length > 1) {
            box.appendChild(h("h3", { text: tr("rlp_seeds_title") }));
            box.appendChild(table(["#", tr("rlp_k_sharpe"), tr("rlp_k_total")], r.seeds.map(function (sd) {
                return [{ cell: String(sd.seed), cls: "num" }, numCell(num(sd.sharpe, 2), sd.sharpe), numCell(pct(sd.total_return, 1), sd.total_return)];
            })));
        }
        if (r.feature_usage && r.feature_usage.length) {
            box.appendChild(h("h3", { text: tr("rlp_features_title") }));
            box.appendChild(note(tr("rlp_features_note")));
            box.appendChild(table(["", "#"], r.feature_usage.slice(0, 12).map(function (kv) { return [{ cell: kv[0], cls: "pk-mono" }, { cell: String(kv[1]), cls: "num" }]; })));
        }

        // fichiers et reprise
        box.appendChild(h("h3", { text: tr("rlp_downloads") }));
        var links = [];
        var art = r.artifacts || {};
        function link(key, text) { return h("a", { class: "btn-secondary", href: "/runs/" + encodeURIComponent(runId) + "/download/" + encodeURIComponent(key), text: text }); }
        if (art.result_json) links.push(link("result_json", tr("rlp_dl_json")));
        if (art.oos_csv) links.push(link("oos_csv", tr("rlp_dl_csv")));
        Object.keys(art).filter(function (k) { return k.indexOf("model_seed") === 0; }).forEach(function (k) {
            links.push(link(k, fmtStr(tr("rlp_dl_model"), { n: k.replace("model_seed", "") })));
        });
        links.push(h("a", { class: "btn-secondary", href: "/rl?run_id=" + encodeURIComponent(runId), text: tr("rlp_reuse") }));
        box.appendChild(h("div", { class: "exp-presets" }, links));
        return box;
    }

    // ------------------------------------------------------------------ liste des runs RL
    function renderRuns(runs) {
        var box = $("rl-runs");
        if (!runs.length) { box.replaceChildren(h("p", { class: "hint", "data-keep": "", text: tr("rlp_none_yet") })); return; }
        var rows = runs.slice(0, 12).map(function (run) {
            var open = h("button", { type: "button", class: "queue-action", text: tr("rlp_load") });
            open.addEventListener("click", function () {
                if (run.status === "done") { track(run.run_id); }
                else track(run.run_id);
            });
            var kind = run.status === "done" ? "ok" : (run.status === "error" ? "neg" : "warn");
            return [{ cell: run.name || run.run_id, cls: "pk-mono" }, run.target || "—", run.algo || "—", { cell: chip(run.status, kind) },
                run.sharpe === undefined || run.sharpe === null ? "—" : { cell: num(run.sharpe, 2) + " / " + num(run.sharpe_buy_hold, 2), cls: "num pk-mono" },
                { cell: open }];
        });
        box.replaceChildren(table(["", tr("rlp_f_target"), tr("rlp_f_algo"), "", tr("rlp_k_sharpe"), ""], rows));
    }
    function refreshRuns() {
        fetch("/api/rl/runs").then(function (r) { return r.json(); }).then(function (b) { renderRuns(b.runs || []); }).catch(function () { /* la liste garde son contenu */ });
    }
    try { renderRuns(JSON.parse($("rl-initial-runs").textContent || "[]")); } catch (e) { renderRuns([]); }

    var initial = $("rl-root").dataset.initialRun;
    if (initial) track(initial);
})();
