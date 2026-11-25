/* VI23 (25/11) : comparateur de runs en « diff ». Une ligne dont les cellules diffèrent d'un run à l'autre est surlignée ; la case
   « Seulement les différences » masque les lignes identiques. Aucune donnée n'est recalculée : on compare le texte affiché. */
(function () {
    "use strict";
    document.querySelectorAll("table[data-diff-table]").forEach(function (table) {
        var rows = table.querySelectorAll("tbody tr");
        var nDiff = 0;
        rows.forEach(function (tr) {
            var cells = Array.prototype.slice.call(tr.querySelectorAll("td"));
            if (cells.length < 2) return;
            var values = cells.map(function (td) { return td.textContent.replace(/\s+/g, " ").trim(); });
            var differs = values.some(function (v) { return v !== values[0]; });
            tr.classList.toggle("row-diff", differs);
            tr.classList.toggle("row-same", !differs);
            if (differs) nDiff++;
        });
        var box = document.getElementById(table.getAttribute("data-diff-table"));
        if (!box) return;
        var count = box.parentNode.querySelector("[data-diff-count]");
        if (count) count.textContent = String(nDiff);
        box.addEventListener("change", function () { table.classList.toggle("only-diff", box.checked); });
    });
})();
