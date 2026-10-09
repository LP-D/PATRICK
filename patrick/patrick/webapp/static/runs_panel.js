/* Page /runs : panneau latéral (3 runs max, empilés sur toute la hauteur) et
   renommage par boîte de dialogue. No-op hors de /runs (garde sur #run-panel). */
(function () {
    "use strict";
    var panel = document.getElementById("run-panel");
    if (!panel) return;
    var MAX = 3;
    var body = document.getElementById("run-panel-body");
    var rows = {};
    document.querySelectorAll(".history-row").forEach(function (tr) { rows[tr.dataset.runId] = tr; });
    var selected = [];   // ids, du plus ancien au plus récent
    var cache = {};      // id -> HTML du fragment (rendu serveur, échappé)

    function render() {
        body.textContent = "";
        selected.forEach(function (id) {
            var section = document.createElement("section");
            section.className = "run-panel-section";
            section.dataset.runId = id;
            section.innerHTML = cache[id] || '<p class="hint">Chargement…</p>';
            body.appendChild(section);
        });
        panel.hidden = selected.length === 0;
        // le bandeau d'aide statistique explique le dernier run ouvert
        if (selected.length) {
            document.dispatchEvent(new CustomEvent("patrick:run-context", { detail: { runId: selected[selected.length - 1] } }));
        }
        document.body.classList.toggle("has-run-panel", selected.length > 0);
        Object.keys(rows).forEach(function (id) {
            rows[id].classList.toggle("is-selected", selected.indexOf(id) !== -1);
        });
    }

    function load(id) {
        if (cache[id]) return;
        fetch("/runs/" + encodeURIComponent(id) + "/panel")
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function (html) { cache[id] = html; render(); })
            .catch(function () { cache[id] = '<p class="hint">Résumé indisponible.</p>'; render(); });
    }

    function toggle(id) {
        var i = selected.indexOf(id);
        if (i !== -1) {
            selected.splice(i, 1);
        } else {
            selected.push(id);
            if (selected.length > MAX) selected.shift();
            load(id);
        }
        render();
    }

    function close() { selected = []; render(); }

    document.getElementById("run-panel-close").addEventListener("click", close);
    body.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-rp-remove]");
        if (btn) toggle(btn.dataset.rpRemove);
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && selected.length && !document.querySelector("dialog[open]")) close();
    });

    var tbody = document.querySelector(".history-table tbody");
    tbody.addEventListener("click", function (e) {
        var rename = e.target.closest("[data-rename]");
        if (rename) { openRename(rename); return; }
        if (e.target.closest("a, button, input, form, label")) return;
        var tr = e.target.closest(".history-row");
        if (tr) toggle(tr.dataset.runId);
    });
    tbody.addEventListener("keydown", function (e) {
        if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("history-row")) {
            e.preventDefault();
            toggle(e.target.dataset.runId);
        }
    });

    // Renommer
    var dialog = document.getElementById("rename-dialog");
    var form = document.getElementById("rename-form");
    var input = document.getElementById("rename-input");
    function openRename(btn) {
        form.action = "/runs/" + encodeURIComponent(btn.dataset.rename) + "/rename";
        input.value = btn.dataset.name || "";
        dialog.showModal();
        input.select();
    }
    document.getElementById("rename-cancel").addEventListener("click", function () { dialog.close(); });
})();
