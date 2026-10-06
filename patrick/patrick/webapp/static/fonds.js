/* Page /fonds : un clic sur une stratégie charge son panneau (fragment HTML rendu par
   le serveur, échappé : GET /api/fund/strategies/{id}/panel), puis :
   - graphique de la valeur (canvas HiDPI, couleurs lues dans les jetons CSS au dessin) ;
   - règles automatiques : créer, appliquer, supprimer (/api/fund/.../rules, /api/fund/rules/{id}/apply) ;
   - Ajuster / Corriger / Supprimer une position, renommer / archiver / supprimer la stratégie,
     tous via /api/fund/* ; les refus de règle (422) s'affichent dans le formulaire. */
(function () {
    "use strict";
    var panel = document.getElementById("fund-panel");
    if (!panel) return;

    var flash = document.getElementById("fund-flash");
    var rows = Array.prototype.slice.call(document.querySelectorAll(".fund-row"));
    var current = null;
    var MONO = getComputedStyle(document.documentElement).getPropertyValue("--mono").trim() || "monospace";

    function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
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

    /* ---- graphique : valeur contre capital ---- */
    function drawChart() {
        var canvas = document.getElementById("fund-chart"), dataEl = document.getElementById("fund-chart-data");
        if (!canvas || !dataEl) return;
        var data = JSON.parse(dataEl.textContent), pts = data.series || [];
        var ratio = window.devicePixelRatio || 1;
        var w = Math.max(280, Math.round(canvas.getBoundingClientRect().width || 600)), h = 260;
        canvas.style.height = h + "px";
        canvas.width = Math.round(w * ratio);
        canvas.height = Math.round(h * ratio);
        var ctx = canvas.getContext("2d");
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, w, h);
        if (pts.length < 2) return;
        var vals = pts.map(function (p) { return p.nav; }).concat([data.capital]);
        var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
        if (min === max) { min -= 1; max += 1; }
        var t0 = new Date(pts[0].t).getTime(), t1 = new Date(pts[pts.length - 1].t).getTime();
        if (t1 === t0) t1 = t0 + 86400000;
        var padL = 78, padR = 14, padT = 12, padB = 26;
        function x(t) { return padL + (new Date(t).getTime() - t0) / (t1 - t0) * (w - padL - padR); }
        function y(v) { return padT + (1 - (v - min) / (max - min)) * (h - padT - padB); }
        ctx.font = "11px " + MONO;
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (var i = 0; i <= 4; i++) {
            var v = min + (max - min) * i / 4, yy = Math.round(y(v)) + 0.5;
            ctx.strokeStyle = token("--chart-grid");
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
            ctx.fillStyle = token("--ink-text-2");
            ctx.fillText(Math.round(v).toLocaleString("fr-FR") + " €", padL - 8, yy);
        }
        ctx.textBaseline = "alphabetic";
        ctx.textAlign = "left";
        ctx.fillText(pts[0].t, padL, h - 7);
        ctx.textAlign = "right";
        ctx.fillText(pts[pts.length - 1].t, w - padR, h - 7);
        ctx.strokeStyle = token("--text-3");
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(padL, y(data.capital)); ctx.lineTo(w - padR, y(data.capital)); ctx.stroke();
        ctx.setLineDash([]);
        ctx.strokeStyle = token("--brand");
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        pts.forEach(function (p, k) { if (k === 0) ctx.moveTo(x(p.t), y(p.nav)); else ctx.lineTo(x(p.t), y(p.nav)); });
        ctx.stroke();
        canvas.setAttribute("aria-label", "Valeur de " + Math.round(pts[0].nav).toLocaleString("fr-FR") + " € le " + pts[0].t +
            " à " + Math.round(pts[pts.length - 1].nav).toLocaleString("fr-FR") + " € le " + pts[pts.length - 1].t);
    }
    window.addEventListener("patrick:themechange", drawChart);
    var resizeTimer = null;
    window.addEventListener("resize", function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(drawChart, 150);
    });

    /* ---- panneau ---- */
    function mark() {
        rows.forEach(function (r) { r.classList.toggle("is-selected", r.getAttribute("data-strategy-id") === current); });
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

    rows.forEach(function (r) {
        function go() { open(r.getAttribute("data-strategy-id")); }
        r.addEventListener("click", go);
        r.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });

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
    if (wanted && rows.some(function (r) { return r.getAttribute("data-strategy-id") === wanted; })) open(wanted);
})();
