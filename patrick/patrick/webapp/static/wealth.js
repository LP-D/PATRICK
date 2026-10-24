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
    var flash = document.getElementById("wealth-flash");
    function say(text, kind) {
        if (!flash) return;
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
    var LANG = document.documentElement.lang || "fr";
    var KIND_KEYS = { deposit: "js_w_kind_deposit", withdrawal: "js_w_kind_withdrawal", buy: "js_w_kind_buy", sell: "js_w_kind_sell",
                      dividend: "js_w_kind_dividend", fee: "js_w_kind_fee", interest: "js_w_kind_interest", term_deposit: "js_w_kind_term_deposit" };
    function kindLabel(kind) { return KIND_KEYS[kind] ? tr(KIND_KEYS[kind], kind) : kind; }
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
            + (skipped ? " " + tr("js_w_skipped", "{n} row(s) skipped.", { n: skipped }) : "");
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
            box.appendChild(hintList(data.errors.map(function (err) { return tr("js_w_line", "row {n}: {msg}", { n: err.line, msg: err.error }); })));
        }
        if ((data.warnings || []).length) {
            box.appendChild(hintList(data.warnings.map(function (w) { return tr("js_w_line", "row {n}: {msg}", { n: w.line, msg: w.warning }); })));
        }
        if (data.rows.length) {
            var wrap = document.createElement("div");
            wrap.className = "table-scroll";
            var table = document.createElement("table");
            table.className = "data-table";
            table.innerHTML = "<thead><tr><th>" + tr("js_w_col_date", "Date") + "</th><th>" + tr("js_w_col_type", "Type") + "</th><th>" + tr("js_w_col_asset", "Asset")
                + "</th><th class='num'>" + tr("js_w_col_qty", "Qty") + "</th><th class='num'>" + tr("js_w_col_amount", "Amount") + "</th>"
                + (multi ? "<th>" + tr("js_w_col_account", "Account") + "</th>" : "") + "<th>" + tr("js_w_col_status", "Status") + "</th></tr></thead>";
            var tbody = document.createElement("tbody");
            data.rows.slice(0, 200).forEach(function (r) {
                var tr_ = document.createElement("tr");
                var cells = [r.ts, kindLabel(r.kind), r.symbol ? (window.PatrickNames ? window.PatrickNames.label(r.symbol) : r.symbol) : "",
                             r.quantity ? r.quantity.toLocaleString(LANG, { maximumFractionDigits: 6 }) : "",
                             (r.amount || 0).toLocaleString(LANG, { minimumFractionDigits: 2, maximumFractionDigits: 2 })];
                if (multi) cells.push((r.source || "") + " → " + (r.target ? names[r.target] || r.target : "—"));
                cells.push(r.status || tr("js_w_to_save", "to save"));
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

    /* ---- graphiques : moteur commun (chart_kit.js) — zoom, périodes, infobulle, légende cliquable, thème ---- */
    var EUR = new Intl.NumberFormat(LANG, { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
    function eur(v) { return EUR.format(v); }
    function pct(v, signed) {
        if (v === null || v === undefined || Number.isNaN(v)) return "—";
        var s = (v * 100).toLocaleString(LANG, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + (LANG === "fr" ? " %" : "%");
        return (signed && v > 0 ? "+" : "") + s;
    }

    /* ---- account chart ---- */
    var host = document.getElementById("wealth-chart");
    var dataEl = document.getElementById("wealth-chart-data");
    if (host && dataEl) {
        var chart = null;
        try { chart = JSON.parse(dataEl.textContent); } catch (e) { chart = null; }
        if (chart) {
            var P = window.PatrickPlot, labels = chart.labels || {};
            var line = function (pts, name, color, width, dash) {
                return { name: name, color: color, width: width, dash: dash,
                         xs: (pts || []).map(function (p) { return P.parseDate(p.t); }), values: (pts || []).map(function (p) { return p.v; }) };
            };
            var series = [line(chart.value, labels.value, "--brand", 2)];
            if ((chart.net_invested || []).length > 1) series.push(line(chart.net_invested, labels.net, "--text-3", 1.25, [4, 4]));
            if ((chart.benchmark_replica || []).length > 1) series.push(line(chart.benchmark_replica, labels.bench, "--warn", 1.25));
            P.create(host, { type: "line", xKind: "time", series: series, yFmt: eur, ranges: true, legend: true, title: host.getAttribute("aria-label") || "", height: 280 });
        }
    }
})();
