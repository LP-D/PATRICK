(function () {
    const I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, (m, k) => (params[k] !== undefined ? params[k] : m));
    }

    const PHASE_LABELS = {
        ingestion: tr("phase_ingestion", "Downloading data"),
        features: tr("phase_features", "Building explanatory variables"),
        scan: tr("phase_scan", "Testing combinations (variables × rebalancing × algorithm)"),
        tuning: tr("phase_tuning", "Fine-tuning the best configurations"),
        export: tr("phase_export", "Saving the final model"),
        done: tr("phase_done", "Done."),
    };

    const form = document.getElementById("run-form");
    const settingsModeToggle = document.getElementById("settings-mode-toggle");
    const settingsModeHint = document.getElementById("settings-mode-hint");
    const settingsModeStorageKey = "patrick-launch-settings-mode";
    const profileStorageKey = "patrick-launch-profiles";
    const profileNameInput = document.getElementById("launch-profile-name");
    const profileList = document.getElementById("launch-profile-list");
    const profileStatus = document.getElementById("launch-profile-status");
    const saveProfileButton = document.getElementById("save-launch-profile");
    const loadProfileButton = document.getElementById("load-launch-profile");
    const deleteProfileButton = document.getElementById("delete-launch-profile");

    const compareForm = document.getElementById("compare-runs-form");
    if (compareForm) {
        const compareButton = document.getElementById("compare-runs-submit");
        const compareCount = document.getElementById("compare-runs-count");
        const compareBoxes = Array.from(document.querySelectorAll(".compare-run-checkbox"));
        function updateCompareRunSelection() {
            const checked = compareBoxes.filter((checkbox) => checkbox.checked).length;
            if (compareButton) compareButton.disabled = checked < 2 || checked > 4;
            if (compareCount) compareCount.textContent = fmtStr(
                tr("compare_runs_selection", "Selected: {count}. Choose 2 to 4 completed runs."),
                { count: checked },
            );
            compareBoxes.forEach((checkbox) => {
                checkbox.disabled = !checkbox.checked && checked >= 4;
            });
        }
        compareBoxes.forEach((checkbox) => checkbox.addEventListener("change", updateCompareRunSelection));
        updateCompareRunSelection();
    }

    function setSettingsMode(mode, persist) {
        if (!form || !settingsModeToggle) return;
        const expert = mode === "expert";
        form.dataset.mode = expert ? "expert" : "simple";
        settingsModeToggle.setAttribute("aria-pressed", String(expert));
        settingsModeToggle.textContent = tr(
            expert ? "settings_mode_hide_expert" : "settings_mode_show_expert",
            expert ? "Hide advanced settings" : "Show advanced settings",
        );
        if (settingsModeHint) {
            settingsModeHint.textContent = tr(
                expert ? "settings_mode_expert_hint" : "settings_mode_simple_hint",
                expert
                    ? "All exploratory options are available below."
                    : "Advanced controls are hidden; their current values are preserved.",
            );
        }
        if (persist) {
            try {
                localStorage.setItem(settingsModeStorageKey, expert ? "expert" : "simple");
            } catch (e) {
                // The toggle still works for this page when storage is unavailable.
            }
        }
    }

    if (form && settingsModeToggle) {
        let savedMode = "simple";
        try {
            savedMode = localStorage.getItem(settingsModeStorageKey) === "expert" ? "expert" : "simple";
        } catch (e) {
            // The default mode remains usable when storage is unavailable.
        }
        setSettingsMode(savedMode, false);
        settingsModeToggle.addEventListener("click", function () {
            setSettingsMode(form.dataset.mode === "expert" ? "simple" : "expert", true);
        });
    }

    function showProfileStatus(message, isError) {
        if (!profileStatus) return;
        profileStatus.textContent = message;
        profileStatus.dataset.error = isError ? "true" : "false";
    }

    function readProfiles() {
        try {
            const parsed = JSON.parse(localStorage.getItem(profileStorageKey) || "[]");
            if (!Array.isArray(parsed)) throw new Error("Stored profiles are not a list.");
            return parsed.filter((profile) =>
                profile && typeof profile.name === "string" && profile.fields && typeof profile.fields === "object");
        } catch (error) {
            showProfileStatus(tr("profile_read_error", "Saved profiles could not be read."), true);
            return [];
        }
    }

    function updateProfileOptions() {
        if (!profileList) return;
        const previous = profileList.value;
        const profiles = readProfiles();
        profileList.replaceChildren(new Option(tr("profile_choose", "Choose a saved profile"), ""));
        profiles.forEach((profile) => profileList.add(new Option(profile.name, profile.name)));
        if (profiles.some((profile) => profile.name === previous)) profileList.value = previous;
        const available = Boolean(profileList.value);
        if (loadProfileButton) loadProfileButton.disabled = !available;
        if (deleteProfileButton) deleteProfileButton.disabled = !available;
    }

    function serializeLaunchForm() {
        const fields = {};
        Array.from(form.elements).forEach((element) => {
            if (!element.name || element.disabled || ["button", "submit", "reset", "file"].includes(element.type)) return;
            const controls = Array.from(form.elements).filter((candidate) => candidate.name === element.name);
            if (Object.prototype.hasOwnProperty.call(fields, element.name)) return;
            if (element.type === "checkbox" || element.type === "radio") {
                fields[element.name] = controls.filter((candidate) => candidate.checked).map((candidate) => candidate.value);
            } else if (element instanceof HTMLSelectElement && element.multiple) {
                fields[element.name] = Array.from(element.selectedOptions).map((option) => option.value);
            } else {
                fields[element.name] = [element.value];
            }
        });
        return fields;
    }

    function applyLaunchProfile(fields) {
        Object.entries(fields).forEach(([name, values]) => {
            if (!Array.isArray(values)) return;
            const controls = Array.from(form.elements).filter((element) => element.name === name);
            controls.forEach((element) => {
                if (element.type === "checkbox" || element.type === "radio") {
                    element.checked = values.includes(element.value);
                } else if (element instanceof HTMLSelectElement && element.multiple) {
                    Array.from(element.options).forEach((option) => { option.selected = values.includes(option.value); });
                } else if (values.length) {
                    element.value = values[0];
                }
                element.dispatchEvent(new Event("input", { bubbles: true }));
                element.dispatchEvent(new Event("change", { bubbles: true }));
            });
        });
        if (typeof refreshAdvStates === "function") refreshAdvStates();
    }

    if (form && profileList && saveProfileButton && loadProfileButton && deleteProfileButton) {
        updateProfileOptions();
        if (profileNameInput) {
            profileNameInput.addEventListener("keydown", function (event) {
                if (event.key === "Enter") event.preventDefault();
            });
        }
        profileList.addEventListener("change", updateProfileOptions);
        saveProfileButton.addEventListener("click", function () {
            const name = (profileNameInput ? profileNameInput.value : "").trim();
            if (!name) {
                showProfileStatus(tr("profile_name_required", "Enter a name for this profile."), true);
                if (profileNameInput) profileNameInput.focus();
                return;
            }
            try {
                const profiles = readProfiles().filter((profile) => profile.name !== name);
                profiles.push({ name: name, fields: serializeLaunchForm() });
                localStorage.setItem(profileStorageKey, JSON.stringify(profiles));
                updateProfileOptions();
                profileList.value = name;
                updateProfileOptions();
                showProfileStatus(tr("profile_saved_notice", "Profile saved."), false);
            } catch (error) {
                showProfileStatus(tr("profile_save_error", "The profile could not be saved in this browser."), true);
            }
        });
        loadProfileButton.addEventListener("click", function () {
            const profile = readProfiles().find((entry) => entry.name === profileList.value);
            if (!profile) {
                showProfileStatus(tr("profile_missing", "Select a profile that still exists."), true);
                updateProfileOptions();
                return;
            }
            applyLaunchProfile(profile.fields);
            if (profileNameInput) profileNameInput.value = profile.name;
            showProfileStatus(tr("profile_loaded", "Profile loaded. Review it before launching."), false);
        });
        deleteProfileButton.addEventListener("click", function () {
            const name = profileList.value;
            if (!name) return;
            try {
                const profiles = readProfiles().filter((profile) => profile.name !== name);
                localStorage.setItem(profileStorageKey, JSON.stringify(profiles));
                updateProfileOptions();
                showProfileStatus(tr("profile_deleted", "Profile deleted."), false);
            } catch (error) {
                showProfileStatus(tr("profile_delete_error", "The profile could not be deleted."), true);
            }
        });
    }

    const errorsBanner = document.getElementById("run-errors");
    const errorsList = document.getElementById("run-errors-list");
    const launchBtn = document.getElementById("launch-btn");
    const noRunMessage = document.getElementById("no-run-message");
    // Liste des derniers runs : occupe la colonne « avancement » AU REPOS,
    // s'efface des qu'un run reel prend sa place (le suivi en direct prime).
    const recentRuns = document.getElementById("recent-runs");
    const statusPanel = document.getElementById("status-panel");
    const progressTitle = document.getElementById("progress-title");

    /* Le titre du panneau suit son contenu : « Avancement » quand un run est
       suivi, « Derniers runs » au repos. Un titre qui décrit autre chose que ce
       qu'il surmonte est une erreur de copie, pas un détail. */
    function setProgressTitle(active) {
        if (!progressTitle) return;
        const next = active ? progressTitle.dataset.titleActive : progressTitle.dataset.titleIdle;
        if (next) progressTitle.textContent = next;
    }
    const runNameLine = document.getElementById("run-name-line");
    const fill = document.getElementById("progress-fill");
    const statusLine = document.getElementById("status-line");
    const logTail = document.getElementById("log-tail");
    const stepsList = document.getElementById("steps-list");
    const resultsPanel = document.getElementById("results-panel");
    const queuePanel = document.getElementById("queue-panel");
    const queueSummary = document.getElementById("queue-summary");
    const queueList = document.getElementById("queue-list");
    const queueToggle = document.getElementById("queue-toggle");
    const clearQueueBtn = document.getElementById("clear-queue-btn");
    const runControls = document.getElementById("run-controls");
    const pauseRunBtn = document.getElementById("pause-run-btn");
    const stopRunBtn = document.getElementById("stop-run-btn");

    let trackedRunId = null;
    let activeJobId = null;
    let resultsLoaded = false;
    let detailPollTimer = null;

    // scaleX plutôt que width : évite le reflow (transform anime en GPU).
    //
    // `measuring` = la phase en cours ne produit AUCUNE mesure de progression
    // (`worker.py` n'incrémente `progress_done` que sur les lignes de fold :
    // pendant l'ingestion et les features, il vaut 0). Afficher 0% y serait un
    // chiffre qui ne mesure rien présenté comme une mesure. La barre balaie
    // alors au lieu d'afficher une valeur, et se pose sur sa vraie valeur au
    // premier fold -- c'est le seul moment de mouvement autorisé de l'app.
    const progressBar = fill ? fill.parentElement : null;
    let queuedCount = 0;
    let wasMeasuring = false;

    function setProgress(pct, measuring) {
        if (!fill) return;
        if (measuring) {
            wasMeasuring = true;
            if (progressBar) progressBar.dataset.progressMode = "measuring";
            return;
        }
        if (progressBar) delete progressBar.dataset.progressMode;
        const target = `scaleX(${Math.max(0, Math.min(100, pct)) / 100})`;
        if (wasMeasuring) {
            // On sort du balayage : repartir de zéro sans transition, puis
            // laisser la jauge se poser. Sans ça elle se rétracterait depuis la
            // pleine largeur du masque, ce qui se lirait comme une régression.
            wasMeasuring = false;
            fill.style.transition = "none";
            fill.style.transform = "scaleX(0)";
            void fill.offsetWidth;              // force le reflow avant de ré-armer
            fill.style.transition = "";
        }
        fill.style.transform = target;
    }

    // --- bandeau d'erreurs de validation (soumission AJAX) ---

    function showErrors(errors) {
        errorsList.innerHTML = "";
        (errors || []).forEach((e) => {
            const li = document.createElement("li");
            li.textContent = e;
            errorsList.appendChild(li);
        });
        errorsBanner.classList.remove("hidden");
        errorsBanner.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function clearErrors() {
        errorsBanner.classList.add("hidden");
        errorsList.innerHTML = "";
    }

    // --- suivi détaillé d'un run (progression/logs/résultats) ---

    function startTracking(runId) {
        if (runId === trackedRunId && detailPollTimer) return;
        trackedRunId = runId;
        resultsLoaded = false;
        noRunMessage.classList.add("hidden");
        if (recentRuns) recentRuns.classList.add("hidden");
        statusPanel.classList.remove("hidden");
        setProgressTitle(true);
        resultsPanel.classList.add("hidden");
        resultsPanel.innerHTML = "";
        setProgress(0, false);
        logTail.textContent = "";
        renderSteps([], false);
        statusLine.textContent = "…";
        if (detailPollTimer) clearInterval(detailPollTimer);
        detailPoll();
        detailPollTimer = setInterval(detailPoll, 1500);
    }

    // 95 -> « 1 min 35 s » : des secondes brutes ne se lisent pas au-delà d'une minute.
    function fmtDuration(totalSeconds) {
        const sec = Math.max(0, Math.round(totalSeconds));
        if (sec < 60) return fmtStr(tr("duration_s", "{s}s"), { s: sec });
        if (sec < 3600) {
            return fmtStr(tr("duration_min", "{m} min {s}s"), { m: Math.floor(sec / 60), s: sec % 60 });
        }
        return fmtStr(tr("duration_h", "{h} h {m} min"), { h: Math.floor(sec / 3600), m: Math.floor((sec % 3600) / 60) });
    }

    // Étapes lisibles envoyées par le serveur (`steps`: [{text, level}]). La
    // dernière est « en cours » tant que le run tourne ; les précédentes sont
    // faites. Le texte passe par `textContent` : jamais interprété comme HTML.
    function renderSteps(steps, running) {
        if (!stepsList) return;
        stepsList.innerHTML = "";
        (steps || []).forEach(function (step, i) {
            const li = document.createElement("li");
            const isLast = i === steps.length - 1;
            li.className = "step step-" + (step.level || "info") + (isLast && running ? " step-current" : "");
            li.textContent = step.text;
            stepsList.appendChild(li);
        });
        stepsList.scrollTop = stepsList.scrollHeight;
    }

    const progressStallThresholdMs = 10 * 60 * 1000;
    let progressWatch = { runId: null, done: null, phase: null, status: null, since: 0, warned: false };

    async function detailPoll() {
        if (!trackedRunId) return;
        let data;
        try {
            const res = await fetch(`/runs/${trackedRunId}/status`);
            data = await res.json();
        } catch (e) {
            statusLine.textContent = tr("status_connection_lost", "Connection to server lost — retrying…");
            return;
        }

        if (runNameLine) runNameLine.textContent = data.name || "";

        if (data.status === "queued") {
            setProgress(0, false);
            logTail.textContent = "";
            renderSteps([], false);
            statusLine.textContent = fmtStr(tr("run_queued_confirm", "Run “{name}” queued (position {position})."),
                { name: data.name || trackedRunId, position: data.queue_position ?? "?" });
            return;
        }

        // `done === 0` pendant tout ce qui précède le premier fold (ingestion,
        // features) : rien n'est mesurable, la barre balaie au lieu de mentir.
        const done = data.progress.done || 0;
        const total = data.progress.total || 0;
        if (progressWatch.runId !== data.id || progressWatch.done !== done ||
            progressWatch.phase !== data.phase || progressWatch.status !== data.status) {
            progressWatch = {
                runId: data.id, done: done, phase: data.phase, status: data.status,
                since: Date.now(), warned: false,
            };
        }
        const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
        setProgress(pct, data.status === "running" && done === 0);
        logTail.textContent = data.log_tail.join("\n");
        logTail.scrollTop = logTail.scrollHeight;
        renderSteps(data.steps, data.status === "running");

        if (data.status === "running") {
            const progressText = total > 0
                ? fmtStr(tr("status_progress_units", "{done} of {total} evaluations"), { done: done, total: total })
                : "";
            const elapsed = fmtDuration(data.elapsed_s);
            const remaining = Number.isFinite(data.estimated_remaining_s)
                ? fmtDuration(data.estimated_remaining_s)
                : null;
            const confidence = data.eta_confidence === "moderate" ? "moderate" : "low";
            const statusText = remaining !== null
                ? tr("status_running_eta", "{phase} — {pct}% ({progress}) · elapsed: {elapsed} · about {remaining} left ({confidence} estimate)")
                : total > 0
                    ? tr("status_running_progress", "{phase} — {pct}% ({progress}) · elapsed: {elapsed}")
                    : tr("status_running", "{phase} — {pct}% · elapsed: {elapsed}");
            const params = {
                phase: PHASE_LABELS[data.phase] || tr("phase_other", "Computing"),
                pct: pct,
                progress: progressText,
                elapsed: elapsed,
                remaining: remaining,
                confidence: tr("eta_confidence_" + confidence,
                    confidence === "moderate" ? "rough" : "preliminary"),
            };
            let renderedStatus = fmtStr(statusText, params);
            if (data.phase === "scan" && done > 0 && !progressWatch.warned &&
                Date.now() - progressWatch.since >= progressStallThresholdMs) {
                renderedStatus += " " + tr(
                    "status_progress_stalled",
                    "No new evaluation for 10 minutes; check the technical log. A long computation may be normal.",
                );
                progressWatch.warned = true;
            }
            statusLine.textContent = renderedStatus;
        } else if (data.status === "paused") {
            statusLine.textContent = tr("run_paused", "Paused — resume any time.");
        } else if (data.status === "error") {
            statusLine.innerHTML = `<span class="error-text">${escapeHtml(fmtStr(tr("status_error", "Error: {error}"), { error: data.error }))}</span>`;
            clearInterval(detailPollTimer);
        } else if (data.status === "done") {
            statusLine.textContent = fmtStr(tr("status_done", "Done in {elapsed}."), { elapsed: fmtDuration(data.elapsed_s) });
            setProgress(100, false);
            clearInterval(detailPollTimer);
            if (!resultsLoaded) {
                resultsLoaded = true;
                loadResults(trackedRunId);
            }
        }
    }

    async function loadResults(runId) {
        const res = await fetch(`/runs/${runId}/results`);
        if (!res.ok) return;
        const data = await res.json();
        resultsPanel.classList.remove("hidden");
        resultsPanel.innerHTML = renderResults(data, runId);
        // Fin de la même séquence que la pose de la jauge (le run se termine),
        // pas un second effet indépendant.
        resultsPanel.classList.add("results-arriving");
        resultsPanel.addEventListener("animationend",
            () => resultsPanel.classList.remove("results-arriving"), { once: true });
        attachSort(data.top_rows);
    }

    function renderResults(data, runId) {
        const best = data.final_best;
        const bestHtml = best
            ? `<div class="best-box">
                 <strong>${tr("results_best_config", "Best config")}</strong> — h=${best.horizon ?? "?"}d
                 ${best.regime ?? ""} N=${best.N ?? "?"} ${best.sampler ?? ""} ${best.algo ?? ""}
                 &rarr; F1_dir=${fmt(best.F1_dir)}
               </div>`
            : "";

        const downloads = Object.entries(data.artifacts || {})
            .map(([key, _]) => `<a href="/runs/${runId}/download/${key}" download>${labelFor(key)}</a>`)
            .join("");

        const cols = data.leaderboard_columns || [];
        const head = cols.map((c) => `<th data-col="${c}">${c}</th>`).join("");
        // `data-k` = index d'origine, identité stable d'une ligne à travers
        // n'importe quel tri (cf. le FLIP dans `attachSort`).
        const rows = (data.top_rows || [])
            .map((r, i) => `<tr data-k="${i}">${cols.map((c) => `<td>${fmt(r[c])}</td>`).join("")}</tr>`)
            .join("");

        const tunedPart = data.n_tuned_evaluations
            ? fmtStr(tr("results_summary_tuned", " + {n} after tuning"), { n: data.n_tuned_evaluations })
            : "";
        const summary = fmtStr(tr("results_summary", "{n} evaluations{tuned}."), { n: data.n_evaluations, tuned: tunedPart });
        const leaderboardTitle = fmtStr(tr("results_leaderboard", "Leaderboard (top {n}, sortable by column)"),
            { n: (data.top_rows || []).length });

        return `
            <h3>${tr("results_title", "Results")}</h3>
            <p>${summary}</p>
            ${bestHtml}
            ${renderStatsBox(data)}
            <div class="downloads">${downloads}</div>
            <h4>${leaderboardTitle}</h4>
            <div style="overflow-x:auto">
                <table class="leaderboard" id="leaderboard-table">
                    <thead><tr>${head}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    // Phase 2 (validité statistique) — holdout / Diebold-Mariano / essais
    // cumulés / PBO, calculés une fois pour la config gagnante (cf.
    // run_manager._summarize_result). Absents (null) si pas de config gagnante
    // ou d'historique insuffisant (holdout désactivé, moins de 10 obs. pour DM...).
    function renderStatsBox(data) {
        const lines = [];

        if (data.holdout && data.holdout.metrics) {
            const h = data.holdout.metrics;
            lines.push(fmtStr(tr("stat_holdout", "Terminal holdout ({n} unseen obs.): F1_dir={f1}"),
                { n: data.holdout.n_test ?? "?", f1: fmt(h.F1_dir) }));
        }

        // Phase X5 : deux comparaisons DM (class_specific + common), plutôt
        // qu'une seule baseline "meilleure sur ce fold" toutes classes
        // confondues -- cf. `validation.baseline_by_asset_class`.
        const dm = data.diebold_mariano;
        const renderDmEntry = (entry) => {
            if (!entry || entry.p_value === null || entry.p_value === undefined) return null;
            const significant = entry.p_value < 0.05;
            const key = significant ? "stat_dm_significant" : "stat_dm_not_significant";
            const fallback = significant
                ? "Diebold-Mariano vs {baseline}: p={p} — significant"
                : "Diebold-Mariano vs {baseline}: p={p} — not significant";
            const cls = significant ? "" : ' class="hint"';
            return `<span${cls}>${fmtStr(tr(key, fallback),
                { baseline: entry.baseline || "?", p: fmt(entry.p_value) })}</span>`;
        };
        if (dm) {
            const classLine = renderDmEntry(dm.class_specific);
            if (classLine) lines.push(classLine);
            const commonLine = renderDmEntry(dm.common);
            if (commonLine) lines.push(commonLine);
        }

        if (data.cumulative_trials) {
            lines.push(fmtStr(tr("stat_cumulative_trials", "{n} cumulative trials on this target/horizon (full history)"),
                { n: data.cumulative_trials }));
        }

        const pbo = data.pbo;
        if (pbo && pbo.pbo !== null && pbo.pbo !== undefined) {
            lines.push(fmtStr(tr("stat_pbo", "PBO (backtest overfitting): {pbo} ({n} combinations)"),
                { pbo: fmt(pbo.pbo), n: pbo.n_combinations ?? 0 }));
        }
        // Rapport de correction, C5 : un PBO ponctuel isolé n'est pas
        // interprétable seul (audit : écart-type ~0.16 sur un tirage unique) --
        // toujours afficher l'intervalle de confiance ou le refus explicite à
        // côté, jamais le chiffre nu seul.
        const rel = pbo && pbo.reliability;
        if (rel && rel.ok) {
            lines.push(`<span class="hint">${fmtStr(
                tr("stat_pbo_reliability", "PBO 90% CI (bootstrap, {n} combinations): [{lo}, {hi}] — a single-run PBO is not interpretable in isolation"),
                { n: rel.n_combinations, lo: fmt(rel.ci_low), hi: fmt(rel.ci_high) })}</span>`);
        } else if (rel && !rel.ok) {
            lines.push(`<span class="flag">${rel.message}</span>`);
        }

        if (!lines.length) return "";
        return `<div class="stats-box">${lines.map((l) => `<p>${l}</p>`).join("")}</div>`;
    }

    function attachSort(rows) {
        const table = document.getElementById("leaderboard-table");
        if (!table) return;
        const tbody = table.querySelector("tbody");
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

        table.querySelectorAll("th").forEach((th) => {
            th.addEventListener("click", () => {
                const col = th.dataset.col;
                const asc = th.dataset.sortAsc !== "true";
                th.dataset.sortAsc = asc;
                const sorted = [...rows].sort((a, b) => {
                    const va = a[col], vb = b[col];
                    if (va === vb) return 0;
                    if (va === null || va === undefined) return 1;
                    if (vb === null || vb === undefined) return -1;
                    return asc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
                });
                const cols = Array.from(table.querySelectorAll("thead th")).map((h) => h.dataset.col);

                // FLIP : on relève la position de chaque ligne AVANT de
                // re-rendre, puis on la replace à son ancienne place et on la
                // laisse rejoindre la nouvelle. Sans ça les lignes se
                // téléportent et on perd de vue où la sienne est partie.
                // `data-k` est l'index d'origine : identité stable d'une ligne
                // à travers n'importe quel tri.
                const before = new Map();
                tbody.querySelectorAll("tr[data-k]").forEach((tr) => {
                    before.set(tr.dataset.k, tr.getBoundingClientRect().top);
                });

                tbody.innerHTML = sorted
                    .map((r) => `<tr data-k="${rows.indexOf(r)}">${
                        cols.map((c) => `<td>${fmt(r[c])}</td>`).join("")}</tr>`)
                    .join("");

                if (reduced.matches || !before.size) return;
                tbody.querySelectorAll("tr[data-k]").forEach((tr) => {
                    const prev = before.get(tr.dataset.k);
                    if (prev === undefined) return;
                    const delta = prev - tr.getBoundingClientRect().top;
                    if (!delta) return;
                    tr.style.transform = `translateY(${delta}px)`;
                    requestAnimationFrame(() => {
                        tr.classList.add("flip-move");
                        tr.style.transform = "";
                        tr.addEventListener("transitionend", () => tr.classList.remove("flip-move"),
                                             { once: true });
                    });
                });
            });
        });
    }

    function fmt(v) {
        if (v === null || v === undefined) return "";
        if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(4);
        return escapeHtml(String(v));
    }

    function labelFor(key) {
        const labels = {
            leaderboard_csv: tr("artifact_leaderboard_csv", "Leaderboard (CSV)"),
            leaderboard_xlsx: tr("artifact_leaderboard_xlsx", "Leaderboard (Excel)"),
            tuned_csv: tr("artifact_tuned_csv", "Refined configs (CSV)"),
            best_model: tr("artifact_best_model", "Best model (joblib)"),
            best_model_meta: tr("artifact_best_model_meta", "Metadata (JSON)"),
        };
        if (labels[key]) return labels[key];
        // Per-horizon export keys (`best_model_h5`, `best_model_meta_h5`,
        // see worker.py::_summarize_result) -- not in the fixed map above
        // since the horizon varies per run.
        const meta = key.match(/^best_model_meta_h(\d+)$/);
        if (meta) return fmtStr(tr("artifact_best_model_meta_h", "Metadata h={h}d (JSON)"), { h: meta[1] });
        const model = key.match(/^best_model_h(\d+)$/);
        if (model) return fmtStr(tr("artifact_best_model_h", "Model h={h}d (joblib)"), { h: model[1] });
        return key;
    }

    function escapeHtml(s) {
        const div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    }

    // --- file d'attente : liste déroulante, réordonnable ---

    const QUEUE_OPEN_KEY = "patrick.queueOpen";
    let queueData = [];          // dernier état connu, dans l'ordre d'exécution
    let queueSignature = null;   // ne reconstruire la liste que si elle a changé : un poll toutes les 4 s qui la vide perdait défilement et focus
    let queueDragging = null;    // <li> en cours de glisser-déposer
    let queuePendingFocus = null;

    function setQueueOpen(open) {
        if (!queueToggle) return;
        queueToggle.setAttribute("aria-expanded", open ? "true" : "false");
        queueList.hidden = !open;
        try { localStorage.setItem(QUEUE_OPEN_KEY, open ? "1" : "0"); } catch (e) { /* stockage indisponible */ }
    }
    let queueStoredOpen = false;
    try { queueStoredOpen = localStorage.getItem(QUEUE_OPEN_KEY) === "1"; } catch (e) { /* idem */ }
    setQueueOpen(queueStoredOpen);

    function buildQueueItem(job, index, total) {
        const label = job.name || job.id;
        const item = document.createElement("li");
        item.className = "queue-item";
        item.draggable = true;
        item.dataset.jobId = job.id;
        item.title = tr("queue_drag", "Drag to change the execution order");

        const rank = document.createElement("span");
        rank.className = "queue-rank";
        rank.textContent = `${index + 1}.`;
        const name = document.createElement("span");
        name.className = "queue-name";
        name.textContent = label;

        const actions = document.createElement("span");
        actions.className = "queue-item-actions";
        [
            ["top", "⤒", "queue_move_top", "Move to top", index === 0],
            ["up", "↑", "queue_move_up", "Move up", index === 0],
            ["down", "↓", "queue_move_down", "Move down", index === total - 1],
            ["remove", "✕", "queue_remove", "Remove", false],
        ].forEach(([action, glyph, key, fallback, disabled]) => {
            const text = tr(key, fallback);
            const button = document.createElement("button");
            button.type = "button";
            button.className = "queue-action queue-icon" + (action === "remove" ? " danger" : "");
            button.dataset.jobAction = action;
            button.textContent = glyph;
            button.disabled = disabled;
            button.title = text;
            button.setAttribute("aria-label", `${text} ${label}`);
            actions.appendChild(button);
        });
        item.append(rank, name, actions);
        return item;
    }

    function renderQueue(queue) {
        queueData = queue;
        queuedCount = queue.length;
        if (!queuePanel) return;
        if (!queue.length) {
            queuePanel.classList.add("hidden");
            queueList.replaceChildren();
            queueSignature = null;
            return;
        }
        queuePanel.classList.remove("hidden");
        queueSummary.textContent = fmtStr(tr("queue_summary", "{n} run(s) queued · next: {next}"),
            { n: queue.length, next: queue[0].name || queue[0].id });

        const signature = queue.map((q) => `${q.id}:${q.name}`).join("|");
        if (signature === queueSignature || queueDragging) return;
        queueSignature = signature;
        const scrollTop = queueList.scrollTop;
        queueList.replaceChildren(...queue.map((job, index) => buildQueueItem(job, index, queue.length)));
        queueList.scrollTop = scrollTop;

        if (queuePendingFocus) {
            const row = queueList.querySelector(`li[data-job-id="${queuePendingFocus.jobId}"]`);
            if (row) {
                const preferred = row.querySelector(`button[data-job-action="${queuePendingFocus.action}"]`);
                const target = preferred && !preferred.disabled ? preferred : row.querySelector("button:not(:disabled)");
                if (target) target.focus();
            }
            queuePendingFocus = null;
        }
    }

    // Pas de fenêtre de confirmation : retirer ou réordonner un run en attente
    // est immédiat et sans conséquence durable (le run se relance depuis
    // l'historique). La réponse du serveur est la vérité : si la requête
    // échoue (élément déjà démarré, réseau), on resynchronise sans alerte.
    async function queueRequest(url, options) {
        let queue = null;
        try {
            const response = await fetch(url, options);
            if (response.ok) queue = (await response.json().catch(() => ({}))).queue || null;
        } catch (e) { /* réseau : resynchronisation ci-dessous */ }
        if (queue) { renderQueue(queue); return; }
        queueSignature = null;   // le DOM a pu être réordonné à la main
        await runStatePoll();
    }

    function reorderQueue(ids) {
        return queueRequest("/api/queue/reorder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order: ids }),
        });
    }

    function moveQueueItem(jobId, action) {
        const ids = queueData.map((q) => q.id);
        const from = ids.indexOf(jobId);
        const to = action === "top" ? 0 : action === "up" ? from - 1 : from + 1;
        if (from < 0 || to < 0 || to >= ids.length || to === from) return;
        ids.splice(to, 0, ids.splice(from, 1)[0]);
        queuePendingFocus = { jobId: jobId, action: action };
        reorderQueue(ids);
    }

    // --- état agrégé (file d'attente + détection du run actif courant) ---

    async function runStatePoll() {
        let data;
        try {
            const res = await fetch("/api/run-state");
            data = await res.json();
        } catch (e) {
            return;
        }

        // Retenu pour le récapitulatif de confirmation : « suis-je 3e ? » est
        // la seule question temporelle qui change le comportement avant de
        // lancer, et elle n'était visible nulle part au moment du clic.
        renderQueue(data.queue || []);

        const active = data.active_run;
        activeJobId = active ? active.id : null;
        if (runControls) runControls.classList.toggle("hidden", !active);
        if (pauseRunBtn) {
            if (!active) {
                delete pauseRunBtn.dataset.jobId;
                delete pauseRunBtn.dataset.paused;
                pauseRunBtn.disabled = true;
                pauseRunBtn.textContent = tr("run_pause", "Pause");
            } else {
                pauseRunBtn.dataset.jobId = active.id;
                pauseRunBtn.dataset.paused = active.status === "paused" ? "true" : "false";
                pauseRunBtn.disabled = false;
                pauseRunBtn.textContent = active.status === "paused"
                    ? tr("run_resume", "Resume") : tr("run_pause", "Pause");
            }
        }

        // Le run actif côté serveur a changé (ex: la file d'attente a avancé
        // automatiquement) : on bascule le suivi dessus sans recharger la page.
        if (active && active.id !== trackedRunId) {
            startTracking(active.id);
        }
    }

    // Erreur de contrôle (pause / reprise / arrêt) : bannière de la page, effacée à l'action suivante.
    function showRunControlError(message) {
        const box = document.getElementById("run-control-error");
        if (!box) return;
        box.textContent = message || "";
        box.classList.toggle("hidden", !message);
    }

    async function sendJobControl(url, options) {
        showRunControlError("");
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                const detail = await response.json().catch(() => ({}));
                showRunControlError(typeof detail.detail === "string" && detail.detail
                    ? detail.detail : tr("run_control_error", "Could not apply this action."));
                return;
            }
            await runStatePoll();
            if (trackedRunId) detailPoll();
        } catch (e) {
            showRunControlError(tr("run_control_error", "Could not apply this action."));
        }
    }

    if (pauseRunBtn) {
        pauseRunBtn.addEventListener("click", () => {
            const paused = pauseRunBtn.dataset.paused === "true";
            const action = paused ? "resume" : "pause";
            sendJobControl(`/api/jobs/${pauseRunBtn.dataset.jobId}/${action}`, { method: "POST" });
        });
    }
    if (stopRunBtn) {
        stopRunBtn.addEventListener("click", () => {
            sendJobControl(`/api/jobs/${activeJobId}/stop`, { method: "POST" });
        });
    }
    if (queueToggle) {
        queueToggle.addEventListener("click", () => {
            setQueueOpen(queueToggle.getAttribute("aria-expanded") !== "true");
        });
    }
    if (queueList) {
        queueList.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-job-action]");
            if (!button || button.disabled) return;
            const jobId = button.closest("li").dataset.jobId;
            if (button.dataset.jobAction === "remove") {
                queueRequest(`/api/queue/${jobId}`, { method: "DELETE" });
            } else {
                moveQueueItem(jobId, button.dataset.jobAction);
            }
        });

        // Glisser-déposer : le <li> est déplacé dans le DOM pendant le survol ;
        // l'ordre résultant n'est envoyé qu'au dépôt. Déposer hors de la liste
        // (ou Échap) annule : dropEffect vaut alors "none".
        queueList.addEventListener("dragstart", (event) => {
            const row = event.target.closest && event.target.closest("li.queue-item");
            if (!row) return;
            queueDragging = row;
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", row.dataset.jobId);   // Firefox l'exige
            row.classList.add("dragging");
        });
        queueList.addEventListener("dragover", (event) => {
            if (!queueDragging) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            const over = event.target.closest("li.queue-item");
            if (!over || over === queueDragging) return;
            const rect = over.getBoundingClientRect();
            const reference = event.clientY > rect.top + rect.height / 2 ? over.nextSibling : over;
            if (reference !== queueDragging.nextSibling) queueList.insertBefore(queueDragging, reference);
        });
        queueList.addEventListener("drop", (event) => event.preventDefault());
        queueList.addEventListener("dragend", (event) => {
            if (!queueDragging) return;
            queueDragging.classList.remove("dragging");
            queueDragging = null;
            const ids = Array.from(queueList.children, (li) => li.dataset.jobId);
            const moved = ids.some((id, i) => !queueData[i] || id !== queueData[i].id);
            if (moved && event.dataTransfer.dropEffect !== "none") {
                reorderQueue(ids);
            } else {
                queueSignature = null;
                renderQueue(queueData);
            }
        });
    }
    if (clearQueueBtn) {
        clearQueueBtn.addEventListener("click", () => queueRequest("/api/queue", { method: "DELETE" }));
    }

    // --- soumission du formulaire settings, sans rechargement de page ---

    if (form) {
        form.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            /* Un run engage plusieurs heures de calcul — le contexte produit
               parle de ~380s rien que pour le pool de features, et de runs
               lancés la nuit. Il était déclenché comme un lien : pas de
               confirmation, pas de récapitulatif, pas de rang en file.
               Deux temps désormais, dans la barre elle-même : le premier clic
               déplie ce qui va tourner, le second lance. Pas de fenêtre
               modale — l'action n'a pas besoin d'interrompre, juste d'être
               relue. */
            if (!confirmArmed) { armConfirm(); return; }
            disarmConfirm();
            clearErrors();
            launchBtn.disabled = true;
            try {
                const res = await fetch("/runs", { method: "POST", body: new FormData(form) });
                const data = await res.json();
                if (!res.ok) {
                    showErrors(data.errors || [tr("run_launch_error", "Error launching the run.")]);
                    return;
                }
                // Chaque job posé (un par cible sélectionnée) est 'queued' à cet
                // instant (cf. run_manager.start_run) : le passage à 'running' est
                // décidé par le worker séparé, repéré par le polling périodique de
                // l'état de la file (runStatePoll), jamais ici.
                runStatePoll();
            } catch (e) {
                showErrors([tr("run_launch_error", "Error launching the run.")]);
            } finally {
                launchBtn.disabled = false;
            }
        });
    }

    /* -----------------------------------------------------------------------
       Validation en langue de l'interface.
       Le navigateur affiche ses bulles natives dans la langue du NAVIGATEUR,
       pas dans celle de la page : « Please fill out this field. » apparaissait
       sur une interface en français. On remplace le message, sans toucher à la
       validation elle-même.
       ----------------------------------------------------------------------- */
    if (form) {
        form.addEventListener("invalid", function (ev) {
            const el = ev.target;
            if (!el.setCustomValidity) return;
            if (el.validity.valueMissing) el.setCustomValidity(tr("validation_required", "Ce champ est obligatoire."));
            else if (el.validity.rangeUnderflow || el.validity.rangeOverflow)
                el.setCustomValidity(tr("validation_range", "Valeur hors des bornes autorisées."));
            else if (el.validity.badInput || el.validity.typeMismatch)
                el.setCustomValidity(tr("validation_type", "Format attendu non respecté."));
        }, true);
        // Le message personnalisé colle au champ tant qu'on ne le vide pas :
        // sans ce nettoyage, un champ corrigé resterait invalide.
        form.addEventListener("input", function (ev) {
            if (ev.target.setCustomValidity) ev.target.setCustomValidity("");
        });
    }

    /* -----------------------------------------------------------------------
       Confirmation de lancement, en deux temps et sans fenêtre modale.
       ----------------------------------------------------------------------- */
    var confirmArmed = false;
    var launchBar = launchBtn ? launchBtn.closest(".launch-bar") : null;

    /* Publie la hauteur réelle de la barre collante dans `--launch-bar-h`, que
       `html { scroll-padding-bottom }` consomme. Elle varie de 68 à 165px selon
       l'état armé, la largeur et l'enroulement du récapitulatif : une valeur
       figée dans le CSS aurait été fausse la moitié du temps. */
    if (launchBar && window.ResizeObserver) {
        new ResizeObserver(function (entries) {
            // `contentRect` EXCLUT le remplissage : mesuré, il rendait 35px pour
            // une barre qui en fait 68 — la réserve de défilement valait la
            // moitié de ce qu'il fallait. C'est la boîte de bordure qui compte.
            var box = entries[0].borderBoxSize && entries[0].borderBoxSize[0];
            var h = Math.round(box ? box.blockSize : entries[0].target.getBoundingClientRect().height);
            document.documentElement.style.setProperty("--launch-bar-h", h + "px");
        }).observe(launchBar);
    }
    var launchLabel = launchBtn ? launchBtn.textContent.trim() : "";
    var cancelBtn = null;

    function countList(value) {
        if (!value) return 0;
        return value.split(",").map(function (x) { return x.trim(); }).filter(Boolean).length;
    }

    /* `horizons` est passé de <input type=text> à <select multiple> : sur un
       <select multiple>, `.value` ne renvoie QUE la valeur de la première
       option sélectionnée (comportement DOM standard), jamais la liste
       entière -- exactement le même piège qu'un `<select multiple
       id="target_symbols">` non traité aurait posé. Les trois lectures
       ci-dessous (comptage pour la projection de combinaisons, résumé de
       confirmation, récap de la barre de lancement) passent par
       `selectedOptions` au lieu de `.value`. */
    function selectedValues(el) {
        if (!el) return [];
        if (el.multiple) return Array.prototype.map.call(el.selectedOptions, function (o) { return o.value; });
        return el.value ? [el.value] : [];
    }

    /* Nombre de combinaisons que le scan va évaluer. Calculé, pas estimé :
       c'est le produit des cardinalités que le formulaire porte déjà. Une
       durée en minutes serait une invention — la machine et la cible la
       déterminent, pas le formulaire. */
    function projectedCombinations() {
        if (!form) return null;
        var grid = countList((form.querySelector("[name=n_features_grid]") || {}).value);
        var horizons = selectedValues(form.querySelector("[name=horizons]")).length;
        var regimes = countList((form.querySelector("[name=regimes]") || {}).value);
        var algos = form.querySelectorAll("[name=algos]:checked").length;
        var samplers = form.querySelectorAll("[name=sampler_candidates]:checked").length;
        if (!grid || !horizons || !algos) return null;
        return grid * horizons * Math.max(1, regimes) * algos * Math.max(1, samplers);
    }

    function armConfirm() {
        if (!launchBar || !launchBtn) return;
        confirmArmed = true;
        launchBar.dataset.confirm = "";
        // `#target_symbol` (singulier) a été remplacé par un `<select multiple
        // id="target_symbols">` -- la confirmation doit lister TOUTES les
        // cibles sélectionnées, pas une seule, sans quoi un lancement en batch
        // se confirmerait sur un résumé qui n'en montre qu'une (ou aucune).
        var targetSelect = form.querySelector("#target_symbols");
        var target = targetSelect
            ? Array.prototype.map.call(targetSelect.selectedOptions, function (o) { return o.value; }).join(", ") || "?"
            : "?";
        var horizons = selectedValues(form.querySelector("[name=horizons]")).join(", ") || "?";
        var regimes = (form.querySelector("[name=regimes]") || {}).value || "?";
        var algos = Array.prototype.map.call(form.querySelectorAll("[name=algos]:checked"),
            function (el) { return el.value; });
        var targetCount = targetSelect ? targetSelect.selectedOptions.length : 0;
        var schemeSel = form.querySelector("[name=scheme]");
        var scheme = schemeSel && schemeSel.selectedIndex >= 0
            ? schemeSel.options[schemeSel.selectedIndex].textContent.trim() : "?";
        var combos = projectedCombinations();
        var stagedBox = form.querySelector("[name=staged_screening]");
        var finalists = parseInt((form.querySelector("[name=screening_finalists_per_group]") || {}).value, 10) || 1;
        var topK = parseInt((form.querySelector("[name=top_k]") || {}).value, 10) || 1;
        var perHorizon = combos !== null ? combos / Math.max(1, selectedValues(form.querySelector("[name=horizons]")).length) : null;
        var stagedLine = stagedBox && stagedBox.checked && perHorizon !== null
            ? fmtStr(tr("confirm_line_staged", "Dépistage par étapes : les {n} candidats sont testés sur le 1er fold, seuls les {f} meilleur(s) de chaque horizon continuent sur les folds suivants."), { n: perHorizon, f: finalists })
            : tr("confirm_line_exhaustive", "Exploration exhaustive : chaque candidat est évalué sur tous les folds.");
        // L'état des briques de rigueur, à l'instant où le refus coûte encore
        // zéro seconde de calcul. Les nommer seulement dans les blocs repliés
        // ne suffit pas : on confirme sans les avoir rouverts.
        var gates = RIGOR_GATES.map(function (name) {
            var el = form.querySelector('input[type=checkbox][name="' + name + '"]');
            if (!el) return null;
            return tr("gate_" + name, name) + " " + (el.checked ? "ON" : "OFF");
        }).filter(Boolean);
        var bits = [
            fmtStr(tr("confirm_line_target", "Cible {t}, horizons {h}, régimes {r}."),
                { t: target, h: horizons, r: regimes }),
            fmtStr(tr("confirm_line_scheme", "Schéma {s}."), { s: scheme }),
            combos !== null
                ? fmtStr(tr("confirm_line_combos", "{n} combinaisons à évaluer par cible."), { n: combos })
                : tr("confirm_line_combos_unknown", "Nombre de combinaisons non calculable depuis ce formulaire."),
            stagedLine,
            fmtStr(tr("confirm_line_models", "Modèles : {models}. Runs cibles en file : {targets}."),
                { models: algos.join(", ") || "?", targets: targetCount }),
            form.querySelector("[name=tuning_enabled]") && form.querySelector("[name=tuning_enabled]").checked
                ? tr("confirm_line_tuning", "Le tuning Optuna est activé et ajoutera des calculs après le scan.")
                  + " " + fmtStr(tr("confirm_line_topk", "Optuna affinera les {k} meilleure(s) configuration(s) de chaque horizon."), { k: topK })
                : tr("confirm_line_tuning_off", "Le tuning Optuna est désactivé."),
            combos !== null && combos >= 1000
                ? tr("confirm_line_large", "Espace de recherche important : vérifie si toutes les grilles et tous les modèles sont utiles.")
                : "",
            queuedCount > 0
                ? fmtStr(tr("confirm_line_queue", "{n} run(s) déjà en file : celui-ci démarrera après."), { n: queuedCount })
                : tr("confirm_line_queue_free", "Aucun run en file : celui-ci démarre immédiatement."),
        ];
        if (gates.length) {
            bits.push(fmtStr(tr("confirm_line_gates", "Rigueur : {g}."), { g: gates.join(", ") }));
        }
        if (launchRecap) launchRecap.textContent = bits.filter(Boolean).join(" ");
        launchBtn.textContent = tr("btn_confirm_launch", "Confirmer le lancement");
        if (!cancelBtn) {
            cancelBtn = document.createElement("button");
            cancelBtn.type = "button";
            cancelBtn.className = "launch-cancel";
            cancelBtn.addEventListener("click", function () { disarmConfirm(); launchBtn.focus(); });
            launchBar.appendChild(cancelBtn);
        }
        cancelBtn.textContent = tr("btn_cancel", "Annuler");
        cancelBtn.hidden = false;
        launchBtn.focus();
    }

    function disarmConfirm() {
        confirmArmed = false;
        if (launchBar) delete launchBar.dataset.confirm;
        if (launchBtn) launchBtn.textContent = launchLabel;
        if (cancelBtn) cancelBtn.hidden = true;
        refreshRecap();
    }

    /* Toute modification du formulaire désarme la confirmation : sinon on
       confirme un récapitulatif qui ne décrit plus ce qu'on va lancer. */
    if (form) {
        form.addEventListener("input", function () { if (confirmArmed) disarmConfirm(); });
        form.addEventListener("change", function () { if (confirmArmed) disarmConfirm(); });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && confirmArmed) disarmConfirm();
        });
    }

    /* -----------------------------------------------------------------------
       Divulgation progressive : résumé d'état des blocs repliés.

       Un bloc replié qui ne dit rien de son contenu ne réduit pas la charge,
       il la déplace — il faut l'ouvrir pour savoir. Chaque `<details.adv>`
       affiche donc ce que ses contrôles valent réellement : cases cochées,
       valeurs de listes. Sans ça, replier neuf blocs revenait à cacher les
       réglages plutôt qu'à les hiérarchiser.

       Le marqueur « modifié » compare à l'état AU CHARGEMENT de la page, pas
       aux défauts du produit : c'est la seule référence dont le navigateur
       dispose honnêtement. Charger un exemple recharge la page, donc la
       référence se réaligne — ce qui est le comportement voulu.
       ----------------------------------------------------------------------- */
    const advBlocks = Array.from(document.querySelectorAll("details.adv"));
    const advBaseline = new Map();

    function advSignature(block) {
        return Array.from(block.querySelectorAll("input, select, textarea"))
            .map((el) => (el.type === "checkbox" || el.type === "radio" ? String(el.checked) : el.value))
            .join("");
    }

    /* Le libellé d'une case, sans son appel de glossaire. Sans ce nettoyage le
       « i » du bouton `.info-icon` se collait au résumé (« Activéi »,
       « Portes de qualité activési ») : `textContent` d'un label inclut le
       texte de TOUS ses descendants, bouton compris. */
    function labelTextOf(el) {
        const label = el.closest("label");
        if (!label) return el.name;
        const clone = label.cloneNode(true);
        clone.querySelectorAll(".info-icon, input, select, textarea").forEach((n) => n.remove());
        return clone.textContent.replace(/\s+/g, " ").trim();
    }

    /* LES BRIQUES DE RIGUEUR SONT TOUJOURS RENDUES, ON COMME OFF.

       Défaut introduit par le repli du formulaire et rattrapé ici : le résumé
       n'itérait que sur les cases COCHÉES. Or `purge`, `calibration` et
       `stacking` valent `false` par défaut — le mot « purge » n'apparaissait
       donc nulle part, et on pouvait lancer un run sans purge sans l'avoir su,
       sur un produit dont l'argument est que la fuite est structurellement
       empêchée. PRODUCT.md l'interdit en toutes lettres : « aucune ne doit
       devenir un défaut silencieux. »

       Une case ordinaire ne se résume que si elle est cochée — c'est un
       réglage. Une brique de rigueur se résume TOUJOURS — c'est une garantie,
       et son absence est précisément l'information qui compte. */
    const RIGOR_GATES = [
        "data_quality_enabled", "purge", "embargo_enabled",
        "uniqueness_weights", "calibration", "stacking",
    ];

    /* Deux éléments au plus après les briques, puis un compte. Le résumé tient
       sur UNE ligne à côté de son titre : mesuré à trois éléments, « Embargo
       (retire les premières lignes de test après la coupure) » repoussait le
       titre sur une deuxième ligne et le résumé cessait d'être un résumé. */
    const ADV_STATE_MAX = 2;

    /* Coupe sur une frontière de mot plutôt qu'au caractère près : les résumés
       tronquaient en plein mot (« Poids d'unicité / bootstr… »). */
    function ellipsize(text, max) {
        if (text.length <= max) return text;
        const cut = text.slice(0, max);
        const boundary = Math.max(cut.lastIndexOf(" "), cut.lastIndexOf("("), cut.lastIndexOf("/"));
        return (boundary > max * 0.5 ? cut.slice(0, boundary) : cut).trimEnd() + "…";
    }

    function advGates(block) {
        const out = [];
        RIGOR_GATES.forEach((name) => {
            const el = block.querySelector(`input[type=checkbox][name="${name}"]`);
            if (el) out.push({ name: name, on: el.checked });
        });
        return out;
    }

    function advSummaryParts(block) {
        const gateNames = advGates(block).map((g) => g.name);
        const parts = [];
        // Une case sans `value` porte son sens dans son libellé (« Purge »,
        // « Embargo ») ; une case avec `value` porte un nom de famille ou
        // d'algo. Les deux se résument, mais pas par la même chaîne.
        Array.from(block.querySelectorAll("input[type=checkbox]:checked")).forEach((el) => {
            if (gateNames.indexOf(el.name) !== -1) return;   // déjà rendue comme brique
            const v = el.getAttribute("value");
            parts.push(v || labelTextOf(el));
        });
        Array.from(block.querySelectorAll("select")).forEach((sel) => {
            if (sel.selectedIndex >= 0) parts.push(sel.options[sel.selectedIndex].textContent.trim());
        });
        return parts;
    }

    /* Écrit le résumé en NŒUDS, pas en chaîne : l'état d'une brique doit être
       lisible sans lire, donc « OFF » se colore. Construit par le DOM et jamais
       par `innerHTML` — les libellés viennent de la traduction, ils n'ont rien
       à faire dans un analyseur HTML. */
    function writeAdvState(out, block) {
        out.textContent = "";
        const gates = advGates(block);
        gates.forEach((g) => {
            const chip = document.createElement("span");
            chip.className = "adv-gate";
            if (!g.on) chip.dataset.off = "";
            chip.textContent = tr("gate_" + g.name, g.name) + " " + (g.on ? "ON" : "OFF");
            out.appendChild(chip);
        });
        const parts = advSummaryParts(block);
        let text;
        if (!parts.length) {
            if (gates.length) return;   // les briques disent déjà tout
            const n = block.querySelectorAll("input, select, textarea").length;
            text = fmtStr(tr("adv_state_fields", "{n} réglage(s)"), { n: n });
        } else {
            const shown = parts.slice(0, ADV_STATE_MAX).map((x) => ellipsize(x, 26)).join(" · ");
            text = parts.length > ADV_STATE_MAX
                ? shown + " " + fmtStr(tr("adv_state_more", "+{n}"), { n: parts.length - ADV_STATE_MAX })
                : shown;
        }
        const tail = document.createElement("span");
        tail.className = "adv-tail";
        tail.textContent = text;
        out.appendChild(tail);
    }

    function refreshAdvStates() {
        advBlocks.forEach((block) => {
            const out = block.querySelector(".adv-state");
            if (!out) return;
            writeAdvState(out, block);
            const base = advBaseline.get(block);
            if (base !== undefined && advSignature(block) !== base) {
                out.dataset.modified = "";
                out.title = tr("adv_state_modified", "Modifié depuis le chargement de la page");
            } else {
                delete out.dataset.modified;
                out.removeAttribute("title");
            }
        });
    }

    /* Récapitulatif de la barre de lancement : au moment du clic, la cible et
       les horizons sont neuf blocs plus haut et hors du champ de vision. */
    const launchRecap = document.getElementById("launch-recap");
    function refreshRecap() {
        if (!launchRecap || !form) return;
        const target = form.querySelector("#target_symbols");
        const horizons = form.querySelector("[name=horizons]");
        const scheme = form.querySelector("[name=scheme]");
        const bits = [];
        if (target) {
            const selected = Array.from(target.selectedOptions).map((o) => o.value);
            if (selected.length === 1) bits.push("<b>" + selected[0] + "</b>");
            else if (selected.length > 1) bits.push(fmtStr(tr("recap_targets_count", "{n} targets"), { n: selected.length }));
        }
        const horizonsVals = selectedValues(horizons);
        if (horizonsVals.length) {
            bits.push(fmtStr(tr("recap_horizons", "horizons {h}"), { h: horizonsVals.join(", ") }));
        }
        if (scheme && scheme.selectedIndex >= 0) bits.push(scheme.options[scheme.selectedIndex].textContent.trim());
        launchRecap.innerHTML = bits.join(" · ");
    }

    // --- aperçu (lecture seule) du nom que le serveur attribuera à chaque
    // cible sélectionnée -- appelle /api/next-run-names, ne réserve rien. ---
    const runNamePreview = document.getElementById("run-name-preview");
    async function refreshRunNamePreview() {
        if (!runNamePreview || !form) return;
        const select = form.querySelector("#target_symbols");
        if (!select) return;
        const selected = Array.from(select.selectedOptions).map((o) => o.value);
        if (!selected.length) {
            runNamePreview.value = "";
            return;
        }
        const params = new URLSearchParams();
        selected.forEach((s) => params.append("target", s));
        try {
            const res = await fetch(`/api/next-run-names?${params}`);
            const names = await res.json();
            runNamePreview.value = selected.map((s) => names[s]).filter(Boolean).join(", ");
        } catch (e) {
            // aperçu best-effort : une panne réseau ne doit pas bloquer le formulaire.
        }
    }

    // --- feature/expanded-horizons : désactive les <option> d'horizon
    // infaisables (historique insuffisant, cf. validation/feasibility.py)
    // pour la/les cible(s) actuellement sélectionnée(s) -- même mécanisme
    // que refreshRunNamePreview ci-dessus (petit endpoint dédié, appelé au
    // chargement et à chaque changement de cible). `disabled`, jamais
    // seulement masqué : une combinaison infaisable reste visible mais non
    // sélectionnable, avec le motif exact en tooltip (`title`). La
    // validation faisant foi reste côté serveur (`forms.build_config_dict`)
    // -- ceci n'est qu'un confort, contournable (JS désactivé, appel direct
    // à l'API) sans jamais laisser passer un run infaisable pour autant. ---
    const horizonsSelect = document.getElementById("horizons");
    async function refreshHorizonFeasibility() {
        if (!horizonsSelect || !form) return;
        const targetSelect = form.querySelector("#target_symbols");
        if (!targetSelect) return;
        const selected = Array.from(targetSelect.selectedOptions).map((o) => o.value);
        if (!selected.length) return;
        const params = new URLSearchParams();
        selected.forEach((s) => params.append("target", s));
        let data;
        try {
            const res = await fetch(`/api/horizon-feasibility?${params}`);
            data = await res.json();
        } catch (e) {
            return; // best-effort : une panne réseau laisse les options telles quelles.
        }
        let deselected = false;
        Array.from(horizonsSelect.options).forEach((opt) => {
            const info = data[opt.value];
            if (info && info.feasible === false) {
                opt.disabled = true;
                opt.title = info.reason || "";
                if (opt.selected) {
                    opt.selected = false;
                    deselected = true;
                }
            } else {
                opt.disabled = false;
                opt.removeAttribute("title");
            }
        });
        if (deselected) refreshRecap();
    }

    if (advBlocks.length || launchRecap) {
        advBlocks.forEach((block) => advBaseline.set(block, advSignature(block)));
        refreshAdvStates();
        refreshRecap();
        if (form) {
            form.addEventListener("change", function () { refreshAdvStates(); refreshRecap(); });
            form.addEventListener("input", refreshRecap);
        }
    }

    const targetSymbolsSelect = document.getElementById("target_symbols");
    if (targetSymbolsSelect) {
        targetSymbolsSelect.addEventListener("change", refreshRunNamePreview);
        targetSymbolsSelect.addEventListener("change", refreshHorizonFeasibility);
        refreshRunNamePreview();
        refreshHorizonFeasibility();
    }

    /* Les lignes de « plus fortes variations » posent leur symbole dans le
       champ Cible. Un symbole absent de la liste des cibles ne peut pas être
       choisi : on le dit au lieu d'échouer en silence. */
    /* L'appel de note suit la méthode choisie : une définition n'a d'intérêt
       que pour la méthode active. */
    const selectionInfo = document.getElementById("selection-method-info");
    const selectionSelect = form ? form.querySelector("[name=selection_method]") : null;
    if (selectionInfo && selectionSelect) {
        selectionSelect.addEventListener("change", function () {
            const m = selectionSelect.value;
            const btn = selectionInfo.querySelector(".info-icon");
            if (!btn) return;
            btn.dataset.term = m;
            btn.dataset.termLabel = m.toUpperCase();
            btn.setAttribute("aria-label", fmtStr(tr("glossary_open_aria", "Définition : {term}"),
                { term: m.toUpperCase() }));
        });
    }

    const moversColumns = document.getElementById("movers-columns");
    if (moversColumns) {
        moversColumns.addEventListener("click", function (ev) {
            const btn = ev.target.closest(".movers-pick");
            if (!btn) return;
            const select = document.getElementById("target_symbols");
            if (!select) return;
            const symbol = btn.dataset.symbol;
            const option = Array.from(select.options).find((o) => o.value === symbol);
            if (!option) {
                btn.title = fmtStr(tr("movers_not_a_target", "{s} n'est pas une cible disponible."), { s: symbol });
                return;
            }
            // Additif, pas remplacement : un clic sur une variation ajoute
            // cette cible à la sélection en cours au lieu de l'écraser --
            // c'est ainsi qu'on compose un batch depuis ce panneau.
            option.selected = true;
            // `change` déclenche le rechargement de l'aperçu marché (market.js)
            // et le rafraîchissement du récapitulatif/de l'aperçu de nom : poser
            // `.selected` seul ne notifie personne.
            select.dispatchEvent(new Event("change", { bubbles: true }));
            select.focus({ preventScroll: false });
        });
    }

    if (window.INITIAL_RUN_ID) {
        startTracking(window.INITIAL_RUN_ID);
    }

    runStatePoll();
    setInterval(runStatePoll, 4000);
})();

/* Page « Lancer » : le benchmark n'a de sens que pour une cible alpha. */
(function () {
    "use strict";
    var kind = document.getElementById("target_kind"), field = document.getElementById("benchmark-field");
    if (!kind || !field) return;
    function sync() { field.hidden = kind.value !== "alpha"; }
    kind.addEventListener("change", sync);
    sync();
})();
