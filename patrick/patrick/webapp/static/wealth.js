/* Roadmap bloc 4 -- PATRIMOINE (patrimoine.html, patrimoine_account.html,
   mouvements.html). No dependency.
   - [data-api] forms and buttons -> JSON fetch (POST/PATCH/DELETE), then
     reload / redirect; server-side validation errors shown in #wealth-flash;
   - movement rows (draggable) dropped on an account card -> transfer
     (real -> real moves, -> fictive copies, fictive -> real refused by the
     server);
   - CSV files dropped on a .drop-zone -> preview (nothing written) ->
     explicit confirmation -> commit;
   - account chart: HiDPI canvas, colours read from the CSS tokens at draw
     time, redrawn on theme change and resize. */
(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback, params) {
        var s = I18N[key] || fallback || key;
        return params ? s.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; }) : s;
    }
    function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
    var flash = document.getElementById("wealth-flash");
    function say(text, kind) {
        if (!flash) { if (kind === "error") window.alert(text); return; }
        flash.textContent = text;
        flash.className = "banner " + (kind === "error" ? "banner-error" : kind === "warning" ? "banner-warning" : "banner-info");
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
        if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));
        return data;
    }
    function after(el, data) {
        if (el.hasAttribute("data-redirect-account") && data.account_id) {
            window.location.href = "/patrimoine/comptes/" + encodeURIComponent(data.account_id);
        } else if (el.getAttribute("data-redirect")) {
            window.location.href = el.getAttribute("data-redirect");
        } else {
            window.location.reload();
        }
    }

    /* ---- dialogs ---- */
    document.querySelectorAll("[data-open-dialog]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var d = document.getElementById(btn.getAttribute("data-open-dialog"));
            if (d && d.showModal) d.showModal();
        });
    });
    document.querySelectorAll("[data-close-dialog]").forEach(function (btn) {
        btn.addEventListener("click", function () { var d = btn.closest("dialog"); if (d) d.close(); });
    });

    /* ---- asset dropdown: "Autre symbole Yahoo" swaps in a free-text field.
       Only one of the two controls carries name="symbol" at a time (a
       nameless or disabled control is left out of FormData). ---- */
    document.querySelectorAll("select[data-symbol-select]").forEach(function (sel) {
        var other = sel.form && sel.form.querySelector("[data-symbol-other]");
        if (!other) return;
        var input = other.querySelector("input");
        function sync(focus) {
            var isOther = sel.value === "__other__";
            other.hidden = !isOther;
            input.disabled = !isOther;
            sel.name = isOther ? "" : "symbol";
            if (isOther && focus) input.focus();
        }
        sel.addEventListener("change", function () { sync(true); });
        sync(false);
    });

    /* ---- JSON forms ---- */
    document.querySelectorAll("form[data-api]").forEach(function (form) {
        form.addEventListener("submit", async function (ev) {
            ev.preventDefault();
            var body = {};
            new FormData(form).forEach(function (v, k) {
                v = typeof v === "string" ? v.trim() : v;
                if (v !== "") body[k] = v;   // empty optional field = server default
            });
            var submit = form.querySelector("[type=submit]");
            if (submit) submit.disabled = true;
            try {
                after(form, await call(form.getAttribute("data-api"), form.getAttribute("data-method"), body));
            } catch (e) {
                var d = form.closest("dialog");
                if (d) d.close();
                say(String(e.message || e), "error");
            } finally {
                if (submit) submit.disabled = false;
            }
        });
    });

    /* ---- action buttons ---- */
    document.querySelectorAll("button[data-api]").forEach(function (btn) {
        btn.addEventListener("click", async function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var confirmText = btn.getAttribute("data-confirm");
            if (confirmText && !(await window.patrickDialog.confirm(
                confirmText, btn.getAttribute("aria-label") || btn.textContent.trim(), true))) return;
            btn.disabled = true;
            try {
                after(btn, await call(btn.getAttribute("data-api"), btn.getAttribute("data-method"), {}));
            } catch (e) {
                say(String(e.message || e), "error");
                btn.disabled = false;
            }
        });
    });

    /* ---- drag & drop: movements onto accounts ---- */
    var MOVEMENT_TYPE = "application/x-patrick-movement";
    document.querySelectorAll(".draggable-row").forEach(function (row) {
        row.addEventListener("dragstart", function (ev) {
            ev.dataTransfer.setData(MOVEMENT_TYPE, row.getAttribute("data-movement-id"));
            ev.dataTransfer.setData("text/plain", "mouvement " + row.getAttribute("data-movement-id"));
            ev.dataTransfer.effectAllowed = "copyMove";
            row.setAttribute("data-dragging", "");
        });
        row.addEventListener("dragend", function () { row.removeAttribute("data-dragging"); });
    });
    function carriesMovement(ev) { return Array.prototype.indexOf.call(ev.dataTransfer.types, MOVEMENT_TYPE) >= 0; }
    function carriesFiles(ev) { return Array.prototype.indexOf.call(ev.dataTransfer.types, "Files") >= 0; }

    document.querySelectorAll(".drop-target").forEach(function (target) {
        target.addEventListener("dragover", function (ev) {
            if (!carriesMovement(ev)) return;
            ev.preventDefault();
            ev.dataTransfer.dropEffect = target.getAttribute("data-account-mode") === "fictive" ? "copy" : "move";
            target.setAttribute("data-over", "");
        });
        target.addEventListener("dragleave", function () { target.removeAttribute("data-over"); });
        target.addEventListener("drop", async function (ev) {
            if (!carriesMovement(ev)) return;
            ev.preventDefault();
            target.removeAttribute("data-over");
            var id = ev.dataTransfer.getData(MOVEMENT_TYPE);
            try {
                var res = await call("/api/wealth/movements/" + encodeURIComponent(id) + "/transfer", "POST",
                                     { account_id: target.getAttribute("data-account-id") });
                if (res.action === "none") return;
                say(res.action === "copied" ? tr("wealth_transfer_copied", "Copied.") : tr("wealth_transfer_moved", "Moved."), "info");
                window.setTimeout(function () { window.location.reload(); }, 700);
            } catch (e) {
                say(String(e.message || e), "error");
            }
        });
    });

    /* ---- CSV import: drop -> preview -> confirm ---- */
    var KIND_FR = { deposit: "Versement", withdrawal: "Retrait", buy: "Achat", sell: "Vente", dividend: "Dividende",
                    fee: "Frais", interest: "Intérêts / bonus", term_deposit: "Dépôt à terme" };
    function hintList(items) {
        var ul = document.createElement("ul");
        ul.className = "hint";
        items.slice(0, 20).forEach(function (text) {
            var li = document.createElement("li");
            li.textContent = text;
            ul.appendChild(li);
        });
        return ul;
    }
    /* A file with an account column (Trade Republic: DEFAULT / PEA) gets one
       selector per value: which account its lines go to, or skipped. Every
       change re-asks the server for the preview (internal transfers and
       duplicates depend on the mapping). */
    function mappingControls(data, accountId, mapping, onChange) {
        var sources = Object.keys(data.sources || {});
        if (sources.length < 2) return null;
        var box = document.createElement("div");
        box.className = "hint";
        sources.forEach(function (src) {
            var label = document.createElement("label");
            label.style.display = "block";
            label.style.marginTop = "6px";
            label.textContent = "Lignes « " + src + " » (" + data.sources[src] + ") → ";
            var sel = document.createElement("select");
            (data.accounts || []).forEach(function (a) {
                var o = document.createElement("option");
                o.value = a.account_id;
                o.textContent = a.name + " (" + a.kind + (a.mode === "fictive" ? ", fictif" : "") + ")";
                sel.appendChild(o);
            });
            var skip = document.createElement("option");
            skip.value = "";
            skip.textContent = "Ignorer ces lignes";
            sel.appendChild(skip);
            sel.value = src in mapping ? mapping[src] : accountId;
            sel.addEventListener("change", function () { mapping[src] = sel.value; onChange(); });
            label.appendChild(sel);
            box.appendChild(label);
        });
        return box;
    }
    function renderPreview(box, accountId, csvText, data, mapping) {
        box.innerHTML = "";
        var multi = Object.keys(data.sources || {}).length > 1;
        var names = {};
        (data.accounts || []).forEach(function (a) { names[a.account_id] = a.name; });
        var p = document.createElement("p");
        p.className = "hint";
        var skipped = data.rows.length - data.to_write;
        p.textContent = tr("wealth_import_preview", "{n} valid, {e} errors.", { n: data.to_write, e: data.errors.length })
            + (skipped ? " " + skipped + " ligne(s) écartée(s) : virements internes, doublons déjà enregistrés ou lignes ignorées." : "");
        box.appendChild(p);
        var controls = mappingControls(data, accountId, mapping, async function () {
            try {
                var again = await call("/api/wealth/accounts/" + encodeURIComponent(accountId) + "/import", "POST",
                                       { csv: csvText, commit: false, accounts: mapping });
                renderPreview(box, accountId, csvText, again, mapping);
            } catch (e) {
                say(String(e.message || e), "error");
            }
        });
        if (controls) box.appendChild(controls);
        if (data.errors.length) {
            box.appendChild(hintList(data.errors.map(function (err) { return "ligne " + err.line + " : " + err.error; })));
        }
        if ((data.warnings || []).length) {
            box.appendChild(hintList(data.warnings.map(function (w) { return "ligne " + w.line + " : " + w.warning; })));
        }
        if (data.rows.length) {
            var wrap = document.createElement("div");
            wrap.className = "table-scroll";
            var table = document.createElement("table");
            table.className = "data-table";
            table.innerHTML = "<thead><tr><th>Date</th><th>Type</th><th>Actif</th><th class='num'>Qté</th><th class='num'>Montant</th>"
                + (multi ? "<th>Compte</th>" : "") + "<th>Statut</th></tr></thead>";
            var tbody = document.createElement("tbody");
            data.rows.slice(0, 200).forEach(function (r) {
                var tr_ = document.createElement("tr");
                var cells = [r.ts, KIND_FR[r.kind] || r.kind, r.symbol || "",
                             r.quantity ? r.quantity.toLocaleString("fr-FR", { maximumFractionDigits: 6 }) : "",
                             (r.amount || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })];
                if (multi) cells.push((r.source || "") + " → " + (r.target ? names[r.target] || r.target : "—"));
                cells.push(r.status || "à enregistrer");
                cells.forEach(function (v, i) {
                    var td = document.createElement("td");
                    td.textContent = v;
                    if (i === 3 || i === 4) td.className = "num";
                    tr_.appendChild(td);
                });
                if (r.status) tr_.style.opacity = "0.55";
                tbody.appendChild(tr_);
            });
            table.appendChild(tbody);
            wrap.appendChild(table);
            box.appendChild(wrap);
        }
        if (data.to_write) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "btn";
            btn.style.marginTop = "10px";
            btn.textContent = "Enregistrer " + data.to_write + " mouvement(s)";
            btn.addEventListener("click", async function () {
                btn.disabled = true;
                try {
                    var done = await call("/api/wealth/accounts/" + encodeURIComponent(accountId) + "/import", "POST",
                                          { csv: csvText, commit: true, accounts: mapping });
                    say(tr("wealth_import_done", "{n} saved.", { n: done.written }), "info");
                    window.setTimeout(function () { window.location.reload(); }, 700);
                } catch (e) {
                    say(String(e.message || e), "error");
                    btn.disabled = false;
                }
            });
            box.appendChild(btn);
        }
    }
    async function importFile(zone, file) {
        var accountId = zone.getAttribute("data-import-account");
        var box = document.querySelector('[data-import-preview="' + accountId + '"]');
        if (!file) return;
        if (file.size > 1000000) { say("Fichier trop volumineux (max 1 Mo).", "error"); return; }
        var bytes = await file.arrayBuffer();
        var text;
        try {
            text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        } catch (e) {
            text = new TextDecoder("windows-1252").decode(bytes);  // French Excel export
        }
        try {
            var data = await call("/api/wealth/accounts/" + encodeURIComponent(accountId) + "/import", "POST",
                                  { csv: text, commit: false });
            if (box) renderPreview(box, accountId, text, data, {});
        } catch (e) {
            say(String(e.message || e), "error");
        }
    }
    document.querySelectorAll(".drop-zone[data-import-account]").forEach(function (zone) {
        var input = zone.querySelector("input[type=file]");
        zone.addEventListener("click", function (ev) { ev.preventDefault(); ev.stopPropagation(); if (input) input.click(); });
        zone.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); if (input) input.click(); }
        });
        if (input) input.addEventListener("change", function () { importFile(zone, input.files[0]); input.value = ""; });
        zone.addEventListener("dragover", function (ev) {
            if (!carriesFiles(ev)) return;
            ev.preventDefault();
            ev.stopPropagation();
            zone.setAttribute("data-over", "");
        });
        zone.addEventListener("dragleave", function () { zone.removeAttribute("data-over"); });
        zone.addEventListener("drop", function (ev) {
            if (!carriesFiles(ev)) return;
            ev.preventDefault();
            ev.stopPropagation();
            zone.removeAttribute("data-over");
            importFile(zone, ev.dataTransfer.files[0]);
        });
    });

    /* ---- charts (HiDPI canvas, colours from the CSS tokens at draw time) ---- */
    var MONO = token("--mono") || "monospace";
    function drawLines(canvas, series, fmtY) {
        var ratio = window.devicePixelRatio || 1;
        var w = Math.max(280, Math.round(canvas.getBoundingClientRect().width || 600));
        var h = 280;
        canvas.style.height = h + "px";
        canvas.width = Math.round(w * ratio);
        canvas.height = Math.round(h * ratio);
        var ctx = canvas.getContext("2d");
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, w, h);
        var all = [], ref = null;
        series.forEach(function (s) {
            s.pts.forEach(function (p) { all.push(p.v); });
            if (!ref && s.pts.length > 1) ref = s.pts;
        });
        if (all.length < 2 || !ref) return;
        var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
        if (min === max) { min -= 1; max += 1; }
        var t0 = new Date(ref[0].t).getTime(), t1 = new Date(ref[ref.length - 1].t).getTime();
        if (t1 === t0) t1 = t0 + 86400000;
        var padL = 72, padR = 14, padT = 12, padB = 26;
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
            ctx.fillText(fmtY(v), padL - 8, yy);
        }
        ctx.textBaseline = "alphabetic";
        ctx.textAlign = "left";
        ctx.fillText(ref[0].t, padL, h - 7);
        ctx.textAlign = "right";
        ctx.fillText(ref[ref.length - 1].t, w - padR, h - 7);
        series.forEach(function (s) {
            if (s.pts.length < 2) return;
            ctx.beginPath();
            ctx.strokeStyle = token(s.color);
            ctx.lineWidth = s.width || 1.5;
            ctx.setLineDash(s.dash || []);
            s.pts.forEach(function (p, k) { if (k === 0) ctx.moveTo(x(p.t), y(p.v)); else ctx.lineTo(x(p.t), y(p.v)); });
            ctx.stroke();
            ctx.setLineDash([]);
        });
    }
    var redraws = [];
    window.addEventListener("patrick:themechange", function () { redraws.forEach(function (f) { f(); }); });
    var resizeTimer = null;
    window.addEventListener("resize", function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(function () { redraws.forEach(function (f) { f(); }); }, 150);
    });
    function eur(v) { return Math.round(v).toLocaleString("fr-FR") + " €"; }
    function pct(v, signed) {
        if (v === null || v === undefined || Number.isNaN(v)) return "—";
        var s = (v * 100).toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " %";
        return (signed && v > 0 ? "+" : "") + s;
    }

    /* ---- account chart ---- */
    var canvas = document.getElementById("wealth-chart");
    var dataEl = document.getElementById("wealth-chart-data");
    if (canvas && dataEl) {
        var chart = null;
        try { chart = JSON.parse(dataEl.textContent); } catch (e) { chart = null; }
        if (chart) {
            var drawAccount = function () {
                drawLines(canvas, [
                    { pts: chart.net_invested || [], color: "--text-3", width: 1.25, dash: [4, 4] },
                    { pts: chart.benchmark_replica || [], color: "--warn", width: 1.25 },
                    { pts: chart.value || [], color: "--brand", width: 2 },
                ], eur);
                var v = chart.value || [];
                if (v.length) {
                    canvas.setAttribute("aria-label", "Valeur du compte du " + v[0].t + " au " + v[v.length - 1].t +
                        " : de " + eur(v[0].v) + " à " + eur(v[v.length - 1].v) + ".");
                }
            };
            drawAccount();
            redraws.push(drawAccount);
        }
    }
})();
