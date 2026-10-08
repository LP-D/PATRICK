/* Page Réglages (/reglages) : tout passe par /api/app/*, voir webapp/settings_routes.py. */
(function () {
    "use strict";
    var I18N = window.I18N || {};
    function tr(key, vars) {
        var text = I18N[key] || key;
        Object.keys(vars || {}).forEach(function (k) { text = text.replace("{" + k + "}", vars[k]); });
        return text;
    }
    function $(id) { return document.getElementById(id); }

    function api(method, url, body) {
        var opts = {method: method, headers: {}};
        if (body !== undefined) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(body);
        }
        return fetch(url, opts).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (data) {
                return {ok: r.ok, status: r.status, data: data};
            });
        });
    }

    var flashTimer = null;
    function flash(text, kind) {
        var box = $("app-flash");
        box.textContent = text;
        box.className = "banner banner-" + (kind || "info");
        clearTimeout(flashTimer);
        if (kind !== "error") { flashTimer = setTimeout(function () { box.className = "banner hidden"; }, 6000); }
    }
    function failed(res) { flash(tr("app_error", {error: (res.data && res.data.error) || res.status}), "error"); }

    var state = {overview: null, inspect: null, inspectTimer: null, referenceTouched: false};

    // ------------------------------------------------------------------ vue d'ensemble
    function load() {
        return api("GET", "/api/app/overview").then(function (res) {
            if (!res.ok) { return failed(res); }
            state.overview = res.data;
            render(res.data);
            loadStatus();
        });
    }

    function render(o) {
        var folder = o.share.folder;
        $("share-current").textContent = folder ? tr("app_share_current", {folder: folder}) : tr("app_share_none");
        $("share-folder").value = folder || "";
        $("share-reference").checked = !!o.share.wealth_reference;
        $("share-clear").classList.toggle("hidden", !folder);
        $("share-open").classList.toggle("hidden", !folder);
        if ($("share-schedule")) {
            $("share-schedule").checked = !!o.share.task.registered;
            $("share-task").textContent = o.share.task.registered
                ? tr("app_task_on", {next: o.share.task.next_run || "—"}) : tr("app_task_off");
        }
        ["sync_on_start", "sync_on_close", "auto_update", "app_window"].forEach(function (key) {
            $("pref-" + key).checked = !!o.prefs[key];
        });
        $("pref-port").value = o.prefs.port;
        var v = o.version;
        $("update-version").textContent = v.git
            ? tr("app_update_version", {commit: v.commit || "?", date: v.date || "?", branch: v.branch || "?"}) : "";
        if (o.update.available) { checkUpdate(false); }
        ["data", "logs", "backups", "install"].forEach(function (key) { $("path-" + key).textContent = o.paths[key] || ""; });
        $("backup-info").textContent = o.backups.count
            ? tr("app_backup_info", {n: o.backups.count, date: o.backups.latest}) : tr("app_backup_none");
        renderLastLaunch(o.last_launch);
        if (folder) { suggest(); inspect(); } else { $("share-note").textContent = ""; suggest(); }
    }

    function renderLastLaunch(last) {
        var box = $("last-launch");
        var s = last && last.sync;
        box.textContent = "";
        if (!s || !s.lines || !s.lines.length) { return; }
        var title = document.createElement("strong");
        title.textContent = tr("app_lastsync_title") + (last.at ? " (" + last.at.slice(0, 16).replace("T", " ") + ")" : "");
        var list = document.createElement("ul");
        s.lines.forEach(function (line) {
            var li = document.createElement("li");
            li.textContent = line;
            list.appendChild(li);
        });
        box.appendChild(title);
        box.appendChild(list);
    }

    function loadStatus() {
        var list = $("share-status");
        if (!state.overview.share.folder) {
            list.innerHTML = "";
            $("share-sync-actions").classList.add("hidden");
            $("share-sync-hint").classList.add("hidden");
            return;
        }
        $("share-sync-actions").classList.remove("hidden");
        $("share-sync-hint").classList.remove("hidden");
        api("GET", "/api/app/share/status").then(function (res) {
            list.innerHTML = "";
            function add(text) {
                var li = document.createElement("li");
                li.textContent = text;
                list.appendChild(li);
            }
            if (!res.ok || res.data.error) { add(tr("app_error", {error: res.data.error || res.status})); return; }
            var s = res.data;
            add(tr("app_status_local", {n: s.local_runs}));
            add(s.remote ? tr("app_status_remote", {n: s.remote.runs, date: (s.remote.created_at || "").slice(0, 10)})
                         : tr("app_status_remote_empty"));
            add(tr("app_status_last", {date: s.last_exchange ? s.last_exchange.slice(0, 16).replace("T", " ") : tr("app_status_never")}));
            var todo = [];
            if (s.need_pull) { todo.push(tr("app_status_pull")); }
            if (s.need_push) { todo.push(tr("app_status_push")); }
            add(tr("app_status_todo", {todo: todo.length ? todo.join(" → ") : tr("app_status_uptodate")}));
            add(s.wealth_reference ? tr("app_status_role_ref") : tr("app_status_role_follow"));
        });
    }

    // ------------------------------------------------------------------ dossier partagé
    function suggest() {
        api("GET", "/api/app/share/suggestions").then(function (res) {
            var list = $("share-suggestions");
            list.innerHTML = "";
            ((res.data && res.data.suggestions) || []).forEach(function (s) {
                var opt = document.createElement("option");
                opt.value = s.path;
                list.appendChild(opt);
            });
        });
    }

    function inspect() {
        var folder = $("share-folder").value.trim();
        var note = $("share-note");
        if (!folder) { note.textContent = ""; return; }
        api("POST", "/api/app/share/inspect", {folder: folder}).then(function (res) {
            var i = res.data;
            if (!res.ok) { note.textContent = ""; return; }
            state.inspect = i;
            // Premier réglage depuis cette page : même valeur par défaut que l'assistant (1er PC = référence).
            if (!state.referenceTouched && !(state.overview && state.overview.share.folder)) {
                $("share-reference").checked = !!i.default_wealth_reference;
            }
            if (i.has_share) {
                note.textContent = tr("app_inspect_share", {runs: i.runs, date: (i.created_at || "").slice(0, 10)});
            } else if (i.exists && !i.writable) {
                note.textContent = tr("app_inspect_readonly");
            } else if (i.exists) {
                note.textContent = i.empty ? tr("app_inspect_empty") : tr("app_inspect_other");
            } else if (i.creatable) {
                note.textContent = tr("app_inspect_create");
            } else {
                note.textContent = tr("app_inspect_missing");
            }
        });
    }

    $("share-folder").addEventListener("input", function () {
        clearTimeout(state.inspectTimer);
        state.inspectTimer = setTimeout(inspect, 400);
    });

    $("share-browse").addEventListener("click", function () {
        var btn = this;
        btn.disabled = true;
        api("POST", "/api/app/share/browse", {initial: $("share-folder").value.trim()}).then(function (res) {
            btn.disabled = false;
            if (res.ok && res.data.folder) { $("share-folder").value = res.data.folder; inspect(); }
        });
    });

    $("share-reference").addEventListener("change", function () { state.referenceTouched = true; });

    $("share-save").addEventListener("click", function () {
        var folder = $("share-folder").value.trim();
        var body = {folder: folder || null, wealth_reference: $("share-reference").checked};
        if ($("share-schedule")) { body.schedule = $("share-schedule").checked; }
        api("POST", "/api/app/share/apply", body).then(function (res) {
            if (!res.ok) { return failed(res); }
            flash((res.data.warnings && res.data.warnings.length) ? res.data.warnings.join(" ") : tr("app_saved"),
                  (res.data.warnings && res.data.warnings.length) ? "warning" : "info");
            load();
        });
    });

    $("share-clear").addEventListener("click", function () {
        window.patrickDialog.confirm(tr("app_confirm_clear"), tr("app_share_clear_label")).then(function (yes) {
            if (!yes) { return; }
            api("POST", "/api/app/share/apply", {folder: null}).then(function (res) {
                if (!res.ok) { return failed(res); }
                flash(tr("app_saved"));
                load();
            });
        });
    });

    $("share-open").addEventListener("click", function () { openFolder("shared"); });

    function openFolder(what) {
        api("POST", "/api/app/open", {what: what}).then(function (res) {
            if (!res.ok) { flash(tr("app_error", {error: (res.data && res.data.detail) || res.status}), "error"); }
        });
    }
    Array.prototype.forEach.call(document.querySelectorAll("[data-open]"), function (btn) {
        btn.addEventListener("click", function () { openFolder(btn.getAttribute("data-open")); });
    });

    // ------------------------------------------------------------------ préférences (cases à cocher)
    ["sync_on_start", "sync_on_close", "auto_update", "app_window"].forEach(function (key) {
        $("pref-" + key).addEventListener("change", function () {
            var body = {};
            body[key] = this.checked;
            api("POST", "/api/app/prefs", body).then(function (res) { res.ok ? flash(tr("app_saved")) : failed(res); });
        });
    });

    $("port-save").addEventListener("click", function () {
        api("POST", "/api/app/prefs", {port: parseInt($("pref-port").value, 10)}).then(function (res) {
            res.ok ? flash(tr("app_saved")) : failed(res);
        });
    });

    // ------------------------------------------------------------------ relance (synchroniser / mettre à jour)
    function relaunch(url) {
        api("GET", "/api/app/boot").then(function (boot) {
            var previous = boot.data.boot_id;
            api("POST", url).then(function (res) {
                if (res.status === 409) { return flash(tr("app_busy_training"), "warning"); }
                if (!res.ok) { return failed(res); }
                $("relaunch-overlay").classList.remove("hidden");
                waitForRestart(previous, Date.now());
            });
        });
    }

    function waitForRestart(previous, since) {
        var message = $("relaunch-message");
        setTimeout(function () {
            fetch("/api/app/relaunch").then(function (r) { return r.json(); }).then(function (data) {
                if (data.boot_id && data.boot_id !== previous) { window.location.reload(); return; }
                if (data.message) { message.textContent = data.message; }
                waitForRestart(previous, since);
            }).catch(function () {
                // Le serveur est arrêté pendant la relance : on continue d'attendre, sans limite fixe (une fusion
                // peut durer longtemps), mais on prévient si rien ne revient après 45 minutes.
                if (Date.now() - since > 45 * 60 * 1000) { message.textContent = tr("app_relaunch_lost"); return; }
                waitForRestart(previous, since);
            });
        }, 2000);
    }

    $("share-sync-now").addEventListener("click", function () {
        window.patrickDialog.confirm(tr("app_confirm_sync"), tr("app_share_sync_now_label")).then(function (yes) {
            if (yes) { relaunch("/api/app/sync-now"); }
        });
    });

    // ------------------------------------------------------------------ mises à jour
    function checkUpdate(announce) {
        var result = $("update-result");
        if (announce) { result.textContent = tr("app_update_checking"); }
        api("POST", "/api/app/update/check").then(function (res) {
            var d = res.data || {};
            var news = $("update-news");
            news.innerHTML = "";
            $("update-apply").classList.toggle("hidden", d.state !== "available");
            if (d.state === "uptodate") {
                result.textContent = tr("app_update_uptodate");
            } else if (d.state === "available") {
                result.textContent = tr("app_update_available", {n: d.behind});
                (d.news || []).forEach(function (line) {
                    var li = document.createElement("li");
                    li.textContent = line;
                    news.appendChild(li);
                });
            } else {
                result.textContent = d.message || "";
            }
        });
    }
    $("update-check").addEventListener("click", function () { checkUpdate(true); });
    $("update-apply").addEventListener("click", function () {
        window.patrickDialog.confirm(tr("app_confirm_update"), tr("app_update_apply_label")).then(function (yes) {
            if (yes) { relaunch("/api/app/update/apply"); }
        });
    });

    // ------------------------------------------------------------------ divers
    if ($("shortcuts-make")) {
        $("shortcuts-make").addEventListener("click", function () {
            api("POST", "/api/app/shortcuts").then(function (res) { res.ok ? flash(tr("app_shortcuts_done")) : failed(res); });
        });
    }
    $("backup-now").addEventListener("click", function () {
        api("POST", "/api/app/backup-now").then(function (res) { res.ok ? flash(tr("app_backup_started")) : failed(res); });
    });

    // ------------------------------------------------------------------ performance (API existante)
    var pj = $("setting-parametric-jobs"), sj = $("setting-scan-jobs");
    fetch("/api/settings").then(function (r) { return r.json(); }).then(function (s) {
        pj.value = s.parametric_jobs; pj.max = s.max_parametric_jobs;
        sj.value = s.scan_jobs; sj.max = s.max_parametric_jobs;
        if (s.env_override !== null || s.env_override_scan !== null) { $("setting-env-note").classList.remove("hidden"); }
    });
    function post(url, value) {
        return api("POST", url, {jobs: parseInt(value, 10)});
    }
    $("perf-save").addEventListener("click", function () {
        post("/api/settings/parametric-jobs", pj.value).then(function (a) {
            if (!a.ok) { $("perf-status").textContent = a.data.error; return; }
            post("/api/settings/scan-jobs", sj.value).then(function (b) {
                $("perf-status").textContent = b.ok ? tr("setting_saved") : b.data.error;
            });
        });
    });

    load();
})();
