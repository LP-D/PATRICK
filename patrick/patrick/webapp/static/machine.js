/* Carte « en cours et file d'attente » (`_machine_card.html`), identique sur /ml, /dl et /rl : une seule machine, une seule file.

   Elle lit `/api/run-state` (le run actif + la file), affiche le run en cours (nom, famille, cible, avancement, pause / arrêt) et la file
   (repliable, réordonnable au glisser-déposer, retrait d'un run ou de toute la file). Les pages qui suivent le détail d'un run (app.js
   pour ML et DL) s'abonnent avec `PatrickMachine.subscribe(function (state) {...})` ({ active, queue } ; rappelé tout de suite si un état
   est déjà connu) au lieu de relire l'état elles-mêmes ; `PatrickMachine.onAction(fn)` signale qu'un contrôle (pause, reprise, arrêt)
   vient d'être appliqué. */
(function () {
    "use strict";
    var card = document.getElementById("machine-card");
    if (!card) return;

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; });
    }
    function $(id) { return document.getElementById(id); }

    var POLL_MS = 4000;
    var QUEUE_OPEN_KEY = "patrick.queueOpen";

    var PHASE_LABELS = {
        ingestion: tr("phase_ingestion", "Downloading data"),
        features: tr("phase_features", "Building explanatory variables"),
        scan: tr("phase_scan", "Testing combinations"),
        tuning: tr("phase_tuning", "Fine-tuning the best configurations"),
        export: tr("phase_export", "Saving the final model"),
        done: tr("phase_done", "Done."),
        rl_data: tr("rlp_phase_rl_data", "Data and features"),
        rl_train: tr("rlp_phase_rl_train", "Training the agents"),
        rl_eval: tr("rlp_phase_rl_eval", "Out-of-sample evaluation"),
        rl_save: tr("rlp_phase_rl_save", "Saving"),
    };

    var current = $("machine-current");
    var idle = $("machine-idle");
    var runName = $("machine-run-name");
    var runKind = $("machine-run-kind");
    var runTarget = $("machine-run-target");
    var fill = $("machine-progress-fill");
    var progressBar = fill ? fill.parentElement : null;
    var statusLine = $("machine-status-line");
    var runControls = $("run-controls");
    var pauseBtn = $("pause-run-btn");
    var stopBtn = $("stop-run-btn");
    var controlError = $("run-control-error");
    var queuePanel = $("queue-panel");
    var queueSummary = $("queue-summary");
    var queueList = $("queue-list");
    var queueToggle = $("queue-toggle");
    var clearQueueBtn = $("clear-queue-btn");

    var state = { active: null, queue: [] };
    var activeJobId = null;
    var queueSignature = null;   // ne reconstruire la liste que si elle a changé : un poll toutes les 4 s qui la vide perdait défilement et focus
    var queueDragging = null;    // <li> en cours de glisser-déposer
    var queuePendingFocus = null;
    var wasMeasuring = false;
    var pollTimer = null;

    var subscribers = [];
    var actionListeners = [];
    var received = false;
    function publish() {
        subscribers.forEach(function (fn) { fn(state); });
    }

    // 95 -> « 1 min 35 s » : des secondes brutes ne se lisent pas au-delà d'une minute.
    function fmtDuration(totalSeconds) {
        var sec = Math.max(0, Math.round(totalSeconds));
        if (sec < 60) return fmtStr(tr("duration_s", "{s}s"), { s: sec });
        if (sec < 3600) return fmtStr(tr("duration_min", "{m} min {s}s"), { m: Math.floor(sec / 60), s: sec % 60 });
        return fmtStr(tr("duration_h", "{h} h {m} min"), { h: Math.floor(sec / 3600), m: Math.floor((sec % 3600) / 60) });
    }

    // scaleX plutôt que width (pas de reflow). `measuring` : la phase en cours ne produit aucune mesure (ingestion, variables) : la
    // barre balaie au lieu d'afficher un 0 % qui ne mesure rien, et se pose sur sa vraie valeur au premier pas mesuré.
    function setProgress(pct, measuring) {
        if (!fill) return;
        if (measuring) {
            wasMeasuring = true;
            if (progressBar) progressBar.dataset.progressMode = "measuring";
            return;
        }
        if (progressBar) delete progressBar.dataset.progressMode;
        if (wasMeasuring) {
            wasMeasuring = false;
            fill.style.transition = "none";
            fill.style.transform = "scaleX(0)";
            void fill.offsetWidth;
            fill.style.transition = "";
        }
        fill.style.transform = "scaleX(" + Math.max(0, Math.min(100, pct)) / 100 + ")";
    }

    // --- run en cours ---

    function statusText(active) {
        if (active.status === "paused") return tr("run_paused", "Paused — resume any time.");
        var done = (active.progress && active.progress.done) || 0;
        var total = (active.progress && active.progress.total) || 0;
        var pct = total > 0 ? Math.min(100, Math.round(done / total * 100)) : 0;
        var phase = PHASE_LABELS[active.phase] || tr("phase_other", "Computing");
        var progress = total > 0
            ? (active.kind === "rl" ? done + "/" + total
                : fmtStr(tr("status_progress_units", "{done} of {total} evaluations"), { done: done, total: total }))
            : "";
        var elapsed = fmtDuration(active.elapsed_s || 0);
        var hasEta = typeof active.estimated_remaining_s === "number" && isFinite(active.estimated_remaining_s);
        var confidence = active.eta_confidence === "moderate" ? "moderate" : "low";
        var template = hasEta ? tr("status_running_eta", "{phase} — {pct}% ({progress}) · elapsed: {elapsed} · about {remaining} left ({confidence} estimate)")
            : total > 0 ? tr("status_running_progress", "{phase} — {pct}% ({progress}) · elapsed: {elapsed}")
            : tr("status_running", "{phase} — {pct}% · elapsed: {elapsed}");
        return fmtStr(template, {
            phase: phase, pct: pct, progress: progress, elapsed: elapsed,
            remaining: hasEta ? fmtDuration(active.estimated_remaining_s) : "",
            confidence: tr("eta_confidence_" + confidence, confidence === "moderate" ? "rough" : "preliminary"),
        });
    }

    function renderCurrent(active) {
        activeJobId = active ? active.id : null;
        current.classList.toggle("hidden", !active);
        idle.classList.toggle("hidden", !!active);
        if (!active) {
            delete pauseBtn.dataset.jobId;
            delete pauseBtn.dataset.paused;
            pauseBtn.disabled = true;
            pauseBtn.textContent = tr("run_pause", "Pause");
            setProgress(0, false);
            return;
        }
        runName.textContent = active.name || active.id;
        runKind.textContent = (active.kind || "ml").toUpperCase();
        runKind.dataset.kind = active.kind || "ml";
        runTarget.textContent = active.target || "";
        var done = (active.progress && active.progress.done) || 0;
        var total = (active.progress && active.progress.total) || 0;
        setProgress(total > 0 ? done / total * 100 : 0, active.status === "running" && done === 0);
        statusLine.textContent = statusText(active);
        var paused = active.status === "paused";
        pauseBtn.dataset.jobId = active.id;
        pauseBtn.dataset.paused = paused ? "true" : "false";
        pauseBtn.disabled = false;
        pauseBtn.textContent = paused ? tr("run_resume", "Resume") : tr("run_pause", "Pause");
    }

    // --- file d'attente : liste déroulante, réordonnable ---

    function setQueueOpen(open) {
        queueToggle.setAttribute("aria-expanded", open ? "true" : "false");
        queueList.hidden = !open;
        try { localStorage.setItem(QUEUE_OPEN_KEY, open ? "1" : "0"); } catch (e) { /* stockage indisponible */ }
    }
    var storedOpen = false;
    try { storedOpen = localStorage.getItem(QUEUE_OPEN_KEY) === "1"; } catch (e) { /* idem */ }
    setQueueOpen(storedOpen);

    function buildQueueItem(job, index, total) {
        var label = job.name || job.id;
        var item = document.createElement("li");
        item.className = "queue-item";
        item.draggable = true;
        item.dataset.jobId = job.id;
        item.title = tr("queue_drag", "Drag to change the execution order");

        var rank = document.createElement("span");
        rank.className = "queue-rank";
        rank.textContent = (index + 1) + ".";
        var name = document.createElement("span");
        name.className = "queue-name";
        name.textContent = label;
        if (job.kind) {
            var kind = document.createElement("span");
            kind.className = "machine-kind";
            kind.dataset.kind = job.kind;
            kind.textContent = job.kind.toUpperCase();
            name.append(" ", kind);
        }

        var actions = document.createElement("span");
        actions.className = "queue-item-actions";
        [
            ["top", "⤒", "queue_move_top", "Move to top", index === 0],
            ["up", "↑", "queue_move_up", "Move up", index === 0],
            ["down", "↓", "queue_move_down", "Move down", index === total - 1],
            ["remove", "✕", "queue_remove", "Remove", false],
        ].forEach(function (spec) {
            var text = tr(spec[2], spec[3]);
            var button = document.createElement("button");
            button.type = "button";
            button.className = "queue-action queue-icon" + (spec[0] === "remove" ? " danger" : "");
            button.dataset.jobAction = spec[0];
            button.textContent = spec[1];
            button.disabled = spec[4];
            button.title = text;
            button.setAttribute("aria-label", text + " " + label);
            actions.appendChild(button);
        });
        item.append(rank, name, actions);
        return item;
    }

    function renderQueue(queue) {
        if (!queue.length) {
            queuePanel.classList.add("hidden");
            queueList.replaceChildren();
            queueSignature = null;
            return;
        }
        queuePanel.classList.remove("hidden");
        queueSummary.textContent = fmtStr(tr("queue_summary", "{n} run(s) queued · next: {next}"),
            { n: queue.length, next: queue[0].name || queue[0].id });

        var signature = queue.map(function (q) { return q.id + ":" + q.name; }).join("|");
        if (signature === queueSignature || queueDragging) return;
        queueSignature = signature;
        var scrollTop = queueList.scrollTop;
        queueList.replaceChildren.apply(queueList, queue.map(function (job, index) { return buildQueueItem(job, index, queue.length); }));
        queueList.scrollTop = scrollTop;

        if (queuePendingFocus) {
            var row = queueList.querySelector('li[data-job-id="' + queuePendingFocus.jobId + '"]');
            if (row) {
                var preferred = row.querySelector('button[data-job-action="' + queuePendingFocus.action + '"]');
                var target = preferred && !preferred.disabled ? preferred : row.querySelector("button:not(:disabled)");
                if (target) target.focus();
            }
            queuePendingFocus = null;
        }
    }

    function render(data) {
        state = { active: data.active_run || null, queue: data.queue || [] };
        received = true;
        renderCurrent(state.active);
        renderQueue(state.queue);
        publish();
    }

    // --- lecture périodique ---

    async function poll() {
        var data;
        try {
            var res = await fetch("/api/run-state");
            data = await res.json();
        } catch (e) {
            return;
        }
        render(data);
    }

    function schedule() {
        clearInterval(pollTimer);
        pollTimer = setInterval(function () { if (!document.hidden) poll(); }, POLL_MS);
    }
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });

    // --- actions ---

    // Pas de fenêtre de confirmation : retirer ou réordonner un run en attente est immédiat et sans conséquence durable (le run se
    // relance depuis l'historique). La réponse du serveur est la vérité : si la requête échoue, on resynchronise sans alerte.
    async function queueRequest(url, options) {
        var queue = null;
        try {
            var response = await fetch(url, options);
            if (response.ok) queue = (await response.json().catch(function () { return {}; })).queue || null;
        } catch (e) { /* réseau : resynchronisation ci-dessous */ }
        if (queue) { state = { active: state.active, queue: queue }; renderQueue(queue); publish(); return; }
        queueSignature = null;   // le DOM a pu être réordonné à la main
        await poll();
    }

    function reorderQueue(ids) {
        return queueRequest("/api/queue/reorder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order: ids }),
        });
    }

    function moveQueueItem(jobId, action) {
        var ids = state.queue.map(function (q) { return q.id; });
        var from = ids.indexOf(jobId);
        var to = action === "top" ? 0 : action === "up" ? from - 1 : from + 1;
        if (from < 0 || to < 0 || to >= ids.length || to === from) return;
        ids.splice(to, 0, ids.splice(from, 1)[0]);
        queuePendingFocus = { jobId: jobId, action: action };
        reorderQueue(ids);
    }

    // Erreur de contrôle (pause / reprise / arrêt) : bannière de la carte, effacée à l'action suivante.
    function showControlError(message) {
        controlError.textContent = message || "";
        controlError.classList.toggle("hidden", !message);
    }

    async function sendJobControl(url, options) {
        showControlError("");
        try {
            var response = await fetch(url, options);
            if (!response.ok) {
                var detail = await response.json().catch(function () { return {}; });
                showControlError(typeof detail.detail === "string" && detail.detail
                    ? detail.detail : tr("run_control_error", "Could not apply this action."));
                return;
            }
            await poll();
            actionListeners.forEach(function (fn) { fn(); });
        } catch (e) {
            showControlError(tr("run_control_error", "Could not apply this action."));
        }
    }

    pauseBtn.addEventListener("click", function () {
        var action = pauseBtn.dataset.paused === "true" ? "resume" : "pause";
        sendJobControl("/api/jobs/" + pauseBtn.dataset.jobId + "/" + action, { method: "POST" });
    });
    stopBtn.addEventListener("click", function () {
        if (activeJobId) sendJobControl("/api/jobs/" + activeJobId + "/stop", { method: "POST" });
    });
    queueToggle.addEventListener("click", function () {
        setQueueOpen(queueToggle.getAttribute("aria-expanded") !== "true");
    });
    clearQueueBtn.addEventListener("click", function () { queueRequest("/api/queue", { method: "DELETE" }); });

    queueList.addEventListener("click", function (event) {
        var button = event.target.closest("button[data-job-action]");
        if (!button || button.disabled) return;
        var jobId = button.closest("li").dataset.jobId;
        if (button.dataset.jobAction === "remove") queueRequest("/api/queue/" + jobId, { method: "DELETE" });
        else moveQueueItem(jobId, button.dataset.jobAction);
    });

    // Glisser-déposer : le <li> est déplacé dans le DOM pendant le survol ; l'ordre résultant n'est envoyé qu'au dépôt. Déposer hors de
    // la liste (ou Échap) annule : dropEffect vaut alors « none ».
    queueList.addEventListener("dragstart", function (event) {
        var row = event.target.closest && event.target.closest("li.queue-item");
        if (!row) return;
        queueDragging = row;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.dataset.jobId);   // Firefox l'exige
        row.classList.add("dragging");
    });
    queueList.addEventListener("dragover", function (event) {
        if (!queueDragging) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        var over = event.target.closest("li.queue-item");
        if (!over || over === queueDragging) return;
        var rect = over.getBoundingClientRect();
        var reference = event.clientY > rect.top + rect.height / 2 ? over.nextSibling : over;
        if (reference !== queueDragging.nextSibling) queueList.insertBefore(queueDragging, reference);
    });
    queueList.addEventListener("drop", function (event) { event.preventDefault(); });
    queueList.addEventListener("dragend", function (event) {
        if (!queueDragging) return;
        queueDragging.classList.remove("dragging");
        queueDragging = null;
        var ids = Array.prototype.map.call(queueList.children, function (li) { return li.dataset.jobId; });
        var moved = ids.some(function (id, i) { return !state.queue[i] || id !== state.queue[i].id; });
        if (moved && event.dataTransfer.dropEffect !== "none") {
            reorderQueue(ids);
        } else {
            queueSignature = null;
            renderQueue(state.queue);
        }
    });

    window.PatrickMachine = {
        refresh: poll,
        state: function () { return state; },
        subscribe: function (fn) { subscribers.push(fn); if (received) fn(state); },
        onAction: function (fn) { actionListeners.push(fn); },
    };
    poll();
    schedule();
})();
