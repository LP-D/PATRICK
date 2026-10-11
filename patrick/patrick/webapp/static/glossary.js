(function () {
    "use strict";

    var dataEl = document.getElementById("glossary-data");
    var I18N = window.I18N || {};
    var GLOSSARY = {};
    if (dataEl) {
        try { GLOSSARY = JSON.parse(dataEl.textContent || "{}"); } catch (e) { GLOSSARY = {}; }
    }
    var labelsEl = document.getElementById("glossary-labels");
    var LABELS = {};
    if (labelsEl) {
        try { LABELS = JSON.parse(labelsEl.textContent || "{}"); } catch (e) { LABELS = {}; }
    }

    var popover = document.getElementById("glossary-popover");
    var titleEl = document.getElementById("glossary-popover-title");
    var bodyEl = document.getElementById("glossary-popover-body");
    var closeBtn = document.getElementById("glossary-popover-close");
    var searchInput = document.getElementById("glossary-search-input");
    var searchStatus = document.getElementById("glossary-search-status");
    var resultsEl = document.getElementById("glossary-search-results");
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

    function termLabel(term) {
        return LABELS[term] || term;
    }

    // Un appel de note fusionné porte plusieurs termes (`data-term="a b c"`) : voir `mergeIcons`.
    function knownTerms(term) {
        return String(term || "").split(" ").filter(function (key) { return key && GLOSSARY[key]; });
    }

    function showTerm(term, label) {
        var terms = knownTerms(term);
        if (!terms.length) return;
        var more = document.getElementById("glossary-popover-link");
        popover.dataset.openTerm = term;
        if (terms.length === 1) {
            titleEl.textContent = label || termLabel(terms[0]);
            bodyEl.textContent = GLOSSARY[terms[0]];
            if (more) more.href = "/vocabulary#term-" + encodeURIComponent(terms[0]);
            return;
        }
        titleEl.textContent = label || terms.map(termLabel).join(" · ");
        bodyEl.replaceChildren();
        terms.forEach(function (key) {
            var para = document.createElement("p");
            var name = document.createElement("strong");
            para.className = "glossary-multi";
            name.textContent = termLabel(key);
            para.appendChild(name);
            para.appendChild(document.createTextNode(" " + GLOSSARY[key]));
            bodyEl.appendChild(para);
        });
        if (more) more.href = "/vocabulary";
    }

    /* Un seul « ? » par zone. Les définitions d'un bloc replié (`details.adv` du formulaire de lancement : algorithmes,
       rééchantillonneurs, familles de variables...) passent derrière l'unique « ? » de son titre, et deux appels de note
       côte à côte (titre d'une page) n'en font qu'un. Le « ? » de la méthode de sélection, réécrit par app.js selon la
       méthode choisie, reste à sa place. */
    function mergedIcon(terms, labels, label) {
        var icon = document.createElement("button");
        icon.type = "button";
        icon.className = "info-icon";
        icon.setAttribute("data-term", terms.join(" "));
        icon.setAttribute("data-term-label", label);
        icon.setAttribute("aria-label", (I18N.glossary_open_aria || "Définition : {term}").replace("{term}", labels.join(", ")));
        icon.textContent = "i";
        return icon;
    }

    // Ajoute les termes d'un appel de note à la liste, avec le libellé que la page lui a donné (sinon celui du glossaire).
    function iconTerm(icon, terms, labels) {
        var keys = knownTerms(icon.getAttribute("data-term"));
        keys.forEach(function (key) {
            if (terms.indexOf(key) !== -1) return;
            terms.push(key);
            labels.push(keys.length === 1 && icon.getAttribute("data-term-label") || termLabel(key));
        });
    }

    // L'appel de note qui suit immédiatement (un simple espace entre les deux), sinon null.
    function neighbourIcon(icon) {
        var node = icon.nextSibling;
        while (node && node.nodeType === 3 && !node.nodeValue.trim()) node = node.nextSibling;
        return node && node.nodeType === 1 && node.classList.contains("info-icon") ? node : null;
    }

    function mergeBlock(block) {
        var host = block.querySelector(".adv-title");
        var icons = Array.prototype.filter.call(block.querySelectorAll(".adv-body .info-icon"), function (icon) {
            return !icon.closest("#selection-method-info");
        });
        if (!host || icons.length < 2) return;
        var terms = [], labels = [];
        icons.forEach(function (icon) { iconTerm(icon, terms, labels); icon.remove(); });
        if (terms.length < 2) return;
        host.appendChild(mergedIcon(terms, labels, (host.textContent || "").replace(/\s+/g, " ").trim()));
    }

    function mergeNeighbours(scope) {
        Array.prototype.forEach.call(scope.querySelectorAll(".info-icon"), function (icon) {
            if (!icon.isConnected || icon.closest("#selection-method-info")) return;
            var next = neighbourIcon(icon);
            if (!next) return;
            var terms = [], labels = [];
            iconTerm(icon, terms, labels);
            while (next) {
                iconTerm(next, terms, labels);
                var after = neighbourIcon(next);
                next.remove();
                next = after;
            }
            if (terms.length < 2) return;
            icon.setAttribute("data-term", terms.join(" "));
            icon.setAttribute("data-term-label", labels.join(" · "));
            icon.setAttribute("aria-label", (I18N.glossary_open_aria || "Définition : {term}").replace("{term}", labels.join(", ")));
        });
    }

    function mergeIcons(root) {
        var scope = root && root.querySelectorAll ? root : document;
        Array.prototype.forEach.call(scope.querySelectorAll("details.adv"), mergeBlock);
        mergeNeighbours(scope);
    }

    function normalized(value) {
        return String(value || "").toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    }

    function renderResults() {
        if (!searchInput || !resultsEl || !searchStatus) return;
        var query = normalized(searchInput.value.trim());
        resultsEl.replaceChildren();
        if (!query) {
            resultsEl.hidden = true;
            searchStatus.textContent = "";
            return;
        }

        var matches = Object.keys(GLOSSARY).filter(function (term) {
            return normalized(termLabel(term) + " " + term + " " + GLOSSARY[term]).indexOf(query) !== -1;
        });
        matches.forEach(function (term) {
            var item = document.createElement("li");
            var button = document.createElement("button");
            var label = document.createElement("span");
            var excerpt = document.createElement("span");
            button.type = "button";
            button.className = "glossary-search-result";
            button.dataset.term = term;
            label.className = "glossary-search-result-title";
            label.textContent = termLabel(term);
            excerpt.className = "glossary-search-result-excerpt";
            excerpt.textContent = GLOSSARY[term];
            button.appendChild(label);
            button.appendChild(excerpt);
            item.appendChild(button);
            resultsEl.appendChild(item);
        });
        resultsEl.hidden = false;
        searchStatus.textContent = matches.length
            ? (I18N.glossary_search_count || "{count} results").replace("{count}", matches.length)
            : (I18N.glossary_search_empty || "No matching terms");
    }

    function hide(restoreFocus) {
        if (popover.classList.contains("hidden")) return;
        popover.classList.add("hidden");
        popover.dataset.openTerm = "";
        if (searchInput) searchInput.value = "";
        renderResults();
        popover.removeAttribute("tabindex");
        var toRestore = restoreFocus && opener && document.contains(opener) ? opener : null;
        opener = null;
        if (toRestore) requestAnimationFrame(function () { toRestore.focus(); });
    }

    function showFor(anchorEl, term) {
        if (!knownTerms(term).length) return;
        if (searchInput) searchInput.value = "";
        renderResults();
        showTerm(term, anchorEl.getAttribute("data-term-label") || term);
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
        var left = window.scrollX + rect.left;
        var maxLeft = window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - 12;
        if (left > maxLeft) left = Math.max(12, maxLeft);
        popover.style.left = left + "px";

        /* Bascule au-dessus de l'appel de note quand il n'y a plus la place
           dessous. Mesuré : le popover atteignait `bottom: 904` pour un
           viewport de 900 — la définition sortait de l'écran par le bas, et
           c'est justement quand on est en bas de formulaire qu'on la demande. */
        var h = popover.offsetHeight;
        var below = rect.bottom + 6 + h <= document.documentElement.clientHeight - 8;
        popover.style.top = (below
            ? window.scrollY + rect.bottom + 6
            : Math.max(window.scrollY + 8, window.scrollY + rect.top - h - 6)) + "px";
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
    if (searchInput) searchInput.addEventListener("input", renderResults);
    if (resultsEl && searchInput) resultsEl.addEventListener("click", function (ev) {
        var button = ev.target.closest ? ev.target.closest("button[data-term]") : null;
        if (!button || !resultsEl.contains(button)) return;
        showTerm(button.dataset.term);
        searchInput.value = "";
        renderResults();
        searchInput.focus();
    });
    window.addEventListener("resize", function () { hide(false); });
    window.addEventListener("scroll", function (ev) {
        if (Date.now() - openedAt < 350) return;
        if (ev.target instanceof Node && popover.contains(ev.target)) return;   // on fait défiler la définition elle-même
        hide(false);
    }, true);

    document.addEventListener("patrick:content", function (ev) { mergeIcons(ev.target); });
    mergeIcons(document);
})();
