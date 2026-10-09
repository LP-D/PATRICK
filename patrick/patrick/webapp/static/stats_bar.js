/* Bandeau d'aide statistique : replié en bas de page, il explique les p-values et la procédure appliquée au run de
   référence. Le run vient, par ordre de priorité, du choix manuel, du panneau d'Historique (événement
   `patrick:run-context`), puis de `data-run-id` posé par la page (détail d'un run). Le contenu est un fragment serveur
   (`/api/stats-help`) : rien n'est calculé côté navigateur. */
(function () {
    "use strict";
    var bar = document.getElementById("stats-bar");
    if (!bar) return;
    var toggle = document.getElementById("stats-bar-toggle");
    var panel = document.getElementById("stats-bar-panel");
    var body = document.getElementById("stats-bar-body");
    var picker = document.getElementById("stats-bar-run");
    var closeBtn = document.getElementById("stats-bar-close");
    var runId = bar.dataset.runId || "";
    var loadedFor = null;
    var pickerFilled = false;

    function setOpen(open) {
        bar.dataset.open = open ? "true" : "false";
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        panel.hidden = !open;
        document.body.classList.toggle("has-stats-bar-open", open);
        if (open) load();
    }

    function load() {
        var key = runId || "__general__";
        if (loadedFor === key) return;
        body.textContent = body.dataset.loading || "…";
        var url = "/api/stats-help" + (runId ? "?run_id=" + encodeURIComponent(runId) : "");
        fetch(url, { headers: { "Accept": "text/html" } })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function (html) { body.innerHTML = html; loadedFor = key; })
            .catch(function () { body.textContent = body.dataset.error || "—"; });
        fillPicker();
    }

    function fillPicker() {
        if (pickerFilled || !picker) return;
        pickerFilled = true;
        fetch("/api/stats-help/runs")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                (data.runs || []).forEach(function (r) {
                    var o = document.createElement("option");
                    o.value = r.run_id;
                    o.textContent = r.label;
                    picker.appendChild(o);
                });
                picker.value = runId;
            })
            .catch(function () { /* confort : la liste reste vide */ });
    }

    function setRun(id) {
        if (!id || id === runId) return;
        runId = id;
        if (picker) picker.value = id;
        if (bar.dataset.open === "true") load();
    }

    toggle.addEventListener("click", function () { setOpen(bar.dataset.open !== "true"); });
    closeBtn.addEventListener("click", function () { setOpen(false); toggle.focus(); });
    if (picker) picker.addEventListener("change", function () { runId = picker.value; loadedFor = null; load(); });
    document.addEventListener("patrick:run-context", function (e) { if (e.detail && e.detail.runId) setRun(e.detail.runId); });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && bar.dataset.open === "true" && !document.querySelector("dialog[open]")) setOpen(false);
    });
})();
