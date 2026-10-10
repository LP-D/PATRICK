/* Page Macro : bouton « Calculer / Actualiser » du tableau FRED contre ALFRED. Lance le calcul (arrière-plan), suit sa progression,
   puis recharge le fragment. Délégation d'événements : le fragment arrive après l'affichage (lazy.js). */
(function () {
    "use strict";
    var timer = null;

    function block() { return document.querySelector("#alfred-vs-fred") && document.querySelector("#alfred-vs-fred").closest(".lazy-block"); }

    function reload() {
        var host = block();
        if (!host) return;
        var lang = new URLSearchParams(window.location.search).get("lang");
        fetch("/fragments/macro-alfred" + (lang ? "?lang=" + encodeURIComponent(lang) : ""), { credentials: "same-origin" })
            .then(function (r) { return r.text(); })
            .then(function (html) { host.innerHTML = html; poll(); });
    }

    function poll() {
        var section = document.querySelector("#alfred-vs-fred");
        if (!section || section.dataset.running !== "1" || timer) return;
        timer = setInterval(function () {
            fetch("/api/macro/alfred-status", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (s) {
                var line = document.querySelector("#alfred-progress");
                if (line && s.total) line.textContent = line.textContent.replace(/\d+ \/ \d+|\d+\/\d+/, s.done + " / " + s.total);
                if (!s.running) { clearInterval(timer); timer = null; reload(); }
            }).catch(function () { clearInterval(timer); timer = null; });
        }, 3000);
    }

    document.addEventListener("click", function (event) {
        var btn = event.target.closest && event.target.closest("#alfred-refresh");
        if (!btn || btn.disabled) return;
        btn.disabled = true;
        btn.textContent = btn.dataset.labelRunning || btn.textContent;
        fetch(btn.dataset.url, { method: "POST", credentials: "same-origin" }).then(function () { reload(); });
    });
    document.addEventListener("patrick:content", poll);
})();
