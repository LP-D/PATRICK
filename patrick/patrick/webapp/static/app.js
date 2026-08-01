(function () {
    const I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, (m, k) => (params[k] !== undefined ? params[k] : m));
    }

    const PHASE_LABELS = {
        ingestion: tr("phase_ingestion", "Ingesting data…"),
        features: tr("phase_features", "Building features…"),
        scan: tr("phase_scan", "Selection × sampler × algo grid…"),
        tuning: tr("phase_tuning", "Optuna tuning of the best configs…"),
        export: tr("phase_export", "Exporting final model…"),
        done: tr("phase_done", "Done."),
    };

    const form = document.getElementById("run-form");
    const errorsBanner = document.getElementById("run-errors");
    const errorsList = document.getElementById("run-errors-list");
    const launchBtn = document.getElementById("launch-btn");
    const noRunMessage = document.getElementById("no-run-message");
    // Liste des derniers runs : occupe la colonne « avancement » AU REPOS,
    // s'efface des qu'un run reel prend sa place (le suivi en direct prime).
    const recentRuns = document.getElementById("recent-runs");
    const statusPanel = document.getElementById("status-panel");
    const runNameLine = document.getElementById("run-name-line");
    const fill = document.getElementById("progress-fill");
    const statusLine = document.getElementById("status-line");
    const logTail = document.getElementById("log-tail");
    const resultsPanel = document.getElementById("results-panel");
    const queuePanel = document.getElementById("queue-panel");
    const queueSummary = document.getElementById("queue-summary");

    let trackedRunId = null;
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
        resultsPanel.classList.add("hidden");
        resultsPanel.innerHTML = "";
        setProgress(0, false);
        logTail.textContent = "";
        statusLine.textContent = "…";
        if (detailPollTimer) clearInterval(detailPollTimer);
        detailPoll();
        detailPollTimer = setInterval(detailPoll, 1500);
    }

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
            statusLine.textContent = fmtStr(tr("run_queued_confirm", "Run “{name}” queued (position {position})."),
                { name: data.name || trackedRunId, position: data.queue_position ?? "?" });
            return;
        }

        // `done === 0` pendant tout ce qui précède le premier fold (ingestion,
        // features) : rien n'est mesurable, la barre balaie au lieu de mentir.
        const done = data.progress.done || 0;
        const total = data.progress.total || 0;
        const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
        setProgress(pct, data.status === "running" && done === 0);
        logTail.textContent = data.log_tail.join("\n");
        logTail.scrollTop = logTail.scrollHeight;

        if (data.status === "running") {
            statusLine.textContent = fmtStr(tr("status_running", "{phase} ({pct}%, {elapsed}s elapsed)"), {
                phase: PHASE_LABELS[data.phase] || data.phase, pct: pct, elapsed: Math.round(data.elapsed_s),
            });
        } else if (data.status === "error") {
            statusLine.innerHTML = `<span class="error-text">${escapeHtml(fmtStr(tr("status_error", "Error: {error}"), { error: data.error }))}</span>`;
            clearInterval(detailPollTimer);
        } else if (data.status === "done") {
            statusLine.textContent = fmtStr(tr("status_done", "Done in {elapsed}s."), { elapsed: Math.round(data.elapsed_s) });
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

        const dm = data.diebold_mariano;
        if (dm && dm.p_value !== null && dm.p_value !== undefined) {
            const significant = dm.p_value < 0.05;
            const key = significant ? "stat_dm_significant" : "stat_dm_not_significant";
            const fallback = significant
                ? "Diebold-Mariano vs {baseline}: p={p} — significant"
                : "Diebold-Mariano vs {baseline}: p={p} — not significant";
            const cls = significant ? "" : ' class="hint"';
            lines.push(`<span${cls}>${fmtStr(tr(key, fallback),
                { baseline: dm.baseline || "?", p: fmt(dm.p_value) })}</span>`);
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
        return labels[key] || key;
    }

    function escapeHtml(s) {
        const div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
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

        if (data.queue && data.queue.length) {
            const names = data.queue.map((q) => q.name).join(", ");
            queueSummary.textContent = fmtStr(tr("queue_summary", "{n} run(s) queued: {names}"),
                { n: data.queue.length, names: names });
            queuePanel.classList.remove("hidden");
        } else {
            queuePanel.classList.add("hidden");
        }

        // Le run actif côté serveur a changé (ex: la file d'attente a avancé
        // automatiquement) : on bascule le suivi dessus sans recharger la page.
        if (data.active_run && data.active_run.id !== trackedRunId) {
            startTracking(data.active_run.id);
        }
    }

    // --- soumission du formulaire settings, sans rechargement de page ---

    if (form) {
        form.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            clearErrors();
            launchBtn.disabled = true;
            try {
                const res = await fetch("/runs", { method: "POST", body: new FormData(form) });
                const data = await res.json();
                if (!res.ok) {
                    showErrors(data.errors || [tr("run_launch_error", "Error launching the run.")]);
                    return;
                }
                if (data.status === "running") {
                    startTracking(data.run_id);
                } else {
                    // "queued" : le run affiché reste celui déjà actif ; on
                    // rafraîchit juste la file d'attente tout de suite plutôt
                    // que d'attendre le prochain tick de runStatePoll.
                    runStatePoll();
                }
            } catch (e) {
                showErrors([tr("run_launch_error", "Error launching the run.")]);
            } finally {
                launchBtn.disabled = false;
            }
        });
    }

    if (window.INITIAL_RUN_ID) {
        startTracking(window.INITIAL_RUN_ID);
    }

    runStatePoll();
    setInterval(runStatePoll, 4000);
})();
