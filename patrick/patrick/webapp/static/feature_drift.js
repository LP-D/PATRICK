/* Roadmap bloc 3 -- on-demand feature drift (PSI) on /targets/{ticker}:
   POST /api/drift/{target}/{horizon}, then a per-feature table. No-op on
   pages without #feature-drift-widget. */
(function () {
    "use strict";
    var widget = document.getElementById("feature-drift-widget");
    if (!widget) return;
    var target = widget.getAttribute("data-target");
    var select = widget.querySelector(".drift-horizon-select");
    var button = widget.querySelector(".drift-measure-btn");
    var out = widget.querySelector(".drift-output");
    var LABEL = { stable: "stable", attention: "attention", significant: "dérive" };
    var STATE = { stable: "ok", attention: "warning", significant: "error" };

    function note(text, cls) {
        out.innerHTML = "";
        var p = document.createElement("p");
        p.className = cls || "hint";
        p.textContent = text;
        out.appendChild(p);
    }

    button.addEventListener("click", async function () {
        button.disabled = true;
        note("Reconstruction du pool de features et mesure en cours…");
        try {
            var res = await fetch("/api/drift/" + encodeURIComponent(target) + "/" + encodeURIComponent(select.value),
                                  { method: "POST" });
            var data = await res.json().catch(function () { return {}; });
            if (!res.ok) { note(data.detail || ("Erreur HTTP " + res.status), "hint sim-guard"); return; }
            out.innerHTML = "";
            var wrap = document.createElement("div");
            wrap.className = "table-scroll";
            var table = document.createElement("table");
            table.className = "data-table";
            table.innerHTML = "<thead><tr><th>Feature</th><th class='num'>PSI</th><th>Statut</th></tr></thead>";
            var tbody = document.createElement("tbody");
            data.features.forEach(function (f) {
                var tr = document.createElement("tr");
                var td1 = document.createElement("td");
                td1.className = "pk-mono";
                td1.textContent = f.feature;
                var td2 = document.createElement("td");
                td2.className = "num pk-mono";
                td2.textContent = f.psi.toFixed(3);
                var td3 = document.createElement("td");
                var badge = document.createElement("span");
                badge.className = "status-badge status-" + (STATE[f.status] || "neutral");
                badge.textContent = LABEL[f.status] || f.status;
                td3.appendChild(badge);
                tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3);
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            wrap.appendChild(table);
            out.appendChild(wrap);
            var foot = document.createElement("p");
            foot.className = "table-footer";
            foot.textContent = "PSI < 0,10 stable · 0,10–0,25 attention · > 0,25 dérive significative. Mesure enregistrée : le badge de la page Prédictions est à jour.";
            out.appendChild(foot);
        } catch (e) {
            note(String(e), "hint sim-guard");
        } finally {
            button.disabled = false;
        }
    });
})();
