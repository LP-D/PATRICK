/* Page /fonds : le total et le tableau des stratégies arrivent après l'affichage (`/fragments/fund-overview`, lazy.js) ; les clics
   sont donc délégués sur #fund-overview. Un clic sur une stratégie charge son panneau (fragment HTML rendu par
   le serveur, échappé : GET /api/fund/strategies/{id}/panel), puis :
   - graphique de la valeur (canvas HiDPI, couleurs lues dans les jetons CSS au dessin) ;
   - règles automatiques : créer, appliquer, supprimer (/api/fund/.../rules, /api/fund/rules/{id}/apply) ;
   - pilote automatique : prévisualiser (fragment HTML rendu serveur), activer, appliquer, désactiver (/api/fund/.../autopilot*) ;
   - Ajuster / Corriger / Supprimer une position, renommer / archiver / supprimer la stratégie,
     tous via /api/fund/* ; les refus de règle (422) s'affichent dans le formulaire. */
(function () {
    "use strict";
    var panel = document.getElementById("fund-panel");
    if (!panel) return;

    var flash = document.getElementById("fund-flash");
    var overview = document.getElementById("fund-overview");
    var current = null;

    function say(text, kind) {
        if (!flash) return;
        flash.textContent = text;
        flash.className = "banner " + (kind === "error" ? "banner-error" : "banner-info");
        flash.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    async function call(url, method, body) {
        var res = await fetch(url, {
            method: method || "POST",
            headers: { "Content-Type": "application/json" },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        var data = {};
        try { data = await res.json(); } catch (e) { data = {}; }
        if (!res.ok) {
            var err = new Error(typeof data.detail === "string" ? data.detail : "HTTP " + res.status);
            err.blocking = data.detail && data.detail.blocking ? data.detail.blocking : null;
            throw err;
        }
        return data;
    }
    /* ---- boîtes de dialogue de la page (aucune boîte du navigateur) : confirmation et nouveau nom.
       Les aides sont celles de confirm.js (window.patrickDialog), chargé après ce script : appelées à l'usage. ---- */
    var renameDialog = document.getElementById("fund-rename-dialog");
    function confirmAction(message, label, danger) {
        return window.patrickDialog.confirm(message, label, danger);
    }
    function askName(current) {
        var input = renameDialog ? renameDialog.querySelector('input[name="name"]') : null;
        return window.patrickDialog.ask(renameDialog, function () { input.value = current; },
                                        function () { return input.value.trim(); });
    }
    function reload(id) { window.location.href = "/fonds" + (id ? "?strategy=" + encodeURIComponent(id) : ""); }

    /* ---- graphique : valeur contre capital (moteur commun chart_kit.js : zoom, périodes, infobulle, thème) ---- */
    function drawChart() {
        var host = document.getElementById("fund-chart"), dataEl = document.getElementById("fund-chart-data");
        if (!host || !dataEl) return;
        var data = JSON.parse(dataEl.textContent), pts = data.series || [], labels = data.labels || {}, P = window.PatrickPlot;
        var eur = new Intl.NumberFormat(document.documentElement.lang || "fr", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
        P.create(host, {
            type: "line", xKind: "time", xs: pts.map(function (p) { return P.parseDate(p.t); }),
            series: [{ name: labels.nav || "", values: pts.map(function (p) { return p.nav; }), color: "--brand", width: 2 }],
            hlines: [{ y: data.capital, color: "--text-3", dash: [5, 4], label: labels.capital }],
            yFmt: function (v) { return eur.format(v); }, ranges: true, title: host.getAttribute("aria-label") || "", height: 260,
        });
    }

    /* ---- panneau ---- */
    function rows() { return Array.prototype.slice.call(document.querySelectorAll(".fund-row")); }
    function mark() {
        rows().forEach(function (r) { r.classList.toggle("is-selected", r.getAttribute("data-strategy-id") === current); });
    }
    function open(id) {
        current = id;
        mark();
        panel.hidden = false;
        panel.textContent = "";
        var loading = document.createElement("p");
        loading.className = "hint";
        loading.textContent = "…";
        panel.appendChild(loading);
        fetch("/api/fund/strategies/" + encodeURIComponent(id) + "/panel")
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function (html) {
                if (current !== id) return;
                panel.innerHTML = html;          // fragment rendu serveur, échappé par Jinja
                drawChart();
                initRuleForms();
                panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
            })
            .catch(function () { if (current === id) loading.textContent = "—"; });
    }
    function close() { current = null; mark(); panel.hidden = true; panel.textContent = ""; }

    /* Lignes du tableau : délégation (elles n'existent qu'une fois le fragment arrivé). Un bouton de la ligne (Supprimer)
       agit seul : il n'ouvre pas le panneau. */
    function rowOf(e) { return e.target.closest(".fund-row"); }
    if (overview) {
        overview.addEventListener("click", function (e) {
            var r = rowOf(e);
            if (r && !e.target.closest("[data-act]")) open(r.getAttribute("data-strategy-id"));
        });
        overview.addEventListener("keydown", function (e) {
            var r = rowOf(e);
            if (!r || e.target.closest("[data-act]")) return;
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(r.getAttribute("data-strategy-id")); }
        });
        /* Le tableau vient d'arriver : la ligne ouverte est marquée ; une stratégie demandée par l'adresse mais absente ferme le panneau. */
        overview.addEventListener("patrick:content", function () {
            if (current && !rows().some(function (r) { return r.getAttribute("data-strategy-id") === current; })) close();
            else mark();
        });
    }

    /* ---- supprimer une stratégie depuis le tableau, sans ouvrir son panneau ---- */
    if (overview) {
        overview.addEventListener("click", async function (e) {
            var btn = e.target.closest('[data-act="delete-strategy"]');
            if (!btn || btn.disabled) return;
            try {
                if (!(await confirmAction(btn.getAttribute("data-confirm"), btn.textContent.trim(), true))) return;
                setBusy(btn, true);
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "DELETE");
                reload(null);
            } catch (err) {
                say((err.blocking || [err.message]).join(" · "), "error");
                setBusy(btn, false);
            }
        });
    }

    /* ---- formulaires en ligne : champs visibles selon l'action choisie ---- */
    function syncActions(form) {
        var select = form.elements.action;
        if (!select) return;
        form.querySelectorAll("[data-actions]").forEach(function (el) {
            el.hidden = el.getAttribute("data-actions").split(" ").indexOf(select.value) === -1;
        });
    }
    function present(v) { return v !== null && v !== undefined && String(v).trim() !== ""; }
    function showError(form, lines) {
        var box = form.querySelector(".fund-form-error");
        if (!box) return;
        box.textContent = lines.join(" · ");
        box.hidden = false;
    }
    function specOf(form) {
        var spec = {};
        ["stop", "target", "leverage"].forEach(function (name) {
            if (form.elements[name]) spec[name] = form.elements[name].value;
        });
        return spec;
    }
    /* ---- formulaire « Nouvelle règle » : champs visibles selon l'instrument, segments selon le modèle ---- */
    function syncRuleForm(form) {
        var f = form.elements, kind = f.kind.value;
        form.querySelectorAll("[data-kinds]").forEach(function (el) {
            el.hidden = el.getAttribute("data-kinds").split(" ").indexOf(kind) === -1;
        });
        var shortable = kind === "cfd" || kind === "future";
        if (f.allow_short) { f.allow_short.disabled = !shortable; if (!shortable) f.allow_short.checked = false; }
        var opt = f.trial_id.options[f.trial_id.selectedIndex], segments = {};
        try { segments = JSON.parse(opt.getAttribute("data-segments") || "{}"); } catch (e) { segments = {}; }
        /* modèle d'alpha : la jambe de couverture apparaît, l'actif négocié est celui du modèle */
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
    function initRuleForms() {
        panel.querySelectorAll('form[data-form="rule"]').forEach(syncRuleForm);
    }
    async function submitRule(form) {
        var f = form.elements, kind = f.kind.value, instrument = { kind: kind };
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
        await call("/api/fund/strategies/" + encodeURIComponent(form.getAttribute("data-strategy-id")) + "/rules", "POST",
                   { name: f["name"].value.trim(), config: config });
    }
    function ruleResult(r) {
        var text = (window.I18N && window.I18N.fund_rule_result) || "{placed} / {already} / {pending} / {refused} / {skipped}";
        var counts = { placed: r.placed.length, already: r.already, pending: r.pending.length,
                       refused: r.refused.length, skipped: r.skipped.length };
        Object.keys(counts).forEach(function (k) { text = text.replace("{" + k + "}", counts[k]); });
        r.refused.slice(0, 3).forEach(function (x) { text += " " + x.signal + " " + x.action + " : " + x.reasons.join(", ") + "."; });
        return text;
    }
    async function submitAdjust(form) {
        var f = form.elements, action = f.action.value;
        var req = { action: action, position_id: form.getAttribute("data-position-id"), date: f.date.value };
        if (action === "increase" || action === "reduce") req.quantity = f.quantity.value;
        if (action !== "modify") {
            if (present(f.price.value)) req.price = f.price.value;
            req.fees_mode = f.fees_mode.value;
            if (req.fees_mode === "manual") req.fees = f.fees.value;
        } else {
            req.spec = specOf(form);
        }
        await call("/api/fund/strategies/" + encodeURIComponent(form.getAttribute("data-strategy-id")) + "/orders", "POST", req);
    }
    async function submitCorrect(form) {
        var f = form.elements;
        // prix vide = cours du marché : toujours envoyé, sinon le serveur garderait l'ancien prix saisi
        var req = { quantity: f.quantity.value, date: f.date.value, fees_mode: f.fees_mode.value, spec: specOf(form),
                    price: f.price.value };
        if (req.fees_mode === "manual") req.fees = f.fees.value;
        await call("/api/fund/orders/" + encodeURIComponent(form.getAttribute("data-order-id")), "PATCH", req);
    }

    panel.addEventListener("change", function (e) {
        var form = e.target.closest("form[data-form]");
        if (!form) return;
        if (form.getAttribute("data-form") === "rule") { syncRuleForm(form); return; }
        if (e.target.name === "action") syncActions(form);
    });
    /* Un envoi à la fois : tant que la requête n'est pas revenue, le bouton est inactif (un double clic créait
       deux ordres). Sur succès la page se recharge ; sur échec le bouton est rendu. */
    function setBusy(control, busy) {
        control.disabled = busy;
        control.setAttribute("aria-busy", busy ? "true" : "false");
    }
    panel.addEventListener("submit", async function (e) {
        var form = e.target.closest("form[data-form]");
        if (!form) return;
        e.preventDefault();
        var send = form.querySelector('button[type="submit"]');
        if (send.disabled) return;
        setBusy(send, true);
        try {
            var which = form.getAttribute("data-form");
            if (which === "adjust") await submitAdjust(form);
            else if (which === "rule") await submitRule(form);
            else await submitCorrect(form);
            reload(current);
        } catch (err) {
            showError(form, err.blocking || [err.message]);
            setBusy(send, false);
        }
    });
    /* ---- pilote automatique : réglages lus dans le bloc, aperçu = fragment HTML rendu serveur (échappé par Jinja) ---- */
    function autoSettings(box) {
        var out = {};
        box.querySelectorAll("[data-auto-field]").forEach(function (el) {
            if (el.type === "checkbox") out[el.name] = el.checked;
            else if (el.name === "gross") out.gross = Number(el.value) / 100;
            else if (el.name === "max_models") out.max_models = Number(el.value);
            else out[el.name] = el.value;
        });
        return out;
    }
    function fill(template, values) {
        return template.replace(/\{(\w+)\}/g, function (m, key) { return values[key] === undefined ? m : values[key]; });
    }
    async function autoAct(btn, act) {
        var box = btn.closest(".fund-auto");
        var base = "/api/fund/strategies/" + encodeURIComponent(box.getAttribute("data-strategy-id")) + "/autopilot";
        if (act === "auto-preview") {
            var query = new URLSearchParams(), settings = autoSettings(box);
            Object.keys(settings).forEach(function (k) {
                query.set(k, settings[k] === true ? "1" : settings[k] === false ? "0" : String(settings[k]));
            });
            var res = await fetch(base + "/preview.html?" + query.toString());
            if (!res.ok) {
                var data = {};
                try { data = await res.json(); } catch (err) { data = {}; }
                throw new Error(typeof data.detail === "string" ? data.detail : "HTTP " + res.status);
            }
            var out = box.querySelector("[data-auto-result]");
            out.innerHTML = await res.text();            // fragment rendu serveur, échappé par Jinja
            out.hidden = false;
            setBusy(btn, false);
        } else if (act === "auto-save") {
            await call(base, "PUT", autoSettings(box));
            say(btn.getAttribute("data-done"), "info");
            setBusy(btn, false);
            open(current);
        } else if (act === "auto-run") {
            var report = await call(base + "/run", "POST", {});
            say(fill(btn.getAttribute("data-done"), {
                placed: report.placed, created: report.created.length, retired: report.retired.length,
                pending: report.pending, refused: report.refused.length }), report.refused.length ? "error" : "info");
            setBusy(btn, false);
            open(current);
        } else {
            await call(base, "DELETE");
            open(current);
        }
    }

    panel.addEventListener("click", async function (e) {
        var btn = e.target.closest("[data-act]");
        if (!btn) return;
        var act = btn.getAttribute("data-act");
        if (btn.disabled) return;
        try {
            if (act === "close-panel") { close(); return; }
            if (act === "toggle") {
                var target = document.getElementById(btn.getAttribute("data-target"));
                if (target) {
                    target.hidden = !target.hidden;
                    var form = target.querySelector("form[data-form]");
                    if (form) syncActions(form);
                }
                return;
            }
            if (act === "rename") {
                var name = await askName(btn.getAttribute("data-name") || "");
                if (!name) return;
                setBusy(btn, true);
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "PATCH", { name: name });
                reload(current);
                return;
            }
            if (btn.hasAttribute("data-confirm")
                && !(await confirmAction(btn.getAttribute("data-confirm"), btn.textContent.trim(), act.indexOf("delete") === 0))) return;
            setBusy(btn, true);
            if (act === "delete-position") {
                await call("/api/fund/positions/" + encodeURIComponent(btn.getAttribute("data-position-id")), "DELETE");
                reload(current);
            } else if (act === "delete-strategy") {
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "DELETE");
                reload(null);
            } else if (act === "apply-rule") {
                var result = await call("/api/fund/rules/" + encodeURIComponent(btn.getAttribute("data-rule-id")) + "/apply", "POST", {});
                say(ruleResult(result), result.refused.length ? "error" : "info");
                setBusy(btn, false);
                open(current);
            } else if (act.indexOf("auto-") === 0) {
                await autoAct(btn, act);
            } else if (act === "delete-rule") {
                await call("/api/fund/rules/" + encodeURIComponent(btn.getAttribute("data-rule-id")), "DELETE");
                open(current);
            } else if (act === "archive") {
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "PATCH", { archived: true });
                reload(null);
            }
        } catch (err) {
            say((err.blocking || [err.message]).join(" · "), "error");
            setBusy(btn, false);
        }
    });

    var archivedBox = document.querySelector(".fund-archived");
    if (archivedBox) {
        archivedBox.addEventListener("click", async function (e) {
            var btn = e.target.closest('[data-act="unarchive"]');
            if (!btn || btn.disabled) return;
            setBusy(btn, true);
            try {
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "PATCH", { archived: false });
                reload(null);
            } catch (err) {
                say((err.blocking || [err.message]).join(" · "), "error");
                setBusy(btn, false);
            }
        });
    }

    var pre = document.getElementById("fund-selected");
    var wanted = pre ? JSON.parse(pre.textContent) : null;
    if (wanted) open(wanted);        // sans attendre le tableau : le panneau et le tableau se chargent en même temps
})();
