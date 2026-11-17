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
        var targets = selectedTargets().map(function (sym) { return window.PatrickNames ? window.PatrickNames.label(sym) : sym; });
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
    // Pause et arrêt : sur la carte « en cours et file d'attente » (machine.js), la même que sur /ml et /dl. Après un arrêt, on relit tout de suite.
    if (window.PatrickMachine) window.PatrickMachine.onAction(function () { if (currentRun) { clearTimeout(pollTimer); poll(); } });
    // Le run RL actif côté serveur (lancé d'ailleurs, ou la file qui avance toute seule) est suivi sans recharger la page : le cadre
    // « Avancement » est désormais le seul endroit qui montre le run en cours.
    if (window.PatrickMachine) window.PatrickMachine.subscribe(function (state) {
        var active = state.active;
        if (active && active.kind === "rl" && (!currentRun || currentRun.id !== active.id)) track(active.id);
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

    var LEGS = [["strategy", "rlp_leg_strategy"], ["agent_ungated", "rlp_leg_agent_raw"], ["buy_hold", "rlp_leg_buy_hold"],
                ["trend", "rlp_leg_trend"], ["momentum", "rlp_leg_momentum"], ["flat", "rlp_leg_flat"]];
    var KPIS = [
        ["total_return", "rlp_k_total", function (v) { return pct(v, 1); }], ["cagr", "rlp_k_cagr", function (v) { return pct(v, 1); }],
        ["vol", "rlp_k_vol", function (v) { return pct(v, 1); }], ["sharpe", "rlp_k_sharpe", function (v) { return num(v, 2); }],
        ["sortino", "rlp_k_sortino", function (v) { return num(v, 2); }], ["max_drawdown", "rlp_k_maxdd", function (v) { return pct(v, 1); }],
        ["turnover", "rlp_k_turnover", function (v) { return num(v, 1); }], ["exposure", "rlp_k_exposure", function (v) { return pct(v, 0); }],
        ["hit_rate", "rlp_k_hit", function (v) { return pct(v, 0); }], ["n_trades", "rlp_k_trades", function (v) { return num(v, 0); }],
        ["cost_drag", "rlp_k_costs", function (v) { return pct(v, 1); }],
        ["gross_return_ann", "rlp_k_gross", function (v) { return pct(v, 1); }], ["cost_ann", "rlp_k_cost_ann", function (v) { return pct(v, 1); }],
        ["long_contrib_ann", "rlp_k_long", function (v) { return pct(v, 1); }], ["short_contrib_ann", "rlp_k_short", function (v) { return pct(v, 1); }],
    ];
    // Ligne de résultat : la stratégie, l'agent sans repli (seulement si le repli a joué) ou une référence. Le momentum 20 j (trop facile
    // à battre : Sharpe médian négatif) ne sert plus que pour un run du moteur 1, qui n'a pas la tendance 200 j.
    function legMetrics(r, key) {
        if (key === "strategy") return r.strategy;
        if (key === "agent_ungated") return (r.folds || []).some(function (f) { return f.gated; }) ? r.agent_ungated : null;
        if (key === "momentum" && (r.baselines || {}).trend) return null;
        return (r.baselines || {})[key] || null;
    }

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

    // Lecture du run (`rl.reading`, calculée par le serveur) : verdict, motif, puis les quatre chiffres qui le justifient.
    var VERDICT_CHIP = { ok: "pos", error: "neg", pending: "warn", neutral: "neutral" };
    function verdictChip(rd) { return rd && rd.verdict ? chip(tr("rlp_rd_" + rd.verdict), VERDICT_CHIP[rd.verdict_state] || "neutral") : null; }
    function readingBlock(rd) {
        if (!rd || !rd.verdict) return h("div", {});
        var why = rd.leak ? tr("rlp_rd_leak_" + rd.leak) : tr("rlp_rd_" + rd.verdict + "_tip");
        var facts = [fmtStr(tr("rlp_rd_engine"), { n: rd.engine })];
        if (typeof rd.excess === "number") facts.push(tr("rlp_rd_excess") + " " + (rd.excess > 0 ? "+" : "") + pct(rd.excess, 1));
        if (typeof rd.cost_ann === "number") facts.push(tr("rlp_k_cost_ann") + " " + pct(rd.cost_ann, 1));
        if (typeof rd.p_vs_buy_hold === "number") facts.push(fmtStr(tr("rlp_stat_p"), { p: pval(rd.p_vs_buy_hold) }));
        return h("div", { class: "rl-reading" }, [
            h("p", { class: "rl-reading-verdict" }, [verdictChip(rd), h("span", { class: "hint", text: " " + why })]),
            h("p", { class: "exp-meta", text: facts.join(" · ") })]);
    }

    function renderResults(r, runId) {
        var box = h("div", { class: "rl-results" });
        box.appendChild(h("p", { class: "exp-meta", text: [r.name + " · " + (window.PatrickNames ? window.PatrickNames.label(r.target) : r.target) + " · " + r.algo,
            fmtStr(tr("rlp_n_obs"), { n: r.strategy.n, start: r.curves.dates[0], end: r.curves.dates[r.curves.dates.length - 1] }),
            fmtStr(tr("rlp_elapsed"), { t: fmtDuration(r.elapsed_s) })].join(" · ") }));
        (r.warnings || []).forEach(function (w) { box.appendChild(h("p", { class: "banner banner-warning", role: "status", text: w })); });
        box.appendChild(readingBlock(r.reading));
        if (typeof r.strategy.agent_share === "number") {
            box.appendChild(h("p", { class: "exp-meta", "data-keep": "", text: fmtStr(tr("rlp_agent_share"), { p: pct(r.strategy.agent_share, 0) }) }));
        }

        // chiffres clés : une colonne par ligne de base
        var legs = LEGS.filter(function (l) { return legMetrics(r, l[0]); });
        var rows = KPIS.filter(function (k) { return r.strategy[k[0]] !== undefined; }).map(function (k) {
            return [k[1] === undefined ? "" : tr(k[1])].concat(legs.map(function (l) {
                var m = legMetrics(r, l[0]);
                var v = m[k[0]];
                return { cell: v === null || v === undefined ? "—" : k[2](v), cls: "num pk-mono" + (l[0] === "strategy" ? " rl-agent-col" : "") };
            }));
        });
        box.appendChild(table([""].concat(legs.map(function (l) { return tr(l[1]); })), rows));

        // l'agent bat-il vraiment la référence ?
        box.appendChild(h("h3", { text: tr("rlp_stats_title") }));
        var st = r.stats;
        var gaps = [gapRow(tr("rlp_stat_vs_bh"), st.vs_buy_hold)];
        if (st.vs_trend) gaps.push(gapRow(tr("rlp_stat_vs_trend"), st.vs_trend));
        if (!st.vs_trend && st.vs_momentum) gaps.push(gapRow(tr("rlp_stat_vs_mom"), st.vs_momentum));
        box.appendChild(table(["", "Δ Sharpe", "", ""], gaps));
        var extra = [];
        if (typeof st.excess_log_growth === "number") extra.push([tr("rlp_stat_excess"), numCell(pct(st.excess_log_growth, 1), st.excess_log_growth), ""]);
        var dl = st.delay || (r.reading || {}).delay;       // moteur 1 : test rejoué sur le fichier hors échantillon
        if (dl) extra.push([tr("rlp_stat_delay"), { cell: num(dl.lagged_sharpe, 2), cls: "num pk-mono" },
            fmtStr(tr("rlp_delay"), { g: num(dl.gross_sharpe, 2), l: num(dl.lagged_sharpe, 2) })]);
        box.appendChild(table(["", "", ""], extra.concat([
            [tr("rlp_stat_psr"), { cell: pct(st.psr, 0), cls: "num pk-mono" }, ""],
            [tr("rlp_stat_dsr"), { cell: st.dsr && st.dsr.dsr !== null ? pct(st.dsr.dsr, 0) : "—", cls: "num pk-mono" },
                fmtStr(tr("rlp_stat_dsr_detail"), { n: st.n_trials, bench: st.dsr && st.dsr.benchmark_sr !== null ? num(st.dsr.benchmark_sr, 3) : "—" })],
        ])));

        // courbes
        box.appendChild(h("h3", { text: tr("rlp_c_equity") }));
        box.appendChild(lineChart({
            dates: r.curves.dates, title: tr("rlp_c_equity"),
            series: [{ values: r.curves.buy_hold, color: "var(--text-3)" }]
                .concat(r.curves.trend ? [{ values: r.curves.trend, color: "var(--info)" }] : [{ values: r.curves.momentum, color: "var(--warn)" }])
                .concat(r.curves.agent && legMetrics(r, "agent_ungated") ? [{ values: r.curves.agent, color: "var(--pos)" }] : [])
                .concat([{ values: r.curves.strategy, color: "var(--brand)" }]),
            hlines: [{ y: 1, dash: "2 4" }], yFmt: function (v) { return num(v, 2); } }));
        box.appendChild(legend([[tr("rlp_leg_strategy"), "var(--brand)"]]
            .concat(r.curves.agent && legMetrics(r, "agent_ungated") ? [[tr("rlp_leg_agent_raw"), "var(--pos)"]] : [])
            .concat([[tr("rlp_leg_buy_hold"), "var(--text-3)"]])
            .concat(r.curves.trend ? [[tr("rlp_leg_trend"), "var(--info)"]] : [[tr("rlp_leg_momentum"), "var(--warn)"]])));
        box.appendChild(h("h3", { text: tr("rlp_c_position") }));
        var shortable = (r.curves.position || []).some(function (v) { return v < 0; });
        box.appendChild(lineChart({ dates: r.curves.dates, series: [{ values: r.curves.position, color: "var(--pos)" }], title: tr("rlp_c_position"),
            yMin: shortable ? -1 : 0, yMax: 1, hlines: [{ y: 0, dash: "0", color: "var(--line-strong)" }], yFmt: function (v) { return num(v, 1); }, height: 150 }));

        // plis
        box.appendChild(h("h3", { text: tr("rlp_folds_title") }));
        var withVal = r.folds.some(function (f) { return f.val_score !== undefined && f.val_score !== null; });
        box.appendChild(table([tr("rlp_col_fold"), tr("rlp_col_train"), tr("rlp_col_test"), tr("rlp_col_n")]
                .concat(withVal ? [tr("rlp_col_val"), tr("rlp_col_used")] : [])
                .concat([tr("rlp_col_agent") + " · Sharpe", tr("rlp_col_bh") + " · Sharpe"]),
            r.folds.map(function (f) {
                var used = f.gated ? chip(tr("rlp_used_bench"), "neutral") : chip(tr("rlp_used_agent"), "pos");
                var agent = f.agent || f.strategy;
                return [{ cell: String(f.fold), cls: "num" }, f.train_start + " → " + f.train_end, f.test_start + " → " + f.test_end,
                    { cell: String(f.n_test), cls: "num" }]
                    .concat(withVal ? [numCell(f.val_score === null ? "—" : pct(f.val_score, 1), f.val_score), { cell: used }] : [])
                    .concat([numCell(num(agent.sharpe, 2), agent.sharpe), numCell(num(f.buy_hold.sharpe, 2), f.buy_hold.sharpe)]);
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
            var state = run.status === "done" && run.verdict ? verdictChip(run) : chip(run.status, kind);
            return [{ cell: run.name || run.run_id, cls: "pk-mono" }, (run.target ? (window.PatrickNames ? window.PatrickNames.label(run.target) : run.target) : "—"), run.algo || "—", { cell: state },
                run.sharpe === undefined || run.sharpe === null ? "—" : { cell: num(run.sharpe, 2) + " / " + num(run.sharpe_buy_hold, 2), cls: "num pk-mono" },
                typeof run.excess === "number" ? numCell((run.excess > 0 ? "+" : "") + pct(run.excess, 1), run.excess) : "—",
                { cell: open }];
        });
        box.replaceChildren(table(["", tr("rlp_f_target"), tr("rlp_f_algo"), tr("rlp_rd_title"), tr("rlp_k_sharpe") + " / B&H", tr("rlp_rd_excess"), ""], rows));
    }
    function refreshRuns() {
        fetch("/api/rl/runs").then(function (r) { return r.json(); }).then(function (b) { renderRuns(b.runs || []); }).catch(function () { /* la liste garde son contenu */ });
    }
    try { renderRuns(JSON.parse($("rl-initial-runs").textContent || "[]")); } catch (e) { renderRuns([]); }

    var initial = $("rl-root").dataset.initialRun;
    if (initial) track(initial);
})();
