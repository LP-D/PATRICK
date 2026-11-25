/* Blocs chargés après l'affichage : tout élément `[data-lazy-url]` reçoit le fragment HTML renvoyé par cette adresse.
   Les sections lourdes (synthèse, tableau des prédictions) n'empêchent plus la page de s'afficher ; une erreur laisse un
   bouton « Réessayer ». Un événement `patrick:content` est émis sur le bloc une fois rempli. */
(function () {
    "use strict";
    var TIMEOUT_MS = 90000;      // le premier calcul d'un bloc lourd prend jusqu'à ~45 s sur la vraie base (/fonds) : marge x2
    var MAX_PENDING = 60;        // réponses 202 successives (10 s chacune) avant d'abandonner : 10 minutes
    function load(el) {
        var url = el.dataset.lazyUrl;
        if (!url) return;
        // `?lang=en` sur la page (sans cookie de langue) doit aussi valoir pour le fragment.
        var lang = new URLSearchParams(window.location.search).get("lang");
        if (lang && url.indexOf("lang=") === -1) url += (url.indexOf("?") === -1 ? "?" : "&") + "lang=" + encodeURIComponent(lang);
        el.setAttribute("aria-busy", "true");
        // CO11 : sans délai maximal, une base verrouillée laissait « Chargement… » indéfiniment.
        var ctrl = window.AbortController ? new AbortController() : null;
        var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS) : null;
        fetch(url, { headers: { "Accept": "text/html" }, credentials: "same-origin", signal: ctrl ? ctrl.signal : undefined })
            .then(function (r) {
                if (timer) clearTimeout(timer);
                if (!r.ok) { var err = new Error(r.status); err.status = r.status; throw err; }
                // 202 : le serveur prépare encore ce bloc (premier calcul du tableau de /predictions) -- on montre son message
                // et on redemande toutes les 10 s, sans passer par le bouton « Réessayer ». CO12 : pas d'appel tant que l'onglet
                // est caché (comme le reste de l'application), et pas plus de MAX_PENDING tentatives.
                if (r.status === 202) {
                    return r.text().then(function (html) {
                        el.innerHTML = html;
                        var tries = (parseInt(el.dataset.lazyTries || "0", 10) || 0) + 1;
                        el.dataset.lazyTries = String(tries);
                        if (tries >= MAX_PENDING) { var e = new Error("pending"); e.status = 504; throw e; }
                        setTimeout(function () { whenVisible(function () { load(el); }); }, 10000);
                        return null;
                    });
                }
                return r.text();
            })
            .then(function (html) {
                if (html === null) return;
                delete el.dataset.lazyTries;
                el.innerHTML = html;
                el.dataset.lazySrc = el.dataset.lazyUrl;          // gardée pour `patrickReloadLazy` (barre de chargement : nouvelles données prêtes)
                el.removeAttribute("data-lazy-url");
                el.setAttribute("aria-busy", "false");
                el.classList.add("lazy-ready");
                el.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
            })
            .catch(function (err) {
                if (timer) clearTimeout(timer);
                el.setAttribute("aria-busy", "false");
                delete el.dataset.lazyTries;
                // CO10 : un 404 vient d'un serveur plus ancien que la page (route absente) : « Réessayer » n'y changerait rien.
                var stale = err && err.status === 404;
                var timeout = err && (err.name === "AbortError" || err.status === 504);
                var msg = stale ? (el.dataset.labelStale || "Server too old: restart it.")
                    : timeout ? (el.dataset.labelTimeout || "No answer from the server.") : (el.dataset.labelError || "Error");
                el.innerHTML = '<p class="banner banner-error" role="alert"></p>';
                el.firstChild.textContent = msg;
                if (!stale) {
                    var btn = document.createElement("button");
                    btn.type = "button"; btn.className = "btn-secondary lazy-retry";
                    btn.textContent = el.dataset.labelRetry || "Retry";
                    btn.addEventListener("click", function () { load(el); });
                    el.firstChild.appendChild(document.createTextNode(" "));
                    el.firstChild.appendChild(btn);
                }
            });
    }
    /* Lance `fn` tout de suite si l'onglet est visible, sinon dès qu'il le redevient. */
    function whenVisible(fn) {
        if (!document.hidden) { fn(); return; }
        document.addEventListener("visibilitychange", function once() {
            if (document.hidden) return;
            document.removeEventListener("visibilitychange", once);
            fn();
        });
    }
    /* Redemande tous les blocs déjà chargés (les chiffres ont été recalculés en tâche de fond : `static/refresh_bar.js`). */
    window.patrickReloadLazy = function () {
        document.querySelectorAll("[data-lazy-src]").forEach(function (el) {
            el.dataset.lazyUrl = el.dataset.lazySrc;
            load(el);
        });
    };
    /* Formulaire `[data-lazy-form]` dans un fragment (hypothèse d'un DCF...) : un changement redemande le bloc avec ces réglages,
       sans recharger la page. */
    function reloadWith(form) {
        var block = form.closest(".lazy-block");
        if (!block) return;
        var params = new URLSearchParams(new FormData(form)).toString();
        block.dataset.lazyUrl = form.getAttribute("action") + (params ? "?" + params : "");
        load(block);
    }
    document.addEventListener("change", function (e) {
        var form = e.target.closest && e.target.closest("form[data-lazy-form]");
        if (form) reloadWith(form);
    });
    document.addEventListener("submit", function (e) {
        var form = e.target.closest && e.target.closest("form[data-lazy-form]");
        if (form) { e.preventDefault(); reloadWith(form); }
    });
    document.querySelectorAll("[data-lazy-url]").forEach(load);
})();
