(function () {
    const PHASE_LABELS = {
        ingestion: "Ingestion des données…",
        features: "Construction des features…",
        scan: "Grille sélection × sampler × algo…",
        tuning: "Affinage Optuna des meilleures configs…",
        export: "Export du modèle final…",
        done: "Terminé.",
    };

    const fill = document.getElementById("progress-fill");
    const statusLine = document.getElementById("status-line");
    const logTail = document.getElementById("log-tail");
    const resultsPanel = document.getElementById("results-panel");

    let resultsLoaded = false;
    let pollTimer = null;

    async function poll() {
        let data;
        try {
            const res = await fetch(`/runs/${RUN_ID}/status`);
            data = await res.json();
        } catch (e) {
            statusLine.textContent = "Connexion au serveur perdue — nouvelle tentative…";
            return;
        }

        const pct = Math.min(100, Math.round((data.progress.done / data.progress.total) * 100));
        fill.style.width = pct + "%";
        logTail.textContent = data.log_tail.join("\n");
        logTail.scrollTop = logTail.scrollHeight;

        if (data.status === "running") {
            statusLine.textContent = `${PHASE_LABELS[data.phase] || data.phase} (${pct}%, ${Math.round(data.elapsed_s)}s écoulées)`;
        } else if (data.status === "error") {
            statusLine.innerHTML = `<span class="error-text">Erreur : ${escapeHtml(data.error)}</span>`;
            clearInterval(pollTimer);
        } else if (data.status === "done") {
            statusLine.textContent = `Terminé en ${Math.round(data.elapsed_s)}s.`;
            fill.style.width = "100%";
            clearInterval(pollTimer);
            if (!resultsLoaded) {
                resultsLoaded = true;
                loadResults();
            }
        }
    }

    async function loadResults() {
        const res = await fetch(`/runs/${RUN_ID}/results`);
        if (!res.ok) return;
        const data = await res.json();
        resultsPanel.classList.remove("hidden");
        resultsPanel.innerHTML = renderResults(data);
        attachSort(data.top_rows);
    }

    function renderResults(data) {
        const best = data.final_best;
        const bestHtml = best
            ? `<div class="best-box">
                 <strong>Meilleure config</strong> — h=${best.horizon ?? "?"}j
                 ${best.regime ?? ""} N=${best.N ?? "?"} ${best.sampler ?? ""} ${best.algo ?? ""}
                 &rarr; F1_dir=${fmt(best.F1_dir)}
               </div>`
            : "";

        const downloads = Object.entries(data.artifacts || {})
            .map(([key, _]) => `<a href="/runs/${RUN_ID}/download/${key}" download>${labelFor(key)}</a>`)
            .join("");

        const cols = data.leaderboard_columns || [];
        const head = cols.map((c) => `<th data-col="${c}">${c}</th>`).join("");
        const rows = (data.top_rows || [])
            .map((r) => `<tr>${cols.map((c) => `<td>${fmt(r[c])}</td>`).join("")}</tr>`)
            .join("");

        return `
            <h2>Résultats</h2>
            <p>${data.n_evaluations} évaluations${data.n_tuned_evaluations ? ` + ${data.n_tuned_evaluations} après tuning` : ""}.</p>
            ${bestHtml}
            <div class="downloads">${downloads}</div>
            <h3>Leaderboard (top ${(data.top_rows || []).length}, triable par colonne)</h3>
            <div style="overflow-x:auto">
                <table class="leaderboard" id="leaderboard-table">
                    <thead><tr>${head}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    function attachSort(rows) {
        const table = document.getElementById("leaderboard-table");
        if (!table) return;
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
                table.querySelector("tbody").innerHTML = sorted
                    .map((r) => `<tr>${cols.map((c) => `<td>${fmt(r[c])}</td>`).join("")}</tr>`)
                    .join("");
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
            leaderboard_csv: "Leaderboard (CSV)",
            leaderboard_xlsx: "Leaderboard (Excel)",
            tuned_csv: "Configs affinées (CSV)",
            best_model: "Meilleur modèle (joblib)",
            best_model_meta: "Métadonnées (JSON)",
        };
        return labels[key] || key;
    }

    function escapeHtml(s) {
        const div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    }

    poll();
    pollTimer = setInterval(poll, 1500);
})();
