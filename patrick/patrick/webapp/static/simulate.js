/* Page /simulate : ticket d'ordre avec aperçu serveur en direct + création de stratégie.
   Aucun calcul métier dans le navigateur : chaque modification du ticket appelle
   POST /api/fund/quote ; « Ouvrir la position » appelle POST /api/fund/strategies/{id}/orders
   avec la graine des frais et l'identifiant de position de l'aperçu (le montant
   affiché est celui qui est enregistré). Tout le texte dynamique passe par
   textContent : noms et motifs viennent de la base ou de Yahoo. */
(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback, params) {
        var s = I18N[key] || fallback || key;
        return params ? s.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; }) : s;
    }
    var flash = document.getElementById("fund-flash");
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
    function num(v, digits) {
        if (v === null || v === undefined) return "—";
        return Number(v).toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }
    function money(v) { return num(v, 2) + " €"; }

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

    /* ---- nouvelle stratégie ---- */
    var newForm = document.getElementById("new-strategy-form");
    if (newForm) {
        newForm.addEventListener("submit", async function (ev) {
            ev.preventDefault();
            var send = newForm.querySelector('button[type="submit"]');
            if (send.disabled) return;          // double clic : la première requête est déjà partie
            send.disabled = true;
            var fd = new FormData(newForm);
            try {
                var res = await call("/api/fund/strategies", "POST", {
                    name: fd.get("name"), wrapper: fd.get("wrapper"),
                    initial_capital: fd.get("initial_capital"), opened_on: fd.get("opened_on"),
                });
                window.location.href = "/simulate?strategy=" + encodeURIComponent(res.strategy_id);
            } catch (e) {
                var d = newForm.closest("dialog");
                if (d) d.close();
                send.disabled = false;
                say(e.message, "error");
            }
        });
    }

    /* ---- ticket ---- */
    var form = document.getElementById("ticket-form");
    if (!form) return;
    var futures = JSON.parse(document.getElementById("futures-data").textContent || "[]");
    var cfdClasses = JSON.parse(document.getElementById("cfd-classes").textContent || "{}");
    var box = document.getElementById("ticket-preview");
    var submit = document.getElementById("ticket-submit");
    var rootSel = document.getElementById("f-root");
    var contractSel = document.getElementById("f-contract");
    var levInput = document.getElementById("f-leverage");
    var levHint = document.getElementById("f-leverage-hint");
    var lastQuote = null, timer = null, searchTimer = null, seq = 0;
    var ticketPosition = null;      // identifiant de position de l'aperçu : garde les frais estimés stables entre deux rafraîchissements

    function kind() { return form.querySelector('input[name="instrument_kind"]:checked').value; }
    function option(sel, label, value) {
        var o = document.createElement("option");
        o.value = value;
        o.textContent = label;
        sel.appendChild(o);
    }
    function fillContracts() {
        contractSel.textContent = "";
        var f = futures.filter(function (x) { return x.root === rootSel.value; })[0];
        (f ? f.contracts : []).forEach(function (c) { option(contractSel, c.label + " (" + c.expiry + ")", c.year + "-" + c.month); });
    }
    function fillRoots() {
        rootSel.textContent = "";
        futures.forEach(function (f) { option(rootSel, f.root + " — " + f.name, f.root); });
        fillContracts();
    }
    function applyKind() {
        var k = kind();
        form.querySelectorAll("[data-kinds]").forEach(function (el) {
            el.hidden = el.getAttribute("data-kinds").split(" ").indexOf(k) === -1;
        });
        var cash = k === "equity" || k === "etf";
        var short = form.querySelector('input[name="side"][value="short"]');
        short.disabled = cash;
        short.parentElement.title = cash ? tr("fund_side_short_blocked") : "";
        if (cash) form.querySelector('input[name="side"][value="long"]').checked = true;
    }
    function applyStrategy() {
        var opt = form.strategy_id.options[form.strategy_id.selectedIndex];
        form.date.min = opt ? opt.getAttribute("data-opened") : "";
    }
    function present(v) { return v !== null && v !== undefined && String(v).trim() !== ""; }

    /* Requête du ticket, ou null tant qu'il manque l'identification de l'instrument. */
    function request() {
        var fd = new FormData(form), k = kind();
        var req = { strategy_id: fd.get("strategy_id"), action: "open", instrument_kind: k, side: fd.get("side"),
                    date: fd.get("date") || undefined, fees_mode: fd.get("fees_mode"), spec: {} };
        if (k === "future") {
            if (!present(fd.get("root")) || !present(fd.get("contract"))) return null;
            var ym = String(fd.get("contract")).split("-");
            req.spec.root = fd.get("root");
            req.spec.year = Number(ym[0]);
            req.spec.month = Number(ym[1]);
            req.quantity = fd.get("contracts");
        } else {
            if (!present(fd.get("symbol"))) return null;
            req.symbol = String(fd.get("symbol")).trim();
        }
        if (k === "equity" || k === "etf") {
            req.quantity = fd.get("quantity");
            req.amount = fd.get("amount");
        }
        if (k === "cfd") {
            req.quantity = fd.get("units");
            req.spec.leverage = fd.get("leverage");
        }
        if (k === "future" || k === "cfd") {
            req.spec.stop = fd.get("stop");
            req.spec.target = fd.get("target");
        }
        if (ticketPosition) req.position_id = ticketPosition;
        if (fd.get("manual_price") && present(fd.get("price"))) req.price = fd.get("price");
        if (req.fees_mode === "manual") req.fees = fd.get("fees");
        return req;
    }

    function row(list, label, value) {
        var dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = label;
        dd.textContent = value;
        dd.className = "pk-mono";
        list.appendChild(dt);
        list.appendChild(dd);
    }
    function messages(cls, title, items) {
        if (!items || !items.length) return;
        var div = document.createElement("div"), strong = document.createElement("strong"), ul = document.createElement("ul");
        div.className = "banner " + cls;
        strong.textContent = title;
        items.forEach(function (m) { var li = document.createElement("li"); li.textContent = m; ul.appendChild(li); });
        div.appendChild(strong);
        div.appendChild(ul);
        box.appendChild(div);
    }
    function renderEmpty() {
        lastQuote = null;
        box.textContent = "";
        var p = document.createElement("p");
        p.className = "hint";
        p.textContent = tr("fund_preview_empty");
        box.appendChild(p);
        submit.disabled = true;
    }
    function renderPreview(q) {
        lastQuote = q;
        box.textContent = "";
        var p = q.preview;
        if (p) {
            var dl = document.createElement("dl");
            dl.className = "fund-preview-list";
            row(dl, tr("fund_pv_day"), p.exec_day + (p.provisional ? " · " + tr("fund_pv_provisional") : ""));
            row(dl, tr("fund_pv_price"), p.price === null ? "—" :
                num(p.price, 4) + " " + p.currency + (p.price_source === "manual" ? " (" + tr("fund_pv_manual") + ")" : ""));
            if (p.currency !== "EUR") row(dl, tr("fund_pv_fx"), num(p.fx_rate, 5));
            row(dl, tr("fund_pv_quantity"), num(p.quantity, 4));
            if (p.notional_local !== null) {
                row(dl, tr("fund_pv_notional"), num(p.notional_local, 2) + " " + p.currency +
                    (p.currency !== "EUR" ? " ≈ " + money(p.notional_base) : ""));
            }
            if (p.margin_required !== null) row(dl, tr("fund_pv_margin"), money(p.margin_required));
            row(dl, tr("fund_pv_fees"), money(p.fees.total));
            row(dl, tr("fund_pv_cash_after"), money(p.cash_after));
            row(dl, tr("fund_pv_power_after"), money(p.buying_power_after));
            box.appendChild(dl);
            ticketPosition = p.position_id;
            if (p.fees.source === "estimated") {
                var detail = document.createElement("p");
                detail.className = "hint";
                detail.textContent = tr("fund_pv_fees_detail", "", { c: money(p.fees.commission), s: money(p.fees.spread), x: money(p.fees.fx) });
                box.appendChild(detail);
            }
            if (p.leverage_cap) {
                levInput.max = p.leverage_cap;
                levHint.textContent = tr("fund_leverage_cap", "", { cap: p.leverage_cap }) +
                    (cfdClasses[p.underlying_class] ? " · " + cfdClasses[p.underlying_class] : "");
            }
        }
        messages("banner-error", tr("fund_blocking_title"), q.blocking);
        messages("banner-warning", tr("fund_warnings_title"), q.warnings);
        submit.disabled = !q.ok;
    }
    function renderError(message) {
        renderPreview({ ok: false, blocking: [message], warnings: [], preview: null });
    }

    async function refresh() {
        var mine = ++seq, req = request();
        if (!req) { renderEmpty(); return; }
        try {
            var q = await call("/api/fund/quote", "POST", req);
            if (mine === seq) renderPreview(q);
        } catch (e) {
            if (mine === seq) renderError(e.message);
        }
    }
    function schedule() {
        window.clearTimeout(timer);
        submit.disabled = true;
        timer = window.setTimeout(refresh, 300);
    }

    /* Suggestions de tickers (Yahoo) pendant la saisie. */
    form.symbol.addEventListener("input", function () {
        window.clearTimeout(searchTimer);
        var q = form.symbol.value.trim();
        if (q.length < 2) return;
        searchTimer = window.setTimeout(async function () {
            try {
                var res = await fetch("/api/fund/instruments/search?q=" + encodeURIComponent(q) + "&kind=" + kind());
                var data = await res.json();
                var list = document.getElementById("f-symbol-list");
                list.textContent = "";
                (data.results || []).forEach(function (r) {
                    var o = document.createElement("option");
                    o.value = r.symbol;
                    o.label = r.name + (r.exchange ? " · " + r.exchange : "");
                    list.appendChild(o);
                });
            } catch (e) { /* suggestions facultatives */ }
        }, 250);
    });

    form.addEventListener("input", schedule);
    form.addEventListener("change", function (ev) {
        if (ev.target.name === "instrument_kind") applyKind();
        if (ev.target.name === "root") fillContracts();
        if (ev.target.name === "strategy_id") applyStrategy();
        if (ev.target.id === "f-manual-price") form.price.disabled = !ev.target.checked;
        if (ev.target.name === "fees_mode") form.fees.disabled = form.fees_mode.value !== "manual";
        schedule();
    });
    form.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        if (!lastQuote || !lastQuote.ok) return;
        var req = request(), p = lastQuote.preview;
        if (!req) return;
        req.position_id = p.position_id;
        if (p.fees.source === "estimated") req.fee_seed = p.fees.seed;
        submit.disabled = true;
        try {
            await call("/api/fund/strategies/" + encodeURIComponent(req.strategy_id) + "/orders", "POST", req);
            window.location.href = "/simulate?strategy=" + encodeURIComponent(req.strategy_id) + "&placed=1";
        } catch (e) {
            say((e.blocking || [e.message]).join(" · "), "error");
            submit.disabled = false;
        }
    });

    fillRoots();
    applyKind();
    applyStrategy();
    renderEmpty();
})();
