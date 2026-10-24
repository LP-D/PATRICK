/* Page /journal : journal de prédictions chaîné (horodatage, empreinte du modèle, chaîne de hachage), vérification, réussite et calibration live par couple,
   écarts avec la table des prédictions, liste des lignes. Données : /api/journal/overview, /api/journal/entries, /api/journal/verify, POST /api/journal/seal. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("aj-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var st = { target: "", offset: 0, per: 100 };

    function short(x) { return x ? String(x).slice(0, 10) : "—"; }
    function kpis(d) {
        var box = PK.clear(document.getElementById("aj-kpis"));
        box.appendChild(PK.kpi(T("aj_k_entries"), int(d.n_entries), T("aj_k_entries_sub", { s: int(d.n_signals), o: int(d.n_outcomes) }), "neutral"));
        box.appendChild(PK.kpi(T("aj_k_span"), d.first_at ? d.first_at.slice(0, 10) : "—", d.last_at ? T("aj_k_span_sub", { d: d.last_at.slice(0, 16) }) : T("aj_k_empty"), "neutral"));
        box.appendChild(PK.kpi(T("aj_k_models"), int(d.n_models), T("aj_k_models_sub"), "neutral"));
        box.appendChild(PK.kpi(T("aj_k_backfill"), int(d.n_backfill), T("aj_k_backfill_sub"), d.n_backfill ? "warning" : "neutral"));
        box.appendChild(PK.kpi(T("aj_k_div"), int(d.n_divergences), T("aj_k_div_sub", { n: int(d.n_checked) }), d.n_divergences ? "error" : "ok"));
    }
    function actions(d) {
        var box = PK.clear(document.getElementById("aj-actions")), out = PK.clear(document.getElementById("aj-chain"));
        var verify = h("button", { type: "button", class: "primary", text: T("aj_verify") }), seal = h("button", { type: "button", class: "btn-secondary", text: T("aj_seal") });
        var csv = h("a", { class: "btn-secondary", href: "/api/journal/export.csv", download: "", text: T("aj_export") });
        verify.addEventListener("click", function () {
            verify.disabled = true; PK.clear(out).appendChild(PK.info(T("aj_verifying")));
            PK.fetchJSON("/api/journal/verify").then(function (r) {
                verify.disabled = false; PK.clear(out);
                if (r.ok) out.appendChild(h("p", { class: "banner banner-info", role: "status", text: T("aj_ok", { n: int(r.n), h: short(r.head) }) }));
                else out.appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("aj_broken", { id: r.first_bad, r: T("aj_reason_" + r.reason) }) }));
            }).catch(function (e) { verify.disabled = false; PK.clear(out).appendChild(PK.empty(e.message)); });
        });
        seal.addEventListener("click", async function () {
            var ok = window.patrickDialog ? await window.patrickDialog.confirm(T("aj_seal_confirm"), T("aj_seal"), false) : false;
            if (!ok) return;
            seal.disabled = true; PK.clear(out).appendChild(PK.info(T("aj_sealing")));
            fetch("/api/journal/seal", { method: "POST" }).then(function (r) { return r.json(); }).then(function (r) { PK.clear(out).appendChild(PK.info(T("aj_sealed", { s: int(r.sealed), o: int(r.outcomes) }))); load(); })
                .catch(function (e) { seal.disabled = false; PK.clear(out).appendChild(PK.empty(e.message)); });
        });
        [verify, seal, csv].forEach(function (b) { box.appendChild(b); });
        box.appendChild(PK.note(T("aj_seal_hint")));
    }
    function pairs(d) {
        var host = PK.clear(document.getElementById("aj-pairs"));
        if (!d.pairs.length) { host.appendChild(PK.empty(T("aj_no_pairs"))); return; }
        var rows = d.pairs.map(function (p) {
            var c = p.calibration;
            return [{ cell: h("a", { class: "ra-cell-link", href: "/targets/" + encodeURIComponent(p.target), title: p.target, text: PK.inst(p.target) }) }, p.horizon, int(p.signals), int(p.judged), int(p.pending), isNum(p.hit_rate) ? pct(p.hit_rate, 0) : "—", isNum(p.last_hit) ? pct(p.last_hit, 0) : "—",
                c ? num(c.ece, 3) : "—", c ? num(c.brier, 3) + " / " + num(c.base_brier, 3) : "—", p.first + " → " + p.last, int(p.models), int(p.backfill)];
        });
        host.appendChild(PK.table([T("ag_c_target"), T("ag_c_horizon"), T("aj_c_signals"), T("aj_c_judged"), T("aj_c_pending"), T("ad_c_hit"), T("aj_c_last", { n: 30 }), "ECE", "Brier / " + T("aj_c_base"), T("aj_c_span"), T("aj_c_models"), T("aj_c_backfill")], rows, { num: [1, 2, 3, 4, 5, 6, 7, 8, 10, 11] }));
        host.appendChild(PK.note(T("aj_pairs_hint", { m: 30 })));
        if (d.divergences.length) {
            host.appendChild(h("h3", { text: T("aj_div_h") }));
            host.appendChild(PK.table([T("ag_c_target"), T("ag_c_horizon"), T("aj_c_date"), T("aj_div_journal"), T("aj_div_table")], d.divergences.map(function (x) { return [PK.inst(x.target), x.horizon, x.day, "y=" + x.journal.y_pred + " p=" + (isNum(x.journal.p_up) ? num(x.journal.p_up, 3) : "—"), "y=" + x.table.y_pred + " p=" + (isNum(x.table.p_up) ? num(x.table.p_up, 3) : "—")]; }), { num: [1] }));
            host.appendChild(PK.note(T("aj_div_hint")));
        }
    }
    function entries() {
        var host = document.getElementById("aj-entries");
        PK.fetchJSON("/api/journal/entries?limit=" + st.per + "&offset=" + st.offset + (st.target ? "&target=" + encodeURIComponent(st.target) : "")).then(function (d) {
            var rows = d.items.map(function (e) {
                return [e.journal_id, (e.recorded_at || "").slice(0, 19), PK.chip(T("aj_kind_" + e.kind), e.kind === "signal" ? "neutral" : "ok"), e.origin === "backfill" ? PK.chip(T("aj_backfill"), "warn") : "", PK.inst(e.target), e.horizon, e.signal_date,
                    isNum(e.y_pred) ? T("ra_cls" + Math.round(e.y_pred)) : "—", isNum(e.p_up) ? num(e.p_up, 3) : "—", isNum(e.y_true) ? (e.y_true >= 0.5 ? T("ra_up") : T("ra_down")) : "—", { cell: short(e.model_hash), cls: "pk-mono" }, { cell: short(e.entry_hash), cls: "pk-mono" }];
            });
            PK.clear(host).appendChild(PK.table(["#", T("aj_c_recorded"), T("aj_c_kind"), T("aj_c_origin"), T("ag_c_target"), T("ag_c_horizon"), T("aj_c_date"), T("aj_c_pred"), "P(up)", T("aj_c_outcome"), T("aj_c_model"), T("aj_c_hash")], rows, { num: [0, 5, 8] }));
            host.appendChild(PK.info(T("aj_entries_n", { a: int(Math.min(d.total, st.offset + 1)), b: int(Math.min(d.total, st.offset + st.per)), n: int(d.total) })));
            var pager = PK.clear(document.getElementById("aj-pager"));
            var prev = h("button", { type: "button", class: "btn-secondary", text: T("ah_prev") }), next = h("button", { type: "button", class: "btn-secondary", text: T("ah_next") });
            prev.disabled = st.offset === 0; next.disabled = st.offset + st.per >= d.total;
            prev.addEventListener("click", function () { st.offset = Math.max(0, st.offset - st.per); entries(); }); next.addEventListener("click", function () { st.offset += st.per; entries(); });
            if (d.total > st.per) { pager.appendChild(prev); pager.appendChild(next); }
            host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
        }).catch(function (e) { PK.clear(host).appendChild(PK.empty(e.message)); });
    }
    function filters(d) {
        var box = PK.clear(document.getElementById("aj-filters")), targets = Array.from(new Set(d.pairs.map(function (p) { return p.target; }))).sort();
        box.appendChild(PK.select([{ value: "", label: T("ah_all_status") }].concat(targets.map(function (t) { return { value: t, label: PK.inst(t) }; })), st.target, function (v) { st.target = v; st.offset = 0; entries(); }, T("ag_c_target")));
    }
    function load() {
        PK.fetchJSON("/api/journal/overview").then(function (d) { kpis(d); actions(d); pairs(d); filters(d); entries(); root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true })); })
            .catch(function (e) { PK.clear(document.getElementById("aj-pairs")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); });
    }
    load();
})();
