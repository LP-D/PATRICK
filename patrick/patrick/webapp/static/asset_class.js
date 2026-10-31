/* Pages de classes d'actifs : le tableau arrive après l'affichage (`/fragments/asset-class/{classe}`, lazy.js), puis recherche instantanée et
   filtres (entraînés, jamais lancés, alpha, historique court), puis un repère de signal par horizon (`/api/class-signals/{classe}`, plus lent :
   il arrive en dernier et ne bloque rien). */
(function () {
    "use strict";
    var I18N = window.I18N || {};

    function norm(s) { return String(s || "").toLocaleLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }

    function initFilters(root) {
        var input = root.querySelector("#cls-search");
        var rows = Array.prototype.slice.call(root.querySelectorAll(".cls-row"));
        if (!input || !rows.length) return;
        var groups = Array.prototype.slice.call(root.querySelectorAll("[data-group]"));
        var count = root.querySelector("#cls-count");
        var none = root.querySelector("#cls-none");
        var chips = Array.prototype.slice.call(root.querySelectorAll("[data-filter]"));
        var filter = "all";
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
    }

    // Un repère par horizon : ▲▲ ▲ ▼ ▼▼ ; vert pour une hausse, orange pour une baisse ; le survol dit l'horizon et le mouvement.
    function fillSignals(root) {
        var host = root.querySelector("[data-class-key]");
        if (!host) return;
        var cells = root.querySelectorAll(".cls-signals[data-symbol]");
        if (!cells.length) return;
        fetch("/api/class-signals/" + encodeURIComponent(host.dataset.classKey), { credentials: "same-origin" })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (data) {
                Array.prototype.forEach.call(cells, function (td) {
                    var row = data[td.dataset.symbol];
                    if (!row) return;
                    row.forEach(function (sig) {
                        var span = document.createElement("span");
                        span.className = "cls-sig cls-sig-" + sig[2];
                        span.textContent = sig[1];
                        span.title = sig[0] + (I18N.day_suffix || "d") + " : " + sig[3];
                        td.appendChild(span);
                    });
                });
            })
            .catch(function () { /* les signaux sont un plus : le tableau reste utilisable sans eux */ });
    }

    function init(root) {
        initFilters(root);
        fillSignals(root);
    }

    // Le tableau n'existe qu'une fois le fragment arrivé (lazy.js émet `patrick:content` sur son bloc).
    document.addEventListener("patrick:content", function (ev) {
        if (ev.target && ev.target.querySelector && ev.target.querySelector("#cls-search")) init(ev.target);
    });
    if (document.getElementById("cls-search")) init(document);
})();
