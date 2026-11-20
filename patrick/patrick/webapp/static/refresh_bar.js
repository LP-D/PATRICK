/* Barre de chargement de l'actualisation d'une page : les pages lourdes lisent un cache (`webapp/view_cache.py`) et le recalculent en tâche de
   fond ; cette barre dit où en est ce recalcul (vue, étape, pourcentage), et la passe de prédictions de l'app pour les pages qui en dépendent.
   Elle interroge `/api/refresh-status` toutes les 2 s (lecture en mémoire côté serveur), reste cachée quand rien ne se recalcule, et, quand un
   recalcul se termine :
   - page « se prépare » (`data-auto-reload`) : elle se recharge toute seule ;
   - page avec des blocs chargés après coup : ces blocs sont redemandés (`window.patrickReloadLazy`) ;
   - autre page : un bouton propose d'afficher les nouvelles données (la page n'est jamais rechargée sous les yeux de l'utilisateur). */
(function () {
    "use strict";
    var bar = document.getElementById("refresh-bar");
    if (!bar) return;
    var views = bar.dataset.views || "";
    var live = bar.dataset.live === "1";
    var autoReload = bar.dataset.autoReload === "1";
    var label = bar.querySelector(".refresh-bar-label");
    var pct = bar.querySelector(".refresh-bar-pct");
    var track = bar.querySelector(".refresh-bar-track");
    var fill = bar.querySelector(".refresh-bar-fill");
    var reloadBtn = bar.querySelector(".refresh-bar-reload");
    var sawRunning = false;
    var idlePolls = 0;

    function fmt(template, values) {
        return template.replace(/\{(\w+)\}/g, function (_, k) { return values[k] === undefined ? "" : values[k]; });
    }

    function show(text, fraction) {
        bar.hidden = false;
        bar.classList.remove("refresh-bar-done");
        label.textContent = text;
        if (fraction === null) {
            bar.classList.add("refresh-bar-indeterminate");
            pct.textContent = "";
            fill.style.width = "";
            track.removeAttribute("aria-valuenow");
        } else {
            var p = Math.round(100 * fraction);
            bar.classList.remove("refresh-bar-indeterminate");
            pct.textContent = p + " %";
            fill.style.width = p + "%";
            track.setAttribute("aria-valuenow", String(p));
        }
    }

    function finished() {
        bar.classList.remove("refresh-bar-indeterminate");
        if (autoReload) { window.location.reload(); return; }
        if (typeof window.patrickReloadLazy === "function" && document.querySelector("[data-lazy-src]")) {
            window.patrickReloadLazy();
            bar.hidden = true;
            return;
        }
        // Page sans bloc différé : on propose, sans recharger sous les yeux de l'utilisateur.
        bar.hidden = false;
        bar.classList.add("refresh-bar-done");
        label.textContent = bar.dataset.tDone || "";
        pct.textContent = "";
        fill.style.width = "100%";
        reloadBtn.hidden = false;
    }

    function render(data) {
        var running = (data.views || []).filter(function (v) { return v.running; });
        var pass = data.live && data.live.running ? data.live : null;
        if (running.length || pass) {
            sawRunning = true;
            idlePolls = 0;
            reloadBtn.hidden = true;
            if (running.length) {
                var v = running[0];
                var text = fmt(bar.dataset.tTitle || "{v}", { v: v.title }) + (v.label ? " — " + v.label : "");
                show(text, v.fraction === undefined ? null : v.fraction);
            } else {
                show(fmt(bar.dataset.tLive || "{d}/{n}", { d: pass.done, n: pass.total }), pass.total ? pass.done / pass.total : null);
            }
            return;
        }
        idlePolls += 1;
        if (sawRunning) {
            sawRunning = false;
            finished();
        } else if (autoReload && idlePolls >= 3) {
            window.location.reload();                 // rien ne tourne et rien n'est prêt : on redemande (le serveur relance le calcul)
        }
    }

    function poll() {
        var url = "/api/refresh-status?views=" + encodeURIComponent(views) + (live ? "&live=1" : "");
        var lang = new URLSearchParams(window.location.search).get("lang");
        if (lang) url += "&lang=" + encodeURIComponent(lang);
        fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) { if (data) render(data); })
            .catch(function () { /* serveur indisponible un instant : on réessaie au prochain tour */ });
    }

    reloadBtn.addEventListener("click", function () { window.location.reload(); });
    poll();
    window.setInterval(poll, 2000);
})();
