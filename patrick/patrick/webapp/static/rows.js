/* Lignes repliables : un tableau long montre ses premières lignes et garde le reste derrière une flèche
   (`data_table(..., collapse_after=N)`, `fold_metrics_table`). Délégation d'événement : fonctionne aussi pour les tableaux
   injectés après coup (panneau latéral de /runs). */
(function () {
    "use strict";
    document.addEventListener("click", function (ev) {
        var btn = ev.target.closest("[data-rows-toggle]");
        if (!btn) return;
        var wrap = btn.previousElementSibling;       // le conteneur .table-scroll juste au-dessus du bouton
        var table = wrap && wrap.querySelector("table");
        if (!table) return;
        var open = btn.getAttribute("aria-expanded") !== "true";
        table.querySelectorAll("tr[data-extra]").forEach(function (tr) { tr.hidden = !open; });
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        var label = btn.querySelector(".rows-toggle-label");
        if (label) label.textContent = open ? btn.dataset.less : btn.dataset.more;
    });
})();
