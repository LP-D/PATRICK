/* Page /derive : moniteur de dérive par cible et horizon. Tableau de tous les couples suivis, détail d'un couple (PSI mesurés dans le temps,
   Page-Hinkley sur les appels live, réussite glissante) et mesure du PSI à la demande. Données : /api/derive/overview, /api/derive/detail. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("ad-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var ACTION_KIND = { retrain: "neg", watch: "warn", ok: "ok", unmeasured: "neutral" };
    var st = { items: [], q: "", action: "", sortKey: "action", sortDir: 1, page: 0, per: 40, thr: null, current: null };
    var ORDER = { retrain: 0, watch: 1, unmeasured: 2, ok: 3 };

    function kpis(d) {
        var box = PK.clear(document.getElementById("ad-kpis"));
        ["retrain", "watch", "ok", "unmeasured"].forEach(function (a) {
            box.appendChild(PK.kpi(T("ad_a_" + a), int(d.counts[a] || 0), T("ad_a_" + a + "_sub"), a === "retrain" && d.counts[a] ? "error" : (a === "watch" && d.counts[a] ? "warning" : (a === "ok" ? "ok" : "neutral"))));
        });
    }
    var COLS = [
        { key: "action", label: "ad_c_action", cell: function (r) { return PK.chip(T("ad_a_" + r.action), ACTION_KIND[r.action]); }, sort: function (r) { return ORDER[r.action]; } },
        { key: "target", label: "ag_c_target", cell: function (r) { return h("a", { class: "ra-cell-link", href: "/targets/" + encodeURIComponent(r.target), text: r.target }); }, sort: function (r) { return r.target.toLowerCase(); } },
        { key: "horizon", label: "ag_c_horizon", num: true, cell: function (r) { return String(r.horizon); }, sort: function (r) { return r.horizon; } },
        { key: "psi", label: "ad_c_psi", num: true, cell: function (r) { return isNum(r.psi) ? num(r.psi, 3) + (r.worst_feature ? " " : "") : "—"; }, sort: function (r) { return r.psi; } },
        { key: "share_significant", label: "ad_c_share", num: true, cell: function (r) { return isNum(r.share_significant) ? pct(r.share_significant, 0) + " (" + r.n_features + ")" : "—"; }, sort: function (r) { return r.share_significant; } },
        { key: "age_days", label: "ad_c_age", num: true, cell: function (r) { return r.age_days === null || r.age_days === undefined ? "—" : T("ad_days", { n: r.age_days }) + (r.stale ? " ⚠" : ""); }, sort: function (r) { return r.age_days; } },
        { key: "n_independent", label: "ad_c_calls", num: true, cell: function (r) { return r.n_hits + " / " + r.n_independent; }, sort: function (r) { return r.n_independent; } },
        { key: "concept_hit_rate", label: "ad_c_hit", num: true, cell: function (r) { return isNum(r.concept_hit_rate) ? pct(r.concept_hit_rate, 0) : "—"; }, sort: function (r) { return r.concept_hit_rate; } },
        { key: "concept_drift", label: "ad_c_concept", cell: function (r) { return r.concept_drift === null || r.concept_drift === undefined ? PK.chip(T("ad_not_testable"), "neutral") : PK.chip(r.concept_drift ? T("ad_break") : T("ad_no_break"), r.concept_drift ? "neg" : "ok"); }, sort: function (r) { return r.concept_drift === null ? 2 : (r.concept_drift ? 0 : 1); } },
    ];
    function filters() {
        var box = PK.clear(document.getElementById("ad-filters"));
        var s = h("input", { type: "search", placeholder: T("ag_filter_q"), "aria-label": T("ag_filter_q"), value: st.q });
        s.addEventListener("input", function () { st.q = s.value; st.page = 0; table(); });
        box.appendChild(s);
        box.appendChild(PK.select([{ value: "", label: T("ah_all_status") }].concat(["retrain", "watch", "ok", "unmeasured"].map(function (a) { return { value: a, label: T("ad_a_" + a) }; })), st.action, function (v) { st.action = v; st.page = 0; table(); }, T("ad_c_action")));
    }
    function table() {
        var host = document.getElementById("ad-table"), q = st.q.trim().toLowerCase();
        var rows = st.items.filter(function (r) { return (!q || r.target.toLowerCase().indexOf(q) >= 0) && (!st.action || r.action === st.action); });
        var col = COLS.filter(function (c) { return c.key === st.sortKey; })[0] || COLS[0];
        rows.sort(function (a, b) {
            var x = col.sort(a), y = col.sort(b), nx = x === null || x === undefined, ny = y === null || y === undefined;
            if (nx && ny) return 0; if (nx) return 1; if (ny) return -1;
            return (x < y ? -1 : (x > y ? 1 : 0)) * st.sortDir;
        });
        var pages = Math.max(1, Math.ceil(rows.length / st.per)); st.page = Math.min(st.page, pages - 1);
        var slice = rows.slice(st.page * st.per, (st.page + 1) * st.per);
        var thead = h("tr", {}, COLS.map(function (c) {
            var th = h("th", { scope: "col", class: c.num ? "num pk-mono" : "", text: T(c.label), tabindex: "0", "aria-sort": c.key === st.sortKey ? (st.sortDir > 0 ? "ascending" : "descending") : "none" });
            function by() { if (st.sortKey === c.key) st.sortDir = -st.sortDir; else { st.sortKey = c.key; st.sortDir = c.num ? -1 : 1; } table(); }
            th.addEventListener("click", by); th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); by(); } });
            return th;
        }));
        var tbody = h("tbody", {}, slice.map(function (r) {
            var tr = h("tr", { class: "ad-row", tabindex: "0", title: r.reason || "" }, COLS.map(function (c) { var td = h("td", { class: c.num ? "num pk-mono" : "" }), v = c.cell(r); if (v && v.nodeType) td.appendChild(v); else td.textContent = v; return td; }));
            function open() { openDetail(r.target, r.horizon); }
            tr.addEventListener("click", function (e) { if (e.target.tagName !== "A") open(); });
            tr.addEventListener("keydown", function (e) { if (e.key === "Enter") open(); });
            return tr;
        }));
        PK.clear(host).appendChild(h("div", { class: "table-scroll" }, [h("table", { class: "data-table ra-sortable" }, [h("thead", {}, [thead]), tbody])]));
        host.appendChild(PK.info(T("ad_rows", { n: int(rows.length), total: int(st.items.length) })));
        var pager = PK.clear(document.getElementById("ad-pager"));
        if (pages > 1) {
            var prev = h("button", { type: "button", class: "btn-secondary", text: T("ah_prev") }), next = h("button", { type: "button", class: "btn-secondary", text: T("ah_next") });
            prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
            prev.addEventListener("click", function () { st.page--; table(); }); next.addEventListener("click", function () { st.page++; table(); });
            pager.appendChild(prev); pager.appendChild(h("span", { class: "pk-mono", text: (st.page + 1) + " / " + pages })); pager.appendChild(next);
        }
    }

    function openDetail(target, horizon) {
        var sec = document.getElementById("detail"), host = PK.clear(document.getElementById("ad-detail"));
        sec.hidden = false;
        document.getElementById("ad-detail-title").textContent = target + " · " + T("ad_h", { h: horizon });
        host.appendChild(h("div", { class: "ra-skeleton" }, [h("div", { class: "skeleton-line", style: { width: "70%" } })]));
        sec.scrollIntoView({ block: "start" });
        PK.fetchJSON("/api/derive/detail?target=" + encodeURIComponent(target) + "&horizon=" + horizon).then(function (d) { renderDetail(host, d); })
            .catch(function (e) { PK.clear(host).appendChild(PK.empty(T("ra_error") + " " + e.message)); });
    }
    function renderDetail(host, d) {
        PK.clear(host);
        var btn = h("button", { type: "button", class: "btn-secondary", text: T("ad_measure") }), out = h("div", {});
        btn.addEventListener("click", function () {
            btn.disabled = true; PK.clear(out).appendChild(PK.info(T("ad_measuring")));
            fetch("/api/drift/" + encodeURIComponent(d.target) + "/" + d.horizon, { method: "POST" }).then(function (r) { return r.json().then(function (b) { if (!r.ok) throw new Error(b.detail || r.status); return b; }); })
                .then(function () { openDetail(d.target, d.horizon); })
                .catch(function (e) { btn.disabled = false; PK.clear(out).appendChild(h("p", { class: "banner banner-error", role: "alert", text: e.message })); });
        });
        host.appendChild(h("div", { class: "ra-controls" }, [btn]));
        host.appendChild(out);
        host.appendChild(PK.note(T("ad_measure_hint")));

        // PSI mesurés dans le temps
        var ps = d.psi_history;
        if (ps.length) {
            var xs = ps.map(function (p) { return PK.dateMs(p.at.slice(0, 10)); }), lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs), pad = Math.max(864e5 * 3, (hi - lo) * 0.05);
            var P = PK.plot({ w: 780, h: 220, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: [0, Math.max(0.35, Math.max.apply(null, ps.map(function (p) { return p.max; })) * 1.1)], fmt: function (v) { return num(v, 2); }, zero: false }, title: T("ad_psi_title") });
            PK.hline(P, d.params.psi_alert, { color: "var(--neg)", label: "0,25" });
            PK.hline(P, 0.1, { color: "var(--warn)", label: "0,10" });
            PK.line(P, xs, ps.map(function (p) { return p.max; }), { color: "var(--neg)", width: 1.6 });
            PK.line(P, xs, ps.map(function (p) { return p.mean; }), { color: "var(--brand)", width: 1.6 });
            PK.points(P, xs, ps.map(function (p) { return p.max; }), { r: 3, color: "var(--neg)", opacity: 0.9 });
            host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ad_psi_h") }), P.node, PK.legend([{ color: "var(--neg)", label: T("ad_psi_max"), line: true }, { color: "var(--brand)", label: T("ad_psi_mean"), line: true }]), PK.note(T("ad_psi_hint"))]));
        } else host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ad_psi_h") }), PK.empty(T("ad_psi_none"))]));
        if (d.latest.features.length) {
            var items = d.latest.features.slice(0, 25), mx = Math.max.apply(null, items.map(function (f) { return f.psi; }).concat([0.3]));
            host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ad_feat_h", { d: (d.latest.at || "").slice(0, 10), n: d.latest.n }) }), h("div", { class: "ra-hbars" }, items.map(function (f) {
                var col = f.level === "alert" || f.level === "drift" || f.psi > d.params.psi_alert ? "var(--neg)" : (f.psi > 0.1 ? "var(--warn)" : "var(--pos)");
                return h("div", { class: "ra-hbar" }, [h("span", { class: "ra-hbar-label", title: f.feature, text: f.feature }), h("span", { class: "ra-hbar-track" }, [h("i", { style: { width: (f.psi / mx * 100).toFixed(1) + "%", background: col } })]), h("span", { class: "ra-hbar-val pk-mono", text: num(f.psi, 3) })]);
            }))]));
        }

        // appels live
        var lv = d.live;
        var chips = h("div", { class: "ra-chips" }, [PK.chip(T("ad_live_n", { r: lv.n_resolved, i: lv.n_independent })), PK.chip(T("ad_live_hit", { h: isNum(lv.hit_rate) ? pct(lv.hit_rate, 0) : "—" })), PK.chip(T("ad_live_params", { d: d.params.delta, l: d.params.lambda }))]);
        if (lv.detected_at !== null) chips.appendChild(PK.chip(T("ad_live_detected", { d: lv.detected_date }), "neg"));
        else if (lv.n_independent < d.params.min_independent) chips.appendChild(PK.chip(T("ad_live_few", { n: d.params.min_independent }), "neutral"));
        host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ad_live_h") }), chips]));
        if (lv.n_independent >= 2) {
            var X = lv.ph.map(function (_, i) { return i + 1; }), Q = PK.plot({ w: 780, h: 200, x: { type: "linear", domain: [0.5, X.length + 0.5], fmt: int, label: T("ad_live_x") }, y: { domain: [0, Math.max(d.params.lambda * 1.15, Math.max.apply(null, lv.ph) * 1.1)], fmt: function (v) { return num(v, 1); } }, title: T("ad_ph_title") });
            PK.hline(Q, d.params.lambda, { color: "var(--neg)", label: T("ad_ph_thr", { l: d.params.lambda }) });
            PK.line(Q, X, lv.ph, { color: "var(--brand)", width: 1.8, area: true });
            if (lv.detected_at !== null) PK.vline(Q, lv.detected_at + 1, { color: "var(--neg)", dash: "", label: T("ad_ph_alarm") });
            host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ad_ph_h") }), Q.node, PK.note(T("ad_ph_hint"))]));
            var rv = lv.rolling.filter(function (v) { return v !== null; });
            if (rv.length) {
                var R = PK.plot({ w: 780, h: 180, x: { type: "linear", domain: [0.5, X.length + 0.5], fmt: int, label: T("ad_live_x") }, y: { domain: [0, 1], fmt: function (v) { return pct(v, 0); }, zero: false }, title: T("ad_roll_title", { w: lv.window }) });
                PK.hline(R, 0.5, { color: "var(--text-3)" });
                PK.line(R, X, lv.rolling, { color: "var(--pos)", width: 1.8 });
                host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("ad_roll_title", { w: lv.window }) }), R.node]));
            }
        }
        host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }

    PK.fetchJSON("/api/derive/overview").then(function (d) {
        st.items = d.items; st.thr = d.thresholds;
        kpis(d); filters(); table();
        root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }).catch(function (e) { PK.clear(document.getElementById("ad-table")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); });
})();
