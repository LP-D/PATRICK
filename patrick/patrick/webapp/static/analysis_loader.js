/* Chargeur commun des pages d'analyse (/runs/{id}/analyse pour un run ML, DL ou RL) : appelle /api/runs/{id}/analysis/{section} quand la
   section approche de l'écran et confie le rendu à `RA.render[section]`, enregistré par `run_analysis*.js` (ML, DL) ou `rl_analysis.js`. */
(function () {
    "use strict";
    var PK = window.PK;
    var root = document.getElementById("ra-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, pct = PK.pct, isNum = PK.isNum;
    var RUN = root.getAttribute("data-run-id");
    var RA = window.RA = { render: {}, data: {}, api: null, mount: null, reload: null, helpers: {} };

    var EMBED = null;
    (function () {
        var el = document.getElementById("ra-embed");
        if (el) { try { EMBED = JSON.parse(el.textContent); } catch (e) { EMBED = null; } }
    })();
    RA.api = function (section, params) {
        if (EMBED) {                                   // rapport exporté : les données de chaque section sont déjà dans la page
            if (PK.qs(params || {})) return Promise.reject(new Error(T("ra_offline")));
            return EMBED[section] ? Promise.resolve(EMBED[section]) : Promise.reject(new Error(T("ra_offline")));
        }
        return PK.fetchJSON("/api/runs/" + encodeURIComponent(RUN) + "/analysis/" + section + (params && Object.keys(params).length ? "?" + PK.qs(params) : ""));
    };
    RA.mount = function (name) { return root.querySelector('[data-ra-mount="' + name + '"]'); };

    function unavailable(name, d) {
        var key = "ra_reason_" + (d.reason || "unknown");
        var text = T(key);
        if (text === key) text = T("ra_reason_unknown");
        return PK.empty(text);
    }

    function skeleton() {
        var box = h("div", { class: "ra-skeleton", role: "status", "aria-busy": "true" });
        [100, 84, 92, 70].forEach(function (w) { box.appendChild(h("div", { class: "skeleton-line", style: { width: w + "%" } })); });
        return box;
    }

    function load(name) {
        var m = RA.mount(name);
        if (!m || m.getAttribute("data-state") === "loading" || m.getAttribute("data-state") === "done") return;
        m.setAttribute("data-state", "loading");
        PK.clear(m).appendChild(skeleton());
        RA.api(name).then(function (d) {
            RA.data[name] = d;
            PK.clear(m);
            if (!d || d.available === false) m.appendChild(unavailable(name, d || {}));
            else RA.render[name](m, d);
            m.setAttribute("data-state", "done");
            m.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));       // help.js replie les textes d'aide longs
        }).catch(function (err) {
            PK.clear(m);
            var retry = h("button", { type: "button", class: "btn-secondary", text: T("ra_retry") });
            retry.addEventListener("click", function () { m.removeAttribute("data-state"); load(name); });
            m.appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + (err && err.message ? err.message : "") }));
            m.appendChild(retry);
            m.removeAttribute("data-state");
        });
    }
    RA.reload = function (name) { var m = RA.mount(name); if (m) { m.removeAttribute("data-state"); load(name); } };

    // ---------------------------------------------------------------- aide commune
    function splitLabel(s) { return T("ra_split_" + s); }
    function stateFor(edge) { return edge === null ? "neutral" : (edge > 0.01 ? "ok" : (edge < -0.01 ? "warning" : "neutral")); }
    function majority(base) { return isNum(base) ? Math.max(base, 1 - base) : null; }
    function foldBands(P, folds) {
        (folds || []).forEach(function (f, i) {
            if (f.split === "holdout") PK.xband(P, PK.dateMs(f.start), PK.dateMs(f.end), { color: "var(--warn-soft)" });
            else if (i % 2 === 0) PK.xband(P, PK.dateMs(f.start), PK.dateMs(f.end), { color: "var(--neutral-soft)" });
        });
    }
    function foldLegend() {
        return PK.legend([{ color: "var(--neutral-soft)", label: T("ra_lg_fold_band") }, { color: "var(--warn-soft)", label: T("ra_lg_holdout_band") }]);
    }
    function row2(a, b) { return h("div", { class: "ra-grid-2" }, [a, b]); }
    function titled(title, node, hint) {
        return h("div", { class: "ra-block" }, [h("h3", { text: title }), hint ? PK.note(hint) : null, node]);
    }
    RA.helpers = { nearestIdx: nearestIdx, splitLabel: splitLabel, stateFor: stateFor, majority: majority, foldBands: foldBands, foldLegend: foldLegend, row2: row2, titled: titled };

    function nearestIdx(arr, v) {
        if (!arr.length) return -1;
        var lo = 0, hi = arr.length - 1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (arr[mid] < v) lo = mid; else hi = mid; }
        return Math.abs(arr[lo] - v) <= Math.abs(arr[hi] - v) ? lo : hi;
    }
    RA.helpers.nearestIdx = nearestIdx;
    // ---------------------------------------------------------------- démarrage
    var order = [].map.call(root.querySelectorAll("[data-ra-mount]"), function (n) { return n.getAttribute("data-ra-mount"); });
    var started = false, ahead = 900;
    // Une section se charge quand elle approche de l'écran (`ahead` pixels). Contrôle par position plutôt que par IntersectionObserver :
    // dans un onglet en arrière-plan le navigateur suspend l'observateur, la page resterait avec ses squelettes.
    function pending() {
        return order.filter(function (n) { var m = RA.mount(n); return m && RA.render[n] && !m.getAttribute("data-state"); });
    }
    function check() {
        var left = pending();
        left.forEach(function (n) {
            var r = RA.mount(n).getBoundingClientRect();
            if (r.top < window.innerHeight + ahead && r.bottom > -ahead) load(n);
        });
        return left.length;
    }
    function start() {
        if (started) return;
        started = true;
        load("overview");
        if (EMBED) { pending().forEach(load); return; }
        var timer = null;
        function soon() { if (timer) return; timer = setTimeout(function () { timer = null; check(); }, 80); }
        window.addEventListener("scroll", soon, { passive: true });
        window.addEventListener("resize", soon);
        check();
        var guard = setInterval(function () { if (!check()) clearInterval(guard); }, 1200);
        document.addEventListener("click", function (ev) {
            var a = ev.target.closest && ev.target.closest(".section-index a[href^='#']");
            if (!a) return;
            var sec = root.querySelector(a.getAttribute("href"));
            var mt = sec && sec.querySelector("[data-ra-mount]");
            if (mt && RA.render[mt.getAttribute("data-ra-mount")]) load(mt.getAttribute("data-ra-mount"));
        });
    }
    window.addEventListener("DOMContentLoaded", function () { setTimeout(start, 0); });
    if (document.readyState !== "loading") setTimeout(start, 0);
})();
