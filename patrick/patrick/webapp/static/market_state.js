/* HMM market state on the synthesis page: reads /api/market-state (cache
   filled by a background thread, ~12 s per market) and polls while the first
   computation is still running. No-op without #market-state. */
(function () {
    "use strict";
    var root = document.getElementById("market-state");
    if (!root) return;
    var STATE = { calme: "ok", normal: "neutral", stress: "error" };
    var LABEL = { calme: "calme", normal: "normal", stress: "stress" };

    function pct(x) { return (x * 100).toFixed(1).replace(".", ",") + " %"; }

    function note(text) {
        root.innerHTML = "";
        var p = document.createElement("p");
        p.className = "hint";
        p.textContent = text;
        root.appendChild(p);
    }

    function cell(tr, text, cls) {
        var td = document.createElement("td");
        if (cls) td.className = cls;
        if (text instanceof Node) td.appendChild(text); else td.textContent = text;
        tr.appendChild(td);
        return td;
    }

    function render(data) {
        root.innerHTML = "";
        var wrap = document.createElement("div");
        wrap.className = "table-scroll";
        var table = document.createElement("table");
        table.className = "data-table";
        table.innerHTML = "<thead><tr><th>Marché</th><th>Régime</th><th class='num'>P(stress)</th>" +
            "<th>Depuis</th><th class='num'>Stress (63 s.)</th><th class='num'>Vol. 21 s.</th>" +
            "<th class='num'>Vol. long terme</th><th class='num'>États</th></tr></thead>";
        var tbody = document.createElement("tbody");
        data.rows.forEach(function (r) {
            var tr = document.createElement("tr");
            cell(tr, r.label);
            if (r.status !== "ok") {
                var msg = r.status === "insufficient" ? "historique insuffisant" : ("indisponible : " + (r.error || ""));
                var td = cell(tr, msg, "na");
                td.colSpan = 7;
                tbody.appendChild(tr);
                return;
            }
            var badge = document.createElement("span");
            badge.className = "status-badge status-" + (STATE[r.regime] || "neutral");
            badge.textContent = LABEL[r.regime] || r.regime;
            cell(tr, badge);
            cell(tr, pct(r.stress_prob), "num pk-mono");
            cell(tr, r.since + " (" + r.sessions_in_regime + " s.)", "pk-mono");
            cell(tr, pct(r.share_stress_63), "num pk-mono");
            cell(tr, pct(r.vol_21d), "num pk-mono");
            cell(tr, pct(r.vol_long), "num pk-mono");
            cell(tr, String(r.n_states), "num pk-mono");
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        root.appendChild(wrap);
        var foot = document.createElement("p");
        foot.className = "table-footer";
        foot.textContent = "Mis à jour : " + data.updated_at + " · dernière séance par marché : " +
            data.rows.filter(function (r) { return r.as_of; }).map(function (r) { return r.label + " " + r.as_of; }).join(", ");
        root.appendChild(foot);
    }

    async function load(attempt) {
        try {
            var res = await fetch("/api/market-state");
            var data = await res.json();
            if (data.rows && data.rows.length) { render(data); return; }
            if (data.error) { note(data.error); return; }
            note("Calcul de l'état du marché (HMM) en cours — environ 10 s par marché…");
            if (attempt < 40) setTimeout(function () { load(attempt + 1); }, 5000);
        } catch (e) {
            note("État du marché indisponible : " + e);
        }
    }
    load(0);
})();
