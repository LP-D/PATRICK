/* Pages de classes d'actifs : recherche instantanée et filtres (entraînés, jamais lancés, alpha, historique court). */
(function () {
    "use strict";
    var input = document.getElementById("cls-search");
    var rows = Array.prototype.slice.call(document.querySelectorAll(".cls-row"));
    if (!input || !rows.length) return;
    var groups = Array.prototype.slice.call(document.querySelectorAll("[data-group]"));
    var count = document.getElementById("cls-count");
    var none = document.getElementById("cls-none");
    var chips = Array.prototype.slice.call(document.querySelectorAll("[data-filter]"));
    var filter = "all";
    function norm(s) { return String(s || "").toLocaleLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
    rows.forEach(function (r) { r.dataset.norm = norm(r.dataset.search); });
    function match(r, q) {
        if (q && r.dataset.norm.indexOf(q) === -1) return false;
        if (filter === "trained") return r.dataset.trained === "1";
        if (filter === "never") return r.dataset.trained !== "1" && r.dataset.alpha !== "1";
        if (filter === "alpha") return r.dataset.alpha === "1";
        if (filter === "short") return r.dataset.short === "1";
        return true;
    }
    function apply() {
        var q = norm(input.value.trim());
        var shown = 0;
        rows.forEach(function (r) { var ok = match(r, q); r.hidden = !ok; if (ok) shown += 1; });
        groups.forEach(function (g) {
            var any = g.querySelector(".cls-row:not([hidden])");
            g.hidden = !any;
            if (q || filter !== "all") { if (any) g.open = true; }
        });
        if (count) count.textContent = shown + " / " + rows.length;
        if (none) none.classList.toggle("hidden", shown !== 0);
    }
    chips.forEach(function (c) {
        c.addEventListener("click", function () {
            filter = c.dataset.filter;
            chips.forEach(function (o) { o.classList.toggle("active", o === c); });
            apply();
        });
    });
    input.addEventListener("input", apply);
    apply();
})();
