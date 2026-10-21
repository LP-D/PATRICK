/* Carnet de recherche : notes, hypothèses, résultats, décisions liés à une cible, un horizon, un run. Utilisé par la page /carnet et par la section
   « Carnet » de l'analyse d'un run. Tout texte saisi s'affiche par textContent (jamais interprété comme du HTML).
   API : /api/carnet/notes (liste, création), /api/carnet/notes/{id} (modification), /api/carnet/stats. */
(function () {
    "use strict";
    var PK = window.PK;
    if (!PK) return;
    var T = PK.T, h = PK.h, int = PK.int, pct = PK.pct;
    var KINDS = ["hypothesis", "note", "result", "decision"], STATUSES = ["open", "confirmed", "refuted", "archived"];
    var STATUS_KIND = { open: "neutral", confirmed: "ok", refuted: "neg", archived: "neutral" };

    function post(url, body) {
        return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) {
            return r.json().then(function (b) { if (!r.ok) throw new Error(T("cn_err_" + (b.detail || "unknown"))); return b; });
        });
    }

    function card(n, onChange) {
        var chips = h("div", { class: "ra-chips" }, [PK.chip(T("cn_k_" + n.kind), n.kind === "hypothesis" ? "warn" : "neutral"), PK.chip(T("cn_s_" + n.status), STATUS_KIND[n.status])]);
        if (n.target) chips.appendChild(h("a", { class: "exp-chip-btn", href: "/targets/" + encodeURIComponent(n.target), text: n.target + (n.horizon ? " · h" + n.horizon : "") }));
        if (n.run_id) chips.appendChild(h("a", { class: "exp-chip-btn", href: "/runs/" + encodeURIComponent(n.run_id) + "/analyse", text: n.run_id }));
        if (n.kind === "hypothesis" && n.before_run !== null && n.before_run !== undefined) chips.appendChild(PK.chip(n.before_run ? T("cn_before_run") : T("cn_after_run"), n.before_run ? "ok" : "warn"));
        n.tags.forEach(function (t) { chips.appendChild(h("span", { class: "exp-chip", text: "#" + t })); });
        var body = h("div", { class: "cn-body" }, [h("strong", { text: n.title }), n.body ? h("p", { class: "cn-text", text: n.body }) : null]);
        var meta = h("p", { class: "hint", "data-keep": "1", text: T("cn_created", { d: (n.created_at || "").slice(0, 16) }) + (n.revisions ? " · " + T("cn_revised", { n: n.revisions, d: (n.updated_at || "").slice(0, 16) }) : "") });
        var actions = h("div", { class: "ra-controls" }), box = null;
        function fail(e) { if (box) box.remove(); box = h("p", { class: "banner banner-error", role: "alert", text: e.message }); actions.parentNode.appendChild(box); }
        if (n.kind === "hypothesis" && n.status === "open") {
            [["confirmed", "cn_confirm"], ["refuted", "cn_refute"]].forEach(function (p) {
                var b = h("button", { type: "button", class: "btn-secondary", text: T(p[1]) });
                b.addEventListener("click", function () { post("/api/carnet/notes/" + n.note_id, { status: p[0] }).then(onChange).catch(function (e) { fail(e); }); });
                actions.appendChild(b);
            });
        }
        if (n.status !== "archived") {
            var arch = h("button", { type: "button", class: "btn-secondary", text: T("cn_archive") });
            arch.addEventListener("click", function () { post("/api/carnet/notes/" + n.note_id, { status: "archived" }).then(onChange).catch(function (e) { fail(e); }); });
            actions.appendChild(arch);
        }
        return h("article", { class: "cn-note cn-" + n.status }, [chips, body, meta, actions]);
    }

    function form(defaults, onSaved) {
        defaults = defaults || {};
        var kind = PK.select(KINDS.map(function (k) { return { value: k, label: T("cn_k_" + k) }; }), defaults.kind || "hypothesis", function () {}, T("cn_f_kind"));
        var title = h("input", { type: "text", class: "ra-num cn-wide", maxlength: 160, placeholder: T("cn_f_title"), "aria-label": T("cn_f_title") });
        var text = h("textarea", { class: "cn-textarea", rows: 3, maxlength: 8000, placeholder: T("cn_f_body"), "aria-label": T("cn_f_body") });
        var tags = h("input", { type: "text", class: "ra-num cn-wide", placeholder: T("cn_f_tags"), "aria-label": T("cn_f_tags") });
        var target = h("input", { type: "text", class: "ra-num", value: defaults.target || "", placeholder: T("ag_c_target"), "aria-label": T("ag_c_target"), disabled: !!defaults.lock });
        var horizon = h("input", { type: "number", class: "ra-num", value: defaults.horizon || "", min: 1, placeholder: T("ag_c_horizon"), "aria-label": T("ag_c_horizon"), disabled: !!defaults.lock });
        var run = h("input", { type: "text", class: "ra-num cn-wide", value: defaults.run_id || "", placeholder: T("cn_f_run"), "aria-label": T("cn_f_run"), disabled: !!defaults.lock });
        var msg = h("div", {});
        var save = h("button", { type: "submit", class: "primary", text: T("cn_save") });
        var f = h("form", { class: "cn-form" }, [h("div", { class: "ra-controls" }, [kind, title]), text, h("div", { class: "ra-controls" }, [tags, target, horizon, run]), h("div", { class: "ra-controls" }, [save]), msg]);
        f.addEventListener("submit", function (ev) {
            ev.preventDefault();
            save.disabled = true;
            post("/api/carnet/notes", { kind: kind.value, title: title.value, body: text.value, tags: tags.value, target: target.value || null, horizon: horizon.value ? +horizon.value : null, run_id: run.value || null })
                .then(function () { save.disabled = false; title.value = ""; text.value = ""; tags.value = ""; PK.clear(msg); onSaved(); })
                .catch(function (e) { save.disabled = false; PK.clear(msg).appendChild(h("p", { class: "banner banner-error", role: "alert", text: e.message })); });
        });
        return f;
    }

    // ================================================================ page /carnet
    var root = document.getElementById("cn-root");
    if (root) {
        var st = { q: "", kind: "", status: "", tag: "", archived: false };
        var list = document.getElementById("cn-list"), filters = document.getElementById("cn-filters"), kpis = document.getElementById("cn-kpis");
        var load = function () {
            PK.fetchJSON("/api/carnet/stats").then(function (s) {
                PK.clear(kpis);
                var hy = s.hypotheses;
                kpis.appendChild(PK.kpi(T("cn_k_total"), int(Object.keys(s.by_kind).reduce(function (a, k) { return a + s.by_kind[k]; }, 0)), T("cn_k_total_sub"), "neutral"));
                kpis.appendChild(PK.kpi(T("cn_k_hyp"), int((hy.open || 0) + (hy.confirmed || 0) + (hy.refuted || 0)), T("cn_k_hyp_sub", { o: hy.open || 0, c: hy.confirmed || 0, r: hy.refuted || 0 }), "neutral"));
                kpis.appendChild(PK.kpi(T("cn_k_rate"), s.confirmation_rate === null ? "—" : pct(s.confirmation_rate, 0), T("cn_k_rate_sub", { n: s.decided }), s.confirmation_rate !== null && s.confirmation_rate > 0.8 && s.decided >= 5 ? "warning" : "neutral"));
            });
            var qs = PK.qs({ q: st.q, kind: st.kind, status: st.status, tag: st.tag, archived: st.archived ? 1 : "" });
            PK.fetchJSON("/api/carnet/notes" + (qs ? "?" + qs : "")).then(function (d) {
                PK.clear(list);
                if (!d.notes.length) list.appendChild(PK.empty(T("cn_none")));
                d.notes.forEach(function (n) { list.appendChild(card(n, load)); });
                list.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
            }).catch(function (e) { PK.clear(list).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); });
        };
        var s = h("input", { type: "search", placeholder: T("cn_filter_q"), "aria-label": T("cn_filter_q") });
        s.addEventListener("input", function () { st.q = s.value; load(); });
        filters.appendChild(s);
        filters.appendChild(PK.select([{ value: "", label: T("ah_all_status") }].concat(KINDS.map(function (k) { return { value: k, label: T("cn_k_" + k) }; })), "", function (v) { st.kind = v; load(); }, T("cn_f_kind")));
        filters.appendChild(PK.select([{ value: "", label: T("ah_all_status") }].concat(STATUSES.map(function (k) { return { value: k, label: T("cn_s_" + k) }; })), "", function (v) { st.status = v; load(); }, T("ah_c_status")));
        var tg = h("input", { type: "text", class: "ra-num", placeholder: "#tag", "aria-label": "tag" });
        tg.addEventListener("change", function () { st.tag = tg.value.replace("#", ""); load(); });
        filters.appendChild(tg);
        var cb = h("input", { type: "checkbox" });
        cb.addEventListener("change", function () { st.archived = cb.checked; load(); });
        filters.appendChild(h("label", { class: "ra-control" }, [cb, h("span", { text: T("cn_show_archived") })]));
        document.getElementById("cn-form").appendChild(form({}, load));
        load();
    }

    // ================================================================ section « Carnet » d'une analyse de run
    if (window.RA && window.RA.render) {
        window.RA.render.notes = function (m, d) {
            var host = h("div", {});
            var draw = function (nd) {
                PK.clear(host);
                if (!nd.notes.length) host.appendChild(PK.empty(T("cn_none_run")));
                nd.notes.forEach(function (n) { host.appendChild(card(n, reload)); });
                if (nd.related.length) {
                    host.appendChild(h("h3", { text: T("cn_related", { n: nd.related.length }) }));
                    nd.related.forEach(function (n) { host.appendChild(card(n, reload)); });
                }
                host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
            };
            var reload = function () { window.RA.api("notes").then(draw); };
            m.appendChild(form({ target: d.target, horizon: d.horizon, run_id: d.run_id, lock: true }, reload));
            m.appendChild(host);
            draw(d);
        };
    }
})();
