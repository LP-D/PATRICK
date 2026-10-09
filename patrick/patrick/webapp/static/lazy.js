/* Blocs chargés après l'affichage : tout élément `[data-lazy-url]` reçoit le fragment HTML renvoyé par cette adresse.
   Les sections lourdes (synthèse, tableau des prédictions) n'empêchent plus la page de s'afficher ; une erreur laisse un
   bouton « Réessayer ». Un événement `patrick:content` est émis sur le bloc une fois rempli. */
(function () {
    "use strict";
    function load(el) {
        var url = el.dataset.lazyUrl;
        if (!url) return;
        el.setAttribute("aria-busy", "true");
        fetch(url, { headers: { "Accept": "text/html" }, credentials: "same-origin" })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function (html) {
                el.innerHTML = html;
                el.removeAttribute("data-lazy-url");
                el.setAttribute("aria-busy", "false");
                el.classList.add("lazy-ready");
                el.dispatchEvent(new CustomEvent("patrick:content", { bubbles: true }));
            })
            .catch(function () {
                el.setAttribute("aria-busy", "false");
                el.innerHTML = '<p class="banner banner-error" role="alert">' + (el.dataset.labelError || "Error") +
                    ' <button type="button" class="btn-secondary lazy-retry">' + (el.dataset.labelRetry || "Retry") + "</button></p>";
                el.querySelector(".lazy-retry").addEventListener("click", function () { load(el); });
            });
    }
    document.querySelectorAll("[data-lazy-url]").forEach(load);
})();
