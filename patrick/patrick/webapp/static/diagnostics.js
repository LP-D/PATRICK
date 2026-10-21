/* Page /diagnostics : processeur, mémoire, disques, processus PATRICK, base de suivi, file de jobs, dossiers de données, journaux (dernières lignes).
   Lecture seule. Données : /api/diagnostics/system, /api/diagnostics/storage, /api/diagnostics/logs, /api/diagnostics/log. */
(function () {
    "use strict";
    var PK = window.PK, root = document.getElementById("dg-root");
    if (!PK || !root) return;
    var T = PK.T, h = PK.h, num = PK.num, pct = PK.pct, int = PK.int, isNum = PK.isNum;
    var st = { auto: true, timer: null, log: "", lines: 200, onlyErr: false, filter: "" };

    function bytes(v) {
        if (!isNum(v)) return "—";
        var u = ["o", "Ko", "Mo", "Go", "To"], i = 0;
        while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
        return num(v, v >= 100 || i === 0 ? 0 : 1) + " " + u[i];
    }
    function gauge(label, value, sub, warnAt) {
        var kind = value >= (warnAt || 90) ? "error" : (value >= (warnAt || 90) - 15 ? "warning" : "ok");
        return PK.kpi(label, num(value, 0) + " %", sub, kind);
    }
    function bar(valuePct, color) { return h("span", { class: "ra-hbar-track" }, [h("i", { style: { width: Math.max(0, Math.min(100, valuePct)).toFixed(1) + "%", background: color || "var(--brand)" } })]); }

    function renderSystem(d) {
        var s = d.system, a = d.app;
        var box = PK.clear(document.getElementById("dg-kpis"));
        box.appendChild(gauge(T("dg_k_cpu"), s.cpu_percent, T("dg_k_cpu_sub", { n: s.cpu_count, f: s.cpu_freq_mhz ? Math.round(s.cpu_freq_mhz) : "—" }), 85));
        box.appendChild(gauge(T("dg_k_ram"), s.memory.percent, T("dg_k_ram_sub", { a: bytes(s.memory.available), t: bytes(s.memory.total) }), 90));
        var data = s.disks.filter(function (x) { return x.holds_data; })[0] || s.disks[0];
        if (data) box.appendChild(gauge(T("dg_k_disk"), data.percent, T("dg_k_disk_sub", { m: data.mount, f: bytes(data.free) }), 92));
        var hb = a.heartbeat;
        box.appendChild(PK.kpi(T("dg_k_worker"), hb ? (hb.alive && hb.age_s !== null && hb.age_s < 60 ? T("dg_alive") : T("dg_stale")) : T("dg_none"), hb ? T("dg_k_worker_sub", { p: hb.pid, a: hb.age_s !== null ? Math.round(hb.age_s) : "—" }) : T("dg_k_worker_none"), hb && hb.alive && hb.age_s < 60 ? "ok" : (hb ? "warning" : "neutral")));
        var j = a.jobs;
        box.appendChild(PK.kpi(T("dg_k_queue"), int((j.queued || 0) + (j.running || 0)), T("dg_k_queue_sub", { r: j.running || 0, q: j.queued || 0, d: j.done || 0 }), "neutral"));

        var items = [[T("dg_a_db"), a.db_path], [T("dg_a_dbsize"), Object.keys(a.db_files).map(function (k) { return k + " " + bytes(a.db_files[k]); }).join(" · ")], [T("dg_a_schema"), a.schema_version], [T("ra_id_git"), a.git ? String(a.git).slice(0, 10) : "—"],
            [T("dg_a_version"), a.version || "—"], [T("dg_a_runs"), Object.keys(a.runs).map(function (k) { return k + " " + a.runs[k]; }).join(" · ")], [T("dg_a_python"), s.python], [T("dg_a_platform"), s.platform], [T("dg_a_boot"), s.boot_time], [T("dg_a_home"), s.home]];
        PK.clear(document.getElementById("dg-app")).appendChild(h("dl", { class: "rp-grid ra-ident" }, items.map(function (p) { return h("div", {}, [h("dt", { text: p[0] }), h("dd", { class: "pk-mono", text: p[1] === undefined || p[1] === null ? "—" : String(p[1]) })]); })));

        var rows = d.processes.map(function (p) { return [PK.chip(T("dg_role_" + p.role), p.role === "worker" ? "ok" : (p.role === "server" ? "neutral" : "warn")), p.pid, bytes(p.rss), p.started, { cell: p.cmd, cls: "pk-mono" }]; });
        PK.clear(document.getElementById("dg-proc")).appendChild(rows.length ? PK.table([T("dg_c_role"), "PID", T("dg_c_mem"), T("dg_c_started"), T("dg_c_cmd")], rows, { num: [1, 2] }) : PK.empty(T("dg_no_proc")));

        var cores = h("div", { class: "ra-hbars" }, s.cpu_per_core.map(function (v, i) { return h("div", { class: "ra-hbar" }, [h("span", { class: "ra-hbar-label", text: T("dg_core", { n: i + 1 }) }), bar(v, v > 85 ? "var(--neg)" : "var(--brand)"), h("span", { class: "ra-hbar-val pk-mono", text: num(v, 0) + " %" })]); }));
        PK.clear(document.getElementById("dg-cpu")).appendChild(cores);

        PK.clear(document.getElementById("dg-disks")).appendChild(PK.table([T("dg_c_mount"), T("dg_c_total"), T("dg_c_used"), T("dg_c_free"), T("dg_c_percent"), T("dg_c_data")],
            s.disks.map(function (x) { return [x.mount, bytes(x.total), bytes(x.used), bytes(x.free), { cell: num(x.percent, 0) + " %", cls: x.percent > 92 ? "neg" : "" }, x.holds_data ? PK.chip(T("dg_data_here"), "ok") : ""]; }), { num: [1, 2, 3, 4] }));
        root.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
    }
    function loadSystem() { PK.fetchJSON("/api/diagnostics/system").then(renderSystem).catch(function (e) { PK.clear(document.getElementById("dg-app")).appendChild(h("p", { class: "banner banner-error", role: "alert", text: T("ra_error") + " " + e.message })); }); }
    function loadStorage() {
        PK.fetchJSON("/api/diagnostics/storage").then(function (d) {
            var mx = Math.max.apply(null, d.items.map(function (i) { return i.bytes; }).concat([1]));
            var rows = d.items.map(function (i) { return [i.name, { cell: i.exists ? bytes(i.bytes) + (i.partial ? " +" : "") : T("dg_absent"), cls: "" }, i.exists ? int(i.files) : "—", { cell: bar(i.bytes / mx * 100, "var(--ra-c2)") }, { cell: i.path, cls: "pk-mono" }]; });
            var host = PK.clear(document.getElementById("dg-storage"));
            host.appendChild(PK.table([T("dg_c_folder"), T("dg_c_size"), T("dg_c_files"), "", T("dg_c_path")], rows, { num: [1, 2] }));
            host.appendChild(PK.info(T("dg_storage_total", { t: bytes(d.total) }) + (d.partial ? " " + T("dg_partial") : "")));
        }).catch(function (e) { PK.clear(document.getElementById("dg-storage")).appendChild(PK.empty(e.message)); });
    }

    // ---------------------------------------------------------------- journaux
    var pre = document.getElementById("dg-log");
    function loadLog() {
        if (!st.log) return;
        PK.fetchJSON("/api/diagnostics/log?name=" + encodeURIComponent(st.log) + "&lines=" + st.lines).then(function (d) {
            var lines = d.lines, f = st.filter.trim().toLowerCase();
            if (st.onlyErr) lines = lines.filter(function (l) { return /error|exception|traceback|failed|erreur|critical/i.test(l); });
            if (f) lines = lines.filter(function (l) { return l.toLowerCase().indexOf(f) >= 0; });
            var atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
            pre.textContent = lines.join("\n") || T("dg_log_empty");
            if (atBottom) pre.scrollTop = pre.scrollHeight;
        }).catch(function (e) { pre.textContent = e.message; });
    }
    function logControls(files) {
        var box = PK.clear(document.getElementById("dg-log-controls"));
        if (!files.length) { box.appendChild(PK.empty(T("dg_no_logs"))); return; }
        if (!st.log) st.log = files[0].name;
        box.appendChild(PK.select(files.map(function (f) { return { value: f.name, label: f.name + " · " + bytes(f.bytes) + " · " + f.modified }; }), st.log, function (v) { st.log = v; loadLog(); }, T("dg_f_file")));
        box.appendChild(PK.select([100, 200, 500].map(function (n) { return { value: n, label: T("dg_lines", { n: n }) }; }), st.lines, function (v) { st.lines = +v; loadLog(); }));
        var cb = h("input", { type: "checkbox" });
        cb.addEventListener("change", function () { st.onlyErr = cb.checked; loadLog(); });
        box.appendChild(h("label", { class: "ra-control" }, [cb, h("span", { text: T("dg_only_errors") })]));
        var q = h("input", { type: "search", class: "ra-num", style: { width: "170px" }, placeholder: T("dg_filter"), "aria-label": T("dg_filter") });
        q.addEventListener("input", function () { st.filter = q.value; loadLog(); });
        box.appendChild(q);
        loadLog();
    }

    function controls() {
        var box = document.getElementById("dg-controls");
        var cb = h("input", { type: "checkbox" });
        cb.checked = true;
        cb.addEventListener("change", function () { st.auto = cb.checked; schedule(); });
        box.appendChild(h("label", { class: "ra-control" }, [cb, h("span", { text: T("dg_auto") })]));
        var now = h("button", { type: "button", class: "btn-secondary", text: T("dg_refresh") });
        now.addEventListener("click", function () { loadSystem(); loadStorage(); loadLog(); });
        box.appendChild(now);
    }
    function schedule() {
        if (st.timer) clearInterval(st.timer);
        st.timer = st.auto ? setInterval(function () { if (!document.hidden) { loadSystem(); if (st.log) loadLog(); } }, 5000) : null;
    }

    controls(); loadSystem(); loadStorage();
    PK.fetchJSON("/api/diagnostics/logs").then(logControls).catch(function (e) { PK.clear(document.getElementById("dg-log-controls")).appendChild(PK.empty(e.message)); });
    schedule();
})();
