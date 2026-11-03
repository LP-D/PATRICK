/* Page /resultats : collage de la newsletter, confirmation, instantané, réglages, cartes d'étude au clic, verdict FDR, saisie manuelle.
   Tout se passe par délégation d'événements (les fragments arrivent après le chargement). Les travaux longs tournent côté serveur et
   se suivent par /api/earnings/status. */
(function () {
    "use strict";
    var I = window.I18N || {};
    var STORE = "patrick-earn-enabled";

    function fmt(template, values) {
        return (template || "").replace(/\{(\w+)\}/g, function (_, k) { return values && values[k] !== undefined ? values[k] : ""; });
    }
    function $(id) { return document.getElementById(id); }
    function say(id, text) { var el = $(id); if (el) el.textContent = text || ""; }
    function announce(host) { document.dispatchEvent(new CustomEvent("patrick:content", { detail: host })); }
    function post(url, body) {
        return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
            .then(function (r) {
                return r.json().catch(function () { return {}; }).then(function (data) {
                    if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
                    return data;
                });
            });
    }
    function poll(kind, onTick) {
        return new Promise(function (resolve, reject) {
            var timer = setInterval(function () {
                fetch("/api/earnings/status", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (all) {
                    var s = all[kind] || {};
                    if (s.running) { if (onTick) onTick(s); return; }
                    clearInterval(timer);
                    if (s.error) reject(new Error(s.error)); else resolve(s.result || {});
                }).catch(function (e) { clearInterval(timer); reject(e); });
            }, 1200);
        });
    }
    function fail(id, e) { say(id, fmt(I.earn_error_generic, { e: e && e.message ? e.message : String(e) })); }

    // ---------------------------------------------------------------------------------------------------- collage
    function onParse(form) {
        var btn = $("earn-parse");
        btn.disabled = true;
        post("/api/earnings/parse", { text: form.elements.text.value, anchor: form.elements.anchor.value }).then(function () {
            return poll("parse", function (s) { say("earn-parse-status", fmt(I.earn_parse_running, { done: s.done, total: s.total })); });
        }).then(function (res) {
            btn.disabled = false;
            if (!res.batch_id) { say("earn-parse-status", I.earn_parse_none); return; }
            say("earn-parse-status", fmt(I.earn_parse_done, { n: "" }));
            window.location.href = "/resultats?batch=" + res.batch_id;
        }).catch(function (e) { btn.disabled = false; fail("earn-parse-status", e); });
    }

    // ------------------------------------------------------------------------------------------------ confirmation
    function onConfirm(form) {
        var edits = [];
        form.querySelectorAll("tbody tr").forEach(function (tr) {
            edits.push({
                item_id: parseInt(tr.dataset.item, 10),
                include: tr.querySelector("[name=include]").checked,
                symbol: tr.querySelector("[name=symbol]").value,
                adr_symbol: tr.querySelector("[name=adr_symbol]").value,
                timing: tr.querySelector("[name=timing]").value
            });
        });
        if (!edits.length) { say("earn-process-status", I.earn_confirm_none); return; }
        var submit = form.querySelector("[type=submit]");
        submit.disabled = true;
        post("/api/earnings/confirm", { batch_id: parseInt(form.dataset.batch, 10), edits: edits }).then(function () {
            return poll("process", function (s) { say("earn-process-status", fmt(I.earn_process_running, { done: s.done, total: s.total, label: s.label })); });
        }).then(function (res) {
            var ing = res.ingest || {};
            var msg = fmt(I.earn_process_done, { events: ing.events || 0, symbols: ing.symbols || 0 });
            if (ing.failed && ing.failed.length) msg += " " + fmt(I.earn_process_failed, { names: ing.failed.map(function (f) { return f.symbol; }).join(", ") });
            say("earn-process-status", msg);
            setTimeout(function () { window.location.reload(); }, 1500);
        }).catch(function (e) { submit.disabled = false; fail("earn-process-status", e); });
    }

    // --------------------------------------------------------------------------------------------------- réglages
    function parseDrift(text) {
        return (text || "").split(",").map(function (p) { return p.trim(); }).filter(Boolean).map(function (p) {
            var m = p.match(/^(-?\d+)\s*-\s*(\d+)$/);
            if (!m) throw new Error(p);
            return [parseInt(m[1], 10), parseInt(m[2], 10)];
        });
    }
    function onConfig(form) {
        var f = form.elements, body;
        try {
            body = {
                model: f.model.value, est_window: [parseInt(f.est_lo.value, 10), parseInt(f.est_hi.value, 10)], est_exclude: parseInt(f.est_exclude.value, 10),
                reaction: f.reaction.value, run_up: [parseInt(f.run_lo.value, 10), parseInt(f.run_hi.value, 10)],
                short_post: [parseInt(f.post_lo.value, 10), parseInt(f.post_hi.value, 10)], drift_windows: parseDrift(f.drift.value), test: f.test.value,
                winsorize: parseFloat(f.winsorize.value), min_events: parseInt(f.min_events.value, 10), big_move_sigma: parseFloat(f.big_move_sigma.value)
            };
        } catch (e) { say("earn-config-status", fmt(I.earn_cfg_error, { e: e.message })); return; }
        post("/api/earnings/config", body).then(function (res) {
            say("earn-config-status", I.earn_cfg_saved + (res.needs_recompute ? " " + I.earn_cfg_recompute_hint : ""));
            $("earn-recompute").hidden = !res.needs_recompute;
            document.querySelectorAll(".earn-result").forEach(function (el) { el.innerHTML = ""; });
        }).catch(function (e) { say("earn-config-status", fmt(I.earn_cfg_error, { e: e.message })); });
    }
    function onRecompute(btn) {
        btn.disabled = true;
        post("/api/earnings/recompute").then(function () {
            return poll("recompute", function (s) { say("earn-config-status", fmt(I.earn_recompute_running, { done: s.done, total: s.total, label: s.label })); });
        }).then(function (res) {
            btn.disabled = false;
            btn.hidden = true;
            say("earn-config-status", fmt(I.earn_recompute_done, { events: res.events || 0 }));
        }).catch(function (e) { btn.disabled = false; fail("earn-config-status", e); });
    }

    function onSnapshot(btn) {
        btn.disabled = true;
        post("/api/earnings/snapshot").then(function () {
            return poll("snapshot", function (s) { say("earn-snapshot-status", fmt(I.earn_snapshot_running, { done: s.done, total: s.total })); });
        }).then(function (res) {
            btn.disabled = false;
            say("earn-snapshot-status", fmt(I.earn_snapshot_done, { consensus: res.consensus || 0, short: res.short || 0, options: res.options || 0 }));
        }).catch(function (e) { btn.disabled = false; fail("earn-snapshot-status", e); });
    }

    // ------------------------------------------------------------------------------------------------- bibliothèque
    function enabledMap() { try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch (e) { return {}; } }
    function saveEnabled(map) { try { localStorage.setItem(STORE, JSON.stringify(map)); } catch (e) { /* stockage indisponible : réglage non mémorisé */ } }
    function applyEnabled(root) {
        var map = enabledMap();
        (root || document).querySelectorAll(".earn-card").forEach(function (card) {
            var box = card.querySelector(".earn-enable");
            var stored = map[card.dataset.study];
            box.checked = stored === undefined ? card.dataset.defaultOn === "1" : !!stored;
            card.classList.toggle("earn-card-off", !box.checked);
        });
    }
    function cardUrl(card, force) {
        var url = card.querySelector(".earn-run").dataset.url;
        card.querySelectorAll("[data-param]").forEach(function (el) {
            var v = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value;
            url += "&p_" + encodeURIComponent(el.dataset.param) + "=" + encodeURIComponent(v);
        });
        return force ? url + "&force=1" : url;
    }
    function runCard(card, force) {
        var host = card.querySelector(".earn-result"), btn = card.querySelector(".earn-run");
        btn.disabled = true;
        host.textContent = I.earn_card_running;
        return fetch(cardUrl(card, force), { credentials: "same-origin" }).then(function (r) {
            return r.text().then(function (html) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                host.innerHTML = html;
                announce(host);
                card.querySelector(".earn-force").hidden = false;
            });
        }).catch(function (e) { host.textContent = fmt(I.earn_card_error, { e: e.message }); })
            .then(function () { btn.disabled = false; });
    }
    function computeAll(btn) {
        var cards = Array.prototype.filter.call(document.querySelectorAll(".earn-card"), function (c) { return c.querySelector(".earn-enable").checked; });
        btn.disabled = true;
        var i = 0;
        (function next() {
            if (i >= cards.length) { btn.disabled = false; say("earn-compute-status", fmt(I.earn_compute_all_done, { n: cards.length })); return; }
            var card = cards[i++];
            say("earn-compute-status", fmt(I.earn_compute_all_running, { done: i, total: cards.length, label: card.dataset.study }));
            runCard(card, false).then(next);
        })();
    }
    function goScope(value) {
        var batch = ($("earn-library-card") || {}).dataset ? $("earn-library-card").dataset.batch : "";
        window.location.href = "/resultats?scope=" + encodeURIComponent(value) + (batch ? "&batch=" + encodeURIComponent(batch) : "");
    }

    // ------------------------------------------------------------------------------------------------- délégation
    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (form.id === "earn-paste") { event.preventDefault(); onParse(form); }
        else if (form.id === "earn-confirm") { event.preventDefault(); onConfirm(form); }
        else if (form.id === "earn-config") { event.preventDefault(); onConfig(form); }
        else if (form.id === "earn-manual") {
            event.preventDefault();
            post("/api/earnings/manual-dates", { symbol: form.dataset.symbol, text: form.elements.text.value }).then(function (res) {
                say("earn-manual-status", fmt(I.earn_manual_done, { added: res.added, events: res.events }));
                setTimeout(function () { window.location.reload(); }, 1200);
            }).catch(function (e) { say("earn-manual-status", fmt(I.earn_manual_error, { e: e.message })); });
        }
    });
    document.addEventListener("click", function (event) {
        var t = event.target.closest ? event.target : event.target.parentElement;
        var run = t.closest && t.closest(".earn-run");
        if (run && !run.disabled) { runCard(run.closest(".earn-card"), false); return; }
        var force = t.closest && t.closest(".earn-force");
        if (force) { runCard(force.closest(".earn-card"), true); return; }
        var id = (t.closest && t.closest("button")) ? t.closest("button").id : "";
        if (id === "earn-snapshot") onSnapshot($(id));
        else if (id === "earn-recompute") onRecompute($(id));
        else if (id === "earn-compute-all") computeAll($(id));
        else if (id === "earn-ledger-run") {
            var btn = $(id), host = $("earn-ledger");
            fetch(btn.dataset.url, { credentials: "same-origin" }).then(function (r) { return r.text(); }).then(function (html) { host.innerHTML = html; announce(host); });
        }
    });
    document.addEventListener("change", function (event) {
        var el = event.target;
        if (el.classList && el.classList.contains("earn-enable")) {
            var card = el.closest(".earn-card"), map = enabledMap();
            map[card.dataset.study] = el.checked;
            saveEnabled(map);
            card.classList.toggle("earn-card-off", !el.checked);
        } else if (el.id === "earn-scope") { goScope(el.value); }
    });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && event.target.id === "earn-scope-symbol" && event.target.value.trim()) { event.preventDefault(); goScope("symbol:" + event.target.value.trim()); }
    });
    document.addEventListener("patrick:content", function (event) {
        var host = event.target && event.target.querySelector ? event.target : (event.detail || document);
        if (host && host.querySelector && host.querySelector(".earn-card")) applyEnabled(host);
    });
    document.addEventListener("DOMContentLoaded", function () { applyEnabled(document); });
})();
