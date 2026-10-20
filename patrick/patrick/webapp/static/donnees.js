/* Page /donnees : data lake, vue « point dans le temps », révisions entre instantanés, calendrier estimé des publications, listes de suivi,
   import d'une série personnelle. Données : /api/donnees/*. Texte toujours par textContent. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("dx-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, spct = PK.spct, int = PK.int, isNum = PK.isNum;
    var PANELS = ["lake", "pit", "rev", "cal", "watch", "import"];
    var st = { tab: "lake", lake: null, key: "", snapshot: "", asOf: "", compare: "", column: "", frame: null, onlyStale: false, filter: "", loaded: {}, wid: null, preview: null, file: null };
    var seq = { frame: 0, series: 0, watch: 0 };

    function box(id) { return PK.clear(document.getElementById(id)); }
    function skeleton() { return h("div", { class: "ra-skeleton", role: "status", "aria-label": T("dx_loading") }, [h("div", { class: "skeleton-line", style: { width: "70%" } })]); }
    function errText(e) { var m = String(e && e.message || e), k = "dx_err_" + m, t = T(k); return t === k ? m : t; }
    function fail(id, e) { box(id).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("dx_error") + " " + errText(e) })); }
    function done() { root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true })); }
    function send(method, url, body) {
        return fetch(url, { method: method, headers: { "Content-Type": "application/json", Accept: "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (b) { if (!r.ok) throw new Error(b.detail || ("HTTP " + r.status)); return b; });
        });
    }
    function label(text, control) { return h("label", { class: "ra-control" }, [h("span", { text: text }), control]); }
    function textInput(value, ph, width, list) {
        var a = { type: "text", class: "ra-num", value: value || "", placeholder: ph || "", style: { width: width || "180px" } };
        if (list) a.list = list;
        return h("input", a);
    }
    function nearest(arr, v) {
        var lo = 0, hi = arr.length - 1;
        if (hi < 0) return -1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (arr[mid] < v) lo = mid; else hi = mid; }
        return Math.abs(arr[lo] - v) <= Math.abs(arr[hi] - v) ? lo : hi;
    }
    function fmtVal(v) { return isNum(v) ? (Math.abs(v) >= 1000 ? int(v) : num(v, Math.abs(v) < 1 ? 4 : 2)) : (v === null || v === undefined ? "—" : String(v)); }

    // ------------------------------------------------------------------------------------------------ onglets
    function tabs() {
        var c = box("dx-tabs");
        c.appendChild(PK.segmented(PANELS.map(function (p) { return { value: p, label: T("dx_tab_" + p) }; }), st.tab, function (v) { show(v); }));
    }
    function show(tab) {
        st.tab = tab;
        PANELS.forEach(function (p) { document.getElementById("dx-p-" + p).hidden = p !== tab; });
        if (!st.loaded[tab]) { st.loaded[tab] = true; ({ lake: loadLake, pit: initPit, rev: initRev, cal: loadCal, watch: initWatch, import: initImport })[tab](); }
        else if (tab === "rev") initRev();
        done();
    }
    function openKey(key) { st.key = key; st.snapshot = ""; st.compare = ""; st.column = ""; st.loaded.pit = false; st.loaded.rev = false; show("pit"); }

    // ------------------------------------------------------------------------------------------------ lake
    function loadLake() {
        box("dx-lake").appendChild(skeleton());
        PK.fetchJSON("/api/donnees/lake").then(function (d) {
            st.lake = d;
            var dl = box("dx-keys");
            d.keys.forEach(function (k) { dl.appendChild(h("option", { value: k.key })); });
            var kind = "all", q = "";
            var c = box("dx-lake-controls");
            var inp = textInput("", T("dx_f_search"), "200px");
            inp.setAttribute("aria-label", T("dx_f_search"));
            inp.addEventListener("input", function () { q = inp.value.trim().toLowerCase(); draw(); });
            c.appendChild(inp);
            c.appendChild(PK.select(["all", "raw", "user", "other"].map(function (k) { return { value: k, label: T("dx_k_" + k) }; }), kind, function (v) { kind = v; draw(); }, T("dx_f_kind")));
            function draw() {
                var rows = d.keys.filter(function (k) { return (kind === "all" || k.kind === kind) && (!q || k.key.toLowerCase().indexOf(q) >= 0); });
                var host = box("dx-lake");
                host.appendChild(PK.info(T("dx_lake_summary", { k: int(d.n_keys), s: int(d.n_snapshots), r: d.root })));
                var shown = rows.slice(0, 300);
                var table = PK.table([T("dx_c_key"), T("dx_c_snaps"), T("dx_c_rows"), T("dx_c_cols"), T("dx_c_from"), T("dx_c_to"), T("dx_c_created"), T("dx_c_pit")],
                    shown.map(function (k) { return [{ cell: h("a", { href: "#", text: k.key, "data-key": k.key }) }, int(k.n_snapshots), int(k.rows), int(k.cols), k.date_min, k.date_max, (k.created_at || "").slice(0, 16).replace("T", " "), { cell: k.pit_version || "—", cls: "pk-mono" }]; }), { num: [1, 2, 3] });
                table.addEventListener("click", function (ev) { var a = ev.target.closest("a[data-key]"); if (a) { ev.preventDefault(); openKey(a.getAttribute("data-key")); } });
                host.appendChild(table);
                if (rows.length > shown.length) host.appendChild(PK.note(T("dx_shown", { n: shown.length, t: rows.length })));
                done();
            }
            draw();
        }).catch(function (e) { fail("dx-lake", e); });
    }

    // ------------------------------------------------------------------------------------------------ point dans le temps
    function pitControls(snaps) {
        var c = box("dx-pit-controls");
        var key = textInput(st.key, T("dx_f_key"), "220px", "dx-keys");
        key.setAttribute("aria-label", T("dx_f_key"));
        var go = h("button", { type: "button", class: "btn-secondary", text: T("dx_open") });
        go.addEventListener("click", function () { if (key.value.trim()) { st.key = key.value.trim(); st.snapshot = ""; st.compare = ""; st.column = ""; st.loaded.rev = false; loadFrame(); } });
        key.addEventListener("keydown", function (e) { if (e.key === "Enter") go.click(); });
        c.appendChild(label(T("dx_f_key"), key));
        c.appendChild(go);
        if (snaps && snaps.length) {
            var opts = snaps.map(function (s) { return { value: s.snapshot_id, label: (s.created_at || "").slice(0, 16).replace("T", " ") + " · " + int(s.rows) + " · " + (s.hash || "") }; }).reverse();
            c.appendChild(PK.select(opts, st.snapshot || snaps[snaps.length - 1].snapshot_id, function (v) { st.snapshot = v; loadFrame(); }, T("dx_f_snapshot")));
            var date = h("input", { type: "date", class: "ra-num", value: st.asOf || "" });
            date.addEventListener("change", function () { st.asOf = date.value; loadFrame(); });
            c.appendChild(label(T("dx_f_asof"), date));
            c.appendChild(PK.select([{ value: "", label: T("dx_none") }].concat(opts), st.compare, function (v) { st.compare = v; if (st.column) loadSeries(); }, T("dx_f_compare")));
        }
    }
    function initPit() {
        pitControls(null);
        if (st.key) loadFrame();
    }
    function loadFrame() {
        var n = ++seq.frame;
        box("dx-pit").appendChild(skeleton());
        box("dx-series");
        PK.fetchJSON("/api/donnees/frame?" + PK.qs({ key: st.key, snapshot: st.snapshot, as_of: st.asOf })).then(function (d) {
            if (n !== seq.frame) return;
            st.frame = d;
            if (!st.asOf) st.asOf = d.as_of;
            if (!st.snapshot) st.snapshot = d.snapshot_id;
            pitControls(d.snapshots);
            renderFrame(d);
        }).catch(function (e) { if (n === seq.frame) fail("dx-pit", e); });
    }
    function renderFrame(d) {
        var host = box("dx-pit");
        host.appendChild(PK.info(T("dx_pit_head", { k: d.key, s: d.snapshot_id, a: d.date_min, b: d.date_max, r: int(d.rows), n: d.n_columns, t: d.as_of, v: int(d.visible_rows) })));
        host.appendChild(PK.info(d.known_snapshot ? T("dx_pit_known", { s: d.known_snapshot }) : T("dx_pit_unknown")));
        host.appendChild(h("div", { class: "ra-legend" }, [PK.chip(T("dx_ok") + " " + d.counts.ok, "ok"), PK.chip(T("dx_stale") + " " + d.counts.stale, d.counts.stale ? "warn" : "neutral"), PK.chip(T("dx_empty") + " " + d.counts.empty, "neutral")]));
        var controls = h("div", { class: "ra-controls" });
        var q = textInput(st.filter, T("dx_f_column"), "180px");
        q.addEventListener("input", function () { st.filter = q.value; draw(); });
        var cb = h("input", { type: "checkbox" });
        cb.checked = st.onlyStale;
        cb.addEventListener("change", function () { st.onlyStale = cb.checked; draw(); });
        controls.appendChild(q);
        controls.appendChild(h("label", { class: "ra-control" }, [cb, h("span", { text: T("dx_only_stale") })]));
        host.appendChild(controls);
        var holder = h("div", {});
        host.appendChild(holder);
        host.appendChild(PK.note(T("dx_pit_note")));
        function draw() {
            var f = st.filter.trim().toLowerCase();
            var rows = d.columns.filter(function (c) { return (!st.onlyStale || c.status === "stale") && (!f || c.column.toLowerCase().indexOf(f) >= 0); }).slice(0, 250);
            PK.clear(holder).appendChild(PK.table([T("dx_c_column"), T("dx_c_status"), T("dx_c_value"), T("dx_c_change"), T("dx_c_age"), T("dx_c_typ"), T("dx_c_cov"), T("dx_c_first")],
                rows.map(function (c) {
                    return [{ cell: h("a", { href: "#", text: c.column, "data-col": c.column }) }, { cell: PK.chip(T("dx_" + c.status), c.status === "ok" ? "ok" : (c.status === "stale" ? "warn" : "neutral")) }, fmtVal(c.last_value), c.last_change || "—",
                        isNum(c.stale_days) ? int(c.stale_days) : "—", isNum(c.typical_days) ? num(c.typical_days, 1) : "—", pct(c.coverage_252, 0), c.first_date || "—"];
                }), { num: [2, 4, 5, 6] }));
            done();
        }
        holder.addEventListener("click", function (ev) { var a = ev.target.closest("a[data-col]"); if (a) { ev.preventDefault(); st.column = a.getAttribute("data-col"); loadSeries(); } });
        draw();
    }
    function loadSeries() {
        var n = ++seq.series;
        box("dx-series").appendChild(skeleton());
        PK.fetchJSON("/api/donnees/series?" + PK.qs({ key: st.key, column: st.column, snapshot: st.snapshot, as_of: st.asOf, compare: st.compare })).then(function (d) {
            if (n !== seq.series) return;
            var host = box("dx-series"), vx = d.dates.map(PK.dateMs), ax = d.after_dates.map(PK.dateMs), cx = d.compare ? d.compare.dates.map(PK.dateMs) : [];
            var xs = vx.concat(ax, cx);
            if (!xs.length) return;
            var lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs), pad = (hi - lo) * 0.01 || 86400000;
            var ys = [d.values, d.after_values].concat(d.compare ? [d.compare.values] : []);
            var P = PK.plot({ w: 780, h: 260, x: { type: "time", domain: [lo - pad, hi + pad] }, y: { domain: PK.extent(ys, 0.06), fmt: fmtVal, zero: false }, title: T("dx_series_title", { c: d.column, t: d.as_of }) });
            if (ax.length) PK.line(P, ax, d.after_values, { color: "var(--text-3)", width: 1.2, dash: "4 3" });
            if (d.compare) PK.line(P, cx, d.compare.values, { color: "var(--ra-c2)", width: 1.4 });
            PK.line(P, vx, d.values, { color: "var(--ra-c1)", width: 1.6 });
            PK.vline(P, PK.dateMs(d.as_of), { color: "var(--warn)" });
            PK.hover(P, function (xv) {
                var i = nearest(vx, xv), lines = i < 0 ? [] : [PK.dateStr(vx[i]), fmtVal(d.values[i])];
                if (d.compare) { var j = nearest(cx, xv); if (j >= 0) lines.push(T("dx_series_compare") + " " + fmtVal(d.compare.values[j])); }
                return lines.length ? lines : null;
            });
            var items = [{ color: "var(--ra-c1)", label: T("dx_series_visible"), line: true }, { color: "var(--text-3)", label: T("dx_series_after"), line: true }];
            if (d.compare) items.push({ color: "var(--ra-c2)", label: T("dx_series_compare"), line: true });
            host.appendChild(h("div", { class: "ra-block" }, [h("h3", { text: T("dx_series_title", { c: d.column, t: d.as_of }) }), PK.legend(items), P.node]));
            done();
        }).catch(function (e) { if (n === seq.series) fail("dx-series", e); });
    }

    // ------------------------------------------------------------------------------------------------ révisions
    function initRev() {
        var c = box("dx-rev-controls");
        box("dx-rev");
        var key = textInput(st.key, T("dx_f_key"), "220px", "dx-keys");
        c.appendChild(label(T("dx_f_key"), key));
        var go = h("button", { type: "button", class: "btn-secondary", text: T("dx_open") });
        c.appendChild(go);
        function withSnaps(snaps) {
            if (snaps.length < 2) { box("dx-rev").appendChild(PK.empty(T("dx_need_two"))); return; }
            var opts = snaps.map(function (s) { return { value: s.snapshot_id, label: (s.created_at || "").slice(0, 16).replace("T", " ") + " · " + (s.hash || "") }; });
            var a = snaps[snaps.length - 2].snapshot_id, b = snaps[snaps.length - 1].snapshot_id;
            c.appendChild(PK.select(opts, a, function (v) { a = v; }, T("dx_f_a")));
            c.appendChild(PK.select(opts, b, function (v) { b = v; }, T("dx_f_b")));
            var run = h("button", { type: "button", class: "btn-secondary", text: T("dx_compare") });
            run.addEventListener("click", function () { loadRev(a, b); });
            c.appendChild(run);
        }
        go.addEventListener("click", function () {
            if (!key.value.trim()) return;
            st.key = key.value.trim();
            PK.fetchJSON("/api/donnees/frame?" + PK.qs({ key: st.key })).then(function (d) { st.frame = d; initRevSelects(d.snapshots); }).catch(function (e) { fail("dx-rev", e); });
        });
        function initRevSelects(snaps) { while (c.children.length > 2) c.removeChild(c.lastChild); withSnaps(snaps); }
        if (st.frame && st.frame.key === st.key) withSnaps(st.frame.snapshots);
        else if (st.key) go.click();
    }
    function loadRev(a, b) {
        box("dx-rev").appendChild(skeleton());
        PK.fetchJSON("/api/donnees/revisions?" + PK.qs({ key: st.key, a: a, b: b })).then(function (d) {
            var host = box("dx-rev");
            host.appendChild(PK.info(T("dx_rev_head", { o: (d.older_created || "").slice(0, 10), n: (d.newer_created || "").slice(0, 10), c: int(d.common_rows), cc: int(d.cells_changed), ro: int(d.cells_revised_old), ca: int(d.cells_appeared), cv: int(d.cells_vanished) }), d.cells_revised_old ? "warn" : ""));
            host.appendChild(PK.info(T("dx_rev_rows", { a: int(d.rows_only_older), b: int(d.rows_only_newer) })));
            if (d.columns_only_older.length || d.columns_only_newer.length) host.appendChild(PK.info(T("dx_rev_cols_only", { a: d.columns_only_older.join(", ") || "—", b: d.columns_only_newer.join(", ") || "—" })));
            if (!d.columns.length) host.appendChild(PK.info(T("dx_rev_clean"), "ok"));
            else host.appendChild(PK.table([T("dx_c_column"), T("dx_c_changed"), T("dx_c_revold"), T("dx_c_appeared"), T("dx_c_vanished"), T("dx_c_maxrel"), T("dx_c_first_d"), T("dx_c_last_d")],
                d.columns.map(function (c) { return [c.column, int(c.changed), { cell: int(c.revised_old), cls: c.revised_old ? "neg" : "" }, int(c.appeared), int(c.vanished), isNum(c.max_rel) ? pct(c.max_rel, 3) : "—", c.first, c.last]; }), { num: [1, 2, 3, 4, 5] }));
            done();
        }).catch(function (e) { fail("dx-rev", e); });
    }

    // ------------------------------------------------------------------------------------------------ calendrier
    function loadCal() {
        box("dx-cal").appendChild(skeleton());
        PK.fetchJSON("/api/donnees/calendar").then(function (d) {
            var host = box("dx-cal");
            host.appendChild(PK.info(T("dx_cal_head", { d: d.as_of, l: d.n_late, s: d.n_soon }), d.n_late ? "warn" : ""));
            var kinds = { late: "warn", soon: "ok", later: "neutral", unknown: "neutral" };
            host.appendChild(PK.table([T("dx_c_series"), T("dx_c_label"), T("dx_c_per"), T("dx_c_lastobs"), T("dx_c_next"), T("dx_c_days"), T("dx_c_late"), T("dx_c_status")],
                d.rows.map(function (r) { return [{ cell: r.series, cls: "pk-mono" }, r.label, T("dx_per_" + r.periodicity), r.last_obs || "—", r.next_expected || "—", isNum(r.days_until) ? int(r.days_until) : "—", isNum(r.late_bdays) ? int(r.late_bdays) : "—", { cell: PK.chip(T("dx_st_" + r.state), kinds[r.state]) }]; }), { num: [5, 6] }));
            done();
        }).catch(function (e) { fail("dx-cal", e); });
    }

    // ------------------------------------------------------------------------------------------------ listes de suivi
    function initWatch() {
        PK.fetchJSON("/api/donnees/symbols").then(function (s) { var dl = box("dx-symbols"); s.forEach(function (x) { dl.appendChild(h("option", { value: x })); }); }).catch(function () { /* l'autocomplétion est facultative */ });
        checkControls();
        loadLists();
    }
    function loadLists(selectId) {
        PK.fetchJSON("/api/donnees/watchlists").then(function (lists) {
            if (selectId) st.wid = selectId;
            if (!lists.some(function (l) { return l.watchlist_id === st.wid; })) st.wid = lists.length ? lists[0].watchlist_id : null;
            var c = box("dx-watch-controls");
            if (lists.length) c.appendChild(PK.select(lists.map(function (l) { return { value: l.watchlist_id, label: l.name + " (" + l.symbols.length + ")" }; }), st.wid, function (v) { st.wid = +v; loadLists(); }, T("dx_w_choose")));
            var add = h("button", { type: "button", class: "btn-secondary", text: T("dx_w_new") });
            add.addEventListener("click", function () { listForm(null); });
            c.appendChild(add);
            var cur = lists.filter(function (l) { return l.watchlist_id === st.wid; })[0];
            if (cur) { listForm(cur); loadOverview(cur.watchlist_id); }
            else { box("dx-watch-form"); box("dx-watch").appendChild(PK.empty(T("dx_w_none"))); listForm(null); }
            done();
        }).catch(function (e) { fail("dx-watch", e); });
    }
    function listForm(item) {
        var f = box("dx-watch-form");
        var name = textInput(item ? item.name : "", T("dx_w_name"), "180px");
        var symbols = h("input", { type: "text", class: "ra-num", value: item ? item.symbols.join(", ") : "", list: "dx-symbols", style: { width: "320px" }, placeholder: T("dx_w_symbols") });
        var tags = textInput(item ? item.tags.join(", ") : "", T("dx_w_tags"), "180px");
        var note = textInput(item ? item.note : "", T("dx_w_note"), "260px");
        var msg = h("span", { class: "hint", role: "status" });
        var save = h("button", { type: "button", class: "btn-secondary", text: item ? T("dx_w_save") : T("dx_w_create") });
        function body() { return { name: name.value, symbols: symbols.value, tags: tags.value, note: note.value }; }
        save.addEventListener("click", function () {
            msg.textContent = "";
            var req = item ? send("PATCH", "/api/donnees/watchlists/" + item.watchlist_id, body()).then(function () { return item.watchlist_id; }) : send("POST", "/api/donnees/watchlists", body()).then(function (r) { return r.watchlist_id; });
            req.then(function (id) { loadLists(id); }).catch(function (e) { msg.textContent = errText(e); msg.className = "hint status-error"; });
        });
        var row = h("div", { class: "ra-controls" }, [label(T("dx_w_name"), name), label(T("dx_w_symbols"), symbols), label(T("dx_w_tags"), tags), label(T("dx_w_note"), note), save]);
        if (item) {
            var del = h("button", { type: "button", class: "btn-secondary", text: T("dx_w_delete") });
            del.addEventListener("click", function () {
                window.patrickDialog.confirm(T("dx_w_delete_confirm", { n: item.name }), T("dx_w_delete_ok"), true).then(function (ok) {
                    if (ok) send("DELETE", "/api/donnees/watchlists/" + item.watchlist_id).then(function () { st.wid = null; loadLists(); }).catch(function (e) { msg.textContent = errText(e); });
                });
            });
            row.appendChild(del);
        }
        row.appendChild(msg);
        f.appendChild(row);
    }
    function spark(values) {
        var pts = values.filter(isNum);
        if (pts.length < 2) return "";
        var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts), w = 90, hh = 22, sp = hi - lo || 1;
        var d = pts.map(function (v, i) { return (i / (pts.length - 1) * w).toFixed(1) + "," + (hh - 2 - (v - lo) / sp * (hh - 4)).toFixed(1); }).join(" ");
        var up = pts[pts.length - 1] >= pts[0];
        return PK.s("svg", { viewBox: "0 0 " + w + " " + hh, width: w, height: hh, role: "img", "aria-hidden": "true" }, [PK.s("polyline", { points: d, fill: "none", stroke: up ? "var(--pos)" : "var(--neg)", "stroke-width": 1.4 })]);
    }
    function loadOverview(id) {
        var n = ++seq.watch;
        box("dx-watch").appendChild(skeleton());
        PK.fetchJSON("/api/donnees/watchlists/" + id + "/overview").then(function (d) {
            if (n !== seq.watch) return;
            var host = box("dx-watch");
            if (d.tags.length) host.appendChild(h("div", { class: "ra-legend" }, d.tags.map(function (t) { return PK.chip(t, "neutral"); })));
            if (!d.rows.length) { host.appendChild(PK.empty(T("dx_w_empty"))); return; }
            if (d.n_missing) host.appendChild(PK.info(T("dx_w_missing", { n: d.n_missing }), "warn"));
            function chg(v) { return isNum(v) ? { cell: spct(v, 1), cls: v < 0 ? "neg" : "pos" } : "—"; }
            host.appendChild(PK.table([T("dx_c_symbol"), T("dx_c_price"), T("dx_c_d1"), T("dx_c_d5"), T("dx_c_d21"), T("dx_c_d63"), T("dx_c_d252"), T("dx_c_stale"), T("dx_c_trend")],
                d.rows.map(function (r) {
                    return r.in_lake ? [r.symbol, fmtVal(r.last_price), chg(r.d1), chg(r.d5), chg(r.d21), chg(r.d63), chg(r.d252), { cell: int(r.stale_bdays), cls: r.stale_bdays > 3 ? "neg" : "" }, { cell: spark(r.spark) }]
                        : [r.symbol, { cell: T("dx_not_in_lake"), cls: "hint" }, "—", "—", "—", "—", "—", "—", ""];
                }), { num: [1, 2, 3, 4, 5, 6, 7] }));
            done();
        }).catch(function (e) { if (n === seq.watch) fail("dx-watch", e); });
    }
    function checkControls() {
        var c = box("dx-check-controls");
        var sym = textInput("", "AAPL, ^GSPC, EURUSD=X", "200px");
        sym.setAttribute("aria-label", T("dx_w_check"));
        var go = h("button", { type: "button", class: "btn-secondary", text: T("dx_w_check_go") });
        go.addEventListener("click", function () {
            var out = box("dx-check");
            out.appendChild(skeleton());
            send("POST", "/api/donnees/ticker-check", { symbol: sym.value.trim() }).then(function (r) {
                var text = T("dx_chk_" + r.status, { n: r.n_obs, a: r.first, b: r.last, r: r.reason || "" });
                PK.clear(out).appendChild(PK.info(r.symbol + " — " + text, r.status === "ok" ? "ok" : "warn"));
            }).catch(function (e) { fail("dx-check", e); });
        });
        c.appendChild(sym);
        c.appendChild(go);
    }

    // ------------------------------------------------------------------------------------------------ import
    function toBase64(buf) {
        var bytes = new Uint8Array(buf), bin = "", chunk = 0x8000;
        for (var i = 0; i < bytes.length; i += chunk) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        return btoa(bin);
    }
    function initImport() {
        var c = box("dx-import-controls");
        var file = h("input", { type: "file", accept: ".csv,.txt,.xlsx,.xlsm", "aria-label": T("dx_i_file") });
        var datecol = textInput("", T("dx_i_datecol"), "160px");
        var dayfirst = "";
        c.appendChild(label(T("dx_i_file"), file));
        c.appendChild(label(T("dx_i_datecol"), datecol));
        c.appendChild(PK.select([{ value: "", label: T("dx_i_df_auto") }, { value: "1", label: T("dx_i_df_day") }, { value: "0", label: T("dx_i_df_month") }], dayfirst, function (v) { dayfirst = v; }, T("dx_i_dayfirst")));
        var go = h("button", { type: "button", class: "btn-secondary", text: T("dx_i_preview") });
        c.appendChild(go);
        function payload(extra) {
            return new Promise(function (resolve, reject) {
                var f = file.files && file.files[0];
                if (!f) { reject(new Error("no_file")); return; }
                var rd = new FileReader();
                rd.onload = function () {
                    var b = { filename: f.name, b64: toBase64(rd.result) };
                    if (datecol.value.trim()) b.date_column = datecol.value.trim();
                    if (dayfirst !== "") b.dayfirst = dayfirst === "1";
                    resolve(Object.assign(b, extra || {}));
                };
                rd.onerror = function () { reject(new Error("bad_file")); };
                rd.readAsArrayBuffer(f);
            });
        }
        go.addEventListener("click", function () {
            box("dx-import").appendChild(skeleton());
            payload().then(function (b) { return send("POST", "/api/donnees/import", b); }).then(function (d) { st.preview = d; renderPreview(d, payload); }).catch(function (e) { fail("dx-import", e); });
        });
    }
    function renderPreview(d, payload) {
        var host = box("dx-import");
        host.appendChild(PK.info(T("dx_i_head", { n: int(d.rows), a: d.date_min, b: d.date_max, d: d.date_column, c: d.columns.length })));
        if (d.bad_dates) host.appendChild(PK.info(T("dx_i_bad_dates", { n: d.bad_dates }), "warn"));
        if (d.duplicates) host.appendChild(PK.info(T("dx_i_dups", { n: d.duplicates }), "warn"));
        if (d.dropped_columns.length) host.appendChild(PK.info(T("dx_i_dropped", { c: d.dropped_columns.join(", ") }), "warn"));
        if (d.issues.length) host.appendChild(PK.table([T("dx_c_column"), T("dx_c_issue"), T("dx_c_detail")], d.issues.map(function (i) { var k = "dx_q_" + i.reason, t = T(k); return [i.series, t === k ? i.reason : t, i.detail]; })));
        else host.appendChild(PK.info(T("dx_i_clean"), "ok"));
        var cols = d.columns.slice(0, 6), dates = d.spark_dates.map(PK.dateMs);
        if (dates.length > 1 && cols.length) {
            var series = cols.map(function (c, i) { return { c: c, y: d.spark[c], color: "var(--ra-c" + (i + 1) + ")" }; });
            var P = PK.plot({ w: 780, h: 220, x: { type: "time", domain: [dates[0], dates[dates.length - 1]] }, y: { domain: PK.extent(series.map(function (s) { return s.y; }), 0.06), fmt: fmtVal, zero: false }, title: T("dx_i_preview") });
            series.forEach(function (s) { PK.line(P, dates, s.y, { color: s.color, width: 1.4 }); });
            host.appendChild(PK.legend(series.map(function (s) { return { color: s.color, label: s.c, line: true }; })));
            host.appendChild(P.node);
        }
        host.appendChild(PK.table([T("dx_f_asof")].concat(d.columns.map(String)), d.head.map(function (r) { return [r.date].concat(d.columns.map(function (c) { return fmtVal(r[c]); })); }), { num: d.columns.map(function (_, i) { return i + 1; }) }));
        if (!d.ok) { host.appendChild(PK.info(T("dx_i_short", { n: d.min_rows }), "warn")); return; }
        var name = textInput("", T("dx_i_name"), "220px");
        var save = h("button", { type: "button", class: "btn-secondary", text: T("dx_i_save") });
        var msg = h("p", { class: "hint", role: "status", "data-keep": "1" });
        save.addEventListener("click", function () {
            msg.textContent = "";
            payload({ commit: true, name: name.value }).then(function (b) { return send("POST", "/api/donnees/import", b); }).then(function (r) {
                msg.textContent = T("dx_i_saved", { k: r.saved.key, s: r.saved.snapshot_id });
                msg.className = "hint status-ok";
                st.loaded.lake = false;
            }).catch(function (e) { msg.textContent = errText(e); msg.className = "hint status-error"; });
        });
        host.appendChild(h("div", { class: "ra-controls" }, [label(T("dx_i_name"), name), save]));
        host.appendChild(msg);
        done();
    }

    tabs();
    show("lake");
})();
