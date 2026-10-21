/* Notification de fin de run (bouton cloche de la barre supérieure). Opt-in, mémorisé dans le navigateur ; aucun appel réseau tant qu'il est coupé.
   Surveille /api/run-state : un run vu en cours ou en file qui n'y figure plus est terminé (ou retiré de la file : /runs/{id}/status répond alors 404,
   rien n'est signalé). Notification du système si le navigateur l'autorise, bandeau dans la page dans tous les cas. Texte par textContent. */
(function () {
    "use strict";
    var btn = document.getElementById("notify-toggle");
    if (!btn) return;
    var I18N = window.I18N || {}, KEY = "patrick-notify", POLL_VISIBLE_MS = 15000, POLL_HIDDEN_MS = 60000, MAX_TOASTS = 3;
    var SESSION_KEY = "patrick-notify-known", known = null, timer = null, busy = false;
    // Les pages sont rechargées à chaque navigation : l'état vu au dernier passage est gardé pour la durée de l'onglet, sinon un run
    // terminé entre deux pages ne serait jamais signalé.
    function loadKnown() { try { var raw = sessionStorage.getItem(SESSION_KEY); return raw ? JSON.parse(raw) : null; } catch (e) { return null; } }
    function saveKnown() { try { if (known) sessionStorage.setItem(SESSION_KEY, JSON.stringify(known)); else sessionStorage.removeItem(SESSION_KEY); } catch (e) { /* sans stockage : base reprise à chaque page */ } }

    function T(key, params) {
        var text = I18N[key] || key;
        Object.keys(params || {}).forEach(function (k) { text = text.split("{" + k + "}").join(String(params[k])); });
        return text;
    }
    function stored() { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; } }
    function remember(on) { try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (e) { /* stockage indisponible : l'état reste celui de la page */ } }
    function denied() { return typeof Notification !== "undefined" && Notification.permission === "denied"; }

    var enabled = stored();
    function paint() {
        btn.setAttribute("aria-pressed", enabled ? "true" : "false");
        var label = enabled ? (denied() ? T("nt_toggle_denied") : T("nt_toggle_on")) : T("nt_toggle_off");
        btn.setAttribute("aria-label", label);
        btn.title = label;
        btn.classList.toggle("is-on", enabled);
        var on = btn.querySelector(".icon-bell-on"), off = btn.querySelector(".icon-bell-off");
        if (on) on.hidden = !enabled;
        if (off) off.hidden = enabled;
    }

    // ---- bandeau dans la page
    function toast(text, href, kind) {
        var host = document.getElementById("run-toasts");
        if (!host) {
            host = document.createElement("div");
            host.id = "run-toasts";
            host.className = "run-toasts";
            host.setAttribute("role", "status");
            host.setAttribute("aria-live", "polite");
            document.body.appendChild(host);
        }
        var el = document.createElement("div");
        el.className = "run-toast run-toast-" + (kind || "ok");
        var span = document.createElement("span");
        span.textContent = text;
        el.appendChild(span);
        if (href) {
            var a = document.createElement("a");
            a.href = href;
            a.textContent = T("nt_open");
            el.appendChild(a);
        }
        var x = document.createElement("button");
        x.type = "button";
        x.className = "run-toast-close";
        x.setAttribute("aria-label", T("nt_close"));
        x.textContent = "×";
        x.addEventListener("click", function () { el.remove(); });
        el.appendChild(x);
        host.appendChild(el);
        setTimeout(function () { if (el.parentNode) el.remove(); }, 15000);
    }
    function system(title, body, href) {
        if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
        try {
            var n = new Notification(title, { body: body, tag: href || title });
            n.onclick = function () { window.focus(); if (href) window.location.href = href; n.close(); };
        } catch (e) { /* certains webviews refusent le constructeur : le bandeau suffit */ }
    }
    function announce(run) {
        var failed = run.status === "error", name = run.name || run.id;
        var title = T(failed ? "nt_error" : "nt_done", { name: name });
        var body = T(failed ? "nt_body_error" : "nt_body_done", { kind: String(run.kind || "").toUpperCase() });
        var href = "/runs/" + encodeURIComponent(run.id);
        toast(title, href, failed ? "error" : "ok");
        system(title, body, href);
    }

    // ---- surveillance
    function ids(state) {
        var out = {};
        if (state.active_run) out[state.active_run.id] = state.active_run;
        (state.queue || []).forEach(function (r) { out[r.id] = r; });
        return out;
    }
    function poll() {
        if (!enabled || busy) return;
        busy = true;
        fetch("/api/run-state", { headers: { Accept: "application/json" } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (state) {
            if (!state) return null;
            var now = ids(state), gone = known ? Object.keys(known).filter(function (id) { return !now[id]; }) : [];
            var previous = known || {};
            known = {};
            Object.keys(now).forEach(function (id) { known[id] = { id: id, name: now[id].name, kind: now[id].kind }; });
            saveKnown();
            return Promise.all(gone.map(function (id) {
                return fetch("/runs/" + encodeURIComponent(id) + "/status", { headers: { Accept: "application/json" } }).then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (s) { return s && (s.status === "done" || s.status === "error") ? { id: id, name: (previous[id] || {}).name, kind: (previous[id] || {}).kind, status: s.status } : null; })
                    .catch(function () { return null; });
            }));
        }).then(function (finished) {
            if (!finished) return;
            finished = finished.filter(Boolean);
            finished.slice(0, MAX_TOASTS).forEach(announce);
            if (finished.length > MAX_TOASTS) toast(T("nt_more", { n: finished.length - MAX_TOASTS }), "/runs", "ok");
        }).catch(function () { /* serveur injoignable : on réessaie au prochain tour */ }).then(function () { busy = false; });
    }
    function schedule() {
        if (timer) { clearTimeout(timer); timer = null; }
        if (!enabled) return;
        timer = setTimeout(function () { poll(); schedule(); }, document.hidden ? POLL_HIDDEN_MS : POLL_VISIBLE_MS);
    }
    document.addEventListener("visibilitychange", function () { if (enabled && !document.hidden) { poll(); schedule(); } });

    btn.addEventListener("click", function () {
        enabled = !enabled;
        remember(enabled);
        known = null;
        saveKnown();
        if (enabled) {
            if (typeof Notification !== "undefined" && Notification.permission === "default") {
                try { Promise.resolve(Notification.requestPermission()).then(paint); } catch (e) { /* ancien navigateur : rappel synchrone ignoré */ }
            }
            toast(T("nt_test"), null, "ok");
            poll();
        }
        paint();
        schedule();
    });

    paint();
    if (enabled) { known = loadKnown(); poll(); schedule(); }
})();
