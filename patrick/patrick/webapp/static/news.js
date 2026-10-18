/* Page /news : bouton « Actualiser » (collecte en arrière-plan, suivie par interrogation) et étude d'événement au clic. */
(function () {
    "use strict";
    var I = window.I18N || {};
    var timer = null;

    function fmt(template, values) {
        return (template || "").replace(/\{(\w+)\}/g, function (_, k) { return values[k] !== undefined ? values[k] : ""; });
    }

    function status(text) {
        var el = document.getElementById("news-status");
        if (el) el.textContent = text;
    }

    function finish(s, btn) {
        clearInterval(timer);
        timer = null;
        btn.disabled = false;
        if (s.error) { status(fmt(I.news_refresh_failed, { e: s.error })); return; }
        var r = s.result || {};
        var msg = fmt(I.news_refresh_done, { added: r.added || 0, scored: r.scored || 0 });
        if (r.errors && r.errors.length) msg += " " + fmt(I.news_refresh_errors, { names: r.errors.map(function (e) { return e[0]; }).join(", ") });
        status(msg);
        if (r.added) setTimeout(function () { window.location.reload(); }, 1200);
    }

    function poll(btn) {
        if (timer) return;
        timer = setInterval(function () {
            fetch(btn.dataset.statusUrl, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (s) {
                if (!s.running) finish(s, btn);
            }).catch(function () { clearInterval(timer); timer = null; btn.disabled = false; });
        }, 1500);
    }

    document.addEventListener("click", function (event) {
        var refresh = event.target.closest && event.target.closest("#news-refresh");
        if (refresh && !refresh.disabled) {
            refresh.disabled = true;
            status(I.news_refreshing || "");
            fetch(refresh.dataset.url, { method: "POST", credentials: "same-origin" }).then(function () { poll(refresh); })
                .catch(function () { refresh.disabled = false; });
            return;
        }
        var study = event.target.closest && event.target.closest("#news-es-run");
        if (study && !study.disabled) {
            study.disabled = true;
            var host = document.getElementById("news-es");
            fetch(study.dataset.url, { credentials: "same-origin" }).then(function (r) { return r.text(); }).then(function (html) {
                host.innerHTML = html;
                document.dispatchEvent(new CustomEvent("patrick:content", { detail: host }));
                study.disabled = false;
            }).catch(function () { study.disabled = false; });
        }
    });
})();
