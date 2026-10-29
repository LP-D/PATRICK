/* Outils de tableau (ADR 0010) : tri par clic sur l'en-tête, filtre texte et export CSV pour tout tableau `.data-table` d'au moins MIN_ROWS lignes.
   Amélioration progressive : sans ce script le tableau reste lisible tel que le serveur l'a rendu. L'en-tête collant vient déjà de patrick.css.
   Délégation sur `patrick:content` : fonctionne aussi pour les tableaux injectés après coup (fragments lazy, panneaux). */
(function () {
    "use strict";
    var MIN_ROWS = 8;
    var FR = (document.documentElement.lang || "fr").slice(0, 2) !== "en";
    var T = FR
        ? { filter: "Filtrer les lignes", csv: "Exporter en CSV", count: "{n} lignes" }
        : { filter: "Filter rows", csv: "Export CSV", count: "{n} rows" };

    function text(cell) { return (cell.textContent || "").replace(/\s+/g, " ").trim(); }

    function toNumber(s) {
        var t = s.replace(/[  \s]/g, "").replace("−", "-").replace(",", ".").replace(/%$/, "");
        return /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t) ? parseFloat(t) : NaN;
    }

    function compare(a, b) {
        var na = toNumber(a), nb = toNumber(b);
        if (!isNaN(na) && !isNaN(nb)) return na - nb;
        if (a === "" || a === "—") return b === "" || b === "—" ? 0 : 1;      // les vides en dernier
        if (b === "" || b === "—") return -1;
        return a.localeCompare(b, FR ? "fr" : "en", { numeric: true, sensitivity: "base" });
    }

    function csvEscape(s) { return /[",;\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }

    function enhance(table) {
        if (table.dataset.tools || table.classList.contains("fold-table") || table.closest(".no-table-tools")) return;
        var body = table.tBodies[0];
        if (!body || body.rows.length < MIN_ROWS) return;
        table.dataset.tools = "1";
        var wrap = table.closest(".table-scroll") || table;
        var toggle = wrap.nextElementSibling && wrap.nextElementSibling.matches("[data-rows-toggle]") ? wrap.nextElementSibling : null;
        var keepVisible = Array.prototype.filter.call(body.rows, function (tr) { return !tr.hasAttribute("data-extra"); }).length;

        var bar = document.createElement("div");
        bar.className = "table-tools";
        var input = document.createElement("input");
        input.type = "search";
        input.placeholder = T.filter;
        input.setAttribute("aria-label", T.filter);
        var count = document.createElement("span");
        count.className = "hint table-tools-count";
        var csv = document.createElement("button");
        csv.type = "button";
        csv.className = "icon-btn icon-btn-sm table-tools-csv";
        csv.title = T.csv;
        csv.setAttribute("aria-label", T.csv);
        csv.textContent = "CSV";
        bar.appendChild(input); bar.appendChild(count); bar.appendChild(csv);
        wrap.parentNode.insertBefore(bar, wrap);

        function open() { return !toggle || toggle.getAttribute("aria-expanded") === "true"; }

        function render() {
            var q = input.value.trim().toLowerCase();
            var shown = 0;
            Array.prototype.forEach.call(body.rows, function (tr, i) {
                var match = !q || text(tr).toLowerCase().indexOf(q) !== -1;
                if (q) tr.hidden = !match;                                   // un filtre actif ignore le repli
                else tr.hidden = tr.hasAttribute("data-extra") && !open();
                if (!tr.hidden) shown += 1;
                if (!q && toggle) {
                    if (i >= keepVisible) tr.setAttribute("data-extra", ""); else tr.removeAttribute("data-extra");
                    tr.hidden = i >= keepVisible && !open();
                }
            });
            count.textContent = T.count.replace("{n}", String(q ? shown : body.rows.length));
            if (toggle) toggle.hidden = !!q;
        }

        Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, col) {
            th.style.cursor = "pointer";
            th.tabIndex = 0;
            th.setAttribute("role", "columnheader");
            function sort() {
                var dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
                Array.prototype.forEach.call(table.tHead.rows[0].cells, function (h) { h.removeAttribute("aria-sort"); });
                th.setAttribute("aria-sort", dir);
                var rows = Array.prototype.slice.call(body.rows);
                rows.sort(function (r1, r2) {
                    var c = compare(text(r1.cells[col] || r1), text(r2.cells[col] || r2));
                    return dir === "ascending" ? c : -c;
                });
                rows.forEach(function (tr) { body.appendChild(tr); });
                render();
            }
            th.addEventListener("click", sort);
            th.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); sort(); } });
        });

        input.addEventListener("input", render);
        if (toggle) toggle.addEventListener("click", function () { window.setTimeout(render, 0); });
        csv.addEventListener("click", function () {
            var lines = [Array.prototype.map.call(table.tHead.rows[0].cells, function (h) { return csvEscape(text(h)); }).join(";")];
            var q = input.value.trim().toLowerCase();
            Array.prototype.forEach.call(body.rows, function (tr) {
                if (q && tr.hidden) return;
                lines.push(Array.prototype.map.call(tr.cells, function (c) { return csvEscape(text(c)); }).join(";"));
            });
            var blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
            var a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = (document.title || "tableau").replace(/[^\w.-]+/g, "_").slice(0, 60) + ".csv";
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
            window.setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
        });
        render();
    }

    function scan(root) { Array.prototype.forEach.call((root || document).querySelectorAll("table.data-table"), enhance); }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { scan(document); });
    else scan(document);
    document.addEventListener("patrick:content", function (ev) { scan(ev.target && ev.target.querySelectorAll ? ev.target : document); });
    window.PatrickTableTools = { enhance: enhance, scan: scan, compare: compare, toNumber: toNumber };
})();
