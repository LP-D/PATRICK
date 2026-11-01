/* Pages « À faire » de la Synthèse (`/a-faire/<ligne>`, `templates/todo.html`) : chaque réentraînement proposé a ses cases à cocher ; « Relancer
   la sélection » demande confirmation, puis met en file les lignes cochées (`POST /api/a-faire/<ligne>/launch`). Le navigateur n'envoie que le
   groupe et les sources : les réglages du réentraînement sont ceux que le serveur propose. */
(function () {
    "use strict";
    var I18N = window.I18N || {};
    var status = document.getElementById("td-status");

    function fmt(text, vars) {
        return String(text).replace(/\{(\w+)\}/g, function (_, k) { return vars[k] !== undefined ? vars[k] : "{" + k + "}"; });
    }
    function withLang(url) {
        var lang = new URLSearchParams(window.location.search).get("lang");
        return lang ? url + (url.indexOf("?") === -1 ? "?" : "&") + "lang=" + encodeURIComponent(lang) : url;
    }
    function say(text, kind) {
        status.textContent = text || "";
        status.hidden = !text;
        status.classList.toggle("banner-error", kind === "error");
    }

    function wire(card) {
        var launch = card.querySelector("[data-td-launch]");
        if (!launch) return;
        var count = card.querySelector(".td-count");

        function picks() { return Array.prototype.slice.call(card.querySelectorAll(".td-pick")); }
        function chosen() { return picks().filter(function (box) { return box.checked; }).map(function (box) { return box.value; }); }
        function refresh() {
            var n = chosen().length;
            count.textContent = fmt(I18N.td_selected, { n: n });
            launch.disabled = n === 0;
        }

        card.addEventListener("change", function (ev) { if (ev.target.classList.contains("td-pick")) refresh(); });
        card.addEventListener("click", function (ev) {
            var all = ev.target.closest("[data-td-all]");
            if (!all) return;
            picks().forEach(function (box) { box.checked = all.dataset.tdAll === "1"; });
            refresh();
        });

        launch.addEventListener("click", async function () {
            var sources = chosen();
            if (!sources.length) { say(I18N.td_js_none, "error"); return; }
            var yes = await window.patrickDialog.confirm(
                fmt(I18N.td_js_confirm, { n: sources.length, title: card.dataset.title, plan: card.dataset.plan }),
                fmt(I18N.td_js_launch, { n: sources.length }));
            if (!yes) return;
            launch.disabled = true;
            say(I18N.td_js_working);
            try {
                var res = await fetch(withLang("/api/a-faire/" + encodeURIComponent(card.dataset.key) + "/launch"), {
                    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ group: card.dataset.group, sources: sources }),
                });
                var out = await res.json();
                if (!out.runs || !out.runs.length) throw new Error((out.errors || [res.status]).join(" · "));
                var errors = out.errors || [];
                say(errors.length
                    ? fmt(I18N.td_js_partial, { n: out.runs.length, e: errors.length, msg: errors.join(" · ") })
                    : fmt(I18N.td_js_done, { n: out.runs.length }), errors.length ? "error" : "");
                if (window.PatrickMachine) window.PatrickMachine.refresh();
                setTimeout(function () { window.location.reload(); }, errors.length ? 6000 : 2500);   // les lignes lancées passent « en file »
            } catch (err) {
                say(fmt(I18N.td_js_error, { msg: err.message }), "error");
                launch.disabled = false;
            }
        });
        refresh();
    }

    document.querySelectorAll(".td-group").forEach(wire);
})();
