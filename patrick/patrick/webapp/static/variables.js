/* Page /variables : explorateur de variables inter-runs (familles, séries d'entrée, cibles × familles, liste filtrable avec détail par variable).
   Données : /api/variables/overview et /api/variables/detail?feature=… (patrick/analysis/features_explorer.py). */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("av-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var st = { rows: [], q: "", family: "", sortKey: "runs", sortDir: -1, page: 0, per: 50 }, famCol = {};

    function hbars(items, fmt, max) {
        var mx = max || Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1e-12]));
        return h("div", { class: "ra-hbars" }, items.map(function (it) {
            return h("div", { class: "ra-hbar" }, [h("span", { class: "ra-hbar-label", title: it.label, text: it.label }), h("span", { class: "ra-hbar-track" }, [h("i", { style: { width: (it.value / mx * 100).toFixed(1) + "%", background: it.color || "var(--brand)" } })]), h("span", { class: "ra-hbar-val pk-mono", text: fmt(it.value) })]);
        }));
    }
    function kpis(d) {
        var box = PK.clear(document.getElementById("av-kpis")), j = d.jaccard;
        box.appendChild(PK.kpi(T("av_k_feat"), int(d.n_features), T("av_k_feat_sub", { r: int(d.n_runs), t: int(d.n_runs_total) }), "neutral"));
        box.appendChild(PK.kpi(T("av_k_jac"), isNum(j.mean) ? num(j.mean, 3) : "—", T("av_k_jac_sub", { n: int(j.n), m: isNum(j.median) ? num(j.median, 3) : "—" }), isNum(j.mean) && j.mean < 0.5 ? "warning" : "neutral"));
        box.appendChild(PK.kpi(T("av_k_low"), isNum(j.share_low) ? pct(j.share_low, 0) : "—", T("av_k_low_sub"), isNum(j.share_low) && j.share_low > 0.5 ? "warning" : "neutral"));
        box.appendChild(PK.kpi(T("av_k_top"), d.features.length ? d.features[0].feature : "—", d.features.length ? T("av_k_top_sub", { r: int(d.features[0].runs), t: int(d.features[0].targets) }) : "", "neutral"));
    }
    function families(d) {
        d.families.forEach(function (f, i) { famCol[f.family] = PK.CAT_COLORS[i % 8]; });
        PK.clear(document.getElementById("av-fam")).appendChild(hbars(d.families.map(function (f) { return { label: T("ra_fam_" + f.family), value: f.share, color: famCol[f.family] }; }), function (v) { return pct(v, 0); }));
    }
    function series(d) {
        PK.clear(document.getElementById("av-series")).appendChild(PK.table([T("av_c_series"), T("av_c_runs"), T("av_c_nfeat"), T("av_c_weight")],
            d.series.map(function (s) { return [{ cell: s.series, cls: "pk-mono" }, int(s.runs), int(s.features), num(s.weight, 1)]; }), { num: [1, 2, 3] }));
    }
    function matrix(d) {
        var m = d.matrix, host = PK.clear(document.getElementById("av-matrix"));
        host.appendChild(PK.heat(m.rows.map(function (r) { return r.target; }), m.families.map(function (f) { return T("ra_fam_" + f); }), function (r, c) {
            var v = m.rows[r].shares[m.families[c]] || 0;
            return { text: v >= 0.005 ? pct(v, 0) : "", intensity: Math.min(1, v * 2.5), base: "var(--brand)", href: "/targets/" + encodeURIComponent(m.rows[r].target) };
        }, { corner: T("av_m_corner") }));
        host.appendChild(PK.note(T("av_m_hint")));
    }

    var COLS = [
        { key: "feature", label: "av_c_feature", cell: function (r) { var a = h("a", { href: "#liste", class: "ra-cell-link pk-mono", text: r.feature }); a.addEventListener("click", function (e) { e.preventDefault(); detail(r.feature); }); return a; }, sort: function (r) { return r.feature.toLowerCase(); } },
        { key: "family", label: "av_c_family", cell: function (r) { return h("span", { class: "exp-chip", style: { color: famCol[r.family] }, text: T("ra_fam_" + r.family) }); }, sort: function (r) { return r.family; } },
        { key: "series", label: "av_c_series", cell: function (r) { return r.series; }, sort: function (r) { return r.series.toLowerCase(); } },
        { key: "runs", label: "av_c_runs", num: true, cell: function (r) { return int(r.runs); }, sort: function (r) { return r.runs; } },
        { key: "targets", label: "av_c_targets", num: true, cell: function (r) { return int(r.targets); }, sort: function (r) { return r.targets; } },
        { key: "mean_freq", label: "av_c_freq", num: true, cell: function (r) { return pct(r.mean_freq, 0); }, sort: function (r) { return r.mean_freq; } },
        { key: "always", label: "av_c_always", num: true, cell: function (r) { return int(r.always); }, sort: function (r) { return r.always; } },
    ];
    function filters(d) {
        var box = PK.clear(document.getElementById("av-filters"));
        var s = h("input", { type: "search", placeholder: T("av_filter_q"), "aria-label": T("av_filter_q"), value: st.q });
        s.addEventListener("input", function () { st.q = s.value; st.page = 0; table(); });
        box.appendChild(s);
        box.appendChild(PK.select([{ value: "", label: T("ah_all_status") }].concat(d.families.map(function (f) { return { value: f.family, label: T("ra_fam_" + f.family) }; })), st.family, function (v) { st.family = v; st.page = 0; table(); }, T("av_c_family")));
    }
    function table() {
        var host = document.getElementById("av-table"), q = st.q.trim().toLowerCase();
        var rows = st.rows.filter(function (r) { return (!q || r.feature.toLowerCase().indexOf(q) >= 0 || r.series.toLowerCase().indexOf(q) >= 0) && (!st.family || r.family === st.family); });
        var col = COLS.filter(function (c) { return c.key === st.sortKey; })[0] || COLS[3];
        rows.sort(function (a, b) { var x = col.sort(a), y = col.sort(b); return (x < y ? -1 : (x > y ? 1 : 0)) * st.sortDir; });
        var pages = Math.max(1, Math.ceil(rows.length / st.per)); st.page = Math.min(st.page, pages - 1);
        var slice = rows.slice(st.page * st.per, (st.page + 1) * st.per);
        var thead = h("tr", {}, COLS.map(function (c) {
            var th = h("th", { scope: "col", class: c.num ? "num pk-mono" : "", text: T(c.label), tabindex: "0", "aria-sort": c.key === st.sortKey ? (st.sortDir > 0 ? "ascending" : "descending") : "none" });
            function by() { if (st.sortKey === c.key) st.sortDir = -st.sortDir; else { st.sortKey = c.key; st.sortDir = c.num ? -1 : 1; } table(); }
            th.addEventListener("click", by); th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); by(); } });
            return th;
        }));
        var tbody = h("tbody", {}, slice.map(function (r) { return h("tr", {}, COLS.map(function (c) { var td = h("td", { class: c.num ? "num pk-mono" : "" }), v = c.cell(r); if (v && v.nodeType) td.appendChild(v); else td.textContent = v; return td; })); }));
        PK.clear(host).appendChild(h("div", { class: "table-scroll" }, [h("table", { class: "data-table ra-sortable" }, [h("thead", {}, [thead]), tbody])]));
        host.appendChild(PK.info(T("av_rows", { n: int(rows.length), total: int(st.rows.length) })));
        var pager = PK.clear(document.getElementById("av-pager"));
        if (pages > 1) {
            var prev = h("button", { type: "button", class: "btn-secondary", text: T("ah_prev") }), next = h("button", { type: "button", class: "btn-secondary", text: T("ah_next") });
            prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
            prev.addEventListener("click", function () { st.page--; table(); }); next.addEventListener("click", function () { st.page++; table(); });
            pager.appendChild(prev); pager.appendChild(h("span", { class: "pk-mono", text: (st.page + 1) + " / " + pages })); pager.appendChild(next);
        }
    }
    function detail(feature) {
        var host = PK.clear(document.getElementById("av-detail"));
        host.appendChild(h("div", { class: "ra-skeleton" }, [h("div", { class: "skeleton-line", style: { width: "60%" } })]));
        PK.fetchJSON("/api/variables/detail?feature=" + encodeURIComponent(feature)).then(function (d) {
            PK.clear(host);
            host.appendChild(h("h3", { class: "pk-mono", text: d.feature }));
            host.appendChild(h("div", { class: "ra-chips" }, [PK.chip(T("ra_fam_" + d.family)), PK.chip(T("av_c_series") + " : " + d.series), PK.chip(T("av_d_runs", { n: int(d.n_runs), t: int(d.targets.length) }))]));
            host.appendChild(PK.table([T("ah_c_name"), T("ah_c_target"), T("ah_c_horizon"), T("ah_c_algo"), T("ah_c_nfeat"), T("av_c_freq"), T("ah_c_f1_test").split(" · ")[0]],
                d.runs.map(function (r) { return [{ cell: h("a", { href: "/runs/" + encodeURIComponent(r.run_id) + "/analyse", text: r.run_id }) }, r.target, r.horizon, r.algo || "—", r.n_features === null ? "—" : r.n_features, pct(r.freq, 0), isNum(r.f1) ? num(r.f1, 3) : "—"]; }), { num: [2, 4, 5, 6] }));
            host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
            host.scrollIntoView({ block: "nearest" });
        }).catch(function (e) { PK.clear(host).appendChild(PK.empty(T("ra_error") + " " + e.message)); });
    }

    PK.fetchJSON("/api/variables/overview").then(function (d) {
        st.rows = d.features;
        kpis(d); families(d); series(d); matrix(d); filters(d); table();
        root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }).catch(function (e) { PK.clear(document.getElementById("av-fam")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); });
})();
