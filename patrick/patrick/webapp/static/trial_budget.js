/* Budget d'essais du formulaire de lancement (ADR 0010) : pour chaque cible choisie (3 au plus) et les horizons cochés, ce que le run prévu
   ajoute au nombre d'essais déjà comptés et ce que cela fait au seuil de Sharpe sous H0. Lecture seule : `/api/trial-budget`.
   Les textes viennent du gabarit (data-*), jamais d'ici. */
(function () {
    "use strict";
    var box = document.getElementById("trial-budget");
    var targets = document.getElementById("target_symbols");
    var horizons = document.getElementById("horizons");
    if (!box || !targets || !horizons) { return; }
    var MAX_TARGETS = 3;
    var timer = null;
    var seq = 0;

    function selected(select) {
        return Array.prototype.filter.call(select.options, function (o) { return o.selected && !o.disabled; })
            .map(function (o) { return o.value; });
    }

    function fill(template, values) {
        return template.replace(/\{(\w+)\}/g, function (m, key) { return key in values ? String(values[key]) : m; });
    }

    function sign(x) { return (x >= 0 ? "+" : "") + x.toFixed(2); }

    function render(results) {
        var list = box.querySelector(".trial-budget-lines");
        list.textContent = "";
        results.forEach(function (res) {
            res.horizons.forEach(function (h) {
                var li = document.createElement("li");
                li.textContent = fill(box.dataset.line, {
                    target: res.name, h: h.horizon, existing: h.existing, added: h.added, after: h.after,
                    before: h.threshold_before.toFixed(2), thr: h.threshold_after.toFixed(2), delta: sign(h.delta_threshold)
                });
                list.appendChild(li);
            });
        });
        box.querySelector(".trial-budget-title").textContent = box.dataset.title;
        box.querySelector(".trial-budget-hint").textContent = box.dataset.hint;
        box.hidden = false;
    }

    function failed() {
        box.querySelector(".trial-budget-title").textContent = box.dataset.title;
        box.querySelector(".trial-budget-lines").textContent = "";
        box.querySelector(".trial-budget-hint").textContent = box.dataset.error;
        box.hidden = false;
    }

    function refresh() {
        var syms = selected(targets).slice(0, MAX_TARGETS);
        var hs = selected(horizons);
        if (!syms.length || !hs.length) { box.hidden = true; return; }
        var mine = ++seq;
        Promise.all(syms.map(function (sym, i) {
            var opt = Array.prototype.find.call(targets.options, function (o) { return o.value === sym; });
            return fetch("/api/trial-budget?target=" + encodeURIComponent(sym) + "&horizons=" + hs.join(","))
                .then(function (r) { if (!r.ok) { throw new Error(String(r.status)); } return r.json(); })
                .then(function (b) { b.name = opt ? opt.textContent.trim() : sym; return b; });
        })).then(function (results) {
            if (mine === seq) { render(results); }
        }).catch(function () {
            if (mine === seq) { failed(); }
        });
    }

    function schedule() {
        window.clearTimeout(timer);
        timer = window.setTimeout(refresh, 250);
    }

    targets.addEventListener("change", schedule);
    horizons.addEventListener("change", schedule);
    schedule();
})();
