/* Mouvement (ADR 0022) : ce que le CSS seul ne sait pas faire. Les durées et les courbes viennent des jetons de patrick.css.
   - Popovers, menus, boîtes et palette entrent depuis leur déclencheur et y retournent : l'origine de la transformation
     (`--origin-x/y`) est posée au moment où ils apparaissent.
   - Un geste au clavier n'anime jamais rien : `<html data-input="keyboard">` coupe les transitions de ce qu'il ouvre.
   - Onglets d'analyse (`.exp-tabs`) : un trait unique glisse d'un onglet à l'autre en ease-in-out, étiré de 12 % à mi-course.
   - Révélations (dossier de l'arborescence, panneau d'onglet, lignes repliées) : `.is-revealing`, enfants décalés de 30 ms,
     durée plus longue pour un grand bloc.
   - Élastique aux limites des listes et des barres qui défilent ; bords estompés et onglet courant gardé dans le champ.
   - `window.patrickMotion.success(el)` : pulsation de réussite (léger gonflement et anneau qui s'éloigne).
   Rien ne bouge avec prefers-reduced-motion. Aucun réseau, aucune dépendance. */
(function () {
    "use strict";

    var root = document.documentElement;
    var reduceQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    function reduced() { return !!(reduceQuery && reduceQuery.matches); }
    function token(name, fallback) {
        var v = getComputedStyle(root).getPropertyValue(name).trim();
        return v || fallback;
    }
    function ms(name, fallback) {
        var v = parseFloat(token(name, ""));
        return isNaN(v) ? fallback : v;
    }
    var each = function (list, fn) { Array.prototype.forEach.call(list, fn); };

    /* ---- Modalité : clavier ou pointeur, et dernier déclencheur ----
       Posée sur <html data-input> dès la touche ou le clic, avant que la page ne réagisse : ce qu'un geste au clavier ouvre
       s'affiche d'un coup (patrick.css), même si le script qui l'ouvre force le calcul du style (focus()). */
    var keyboard = false, lastTrigger = null, lastHover = null;
    function setInput(isKeyboard) {
        keyboard = isKeyboard;
        var value = isKeyboard ? "keyboard" : "pointer";
        if (root.getAttribute("data-input") !== value) root.setAttribute("data-input", value);
    }
    document.addEventListener("keydown", function (e) {
        if (e.key === "Shift" || e.key === "Control" || e.key === "Alt" || e.key === "Meta") return;
        setInput(true);
        if (document.activeElement && document.activeElement !== document.body) lastTrigger = document.activeElement;
    }, true);
    document.addEventListener("pointerdown", function (e) {
        setInput(false);
        var t = e.target;
        lastTrigger = t && t.closest ? (t.closest("button, a, summary, [role='button'], [role='tab'], [tabindex]") || t) : null;
    }, true);
    document.addEventListener("pointerover", function (e) { lastHover = e.target; if (keyboard) setInput(false); }, true);

    /* ---- Origine : le centre du déclencheur, rapporté au popover (rogné à ses bords) ---- */
    var POPS = ".glossary-popover, .help-pop, .pred-pop, .mega-panel, .cmdk, dialog.modal, .history-dialog";
    function shown(el) {
        if (el.tagName === "DIALOG") return el.open;
        return !el.hidden && !el.classList.contains("hidden");
    }
    function triggerFor(pop) {
        if (pop.classList.contains("mega-panel")) return document.getElementById("mega-trigger");
        if (pop.classList.contains("pred-pop")) {
            return lastHover && lastHover.closest ? (lastHover.closest("td, th, .q-mark, a, button") || lastHover) : null;
        }
        if (pop.classList.contains("cmdk")) {
            var opener = document.getElementById("cmdk-open");
            return lastTrigger && opener && opener.contains(lastTrigger) ? opener : null;
        }
        return lastTrigger;
    }
    function setOrigin(pop) {
        var box = pop.classList.contains("cmdk") ? pop.querySelector(".cmdk-panel") : pop;
        var trig = triggerFor(pop);
        if (!box) return;
        if (!trig || !trig.getBoundingClientRect || trig === document.body || box.contains(trig)) {
            box.style.removeProperty("--origin-x");
            box.style.removeProperty("--origin-y");
            return;
        }
        var t = trig.getBoundingClientRect(), p = box.getBoundingClientRect();
        if (!p.width || !p.height || (!t.width && !t.height)) return;
        var x = Math.min(Math.max(t.left + t.width / 2 - p.left, 0), p.width);
        var y = Math.min(Math.max(t.top + t.height / 2 - p.top, 0), p.height);
        box.style.setProperty("--origin-x", x.toFixed(1) + "px");
        box.style.setProperty("--origin-y", y.toFixed(1) + "px");
    }

    /* ---- Révélations : décalage des enfants, poids selon la taille ---- */
    function reveal(el, index) {
        if (reduced() || keyboard) return;
        window.clearTimeout(el._revealTimer);
        el.classList.remove("is-revealing", "reveal-block");
        if (el.matches(".exp-panel, [data-reveal='block']")) {
            var h = el.getBoundingClientRect().height;
            el.style.setProperty("--reveal-dur", Math.round(Math.min(440, ms("--dur-reveal", 320) * 0.75 + h / 10)) + "ms");
            el.classList.add("reveal-block");
        } else if (el.tagName === "TR") {
            el.style.setProperty("--i", String(Math.min(index || 0, 10)));
        } else {
            each(el.children, function (child, i) { child.style.setProperty("--i", String(Math.min(i, 10))); });
        }
        void el.offsetWidth;                       // relance l'animation si le bloc s'était déjà révélé
        el.classList.add("is-revealing");
        el._revealTimer = window.setTimeout(function () { el.classList.remove("is-revealing", "reveal-block"); }, 900);
    }
    var REVEALS = ".nav-tree, .exp-panel, tr[data-extra], [data-reveal]";

    /* ---- Onglets d'analyse : un seul trait qui glisse ---- */
    var tablists = [];
    function inkFor(list) {
        var ink = list.querySelector(":scope > .tab-ink");
        if (!ink) {
            ink = document.createElement("span");
            ink.className = "tab-ink";
            ink.setAttribute("aria-hidden", "true");
            list.appendChild(ink);
            list.classList.add("has-ink");
        }
        return ink;
    }
    function placeInk(list, tab, animate) {
        var ink = inkFor(list), from = list._inkTab;
        var x1 = tab.offsetLeft, w1 = tab.offsetWidth;
        if (!w1) return;
        // Point de départ = là où le trait se trouve à l'écran (il peut être en plein trajet si l'on clique vite).
        var seen = ink.getBoundingClientRect(), box = list.getBoundingClientRect();
        var x0 = seen.left - box.left + list.scrollLeft, w0 = seen.width;
        if (ink.getAnimations) ink.getAnimations().forEach(function (a) { a.cancel(); });
        ink.style.left = x1 + "px";
        ink.style.width = w1 + "px";
        list._inkTab = tab;
        if (!animate || !from || from === tab || !ink.animate || reduced() || !w0) return;
        var stretch = parseFloat(token("--stretch", "1.12")) || 1.12;
        var midW = (w0 + w1) / 2 * stretch;
        var midLeft = (x0 + w0 / 2 + x1 + w1 / 2) / 2 - midW / 2;
        ink.animate([
            { transform: "translateX(" + (x0 - x1) + "px) scaleX(" + (w0 / w1) + ")" },
            { transform: "translateX(" + (midLeft - x1) + "px) scaleX(" + (midW / w1) + ")", offset: 0.5 },
            { transform: "none" }
        ], { duration: ms("--dur-move", 260), easing: token("--ease-move", "cubic-bezier(0.65, 0, 0.35, 1)") });
    }
    function keepInView(list, item, smooth) {
        var pad = 32, left = item.offsetLeft, right = left + item.offsetWidth, target = null;
        if (left - pad < list.scrollLeft) target = Math.max(0, left - pad);
        else if (right + pad > list.scrollLeft + list.clientWidth) target = right + pad - list.clientWidth;
        if (target === null) return;
        if (smooth && list.scrollTo && !reduced()) list.scrollTo({ left: target, behavior: "smooth" });
        else list.scrollLeft = target;
    }
    function edges(list) {
        var max = list.scrollWidth - list.clientWidth, parts = [];
        if (list.scrollLeft > 1) parts.push("start");
        if (list.scrollLeft < max - 1) parts.push("end");
        if (parts.length) list.setAttribute("data-overflow", parts.join(" "));
        else list.removeAttribute("data-overflow");
    }
    function initStrip(list) {
        edges(list);
        list.addEventListener("scroll", function () { edges(list); }, { passive: true });
        var current = list.querySelector("[aria-selected='true'], [aria-current='page']");
        if (current) keepInView(list, current, false);
        if (list.matches(".exp-tabs") && current) placeInk(list, current, false);
        tablists.push(list);
    }

    /* ---- Élastique aux limites (molette ou pavé tactile) ---- */
    var ELASTIC_X = ".table-scroll, .exp-tabs, .run-tabs";
    var ELASTIC_Y = ".cmdk-list, .mega-panel, .glossary-popover-body, .help-pop";
    function rubber(x) {                                   // cède de moins en moins : jamais plus de 48 px
        var limit = 48, a = Math.abs(x), s = x < 0 ? -1 : 1;
        return s * (1 - 1 / (a * 0.55 / limit + 1)) * limit;
    }
    function release(el) {
        window.clearTimeout(el._elasticTimer);
        el._elasticOver = 0;
        el.classList.add("is-releasing");
        el.style.setProperty("--elastic", "0px");
        window.clearTimeout(el._elasticDone);
        el._elasticDone = window.setTimeout(function () {
            if (!el._elasticOver) el.classList.remove("is-releasing", "is-stretched");
        }, 400);
    }
    document.addEventListener("wheel", function (e) {
        if (reduced() || e.ctrlKey || !e.target.closest) return;
        var el = e.target.closest(ELASTIC_X + ", " + ELASTIC_Y);
        if (!el) return;
        var axis = el.matches(ELASTIC_X) ? "x" : "y";
        var horizontal = Math.abs(e.deltaX) > Math.abs(e.deltaY);
        var d = axis === "x" ? (horizontal ? e.deltaX : (e.shiftKey ? e.deltaY : 0)) : (horizontal ? 0 : e.deltaY);
        if (!d) return;
        if (e.deltaMode === 1) d *= 16;
        var max = axis === "x" ? el.scrollWidth - el.clientWidth : el.scrollHeight - el.clientHeight;
        if (max < 2) return;                               // rien à faire défiler : la molette garde son rôle habituel
        var pos = axis === "x" ? el.scrollLeft : el.scrollTop;
        var pushing = (d < 0 && pos <= 0) || (d > 0 && pos >= max - 1);
        if (!pushing) { if (el._elasticOver) release(el); return; }
        el.setAttribute("data-elastic", axis);
        var over = el._elasticOver || 0;
        if (over && (over > 0) !== (d > 0)) over = 0;
        el._elasticOver = over + d;
        el.classList.remove("is-releasing");
        el.classList.add("is-stretched");
        el.style.setProperty("--elastic", (-rubber(el._elasticOver)).toFixed(1) + "px");
        window.clearTimeout(el._elasticTimer);
        el._elasticTimer = window.setTimeout(function () { release(el); }, 120);
    }, { passive: true, capture: true });

    /* ---- Pulsation de réussite ---- */
    function success(el) {
        if (!el || !el.animate || reduced()) return;
        var ring = token("--pos", "#30d158");
        el.animate([{ scale: 1 }, { scale: 1.02, offset: 0.3 }, { scale: 1 }],
            { duration: 420, easing: token("--ease-enter", "ease-out") });
        el.animate([
            { outline: "2px solid " + ring, outlineOffset: "0px" },
            { outline: "2px solid transparent", outlineOffset: "7px" }
        ], { duration: 640, easing: token("--ease-enter", "ease-out") });
    }

    /* ---- Un seul observateur pour tout ce qui apparaît ou change d'état ---- */
    var state = typeof WeakMap === "function" ? new WeakMap() : null;
    var observer = new MutationObserver(function (records) {
        var rowIndex = new Map();
        records.forEach(function (r) {
            var el = r.target;
            if (el.nodeType !== 1) return;
            if (r.attributeName === "aria-selected") {
                var list = el.closest(".exp-tabs");
                if (list && el.getAttribute("aria-selected") === "true") {
                    placeInk(list, el, !keyboard);
                    keepInView(list, el, !keyboard);
                }
                return;
            }
            if (el.matches(POPS)) {
                var now = shown(el), before = state ? state.get(el) : undefined;
                if (now === before) return;
                if (state) state.set(el, now);
                if (now) setOrigin(el);
                // Bulles en rafale (survol d'une case à l'autre) : la première s'anime, les suivantes s'affichent d'un coup.
                if (!now && el.classList.contains("pred-pop")) {
                    el.setAttribute("data-warm", "");
                    window.clearTimeout(el._warmTimer);
                    el._warmTimer = window.setTimeout(function () { el.removeAttribute("data-warm"); }, 400);
                }
                return;
            }
            if (r.attributeName === "hidden" && !el.hidden && el.matches(REVEALS)) {
                if (el.tagName === "TR") {
                    var body = el.parentNode, n = rowIndex.get(body) || 0;
                    rowIndex.set(body, n + 1);
                    reveal(el, n);
                } else {
                    reveal(el);
                }
            }
        });
    });

    function start() {
        each(document.querySelectorAll(POPS), function (el) { if (state) state.set(el, shown(el)); });
        each(document.querySelectorAll(".exp-tabs, .run-tabs"), initStrip);
        observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ["hidden", "class", "open", "aria-selected"] });
        var resizeTimer = null;
        window.addEventListener("resize", function () {
            window.clearTimeout(resizeTimer);
            resizeTimer = window.setTimeout(function () {
                tablists.forEach(function (list) {
                    edges(list);
                    if (list._inkTab) placeInk(list, list._inkTab, false);
                });
            }, 120);
        });
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(function () {
                tablists.forEach(function (list) { if (list._inkTab) placeInk(list, list._inkTab, false); edges(list); });
            });
        }
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();

    window.patrickMotion = {
        success: success,
        reduced: reduced,
        keyboard: function () { return keyboard; }
    };
})();
