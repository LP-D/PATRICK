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
            if (confirmText && !window.confirm(confirmText)) return;
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
    function renderPreview(box, accountId, csvText, data) {
        box.innerHTML = "";
        var p = document.createElement("p");
        p.className = "hint";
        p.textContent = tr("wealth_import_preview", "{n} valid, {e} errors.", { n: data.rows.length, e: data.errors.length });
        box.appendChild(p);
        if (data.errors.length) {
            var ul = document.createElement("ul");
            ul.className = "hint";
            data.errors.slice(0, 20).forEach(function (err) {
                var li = document.createElement("li");
                li.textContent = "ligne " + err.line + " : " + err.error;
                ul.appendChild(li);
            });
            box.appendChild(ul);
        }
        if (data.rows.length) {
            var wrap = document.createElement("div");
            wrap.className = "table-scroll";
            var table = document.createElement("table");
            table.className = "data-table";
            table.innerHTML = "<thead><tr><th>Date</th><th>Type</th><th>Actif</th><th class='num'>Montant</th></tr></thead>";
            var tbody = document.createElement("tbody");
            data.rows.slice(0, 50).forEach(function (r) {
                var tr_ = document.createElement("tr");
                [r.ts, r.kind, r.symbol || "", (r.amount || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })]
                    .forEach(function (v, i) {
                        var td = document.createElement("td");
                        td.textContent = v;
                        if (i === 3) td.className = "num";
                        tr_.appendChild(td);
                    });
                tbody.appendChild(tr_);
            });
            table.appendChild(tbody);
            wrap.appendChild(table);
            box.appendChild(wrap);
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "btn";
            btn.style.marginTop = "10px";
            btn.textContent = "Enregistrer " + data.rows.length + " mouvement(s)";
            btn.addEventListener("click", async function () {
                btn.disabled = true;
                try {
                    var done = await call("/api/wealth/accounts/" + encodeURIComponent(accountId) + "/import", "POST",
                                          { csv: csvText, commit: true });
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
        var text = await file.text();
        try {
            var data = await call("/api/wealth/accounts/" + encodeURIComponent(accountId) + "/import", "POST",
                                  { csv: text, commit: false });
            if (box) renderPreview(box, accountId, text, data);
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

    /* ---- account chart ---- */
    var canvas = document.getElementById("wealth-chart");
    var dataEl = document.getElementById("wealth-chart-data");
    if (!canvas || !dataEl) return;
    var chart;
    try { chart = JSON.parse(dataEl.textContent); } catch (e) { return; }
    var MONO = token("--mono") || "monospace";

    function draw() {
        var ratio = window.devicePixelRatio || 1;
        var w = Math.max(280, Math.round(canvas.getBoundingClientRect().width || 600));
        var h = 280;
        canvas.style.height = h + "px";
        canvas.width = Math.round(w * ratio);
        canvas.height = Math.round(h * ratio);
        var ctx = canvas.getContext("2d");
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, w, h);
        var series = [
            { pts: chart.net_invested || [], color: token("--text-3"), width: 1.25, dash: [4, 4] },
            { pts: chart.benchmark_replica || [], color: token("--warn"), width: 1.25 },
            { pts: chart.value || [], color: token("--brand"), width: 2 },
        ];
        var all = [];
        series.forEach(function (s) { s.pts.forEach(function (p) { all.push(p.v); }); });
        if (all.length < 2) return;
        var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
        if (min === max) { min -= 1; max += 1; }
        var t0 = new Date(chart.value[0].t).getTime(), t1 = new Date(chart.value[chart.value.length - 1].t).getTime();
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
            ctx.fillText(Math.round(v).toLocaleString("fr-FR") + " €", padL - 8, yy);
        }
        ctx.textBaseline = "alphabetic";
        ctx.textAlign = "left";
        ctx.fillText(chart.value[0].t, padL, h - 7);
        ctx.textAlign = "right";
        ctx.fillText(chart.value[chart.value.length - 1].t, w - padR, h - 7);
        series.forEach(function (s) {
            if (s.pts.length < 2) return;
            ctx.beginPath();
            ctx.strokeStyle = s.color;
            ctx.lineWidth = s.width;
            ctx.setLineDash(s.dash || []);
            s.pts.forEach(function (p, k) { if (k === 0) ctx.moveTo(x(p.t), y(p.v)); else ctx.lineTo(x(p.t), y(p.v)); });
            ctx.stroke();
            ctx.setLineDash([]);
        });
        var last = chart.value[chart.value.length - 1];
        canvas.setAttribute("aria-label", "Valeur du compte du " + chart.value[0].t + " au " + last.t +
            " : de " + Math.round(chart.value[0].v).toLocaleString("fr-FR") + " € à " + Math.round(last.v).toLocaleString("fr-FR") + " €.");
    }
    draw();
    window.addEventListener("patrick:themechange", draw);
    var timer = null;
    window.addEventListener("resize", function () { window.clearTimeout(timer); timer = window.setTimeout(draw, 150); });
})();
