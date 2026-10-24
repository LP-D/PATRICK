/* Pages /modeles (registre de modèles : un modèle en titre par cible × horizon) et /modeles/fiche (fiche automatique d'un couple : données,
   configuration, métriques, suivi live, dérive, versions, historique des duels, limites connues, promotion d'une version).
   Données : /api/modeles/overview, /api/modeles/card, POST /api/modeles/promote (patrick/analysis/model_registry.py). */
(function () {
    "use strict";
    var PK = window.PK;
    if (!PK) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var DRIFT_KIND = { retrain: "neg", watch: "warn", ok: "ok", unmeasured: "neutral" };

    function cardUrl(t, hz) { return "/modeles/fiche?target=" + encodeURIComponent(t) + "&horizon=" + hz; }
    function driftChip(a) { return a ? PK.chip(T("ad_a_" + a), DRIFT_KIND[a] || "neutral") : "—"; }

    // ================================================================ liste
    var listRoot = document.getElementById("am-root");
    if (listRoot) {
        var st = { items: [], q: "", status: "", sortKey: "target", sortDir: 1, page: 0, per: 50 };
        var COLS = [
            { key: "target", label: "ag_c_target", cell: function (r) { return h("a", { class: "ra-cell-link", href: cardUrl(r.target, r.horizon), title: r.target, text: PK.inst(r.target) }); }, sort: function (r) { return PK.inst(r.target).toLowerCase(); } },
            { key: "horizon", label: "ag_c_horizon", num: true, cell: function (r) { return String(r.horizon); }, sort: function (r) { return r.horizon; } },
            { key: "algo", label: "ah_c_algo", cell: function (r) { return (r.algo || "—") + (r.n_features ? " · N=" + r.n_features : ""); }, sort: function (r) { return r.algo || ""; } },
            { key: "implicit", label: "am_c_title", cell: function (r) { return PK.chip(r.implicit ? T("am_implicit") : T("am_explicit"), r.implicit ? "neutral" : "ok"); }, sort: function (r) { return r.implicit ? 1 : 0; } },
            { key: "n_versions", label: "am_c_versions", num: true, cell: function (r) { return String(r.n_versions); }, sort: function (r) { return r.n_versions; } },
            { key: "f1_test", label: "ra_m_f1dir", num: true, cell: function (r) { return isNum(r.f1_test) ? num(r.f1_test, 3) + " / " + (isNum(r.f1_holdout) ? num(r.f1_holdout, 3) : "—") : "—"; }, sort: function (r) { return r.f1_holdout; } },
            { key: "live_judged", label: "am_c_live", num: true, cell: function (r) { return r.live_judged ? r.live_judged + " · " + pct(r.live_hit, 0) : "—"; }, sort: function (r) { return r.live_judged; } },
            { key: "drift", label: "nav_drift", cell: function (r) { return driftChip(r.drift); }, sort: function (r) { return r.drift || ""; } },
            { key: "age_days", label: "am_c_age", num: true, cell: function (r) { return r.age_days === null || r.age_days === undefined ? "—" : T("ad_days", { n: r.age_days }); }, sort: function (r) { return r.age_days; } },
            { key: "artifact_exists", label: "am_c_file", cell: function (r) { return PK.chip(r.artifact_exists ? T("am_file_ok") : T("am_file_missing"), r.artifact_exists ? "ok" : "warn"); }, sort: function (r) { return r.artifact_exists ? 1 : 0; } },
        ];
        var drawKpis = function (d) {
            var box = PK.clear(document.getElementById("am-kpis")), c = d.counts;
            box.appendChild(PK.kpi(T("am_k_pairs"), int(c.pairs), T("am_k_pairs_sub"), "neutral"));
            box.appendChild(PK.kpi(T("am_k_explicit"), int(c.explicit), T("am_k_explicit_sub"), "neutral"));
            box.appendChild(PK.kpi(T("am_k_stale"), int(c.stale), T("am_k_stale_sub", { d: d.stale_days }), c.stale ? "warning" : "ok"));
            box.appendChild(PK.kpi(T("am_k_nofile"), int(c.no_file), T("am_k_nofile_sub"), c.no_file ? "warning" : "ok"));
        };
        var drawFilters = function () {
            var box = PK.clear(document.getElementById("am-filters"));
            var s = h("input", { type: "search", placeholder: T("ag_filter_q"), "aria-label": T("ag_filter_q"), value: st.q });
            s.addEventListener("input", function () { st.q = s.value; st.page = 0; drawTable(); });
            box.appendChild(s);
            box.appendChild(PK.select([{ value: "", label: T("ah_all_status") }, { value: "explicit", label: T("am_explicit") }, { value: "implicit", label: T("am_implicit") }, { value: "stale", label: T("am_stale") }, { value: "nofile", label: T("am_file_missing") }], st.status, function (v) { st.status = v; st.page = 0; drawTable(); }, T("am_c_title")));
        };
        var drawTable = function () {
            var host = document.getElementById("am-table"), q = st.q.trim().toLowerCase();
            var rows = st.items.filter(function (r) {
                if (q && !PK.instMatch(r.target, q)) return false;
                if (st.status === "explicit" && r.implicit) return false;
                if (st.status === "implicit" && !r.implicit) return false;
                if (st.status === "stale" && !(r.age_days > 90)) return false;
                if (st.status === "nofile" && r.artifact_exists) return false;
                return true;
            });
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
                function by() { if (st.sortKey === c.key) st.sortDir = -st.sortDir; else { st.sortKey = c.key; st.sortDir = 1; } drawTable(); }
                th.addEventListener("click", by); th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); by(); } });
                return th;
            }));
            var tbody = h("tbody", {}, slice.map(function (r) { return h("tr", {}, COLS.map(function (c) { var td = h("td", { class: c.num ? "num pk-mono" : "" }), v = c.cell(r); if (v && v.nodeType) td.appendChild(v); else td.textContent = v; return td; })); }));
            PK.clear(host).appendChild(h("div", { class: "table-scroll" }, [h("table", { class: "data-table ra-sortable" }, [h("thead", {}, [thead]), tbody])]));
            host.appendChild(PK.info(T("am_rows", { n: int(rows.length), total: int(st.items.length) })));
            var pager = PK.clear(document.getElementById("am-pager"));
            if (pages > 1) {
                var prev = h("button", { type: "button", class: "btn-secondary", text: T("ah_prev") }), next = h("button", { type: "button", class: "btn-secondary", text: T("ah_next") });
                prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
                prev.addEventListener("click", function () { st.page--; drawTable(); }); next.addEventListener("click", function () { st.page++; drawTable(); });
                pager.appendChild(prev); pager.appendChild(h("span", { class: "pk-mono", text: (st.page + 1) + " / " + pages })); pager.appendChild(next);
            }
        };
        PK.fetchJSON("/api/modeles/overview").then(function (d) { st.items = d.items; drawKpis(d); drawFilters(); drawTable(); listRoot.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true })); })
            .catch(function (e) { PK.clear(document.getElementById("am-table")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); });
    }

    // ================================================================ fiche
    var cardRoot = document.getElementById("am-card");
    if (cardRoot) {
        var target = cardRoot.getAttribute("data-target"), horizon = +cardRoot.getAttribute("data-horizon");
        var section = function (title, node, hint) { return h("section", { class: "card ra-section" }, [h("h2", { text: title }), hint ? PK.note(hint) : null, node]); };
        var fmtParams = function (p) {
            var o = {};
            Object.keys(p || {}).forEach(function (k) { var v = p[k]; o[k] = v === null || v === undefined ? "—" : (typeof v === "number" ? (k === "p" ? PK.pval(v) : (Math.abs(v) <= 1 && k !== "n" && k !== "m" && k !== "d" && k !== "h" ? pct(v, 1) : num(v, 3))) : v); });
            return o;
        };
        var render = function (d) {
            PK.clear(cardRoot);
            var c = d.current, hd = d.metrics || {};
            var grid = h("div", { class: "metric-grid ra-kpis" }, [
                PK.kpi(T("am_k_model"), (c.algo || "—") + " · N=" + (c.n_features || "—"), c.implicit ? T("am_implicit_sub") : T("am_explicit_sub", { d: (c.promoted_at || "").slice(0, 10), r: c.reason }), c.implicit ? "neutral" : "ok"),
                PK.kpi(T("ra_k_acc_test"), hd.test ? pct(hd.test.acc, 1) : "—", hd.test ? T("ra_k_acc_sub", { lo: pct(hd.test.acc_lo, 1), hi: pct(hd.test.acc_hi, 1), maj: pct(Math.max(hd.test.base_up, 1 - hd.test.base_up), 1), n: int(hd.test.n) }) : "", "neutral"),
                PK.kpi(T("ra_k_acc_holdout"), hd.holdout ? pct(hd.holdout.acc, 1) : "—", hd.holdout ? T("ra_k_acc_sub", { lo: pct(hd.holdout.acc_lo, 1), hi: pct(hd.holdout.acc_hi, 1), maj: pct(Math.max(hd.holdout.base_up, 1 - hd.holdout.base_up), 1), n: int(hd.holdout.n) }) : "", "neutral"),
                PK.kpi(T("am_k_live"), d.live.judged ? pct(d.live.hit, 0) : "—", T("am_k_live_sub", { j: d.live.judged, n: d.live.n }), "neutral"),
                PK.kpi(T("nav_drift"), d.drift.action ? T("ad_a_" + d.drift.action) : "—", d.drift.reason || "", d.drift.action === "retrain" ? "error" : (d.drift.action === "watch" ? "warning" : "neutral"))]);
            cardRoot.appendChild(grid);
            var links = h("p", { class: "row" }, [h("a", { class: "btn-secondary", href: "/runs/" + encodeURIComponent(c.run_id) + "/analyse", text: T("ra_open_analysis") }), h("a", { class: "btn-secondary", href: "/runs/" + encodeURIComponent(c.run_id) + "/analyse/export", download: "", text: T("ra_export_html") }),
                h("a", { class: "btn-secondary", href: "/targets/" + encodeURIComponent(target), text: T("am_open_target") }), h("a", { class: "btn-secondary", href: "/derive", text: T("nav_drift") })]);
            cardRoot.appendChild(links);

            var lim = h("ul", { class: "ra-guide" }, d.limits.map(function (l) {
                return h("li", { class: "ra-guide-" + l.level }, [h("span", { class: "ra-guide-icon", "aria-hidden": "true", text: l.level === "warn" ? "!" : "i" }), h("span", { text: l.key.indexOf("g_") === 0 ? T("ra_g_" + l.key.slice(2), fmtGuide(l.params)) : T("am_l_" + l.key, fmtParams(l.params)) })]);
            }));
            cardRoot.appendChild(section(T("am_s_limits"), d.limits.length ? lim : PK.empty(T("am_no_limits")), T("am_h_limits")));

            var dt = d.data, items = [[T("ra_id_snapshot"), dt.snapshot_id], [T("ra_id_config"), dt.config_hash], [T("ra_id_git"), dt.git_sha ? String(dt.git_sha).slice(0, 10) : "—"], [T("ra_id_seed"), dt.seed], [T("ra_id_scheme"), dt.scheme === "cpcv" ? "CPCV" : "walk-forward"],
                [T("am_d_from"), dt.trained_from], [T("am_d_test_from"), dt.trained_to], [T("ra_id_nfeat"), dt.n_features], [T("am_d_calib"), dt.calibration === null ? "—" : (dt.calibration ? T("ra_on") : T("ra_off"))]];
            var dl = h("dl", { class: "rp-grid ra-ident" }, items.map(function (p) { return h("div", {}, [h("dt", { text: p[0] }), h("dd", { class: "pk-mono", text: p[1] === undefined || p[1] === null ? "—" : String(p[1]) })]); }));
            var data = h("div", {}, [dl]);
            if (dt.top_features.length) data.appendChild(h("div", { class: "ra-chips" }, dt.top_features.map(function (f) { return PK.chip(f); })));
            cardRoot.appendChild(section(T("am_s_data"), data, T("am_h_data")));

            var g = d.guardrails;
            if (g) {
                cardRoot.appendChild(section(T("ag_s_pairs"), h("div", { class: "ra-chips" }, [PK.chip(T("am_g_trials", { n: int(g.trials) })), PK.chip(T("am_g_pdef", { p: PK.pval(g.p_deflated) }), g.verdict === "beyond_noise" ? "ok" : "warn"), PK.chip(T("am_g_reads", { r: g.reads_recorded, i: g.reads_inferred, d: g.duels })), PK.chip(T("ag_v_" + (g.verdict || "within_noise")))]), T("ag_h_pairs")));
            }

            var vrows = d.versions.map(function (v) {
                var btn = v.current ? PK.chip(T("am_current"), "ok") : h("button", { type: "button", class: "btn-secondary", text: T("am_promote"), disabled: !v.artifact_exists });
                if (!v.current) btn.addEventListener("click", function () { promote(v); });
                return [{ cell: h("a", { href: "/runs/" + encodeURIComponent(v.run_id) + "/analyse", text: v.run_id }) }, (v.started_at || "").slice(0, 16), v.algo || "—", v.n_features, isNum(v.f1_test) ? num(v.f1_test, 3) : "—", isNum(v.f1_holdout) ? num(v.f1_holdout, 3) : "—", v.live_judged ? v.live_judged + " · " + pct(v.live_hit, 0) : "—", PK.chip(v.artifact_exists ? T("am_file_ok") : T("am_file_missing"), v.artifact_exists ? "ok" : "warn"), { cell: btn }];
            });
            cardRoot.appendChild(section(T("am_s_versions"), PK.table([T("ah_c_name"), T("ah_c_started"), T("ah_c_algo"), T("ah_c_nfeat"), T("ah_c_f1_test").split(" · ")[0], T("ah_c_f1_hold").split(" · ")[0], T("am_c_live"), T("am_c_file"), ""], vrows, { num: [3, 4, 5] }), T("am_h_versions")));

            if (d.archive.length) {
                var arows = d.archive.map(function (a) {
                    var duel = a.duel || {}, ch = duel.challenger && isNum(duel.challenger.f1_dir) ? num(duel.challenger.f1_dir, 3) : "—", cp = duel.champion && isNum(duel.champion.f1_dir) ? num(duel.champion.f1_dir, 3) : "—";
                    return [a.decided_at, T("am_role_" + a.role), a.run_id, a.algo || "—", a.n_features === null ? "—" : a.n_features, isNum(a.f1_dir) ? num(a.f1_dir, 3) : "—", cp + " / " + ch];
                });
                cardRoot.appendChild(section(T("am_s_archive"), PK.table([T("ra_hl_a_when"), T("am_c_role"), T("ra_hl_a_run"), T("ah_c_algo"), T("ah_c_nfeat"), "F1 WF", T("am_c_duel")], arows, { num: [4, 5] }), T("am_h_archive")));
            }
            cardRoot.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
        };
        var fmtGuide = function (p) {
            var PCT = { acc: 1, maj: 1, lo: 1, hi: 1, test: 1, holdout: 1, share: 1, base: 1, worst: 1, max_dd: 1, bh_dd: 1, ret: 1, bh_ret: 1, dsr: 1 }, o = {};
            Object.keys(p || {}).forEach(function (k) { var v = p[k]; o[k] = v === null || v === undefined ? "—" : (typeof v === "string" ? v : (k === "p" ? PK.pval(v) : (PCT[k] ? pct(v, 1) : (k === "edge" || k === "drop" || k === "spread" ? PK.spct(v, 1) : (["auc", "rho", "ece", "brier", "base_brier", "sharpe", "bh_sharpe"].indexOf(k) >= 0 ? num(v, 3) : int(v)))))); });
            return o;
        };
        var load = function () {
            PK.fetchJSON("/api/modeles/card?target=" + encodeURIComponent(target) + "&horizon=" + horizon).then(render)
                .catch(function (e) { PK.clear(cardRoot).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); });
        };
        var promote = async function (v) {
            var ok = window.patrickDialog ? await window.patrickDialog.confirm(T("am_promote_confirm", { t: PK.inst(target), h: horizon, r: v.run_id }), T("am_promote"), false) : false;
            if (!ok) return;
            fetch("/api/modeles/promote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target: target, horizon: horizon, run_id: v.run_id }) })
                .then(function (r) { return r.json().then(function (b) { if (!r.ok) throw new Error(T("am_err_" + (b.detail || "unknown"))); return b; }); })
                .then(function () { load(); })
                .catch(function (e) { cardRoot.insertBefore(h("p", { class: "banner banner-error", role: "alert", text: e.message }), cardRoot.firstChild); });
        };
        load();
    }
})();
