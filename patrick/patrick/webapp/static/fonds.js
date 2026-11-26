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
        if (kind !== "error" && window.patrickMotion) window.patrickMotion.success(flash);    // pulsation de réussite
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

    /* ---- graphique : valeur nette, valeur avant frais (pointillés) et capital (moteur commun chart_kit.js : zoom, périodes, infobulle, thème) ---- */
    /* D22 : deux fonds en base 100 au premier jour où les deux ont une valeur (capitaux différents : seules les trajectoires se comparent). */
    function rebase(a, b) {
        var bm = {};
        b.forEach(function (p) { if (p.nav != null) bm[p.t] = p.nav; });
        var start = null;
        for (var i = 0; i < a.length; i++) { if (a[i].nav != null && bm[a[i].t] != null) { start = a[i].t; break; } }
        if (!start) return null;
        var a0 = a.filter(function (p) { return p.t === start; })[0].nav, b0 = bm[start];
        var days = a.filter(function (p) { return p.t >= start; }).map(function (p) { return p.t; });
        return { days: days,
                 a: days.map(function (t) { var p = a.filter(function (q) { return q.t === t; })[0]; return p && p.nav != null ? 100 * p.nav / a0 : null; }),
                 b: days.map(function (t) { return bm[t] != null ? 100 * bm[t] / b0 : null; }) };
    }
    function setupCompare(data) {
        var sel = document.getElementById("fund-compare-select");
        if (!sel || sel.dataset.ready) return;
        sel.dataset.ready = "1";
        // Le tableau des fonds arrive en différé (bloc chargé après la page) : la liste se remplit dès qu'il est là, et à la prise de focus.
        function fill() {
            var have = {};
            Array.prototype.forEach.call(sel.options, function (o) { have[o.value] = true; });
            rows().forEach(function (r) {
                var id = r.getAttribute("data-strategy-id");
                if (!id || id === sel.getAttribute("data-self") || have[id]) return;
                var o = document.createElement("option");
                o.value = id; o.textContent = (r.querySelector("td") || r).textContent.trim();
                sel.appendChild(o);
            });
        }
        fill();
        sel.addEventListener("focus", fill);
        document.addEventListener("patrick:content", fill);
        sel.addEventListener("change", function () {
            if (!sel.value) { drawChart(); return; }
            fetch("/api/fund/strategies/" + encodeURIComponent(sel.value) + "/series").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
                .then(function (other) {
                    var reb = rebase(data.series || [], other.series || []), host = document.getElementById("fund-chart"), P = window.PatrickPlot;
                    if (!reb || !host) return;
                    var self = (rows().filter(function (r) { return r.getAttribute("data-strategy-id") === sel.getAttribute("data-self"); })[0] || {});
                    P.create(host, {
                        type: "line", xKind: "time", xs: reb.days.map(P.parseDate),
                        series: [{ name: (self.querySelector ? self.querySelector("td").textContent.trim() : ""), values: reb.a, color: "--brand", width: 2 },
                                 { name: other.name, values: reb.b, color: "--text-2", width: 1.6, dash: [5, 3] }],
                        hlines: [{ y: 100, color: "--text-3", dash: [5, 4], label: (data.labels || {}).rebased }],
                        ranges: true, title: host.getAttribute("aria-label") || "", height: 260, sync: "fund-chart",
                    });
                }).catch(function () { sel.value = ""; });
        });
    }

    /* VI5 (25/11) : calendrier des rendements quotidiens (12 derniers mois) : colonnes = semaines, lignes = jours ouvrés ; vert / rouge, plus
       foncé quand le mouvement est grand (échelle : 2 écarts-types des rendements affichés). La valeur exacte est dans l'infobulle. */
    function drawCalendar(pts) {
        var host = document.getElementById("fund-calendar");
        if (!host || pts.length < 3) return;
        var rets = [];
        for (var i = 1; i < pts.length; i++) {
            var a = pts[i - 1].nav, b = pts[i].nav;
            if (a > 0 && b != null) rets.push({ t: pts[i].t, r: b / a - 1 });
        }
        var last = rets.length ? new Date(rets[rets.length - 1].t + "T00:00:00") : null;
        if (!last) return;
        var start = new Date(last); start.setDate(start.getDate() - 364);
        rets = rets.filter(function (x) { return new Date(x.t + "T00:00:00") >= start; });
        var sd = Math.sqrt(rets.reduce(function (s, x) { return s + x.r * x.r; }, 0) / Math.max(1, rets.length)) || 0.01;
        var pct = new Intl.NumberFormat(document.documentElement.lang || "fr", { style: "percent", maximumFractionDigits: 2, signDisplay: "always" });
        host.textContent = "";
        var grid = document.createElement("div");
        grid.className = "ret-cal-grid";
        rets.forEach(function (x) {
            var d = new Date(x.t + "T00:00:00"), dow = d.getDay();
            if (dow === 0 || dow === 6) return;                         // week-end : pas de séance pour la plupart des actifs
            var week = Math.floor((d - start) / 604800000);
            var cell = document.createElement("span");
            var k = Math.min(1, Math.abs(x.r) / (2 * sd));
            cell.className = "ret-cell " + (x.r >= 0 ? "is-up" : "is-down");
            cell.style.gridColumn = String(week + 1);
            cell.style.gridRow = String(dow);
            cell.style.opacity = String(0.25 + 0.75 * k);
            cell.title = x.t + " : " + pct.format(x.r);
            grid.appendChild(cell);
        });
        host.appendChild(grid);
        var legend = document.createElement("p");
        legend.className = "hint";
        legend.textContent = host.getAttribute("data-label-legend") || "";
        host.appendChild(legend);
    }

    function drawChart() {
        var host = document.getElementById("fund-chart"), dataEl = document.getElementById("fund-chart-data");
        if (!host || !dataEl) return;
        var data = JSON.parse(dataEl.textContent), pts = data.series || [], labels = data.labels || {}, P = window.PatrickPlot;
        setupCompare(data);
        var eur = new Intl.NumberFormat(document.documentElement.lang || "fr", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
        P.create(host, {
            type: "line", xKind: "time", xs: pts.map(function (p) { return P.parseDate(p.t); }),
            series: [{ name: labels.nav || "", values: pts.map(function (p) { return p.nav; }), color: "--brand", width: 2 }]
                .concat(pts.length && pts[0].gross != null ? [{ name: labels.gross || "", values: pts.map(function (p) { return p.gross; }),
                                                               color: "--text-2", width: 1.5, dash: [4, 3] }] : []),
            hlines: [{ y: data.capital, color: "--text-3", dash: [5, 4], label: labels.capital }],
            yFmt: function (v) { return eur.format(v); }, ranges: true, title: host.getAttribute("aria-label") || "", height: 260,
            sync: "fund-chart",
        });
        drawCalendar(pts);
        var corr = document.querySelector(".fund-corr[data-corr-url]");
        if (corr) corr.addEventListener("toggle", function () {            // VI4 : calculée seulement si on la regarde
            if (!corr.open || corr.dataset.loaded) return;
            corr.dataset.loaded = "1";
            fetch(corr.getAttribute("data-corr-url"), { credentials: "same-origin" })
                .then(function (r) { return r.ok ? r.text() : ""; })
                .then(function (html) { corr.querySelector(".fund-corr-body").innerHTML = html; });
        });
        // D12 (24/11) : perte depuis le plus haut de la valeur nette, sous la courbe, même réticule (`sync`).
        var ddHost = document.getElementById("fund-chart-dd");
        if (ddHost && pts.length > 1) {
            var peak = -Infinity, dd = pts.map(function (p) {
                if (p.nav == null || !isFinite(p.nav)) return null;
                peak = Math.max(peak, p.nav);
                return peak > 0 ? p.nav / peak - 1 : null;
            });
            var pctFmt = new Intl.NumberFormat(document.documentElement.lang || "fr", { style: "percent", maximumFractionDigits: 1 });
            P.create(ddHost, {
                type: "line", xKind: "time", xs: pts.map(function (p) { return P.parseDate(p.t); }),
                series: [{ name: labels.drawdown || "", values: dd, color: "--neg", width: 1.5 }],
                yFmt: function (v) { return pctFmt.format(v); }, title: ddHost.getAttribute("aria-label") || "", height: 120,
                finance: true, area: true, sync: "fund-chart",
            });
        }
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
                loadRuleForm();
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
        var opt = f.trial_id.options[f.trial_id.selectedIndex], segments = {}, pup = {};
        try { segments = JSON.parse(opt.getAttribute("data-segments") || "{}"); } catch (e) { segments = {}; }
        try { pup = JSON.parse(opt.getAttribute("data-pup") || "{}"); } catch (e) { pup = {}; }
        /* sans P(hausse) enregistrée, seuls la direction et la sortie à l'horizon sont possibles */
        var hasPup = Object.keys(pup).length > 0;
        f.signal_mode.options[0].disabled = !hasPup;
        if (!hasPup) f.signal_mode.value = "direction";
        var mode = f.signal_mode.value, usable = mode === "threshold" ? pup : segments;
        form.querySelectorAll("[data-modes]").forEach(function (el) { el.hidden = el.getAttribute("data-modes") !== mode; });
        /* modèle d'alpha : la jambe de couverture apparaît, l'actif négocié est celui du modèle */
        var alpha = opt.getAttribute("data-kind") === "alpha";
        form.querySelectorAll("[data-alpha-only]").forEach(function (el) { el.hidden = !alpha; });
        if (alpha) {
            f.hedge_symbol.placeholder = opt.getAttribute("data-benchmark") || "";
            if (f.symbol && !f.symbol.value.trim()) f.symbol.value = opt.getAttribute("data-asset") || "";
        }
        Array.prototype.forEach.call(f.segment.options, function (o) { o.disabled = !usable[o.value]; });
        if (f.segment.options[f.segment.selectedIndex].disabled) {
            var first = Array.prototype.find.call(f.segment.options, function (o) { return !o.disabled; });
            if (first) f.segment.value = first.value;
        }
    }
    /* Choisir un modèle renseigne tout de suite l'instrument concerné : type conseillé (action, ETF ou CFD) et ticker. */
    function applyModel(form) {
        var f = form.elements, opt = f.trial_id.options[f.trial_id.selectedIndex];
        if (!opt) return;
        var hint = opt.getAttribute("data-kind-hint"), symbol = opt.getAttribute("data-symbol");
        if (hint && f.kind.value !== "future") f.kind.value = hint;
        if (f.symbol && symbol) f.symbol.value = symbol;
        syncRuleForm(form);
    }
    function initRuleForms() {
        panel.querySelectorAll('form[data-form="rule"]').forEach(applyModel);
    }
    /* Le formulaire « Nouvelle règle » liste tous les modèles : il se charge à part, juste après le panneau, pour que le détail
       de la stratégie s'affiche tout de suite. */
    function loadRuleForm() {
        var box = panel.querySelector("[data-rule-form-url]");
        if (!box) return;
        var url = box.getAttribute("data-rule-form-url"), id = current;
        fetch(url)
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function (html) {
                if (current !== id || !box.isConnected) return;
                box.innerHTML = html;             // fragment rendu serveur, échappé par Jinja
                initRuleForms();
            })
            .catch(function () { if (box.isConnected) box.textContent = "—"; });
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
            trial_id: Number(f.trial_id.value), segment: f.segment.value, allow_short: !!f.allow_short.checked,
            instrument: instrument,
            sizing: (kind === "equity" || kind === "etf") ? { amount: Number(f.amount.value) } : { quantity: Number(f.quantity.value) },
        };
        var chosen = f.trial_id.options[f.trial_id.selectedIndex];
        if (f.signal_mode.value === "direction") {
            config.signal = { mode: "direction" };
            config.hold = { mode: "horizon", sessions: Number(chosen.getAttribute("data-horizon")) };
        } else {
            config.enter = Number(f.enter.value);
            config.exit = Number(f.exit.value);
        }
        config.follow_champion = !!f.follow_champion.checked && f.segment.value === "live";
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
        if (form.getAttribute("data-form") === "rule") {
            if (e.target.name === "trial_id") applyModel(form); else syncRuleForm(form);
            return;
        }
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
            else if (el.name === "max_models") out.max_models = el.value.trim() === "" ? null : Number(el.value);   // vide : aucun plafond
            else if (el.name === "max_class_share") out.max_class_share = Number(el.value) / 100;
            else if (el.name === "max_drawdown") out.max_drawdown = el.value.trim() === "" ? null : Number(el.value) / 100;   // vide : pas d'arrêt
            else if (el.name === "min_position") out.min_position = el.value.trim() === "" ? null : Number(el.value);   // vide : aucune taille minimale
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
                query.set(k, settings[k] === true ? "1" : settings[k] === false ? "0" : settings[k] === null ? "" : String(settings[k]));
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
                replaced: (report.replaced || []).length,
                pending: report.pending, refused: report.refused.length }), report.refused.length ? "error" : "info");
            setBusy(btn, false);
            open(current);
        } else {
            await call(base, "DELETE");
            open(current);
        }
    }

    /* ---- carte de création : la gamme choisit le bloc (simulation, fonds reproductibles « tous signaux » ou fonds combinés), les classes
       proposées et le capital par défaut ---- */
    var classes = document.getElementById("fund-classes");
    var family = document.getElementById("fund-family");
    function applySplit() {
        var mode = classes.querySelector("[name='split']").value;
        classes.querySelectorAll("[data-split]").forEach(function (el) { el.hidden = el.getAttribute("data-split") !== mode; });
    }
    function applyFamily() {
        var key = family.value, block = (key === "real" || key === "combo") ? key : "quant";
        document.querySelectorAll("[data-create-block]").forEach(function (el) {
            el.hidden = el.getAttribute("data-create-block") !== block;
        });
        document.querySelectorAll("[data-family-rule]").forEach(function (el) { el.hidden = el.getAttribute("data-family-rule") !== key; });
        if (block !== "quant") return;
        classes.querySelectorAll("[data-families]").forEach(function (el) {
            el.hidden = el.getAttribute("data-families").split(" ").indexOf(key) < 0;
        });
        var capital = classes.querySelector("[name='capital']"), wanted = family.selectedOptions[0].getAttribute("data-capital");
        if (capital && wanted) capital.value = wanted;           // 10 M€ d'étude, 5 000 € pour un CTO ou un PEA reproductible
    }
    if (family && classes) {
        family.addEventListener("change", applyFamily);
        classes.querySelector("[name='split']").addEventListener("change", applySplit);
        applyFamily();
        applySplit();
    }
    function classOptions() {
        var out = { classes: [], tiers: [], family: family ? family.value : "systematic" };
        classes.querySelectorAll("[data-cls-field]").forEach(function (el) {
            if (el.name === "class") { if (el.checked && !el.closest("label").hidden) out.classes.push(el.value); }     // classes de la gamme seulement
            else if (el.name === "tier_pick") { if (el.checked) out.tiers.push(el.value); }
            else if (el.type === "checkbox") out[el.name] = el.checked;
            else if (el.name === "horizons") {
                out.horizons = el.value.split(",").map(function (h) { return Number(h.trim()); }).filter(function (h) { return h > 0; });
            }
            else if (el.name === "gross") out.gross = Number(el.value) / 100;
            else if (el.name === "capital") out.capital = Number(el.value);
            else if (el.name === "max_models") out.max_models = el.value.trim() === "" ? null : Number(el.value);
            else out[el.name] = el.value;
        });
        return out;
    }
    async function classesAct(btn, act) {
        var options = classOptions(), out = classes.querySelector("[data-cls-result]");
        if (act === "classes-preview") {
            var query = new URLSearchParams();
            query.set("classes", options.classes.join(","));
            query.set("tiers", options.tiers.join(","));
            query.set("horizons", options.horizons.join(","));
            ["family", "split", "tier", "capital", "gross"].forEach(function (k) { query.set(k, String(options[k])); });
            query.set("max_models", options.max_models === null ? "" : String(options.max_models));
            var res = await fetch("/api/fund/asset-classes/preview.html?" + query.toString());
            if (!res.ok) {
                var data = {};
                try { data = await res.json(); } catch (err) { data = {}; }
                throw new Error(typeof data.detail === "string" ? data.detail : "HTTP " + res.status);
            }
            out.innerHTML = await res.text();            // fragment rendu serveur, échappé par Jinja
            out.hidden = false;
            setBusy(btn, false);
        } else {
            var done = await call("/api/fund/asset-classes", "POST", options);
            var created = done.rows.filter(function (r) { return r.created; }).length;
            var text = fill(btn.getAttribute("data-done"), { created: created, reused: done.rows.length - created });
            say(done.cycle_started ? text + " " + btn.getAttribute("data-cycle") : text, "info");
            setTimeout(function () { reload(null); }, 1500);
        }
    }
    if (classes) {
        classes.addEventListener("click", async function (e) {
            var btn = e.target.closest("[data-act]");
            if (!btn || btn.disabled) return;
            setBusy(btn, true);
            try {
                await classesAct(btn, btn.getAttribute("data-act"));
            } catch (err) {
                say((err.blocking || [err.message]).join(" · "), "error");
                setBusy(btn, false);
            }
        });
    }

    /* ---- fonds réels (PEA et CTO) : réglages lus dans la section, création ou reprise des deux fonds ---- */
    var real = document.getElementById("fund-real");
    function realOptions() {
        var out = {};
        real.querySelectorAll("[data-real-field]").forEach(function (el) {
            if (el.type === "checkbox") out[el.name] = el.checked;
            else out[el.name] = el.value.trim() === "" ? null : Number(el.value);
        });
        return out;
    }
    if (real) {
        real.addEventListener("click", async function (e) {
            var btn = e.target.closest("[data-act='real-create']");
            if (!btn || btn.disabled) return;
            setBusy(btn, true);
            try {
                var done = await call("/api/fund/real", "POST", realOptions());
                var created = done.rows.filter(function (r) { return r.created; }).length;
                var text = fill(btn.getAttribute("data-done"), { created: created, reused: done.rows.length - created });
                say(done.cycle_started ? text + " " + btn.getAttribute("data-cycle") : text, "info");
                setTimeout(function () { window.location.href = "/fonds?categorie=real"; }, 1500);
            } catch (err) {
                say((err.blocking || [err.message]).join(" · "), "error");
                setBusy(btn, false);
            }
        });
    }

    /* ---- fonds de test combinés : variantes cochées et réglages ; aperçu = une ligne par fonds (textContent, jamais de HTML) ---- */
    var comboBlock = document.getElementById("fund-combo");
    function comboOptions() {
        var out = { only: [] };
        comboBlock.querySelectorAll("[data-combo-field]").forEach(function (el) {
            if (el.name === "only") { if (el.checked) out.only.push(el.value); }
            else if (el.type === "checkbox") out[el.name] = el.checked;
            else if (el.name === "horizons") {
                out.horizons = el.value.split(",").map(function (h) { return Number(h.trim()); }).filter(function (h) { return h > 0; });
            }
            else if (el.name === "tier") out.tier = el.value;
            else out[el.name] = el.value.trim() === "" ? null : Number(el.value);
        });
        return out;
    }
    if (comboBlock) {
        comboBlock.addEventListener("click", async function (e) {
            var btn = e.target.closest("[data-act='combo-preview'], [data-act='combo-create']");
            if (!btn || btn.disabled) return;
            setBusy(btn, true);
            try {
                var preview = btn.getAttribute("data-act") === "combo-preview";
                var options = comboOptions();
                if (preview) { options.dry_run = true; options.run = false; }
                var done = await call("/api/fund/combo", "POST", options);
                if (preview) {
                    var list = comboBlock.querySelector("[data-combo-result]");
                    list.textContent = "";
                    done.rows.forEach(function (r) {
                        var li = document.createElement("li");
                        li.textContent = fill(btn.getAttribute("data-line"), {
                            name: r.name, n: r.candidates,
                            state: r.strategy_id ? btn.getAttribute("data-existing") : btn.getAttribute("data-new") });
                        list.appendChild(li);
                    });
                    list.hidden = false;
                    setBusy(btn, false);
                    return;
                }
                var created = done.rows.filter(function (r) { return r.created; }).length;
                var text = fill(btn.getAttribute("data-done"), { created: created, reused: done.rows.length - created });
                say(done.cycle_started ? text + " " + btn.getAttribute("data-cycle") : text, "info");
                setTimeout(function () { window.location.href = "/fonds?categorie=lab"; }, 1500);
            } catch (err) {
                say((err.blocking || [err.message]).join(" · "), "error");
                setBusy(btn, false);
            }
        });
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
            } else if (act === "limit-cancel") {               // A12 : annule un ordre limite en attente (ses exécutions restent)
                await call("/api/fund/limit-orders/" + encodeURIComponent(btn.getAttribute("data-limit-id")) + "/cancel", "POST", {});
                open(current);
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
