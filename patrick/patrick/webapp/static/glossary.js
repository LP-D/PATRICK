(function () {
    "use strict";

    var dataEl = document.getElementById("glossary-data");
    var GLOSSARY = {};
    if (dataEl) {
        try { GLOSSARY = JSON.parse(dataEl.textContent || "{}"); } catch (e) { GLOSSARY = {}; }
    }

    var popover = document.getElementById("glossary-popover");
    var titleEl = document.getElementById("glossary-popover-title");
    var bodyEl = document.getElementById("glossary-popover-body");
    var closeBtn = document.getElementById("glossary-popover-close");
    if (!popover || !titleEl || !bodyEl) return;

    // L'élément qui a ouvert le popover : le focus doit lui revenir à la
    // fermeture, sinon on le renvoie en haut du document et on perd sa place
    // dans un formulaire de 65 contrôles.
    var opener = null;
    // Instant d'ouverture. Le repli d'un bloc `<details>`, la pose du focus ou
    // un ancrage peuvent produire un événement `scroll` DANS le même geste que
    // l'ouverture : sans cette fenêtre de grâce, le popover se refermait aussi
    // sec, avant même d'avoir reçu le focus. Mesuré : ouverture puis fermeture
    // en deux mutations de classe consécutives.
    var openedAt = 0;

    function hide(restoreFocus) {
        if (popover.classList.contains("hidden")) return;
        popover.classList.add("hidden");
        popover.dataset.openTerm = "";
        popover.removeAttribute("tabindex");
        var toRestore = restoreFocus && opener && document.contains(opener) ? opener : null;
        opener = null;
        if (toRestore) requestAnimationFrame(function () { toRestore.focus(); });
    }

    function showFor(anchorEl, term) {
        var text = GLOSSARY[term];
        if (!text) return;
        titleEl.textContent = anchorEl.getAttribute("data-term-label") || term;
        bodyEl.textContent = text;
        popover.classList.remove("hidden");

        /* Le popover s'ouvrait sans que rien ne bouge : au clavier comme au
           lecteur d'écran, du contenu apparaissait hors du chemin de
           tabulation et n'était jamais annoncé. Il devient donc focusable et
           reçoit le focus, `role="dialog"` le nomme, et Échap le referme en
           rendant le focus à l'appel de note. */
        opener = anchorEl;
        openedAt = Date.now();
        popover.setAttribute("tabindex", "-1");
        popover.setAttribute("aria-labelledby", "glossary-popover-title");
        /* Le focus est posé à la frame suivante, pas dans le même tour : le
           popover sort de `display: none` via une transition `allow-discrete`,
           et un `focus()` synchrone sur un élément que le moteur n'a pas
           encore reflowé est silencieusement ignoré. Mesuré : sans ce délai,
           `document.activeElement` restait `body`. */
        requestAnimationFrame(function () {
            if (!popover.classList.contains("hidden")) popover.focus();
        });

        var rect = anchorEl.getBoundingClientRect();
        var top = window.scrollY + rect.bottom + 6;
        var left = window.scrollX + rect.left;
        var maxLeft = window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - 12;
        if (left > maxLeft) left = Math.max(12, maxLeft);
        popover.style.top = top + "px";
        popover.style.left = left + "px";
    }

    document.addEventListener("click", function (ev) {
        var icon = ev.target.closest ? ev.target.closest(".info-icon") : null;
        if (icon) {
            ev.preventDefault();
            var term = icon.getAttribute("data-term");
            var alreadyOpenForThis = !popover.classList.contains("hidden") && popover.dataset.openTerm === term;
            if (alreadyOpenForThis) {
                hide(true);
            } else {
                showFor(icon, term);
                popover.dataset.openTerm = term;
            }
            return;
        }
        if (popover.contains(ev.target)) return;
        hide(false);
    });

    document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") hide(true);
        // Le popover ne piège pas le focus — ce n'est pas une boîte de
        // dialogue modale — mais tabuler hors de lui doit le refermer, sinon
        // il reste ouvert par-dessus les champs qu'on vient rejoindre.
        if (ev.key === "Tab" && !popover.classList.contains("hidden")) {
            setTimeout(function () {
                if (!popover.contains(document.activeElement)) hide(false);
            }, 0);
        }
    });

    if (closeBtn) closeBtn.addEventListener("click", function () { hide(true); });
    window.addEventListener("resize", function () { hide(false); });
    window.addEventListener("scroll", function () {
        if (Date.now() - openedAt < 350) return;
        hide(false);
    }, true);
})();
