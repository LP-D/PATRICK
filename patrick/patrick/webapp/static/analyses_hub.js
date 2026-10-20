/* Page /analyses : tous les entraînements (ML, DL, RL) dans un tableau filtrable et triable, carte cible × horizon, distribution des
   scores par algorithme, nuage des runs RL. Données : /api/analyses/index puis /api/analyses/maps. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("ah-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var st = { rows: [], q: "", kind: "", status: "done", horizon: "", noSuspect: false, sortKey: "started_at", sortDir: -1, page: 0, per: 100 };

    // ---------------------------------------------------------------- colonnes
    function badge(kind) { return h("span", { class: "ra-kind ra-kind-" + kind, text: kind.toUpperCase() }); }
    function dash(v, f) { return isNum(v) ? f(v) : "—"; }
    var COLS = [
        { key: "kind", label: "ah_c_kind", cell: function (r) { return badge(r.kind); }, sort: function (r) { return r.kind; } },
        { key: "name", label: "ah_c_name", cell: function (r) { return h("a", { class: "ra-cell-link", href: r.url, text: r.name || r.id }); }, sort: function (r) { return (r.name || r.id || "").toLowerCase(); } },
        { key: "target", label: "ah_c_target", cell: function (r) { return r.target || "—"; }, sort: function (r) { return (r.target || "").toLowerCase(); } },
        { key: "horizon", label: "ah_c_horizon", num: true, cell: function (r) { return r.horizon === null || r.horizon === undefined ? "—" : String(r.horizon); }, sort: function (r) { return r.horizon; } },
        { key: "algo", label: "ah_c_algo", cell: function (r) { return r.algo || "—"; }, sort: function (r) { return (r.algo || "").toLowerCase(); } },
        { key: "n_features", label: "ah_c_nfeat", num: true, cell: function (r) { return r.n_features === null || r.n_features === undefined ? "—" : String(r.n_features); }, sort: function (r) { return r.n_features; } },
        { key: "status", label: "ah_c_status", cell: function (r) { return statusChip(r); }, sort: function (r) { return r.status; } },
        { key: "f1_test", label: "ah_c_f1_test", num: true, cell: function (r) { return r.kind === "rl" ? dash(r.sharpe, function (v) { return "S " + num(v, 2); }) : dash(r.f1_test, function (v) { return num(v, 3); }); }, sort: function (r) { return r.kind === "rl" ? r.sharpe : r.f1_test; } },
        { key: "f1_holdout", label: "ah_c_f1_hold", num: true, cell: function (r) { return r.kind === "rl" ? dash(r.sharpe_bh, function (v) { return "BH " + num(v, 2); }) : dash(r.f1_holdout, function (v) { return num(v, 3); }); }, sort: function (r) { return r.kind === "rl" ? r.sharpe_bh : r.f1_holdout; } },
        { key: "auc_test", label: "ah_c_auc", num: true, cell: function (r) { return r.kind === "rl" ? dash(r.dsr, function (v) { return "DSR " + pct(v, 0); }) : dash(r.auc_test, function (v) { return num(v, 3); }); }, sort: function (r) { return r.kind === "rl" ? r.dsr : r.auc_test; } },
        { key: "dm_p", label: "ah_c_dm", num: true, cell: function (r) { return dash(r.dm_p, PK.pval); }, sort: function (r) { return r.dm_p; } },
        { key: "n_trials", label: "ah_c_trials", num: true, cell: function (r) { return r.n_trials === null || r.n_trials === undefined ? "—" : String(r.n_trials); }, sort: function (r) { return r.n_trials; } },
        { key: "started_at", label: "ah_c_started", cell: function (r) { return (r.started_at || "—").slice(0, 16); }, sort: function (r) { return r.started_at || ""; } },
    ];
    function statusChip(r) {
        var kind = r.status === "done" ? "ok" : (r.status === "failed" || r.status === "error" ? "neg" : "neutral");
        var span = PK.chip(r.status + (r.suspect ? " ⚠" : ""), r.suspect ? "warn" : kind);
        if (r.suspect) span.title = T("ah_suspect");
        return span;
    }

    // ---------------------------------------------------------------- filtres
    function filtered() {
        var q = st.q.trim().toLowerCase();
        return st.rows.filter(function (r) {
            if (st.kind && r.kind !== st.kind) return false;
            if (st.status === "done" && r.status !== "done") return false;
            if (st.status === "failed" && r.status !== "failed" && r.status !== "error") return false;
            if (st.status === "active" && ["running", "queued", "paused"].indexOf(r.status) < 0) return false;
            if (st.horizon && String(r.horizon) !== st.horizon) return false;
            if (st.noSuspect && r.suspect) return false;
            if (q && ((r.name || "") + " " + (r.target || "") + " " + (r.algo || "") + " " + r.id).toLowerCase().indexOf(q) < 0) return false;
            return true;
        });
    }
    function buildFilters() {
        var box = document.getElementById("ah-filters");
        PK.clear(box);
        var search = h("input", { type: "search", placeholder: T("ah_filter_q"), "aria-label": T("ah_filter_q"), value: st.q });
        search.addEventListener("input", function () { st.q = search.value; st.page = 0; drawTable(); });
        box.appendChild(search);
        box.appendChild(PK.select([{ value: "", label: T("ah_all_kinds") }, { value: "ml", label: "ML" }, { value: "dl", label: "DL" }, { value: "rl", label: "RL" }], st.kind, function (v) { st.kind = v; st.page = 0; drawTable(); }, T("ah_f_kind")));
        box.appendChild(PK.select([{ value: "done", label: T("ah_st_done") }, { value: "", label: T("ah_all_status") }, { value: "active", label: T("ah_st_active") }, { value: "failed", label: T("ah_st_failed") }], st.status, function (v) { st.status = v; st.page = 0; drawTable(); }, T("ah_f_status")));
        var hs = Array.from(new Set(st.rows.map(function (r) { return r.horizon; }).filter(function (v) { return v !== null && v !== undefined; }))).sort(function (a, b) { return a - b; });
        box.appendChild(PK.select([{ value: "", label: T("ah_all_horizons") }].concat(hs.map(function (v) { return { value: String(v), label: String(v) }; })), st.horizon, function (v) { st.horizon = v; st.page = 0; drawTable(); }, T("ah_f_horizon")));
        var cb = h("input", { type: "checkbox" });
        cb.checked = st.noSuspect;
        cb.addEventListener("change", function () { st.noSuspect = cb.checked; st.page = 0; drawTable(); });
        box.appendChild(h("label", { class: "ra-control" }, [cb, h("span", { text: T("ah_hide_suspect") })]));
    }

    // ---------------------------------------------------------------- tableau
    function drawKpis() {
        var box = document.getElementById("ah-kpis");
        PK.clear(box);
        var c = {}, done = 0, failed = 0;
        st.rows.forEach(function (r) { c[r.kind] = (c[r.kind] || 0) + 1; if (r.status === "done") done++; if (r.status === "failed" || r.status === "error") failed++; });
        box.appendChild(PK.kpi(T("ah_k_total"), int(st.rows.length), T("ah_k_total_sub", { d: int(done), f: int(failed) }), "neutral"));
        ["ml", "dl", "rl"].forEach(function (k) { box.appendChild(PK.kpi(T("ah_k_" + k), int(c[k] || 0), T("ah_k_" + k + "_sub"), "neutral")); });
    }
    function drawTable() {
        var host = document.getElementById("ah-table"), rows = filtered();
        var col = COLS.filter(function (c) { return c.key === st.sortKey; })[0] || COLS[COLS.length - 1];
        rows.sort(function (a, b) {
            var x = col.sort(a), y = col.sort(b), nx = x === null || x === undefined || (typeof x === "number" && !isFinite(x)), ny = y === null || y === undefined || (typeof y === "number" && !isFinite(y));
            if (nx && ny) return 0;
            if (nx) return 1;
            if (ny) return -1;
            return (x < y ? -1 : (x > y ? 1 : 0)) * st.sortDir;
        });
        var pages = Math.max(1, Math.ceil(rows.length / st.per));
        st.page = Math.min(st.page, pages - 1);
        var slice = rows.slice(st.page * st.per, (st.page + 1) * st.per);
        var thead = h("tr", {}, COLS.map(function (c) {
            var th = h("th", { scope: "col", class: c.num ? "num pk-mono" : "", text: T(c.label), "aria-sort": c.key === st.sortKey ? (st.sortDir > 0 ? "ascending" : "descending") : "none", tabindex: "0" });
            function sortBy() { if (st.sortKey === c.key) st.sortDir = -st.sortDir; else { st.sortKey = c.key; st.sortDir = c.num ? -1 : 1; } drawTable(); }
            th.addEventListener("click", sortBy);
            th.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); sortBy(); } });
            return th;
        }));
        var tbody = h("tbody", {}, slice.map(function (r) {
            return h("tr", { class: r.suspect ? "row-suspect" : "" }, COLS.map(function (c) {
                var td = h("td", { class: c.num ? "num pk-mono" : "" });
                var v = c.cell(r);
                if (v && v.nodeType) td.appendChild(v); else td.textContent = v;
                return td;
            }));
        }));
        PK.clear(host).appendChild(h("div", { class: "table-scroll" }, [h("table", { class: "data-table ra-sortable" }, [h("thead", {}, [thead]), tbody])]));
        host.appendChild(PK.info(T("ah_rows", { n: int(rows.length), total: int(st.rows.length) })));
        var pager = document.getElementById("ah-pager");
        PK.clear(pager);
        if (pages > 1) {
            var prev = h("button", { type: "button", class: "btn-secondary", text: T("ah_prev") }), next = h("button", { type: "button", class: "btn-secondary", text: T("ah_next") });
            prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
            prev.addEventListener("click", function () { st.page--; drawTable(); });
            next.addEventListener("click", function () { st.page++; drawTable(); });
            pager.appendChild(prev); pager.appendChild(h("span", { class: "pk-mono", text: (st.page + 1) + " / " + pages })); pager.appendChild(next);
        }
        host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }

    // ---------------------------------------------------------------- carte cible × horizon
    function drawMap(d) {
        var host = document.getElementById("ah-map"), metric = "f1_holdout", query = "", per = 40;
        var cells = {};
        d.cells.forEach(function (c) { cells[c.target + "|" + c.horizon] = c; });
        function draw() {
            PK.clear(host);
            host.appendChild(PK.segmented([{ value: "f1_holdout", label: T("ah_map_holdout") }, { value: "f1_test", label: T("ah_map_test") }], metric, function (v) { metric = v; draw(); }));
            var search = h("input", { type: "search", class: "ra-num", style: { width: "180px", "margin-left": "12px" }, placeholder: T("ah_filter_q"), value: query });
            search.addEventListener("change", function () { query = search.value; draw(); });
            host.appendChild(search);
            var ts = d.targets.filter(function (t) { return !query || t.toLowerCase().indexOf(query.trim().toLowerCase()) >= 0; });
            ts.sort(function (a, b) {
                function best(t) { var m = -1; d.horizons.forEach(function (hz) { var c = cells[t + "|" + hz]; if (c && isNum(c[metric]) && c[metric] > m) m = c[metric]; }); return m; }
                return best(b) - best(a);
            });
            var shown = ts.slice(0, per);
            host.appendChild(PK.heat(shown, d.horizons.map(String), function (r, c) {
                var cell = cells[shown[r] + "|" + d.horizons[c]];
                if (!cell || !isNum(cell[metric])) return { text: "" };
                var v = cell[metric], dev = Math.min(1, Math.abs(v - 0.5) / 0.12);
                return { text: num(v, 2), intensity: dev, base: v >= 0.5 ? "var(--pos)" : "var(--neg)", href: "/runs/" + encodeURIComponent(cell.run_id) + "/analyse", title: cell.algo + (cell.suspect ? " ⚠" : "") };
            }, { corner: T("ah_map_corner") }));
            host.appendChild(PK.info(T("ah_map_shown", { n: shown.length, total: ts.length })));
            host.appendChild(PK.note(T("ah_map_hint")));
            host.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
        }
        draw();
    }

    // ---------------------------------------------------------------- distribution par algorithme
    function drawAlgos(d) {
        var host = document.getElementById("ah-algos");
        var algos = d.algos.filter(function (a) { return a.holdout || a.test; });
        if (!algos.length) { host.appendChild(PK.empty(T("ra_reason_not_enough"))); return; }
        var lo = 1, hi = 0;
        algos.forEach(function (a) { ["test", "holdout"].forEach(function (k) { if (a[k]) { lo = Math.min(lo, a[k].min); hi = Math.max(hi, a[k].max); } }); });
        var rowH = 34, H = 30 + algos.length * rowH + 24;
        var P = PK.plot({ w: 780, h: H, m: { l: 100, t: 10, b: 24, r: 14 }, x: { type: "linear", domain: [Math.max(0, lo - 0.02), Math.min(1, hi + 0.02)], fmt: function (v) { return num(v, 2); }, label: T("ah_box_x") }, y: { domain: [0, 1], ticks: [], zero: false }, title: T("ah_s_algos") });
        PK.vline(P, 0.5, { color: "var(--text-3)" });
        algos.forEach(function (a, i) {
            var y = P.m.t + i * rowH + 17;
            P.add(PK.s("text", { x: P.m.l - 8, y: y + 4, "text-anchor": "end", class: "ra-axis", text: a.algo + " (" + ((a.holdout || a.test).n) + ")" }));
            [["test", -6, "var(--brand)"], ["holdout", 6, "var(--warn)"]].forEach(function (p) {
                var b = a[p[0]];
                if (!b) return;
                var yy = y + p[1];
                P.add(PK.s("line", { x1: P.X(b.min), x2: P.X(b.max), y1: yy, y2: yy, stroke: p[2], "stroke-width": 1, "stroke-opacity": 0.7 }));
                PK.hoverTip(P.add(PK.s("rect", { x: P.X(b.q1), y: yy - 4, width: Math.max(1, P.X(b.q3) - P.X(b.q1)), height: 8, fill: p[2], "fill-opacity": 0.55, stroke: p[2] })),
                    function () { return [a.algo + " · " + T("ra_split_" + p[0]), T("ah_box_t", { med: num(b.median, 3), q1: num(b.q1, 3), q3: num(b.q3, 3), mn: num(b.min, 3), mx: num(b.max, 3), n: b.n })]; });
                P.add(PK.s("line", { x1: P.X(b.median), x2: P.X(b.median), y1: yy - 5, y2: yy + 5, stroke: "var(--text)", "stroke-width": 2 }));
            });
        });
        host.appendChild(P.node);
        host.appendChild(PK.legend([{ color: "var(--brand)", label: T("ra_split_test") }, { color: "var(--warn)", label: T("ra_split_holdout") }]));
        host.appendChild(PK.note(T("ah_box_hint")));
    }

    // ---------------------------------------------------------------- nuage RL
    function drawRL(d) {
        var host = document.getElementById("ah-rl"), pts = d.rl.filter(function (p) { return isNum(p.sharpe) && isNum(p.sharpe_bh); });
        if (!pts.length) { host.appendChild(PK.empty(T("ah_rl_none"))); return; }
        var xs = pts.map(function (p) { return p.sharpe_bh; }), ys = pts.map(function (p) { return p.sharpe; });
        var dom = PK.extent([xs, ys], 0.08);
        var P = PK.plot({ w: 560, h: 380, x: { type: "linear", domain: dom, fmt: function (v) { return num(v, 1); }, label: T("ah_rl_x") }, y: { domain: dom, fmt: function (v) { return num(v, 1); }, label: T("ah_rl_y") }, title: T("ah_s_rl") });
        P.add(PK.s("line", { x1: P.X(dom[0]), y1: P.Y(dom[0]), x2: P.X(dom[1]), y2: P.Y(dom[1]), stroke: "var(--text-3)", "stroke-dasharray": "4 4" }));
        pts.forEach(function (p) {
            var c = PK.s("circle", { cx: P.X(p.sharpe_bh), cy: P.Y(p.sharpe), r: 3.6, fill: p.sharpe > p.sharpe_bh ? "var(--pos)" : "var(--neg)", "fill-opacity": 0.6 });
            c.style.cursor = "pointer";
            c.addEventListener("click", function () { window.location.href = "/runs/" + encodeURIComponent(p.id) + "/analyse"; });
            PK.hoverTip(P.add(c), function () { return [p.target + " · " + p.algo, T("ah_rl_t", { s: num(p.sharpe, 2), b: num(p.sharpe_bh, 2), d: isNum(p.dsr) ? pct(p.dsr, 0) : "—" })]; });
        });
        var above = pts.filter(function (p) { return p.sharpe > p.sharpe_bh; }).length;
        host.appendChild(P.node);
        host.appendChild(PK.info(T("ah_rl_count", { a: above, n: pts.length })));
        host.appendChild(PK.note(T("ah_rl_hint")));
    }

    // ---------------------------------------------------------------- démarrage
    PK.fetchJSON("/api/analyses/index").then(function (d) {
        st.rows = d.rows;
        drawKpis();
        buildFilters();
        drawTable();
    }).catch(function (e) {
        PK.clear(document.getElementById("ah-table")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message }));
    });
    PK.fetchJSON("/api/analyses/maps").then(function (d) { drawMap(d); drawAlgos(d); drawRL(d); }).catch(function (e) {
        ["ah-map", "ah-algos", "ah-rl"].forEach(function (id) { PK.clear(document.getElementById(id)).appendChild(PK.empty(T("ra_error") + " " + e.message)); });
    });
})();
