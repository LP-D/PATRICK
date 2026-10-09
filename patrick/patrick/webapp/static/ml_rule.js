/* Page /simulate : carte « Piloter avec un modèle ML ». Mêmes champs et même API que la section « Règles automatiques » de
   /fonds : crée la règle, l'applique tout de suite, puis ouvre le fonds de la stratégie. Les ordres passent par
   `fund.service.place_order` (mêmes règles d'enveloppe, mêmes frais) : rien de nouveau côté serveur. */
(function () {
    "use strict";
    var form = document.getElementById("ml-rule-form");
    if (!form) return;

    function present(v) { return v !== null && v !== undefined && String(v).trim() !== ""; }

    async function call(url, method, body) {
        var res = await fetch(url, { method: method, headers: { "Content-Type": "application/json" },
                                     body: body === undefined ? undefined : JSON.stringify(body) });
        var data = null;
        try { data = await res.json(); } catch (e) { data = null; }
        if (!res.ok) {
            var detail = data && (data.detail || data.error);
            var err = new Error(typeof detail === "string" ? detail : res.status + "");
            err.blocking = data && data.blocking;
            throw err;
        }
        return data;
    }

    function sync() {
        var f = form.elements, kind = f.kind.value;
        form.querySelectorAll("[data-kinds]").forEach(function (el) {
            el.hidden = el.getAttribute("data-kinds").split(" ").indexOf(kind) === -1;
        });
        var shortable = kind === "cfd" || kind === "future";
        if (f.allow_short) { f.allow_short.disabled = !shortable; if (!shortable) f.allow_short.checked = false; }
        var opt = f.trial_id.options[f.trial_id.selectedIndex], segments = {};
        if (!opt) return;
        try { segments = JSON.parse(opt.getAttribute("data-segments") || "{}"); } catch (e) { segments = {}; }
        var alpha = opt.getAttribute("data-kind") === "alpha";
        form.querySelectorAll("[data-alpha-only]").forEach(function (el) { el.hidden = !alpha; });
        if (alpha) {
            f.hedge_symbol.placeholder = opt.getAttribute("data-benchmark") || "";
            if (f.symbol && !f.symbol.value.trim()) f.symbol.value = opt.getAttribute("data-asset") || "";
        }
        Array.prototype.forEach.call(f.segment.options, function (o) { o.disabled = !segments[o.value]; });
        if (f.segment.options[f.segment.selectedIndex].disabled) {
            var first = Array.prototype.find.call(f.segment.options, function (o) { return !o.disabled; });
            if (first) f.segment.value = first.value;
        }
    }

    function showError(lines) {
        var box = form.querySelector(".fund-form-error");
        box.textContent = lines.join(" · ");
        box.hidden = false;
    }

    form.addEventListener("change", sync);
    sync();
    form.addEventListener("submit", async function (e) {
        e.preventDefault();
        var send = form.querySelector('button[type="submit"]');
        if (send.disabled) return;
        send.disabled = true;
        form.querySelector(".fund-form-error").hidden = true;
        var f = form.elements, kind = f.kind.value, instrument = { kind: kind };
        try {
            if (kind === "future") {
                instrument.spec = { root: f.root.value.trim().toUpperCase(), year: Number(f.year.value), month: Number(f.month.value) };
            } else {
                instrument.symbol = f.symbol.value.trim();
                if (kind === "cfd" && present(f.leverage.value)) instrument.spec = { leverage: Number(f.leverage.value) };
            }
            var config = {
                trial_id: Number(f.trial_id.value), segment: f.segment.value,
                enter: Number(f.enter.value), exit: Number(f.exit.value), allow_short: !!f.allow_short.checked,
                instrument: instrument,
                sizing: (kind === "equity" || kind === "etf") ? { amount: Number(f.amount.value) } : { quantity: Number(f.quantity.value) },
            };
            var chosen = f.trial_id.options[f.trial_id.selectedIndex];
            if (chosen && chosen.getAttribute("data-kind") === "alpha") {
                config.hedge = { kind: "cfd", symbol: f.hedge_symbol.value.trim() };
                if (present(f.hedge_leverage.value)) config.hedge.spec = { leverage: Number(f.hedge_leverage.value) };
            }
            var strategy = f.strategy_id.value;
            var created = await call("/api/fund/strategies/" + encodeURIComponent(strategy) + "/rules", "POST",
                                     { name: f["name"].value.trim(), config: config });
            var ruleId = created.rule_id || (created.rule && created.rule.rule_id);
            if (ruleId) await call("/api/fund/rules/" + encodeURIComponent(ruleId) + "/apply", "POST", {});
            window.location.href = "/fonds?strategy=" + encodeURIComponent(strategy);
        } catch (err) {
            showError(err.blocking || [err.message]);
            send.disabled = false;
        }
    });
})();
