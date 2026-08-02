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

        // Retenu pour le récapitulatif de confirmation : « suis-je 3e ? » est
        // la seule question temporelle qui change le comportement avant de
        // lancer, et elle n'était visible nulle part au moment du clic.
        queuedCount = (data.queue && data.queue.length) || 0;

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

    /* -----------------------------------------------------------------------
       Chargement d'un exemple : confirmer avant d'écraser la saisie.
       ----------------------------------------------------------------------- */
    const exampleForm = document.getElementById("example-form");
    const exampleSelect = document.getElementById("load");
    if (exampleForm && exampleSelect && form) {
        // Empreinte du formulaire au chargement : c'est la seule référence
        // honnête dont dispose le navigateur pour dire « tu as saisi quelque
        // chose ». Charger un exemple recharge la page, donc elle se réaligne.
        const formBaseline = new URLSearchParams(new FormData(form)).toString();
        exampleSelect.addEventListener("change", function () {
            if (!exampleSelect.value) return;
            const dirty = new URLSearchParams(new FormData(form)).toString() !== formBaseline;
            if (dirty && !window.confirm(fmtStr(
                tr("load_example_confirm",
                   "Charger « {name} » remplacera toute la configuration en cours. Continuer ?"),
                { name: exampleSelect.value }))) {
                exampleSelect.value = "";
                return;
            }
            exampleForm.submit();
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

    /* Nombre de combinaisons que le scan va évaluer. Calculé, pas estimé :
       c'est le produit des cardinalités que le formulaire porte déjà. Une
       durée en minutes serait une invention — la machine et la cible la
       déterminent, pas le formulaire. */
    function projectedCombinations() {
        if (!form) return null;
        var grid = countList((form.querySelector("[name=n_features_grid]") || {}).value);
        var horizons = countList((form.querySelector("[name=horizons]") || {}).value);
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
        var target = (form.querySelector("#target_symbol") || {}).value || "?";
        var horizons = (form.querySelector("[name=horizons]") || {}).value || "?";
        var regimes = (form.querySelector("[name=regimes]") || {}).value || "?";
        var schemeSel = form.querySelector("[name=scheme]");
        var scheme = schemeSel && schemeSel.selectedIndex >= 0
            ? schemeSel.options[schemeSel.selectedIndex].textContent.trim() : "?";
        var combos = projectedCombinations();
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
                ? fmtStr(tr("confirm_line_combos", "{n} combinaisons à évaluer."), { n: combos })
                : tr("confirm_line_combos_unknown", "Nombre de combinaisons non calculable depuis ce formulaire."),
            queuedCount > 0
                ? fmtStr(tr("confirm_line_queue", "{n} run(s) déjà en file : celui-ci démarrera après."), { n: queuedCount })
                : tr("confirm_line_queue_free", "Aucun run en file : celui-ci démarre immédiatement."),
        ];
        if (gates.length) {
            bits.push(fmtStr(tr("confirm_line_gates", "Rigueur : {g}."), { g: gates.join(", ") }));
        }
        if (launchRecap) launchRecap.textContent = bits.join(" ");
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
        const target = form.querySelector("#target_symbol");
        const horizons = form.querySelector("[name=horizons]");
        const scheme = form.querySelector("[name=scheme]");
        const bits = [];
        if (target && target.value) bits.push("<b>" + target.value + "</b>");
        if (horizons && horizons.value) {
            bits.push(fmtStr(tr("recap_horizons", "horizons {h}"), { h: horizons.value }));
        }
        if (scheme && scheme.selectedIndex >= 0) bits.push(scheme.options[scheme.selectedIndex].textContent.trim());
        launchRecap.innerHTML = bits.join(" · ");
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
            const select = document.getElementById("target_symbol");
            if (!select) return;
            const symbol = btn.dataset.symbol;
            const match = Array.from(select.options).some((o) => o.value === symbol);
            if (!match) {
                btn.title = fmtStr(tr("movers_not_a_target", "{s} n'est pas une cible disponible."), { s: symbol });
                return;
            }
            select.value = symbol;
            // `change` déclenche le rechargement de l'aperçu marché (market.js)
            // et le rafraîchissement du récapitulatif : poser `.value` seul ne
            // notifie personne.
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
