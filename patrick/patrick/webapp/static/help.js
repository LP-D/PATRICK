/* Texte minimal : les aides statiques (sous-titres, notes, `.hint`) passent derrière un « ? ».

   Un élément d'aide est replié (`.help-folded`) et son contenu est présenté par un bouton « ? » placé au bon endroit :
   fin du libellé du champ, fin du titre du panneau, ou à la place de la note. Les messages d'état dynamiques ne sont pas
   touchés : tout élément avec un `id`, un `aria-live`, un `role`, `data-keep`, ou créé après le chargement (sans passage par
   `scan`) reste visible. Les fragments chargés plus tard (`lazy.js`) sont traités à l'événement `patrick:content`.

   Trois règles gardent les « ? » utiles :
   - une phrase courte (`INLINE_MAX`) reste affichée : pas de « ? » pour si peu, le lecteur est un initié ;
   - un seul « ? » par zone : le texte hors de tout cadre rejoint le titre de la page, deux textes identiques n'en font qu'un ;
   - une donnée n'est jamais de l'aide : le contenu d'une cellule de tableau, d'un résumé ou d'une bulle de survol
     (`.pop-content`, recopié dans `.pred-pop` par predictions_pop.js) n'est pas replié. */
(function () {
    "use strict";

    var I18N = window.I18N || {};
    var STATIC = ".hint, .page-subtitle, .table-footer, .scope-line, .block-note, .pred-legend, .profile-desc, "
               + ".headline-sub, .banner:not(.banner-error):not(.banner-warning)";
    var PAREN = /^([^()]{2,}?)\s*\(([^()]{10,})\)\s*[:.]?$/;      // « Libellé (explication) »
    var HEADINGS = "h1, h2, h3, h4, legend, summary, .dash-panel-title, .page-title, .group-title, .card-title, .adv-title";
    var CONTAINERS = ".card, .dash-panel, section, fieldset, details, .panel";
    var SKIP_INSIDE = ".glossary-popover, .cmdk, dialog, .stats-bar, .help-pop, .info-pop, .pop-content, .pred-pop, "
                    + "td, th, summary";
    var PAGE_TITLE = "h1.page-title, main h1";
    var SECTION_HEADINGS = "h2, h3, h4, legend, .dash-panel-title, .group-title, .card-title";
    var MIN_CHARS = 8;
    var INLINE_MAX = 120;          // phrase courte : reste visible telle quelle (environ une ligne)
    var INLINE_CARD_MAX = 150;     // description d'une carte de profil : visible pour toutes ou pour aucune (grille homogène)
    var INLINE_PAREN_MAX = 60;     // « Libellé (explication) » : une explication courte reste dans le libellé
    var anchors = new Map();       // ancre (titre, libellé) -> { button, items: [élément replié, ...] }
    var pop = null, opener = null, openedAt = 0;

    function tr(key, fallback) { return I18N[key] || fallback; }

    function normalized(text) { return (text || "").replace(/\s+/g, " ").trim(); }

    // Longueur du texte réellement lu : sans le contenu des bulles (`.pop-content`) ni les boutons (« ? », « i »).
    function textLength(el) {
        var copy = el.cloneNode(true);
        Array.prototype.forEach.call(copy.querySelectorAll(".pop-content, button, script, style"),
                                     function (n) { n.remove(); });
        return normalized(copy.textContent).length;
    }

    function eligible(el) {
        if (el.classList.contains("help-folded") || el.hasAttribute("data-keep")) return false;
        // `data-help="fold"` : texte réécrit par un script (id, aria-live) mais qui reste de l'aide, donc replié.
        var forced = el.getAttribute("data-help") === "fold";
        if (!forced && (el.id || el.hasAttribute("aria-live") || el.hasAttribute("role"))) return false;
        if (el.hidden || el.classList.contains("hidden")) return false;
        if (el.closest(SKIP_INSIDE)) return false;
        if (el.querySelector("button, input, select, textarea")) return false;
        var length = textLength(el);
        if (length < MIN_CHARS) return false;
        return forced || length > (el.closest("[data-help-host]") ? INLINE_CARD_MAX : INLINE_MAX);
    }

    function firstTextNode(label) {
        for (var i = 0; i < label.childNodes.length; i++) {
            var n = label.childNodes[i];
            if (n.nodeType === 3 && n.nodeValue.trim()) return n;
        }
        return null;
    }

    // Texte d'en-tête de page hors de tout cadre (sous-titre, aide des onglets, légende) : son « ? » rejoint le titre.
    // Plus bas dans la page (après un titre de section), la note garde son propre « ? » : elle reste à côté de ce qu'elle explique.
    function pageTitle(el) {
        var title = document.querySelector(PAGE_TITLE);
        if (!title || title.contains(el)) return null;
        if (!(title.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) return null;
        var sections = document.querySelectorAll(SECTION_HEADINGS);
        for (var i = 0; i < sections.length; i++) {
            if (sections[i].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) return null;
        }
        return title;
    }

    function headingAbove(el) {
        var prev = el.previousElementSibling;
        while (prev && prev.matches(STATIC)) prev = prev.previousElementSibling;
        if (prev && prev.matches(HEADINGS)) return prev;
        var box = el.parentElement ? el.parentElement.closest(CONTAINERS) : null;
        if (box) {
            var head = box.querySelector(HEADINGS);
            if (head && head !== el && (head.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)
                    && !head.contains(el)) return head;
        }
        return pageTitle(el);
    }

    function contextName(node) {
        var named = node.querySelector ? node.querySelector(".profile-name") : null;
        if (named) node = named;
        var text = normalized(node.textContent);
        return text.length > 40 ? text.slice(0, 40) + "…" : text;
    }

    function makeButton(context) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "help-q";
        b.setAttribute("aria-expanded", "false");
        var label = tr("help_aria", "Aide");
        b.setAttribute("aria-label", context ? label + " : " + context : label);
        return b;
    }

    function fold(el, forcedAnchor) {
        var label = forcedAnchor || el.closest("label");
        var link = forcedAnchor ? null : el.closest("a");
        var anchor, button, entry;
        var host = forcedAnchor ? null : el.closest("[data-help-host]");
        if (forcedAnchor) {
            anchor = forcedAnchor;
        } else if (host) {
            anchor = host;               // carte : le « ? » vit dans l'hôte (placé en haut à droite par le CSS)
        } else if (link) {
            anchor = link;               // un bouton ne s'imbrique pas dans un lien : le « ? » se place après le lien
        } else if (label && label.contains(el)) {
            anchor = label;
        } else {
            anchor = headingAbove(el);
        }
        entry = anchor ? anchors.get(anchor) : null;
        if (!entry) {
            button = makeButton(anchor ? contextName(anchor) : "");
            entry = { button: button, items: [] };
            if (anchor && anchor === link) {
                link.parentNode.insertBefore(button, link.nextSibling);
            } else if (anchor && anchor === label) {
                var textNode = firstTextNode(label);
                if (textNode) textNode.parentNode.insertBefore(button, textNode.nextSibling);
                else label.insertBefore(button, label.firstChild);
            } else if (anchor) {
                anchor.appendChild(button);
            } else {
                el.parentNode.insertBefore(button, el);
            }
            if (anchor) anchors.set(anchor, entry);
        }
        entry.items.push(el);
        if (!forcedAnchor) {
            el.classList.add("help-folded");
            el.setAttribute("data-help-owner", "1");
        }
        entry.button._help = entry;
    }

    // « Libellé (explication) » : le libellé reste, l'explication passe derrière le « ? » du champ
    // (sauf si elle est courte : elle reste dans le libellé).
    function foldLabelParens(label) {
        if (label.hasAttribute("data-help-paren") || label.closest(SKIP_INSIDE)) return;
        var node = firstTextNode(label);
        if (!node) return;
        var m = PAREN.exec(node.nodeValue.replace(/\s+/g, " ").trim());
        if (!m) return;
        label.setAttribute("data-help-paren", "1");
        if (m[2].length <= INLINE_PAREN_MAX) return;
        node.nodeValue = m[1] + " ";
        var note = document.createElement("span");
        note.textContent = m[2].charAt(0).toUpperCase() + m[2].slice(1);
        fold(note, label);
    }

    function scan(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var found = Array.prototype.filter.call(scope.querySelectorAll(STATIC), eligible);
        if (scope !== document && scope.matches && scope.matches(STATIC) && eligible(scope)) found.unshift(scope);
        found.forEach(function (el) { fold(el); });
        Array.prototype.forEach.call(scope.querySelectorAll("label"), foldLabelParens);
        document.documentElement.classList.remove("help-pending");
    }

    function ensurePop() {
        if (pop) return pop;
        pop = document.createElement("div");
        pop.className = "help-pop hidden";
        pop.id = "help-pop";
        pop.setAttribute("role", "note");
        pop.setAttribute("tabindex", "-1");
        document.body.appendChild(pop);
        return pop;
    }

    function hide(restoreFocus) {
        if (!pop || pop.classList.contains("hidden")) return;
        pop.classList.add("hidden");
        if (opener) {
            opener.setAttribute("aria-expanded", "false");
            opener.removeAttribute("aria-controls");
            if (restoreFocus) opener.focus();
        }
        opener = null;
    }

    function show(button) {
        var p = ensurePop();
        var seen = {};
        p.replaceChildren();
        button._help.items.forEach(function (el) {
            var key = normalized(el.textContent);
            if (!key || seen[key]) return;      // deux textes identiques ne s'affichent qu'une fois
            seen[key] = true;
            var para = document.createElement("p");
            Array.prototype.forEach.call(el.childNodes, function (n) { para.appendChild(n.cloneNode(true)); });
            p.appendChild(para);
        });
        p.classList.remove("hidden");
        opener = button;
        openedAt = Date.now();
        button.setAttribute("aria-expanded", "true");
        button.setAttribute("aria-controls", "help-pop");
        var rect = button.getBoundingClientRect();
        var left = window.scrollX + rect.left;
        var maxLeft = window.scrollX + document.documentElement.clientWidth - p.offsetWidth - 12;
        if (left > maxLeft) left = Math.max(12, maxLeft);
        p.style.left = left + "px";
        var h = p.offsetHeight;
        var below = rect.bottom + 6 + h <= document.documentElement.clientHeight - 8;
        p.style.top = (below ? window.scrollY + rect.bottom + 6
                             : Math.max(window.scrollY + 8, window.scrollY + rect.top - h - 6)) + "px";
    }

    document.addEventListener("click", function (ev) {
        var button = ev.target.closest ? ev.target.closest(".help-q") : null;
        if (button && button._help) {
            ev.preventDefault();
            ev.stopPropagation();
            if (opener === button) hide(true); else { hide(false); show(button); }
            return;
        }
        if (pop && pop.contains(ev.target)) return;
        hide(false);
    }, true);

    document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") hide(true);
    });
    window.addEventListener("resize", function () { hide(false); });
    window.addEventListener("scroll", function (ev) {
        if (Date.now() - openedAt < 350) return;
        if (pop && ev.target instanceof Node && pop.contains(ev.target)) return;   // on fait défiler la bulle elle-même
        hide(false);
    }, true);
    document.addEventListener("patrick:content", function (ev) { scan(ev.target); });

    window.PatrickHelp = { scan: scan };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { scan(document); });
    else scan(document);
    // Filet de sécurité : si un bloc repose sur `help-pending` et que le balayage échoue, l'aide reste lisible.
    setTimeout(function () { document.documentElement.classList.remove("help-pending"); }, 2500);
})();
