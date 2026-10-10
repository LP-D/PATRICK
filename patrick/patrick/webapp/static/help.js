/* Texte minimal : les aides statiques (sous-titres, notes, `.hint`) passent derrière un « ? ».

   Un élément d'aide est replié (`.help-folded`) et son contenu est présenté par un bouton « ? » placé au bon endroit :
   fin du libellé du champ, fin du titre du panneau, ou à la place de la note. Les messages d'état dynamiques ne sont pas
   touchés : tout élément avec un `id`, un `aria-live`, un `role`, `data-keep`, ou créé après le chargement (sans passage par
   `scan`) reste visible. Les fragments chargés plus tard (`lazy.js`) sont traités à l'événement `patrick:content`. */
(function () {
    "use strict";

    var I18N = window.I18N || {};
    var STATIC = ".hint, .page-subtitle, .table-footer, .scope-line, .block-note, .pred-legend, .profile-desc, "
               + ".headline-sub, .banner:not(.banner-error):not(.banner-warning)";
    var PAREN = /^([^()]{2,}?)\s*\(([^()]{10,})\)\s*[:.]?$/;      // « Libellé (explication) »
    var HEADINGS = "h1, h2, h3, h4, legend, summary, .dash-panel-title, .page-title, .group-title, .card-title, .adv-title";
    var CONTAINERS = ".card, .dash-panel, section, fieldset, details, .panel";
    var SKIP_INSIDE = ".glossary-popover, .cmdk, dialog, .stats-bar, .help-pop, .info-pop";
    var MIN_CHARS = 8;
    var anchors = new Map();       // ancre (titre, libellé) -> { button, items: [élément replié, ...] }
    var pop = null, opener = null, openedAt = 0;

    function tr(key, fallback) { return I18N[key] || fallback; }

    function eligible(el) {
        if (el.classList.contains("help-folded") || el.hasAttribute("data-keep")) return false;
        // `data-help="fold"` : texte réécrit par un script (id, aria-live) mais qui reste de l'aide, donc replié.
        if (el.getAttribute("data-help") !== "fold" && (el.id || el.hasAttribute("aria-live") || el.hasAttribute("role"))) return false;
        if (el.hidden || el.classList.contains("hidden")) return false;
        if (el.closest(SKIP_INSIDE)) return false;
        if (el.querySelector("button, input, select, textarea")) return false;
        return (el.textContent || "").trim().length >= MIN_CHARS;
    }

    function firstTextNode(label) {
        for (var i = 0; i < label.childNodes.length; i++) {
            var n = label.childNodes[i];
            if (n.nodeType === 3 && n.nodeValue.trim()) return n;
        }
        return null;
    }

    function headingAbove(el) {
        var prev = el.previousElementSibling;
        while (prev && prev.matches(STATIC)) prev = prev.previousElementSibling;
        if (prev && prev.matches(HEADINGS)) return prev;
        var box = el.parentElement ? el.parentElement.closest(CONTAINERS) : null;
        if (!box) return null;
        var head = box.querySelector(HEADINGS);
        if (head && head !== el && (head.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)
                && !head.contains(el)) return head;
        return null;
    }

    function contextName(node) {
        var named = node.querySelector ? node.querySelector(".profile-name") : null;
        if (named) node = named;
        var text = (node.textContent || "").replace(/\s+/g, " ").trim();
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

    // « Libellé (explication) » : le libellé reste, l'explication passe derrière le « ? » du champ.
    function foldLabelParens(label) {
        if (label.hasAttribute("data-help-paren") || label.closest(SKIP_INSIDE)) return;
        var node = firstTextNode(label);
        if (!node) return;
        var m = PAREN.exec(node.nodeValue.replace(/\s+/g, " ").trim());
        if (!m) return;
        label.setAttribute("data-help-paren", "1");
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
        p.replaceChildren();
        button._help.items.forEach(function (el) {
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
    window.addEventListener("scroll", function () {
        if (Date.now() - openedAt < 350) return;
        hide(false);
    }, true);
    document.addEventListener("patrick:content", function (ev) { scan(ev.target); });

    window.PatrickHelp = { scan: scan };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { scan(document); });
    else scan(document);
    // Filet de sécurité : si un bloc repose sur `help-pending` et que le balayage échoue, l'aide reste lisible.
    setTimeout(function () { document.documentElement.classList.remove("help-pending"); }, 2500);
})();
