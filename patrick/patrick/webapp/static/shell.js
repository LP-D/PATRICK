/* Design system v3 shell (base_v2.html): theme toggle, collapsible sidebar,
   mobile drawer, command palette. No dependency, no network. Every storage
   access is guarded: a blocked localStorage degrades to OS theme + expanded
   sidebar, never to a broken page. */
(function () {
    "use strict";

    var root = document.documentElement;

    function store(key, value) {
        try {
            if (value === null) localStorage.removeItem(key);
            else localStorage.setItem(key, value);
        } catch (e) { /* storage unavailable */ }
    }

    /* ---- Theme ---- */
    function effectiveTheme() {
        var explicit = root.getAttribute("data-theme");
        if (explicit) return explicit;
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    function announceTheme() {
        // Charts read their colours from CSS tokens at draw time: they
        // listen to this event and redraw with the new palette.
        window.dispatchEvent(new CustomEvent("patrick:themechange", { detail: { theme: effectiveTheme() } }));
    }
    var themeBtn = document.getElementById("theme-toggle");
    if (themeBtn) {
        themeBtn.addEventListener("click", function () {
            var next = effectiveTheme() === "dark" ? "light" : "dark";
            root.setAttribute("data-theme", next);
            store("patrick-theme", next);
            announceTheme();
        });
    }
    if (window.matchMedia) {
        var mq = window.matchMedia("(prefers-color-scheme: light)");
        var onSystem = function () { if (!root.getAttribute("data-theme")) announceTheme(); };
        if (mq.addEventListener) mq.addEventListener("change", onSystem);
    }

    /* ---- Sidebar: desktop collapse, mobile drawer ---- */
    var sideBtn = document.getElementById("sidebar-toggle");
    if (sideBtn) {
        sideBtn.setAttribute("aria-expanded", root.getAttribute("data-sidebar") === "collapsed" ? "false" : "true");
        sideBtn.addEventListener("click", function () {
            var collapsed = root.getAttribute("data-sidebar") === "collapsed";
            if (collapsed) root.removeAttribute("data-sidebar");
            else root.setAttribute("data-sidebar", "collapsed");
            sideBtn.setAttribute("aria-expanded", collapsed ? "true" : "false");
            store("patrick-sidebar", collapsed ? null : "collapsed");
            // Canvas charts size themselves on resize: the content column
            // just changed width.
            window.setTimeout(function () { window.dispatchEvent(new Event("resize")); }, 220);
        });
    }
    var openBtn = document.getElementById("nav-open");
    var scrim = document.getElementById("nav-scrim");
    function setDrawer(open) {
        if (open) root.setAttribute("data-nav-open", "");
        else root.removeAttribute("data-nav-open");
        if (scrim) scrim.hidden = !open;
        if (openBtn) openBtn.setAttribute("aria-expanded", open ? "true" : "false");
    }
    if (openBtn) openBtn.addEventListener("click", function () { setDrawer(true); });
    if (scrim) scrim.addEventListener("click", function () { setDrawer(false); });

    /* ---- Arborescence de navigation (style explorateur de VS Code) ----
       Categories et dossiers sont des boutons `aria-expanded` qui montrent / cachent la liste qui les suit. L'etat
       (cle -> ouvert) est range dans localStorage['patrick-nav-tree'] ; le petit script de base_v2.html le rejoue avant le
       premier rendu. Une branche qui contient la page courante s'ouvre toujours (`data-has-active`).
       Clavier : ↑ ↓ passent d'une ligne visible a l'autre, → ouvre un dossier (puis entre dedans), ← le referme (puis remonte
       au parent), Debut / Fin, Entree ou Espace ouvrent / ferment ; Tab reste le parcours habituel des liens visibles. */
    var tree = document.getElementById("sidebar-tree");
    if (tree) {
        var TREE_KEY = "patrick-nav-tree";
        var treeState = {};
        try { treeState = JSON.parse(localStorage.getItem(TREE_KEY) || "{}") || {}; } catch (e) { treeState = {}; }
        var ROW = ".sidebar-nav-heading, .nav-folder-btn, .nav-leaf a";
        var boxButton = function (box) { return box.querySelector(":scope > button"); };
        var boxList = function (box) { return box.querySelector(":scope > ul"); };
        var isOpen = function (btn) { return btn.getAttribute("aria-expanded") === "true"; };
        var setBox = function (box, open) {
            var btn = boxButton(box), list = boxList(box);
            if (!btn || !list) return;
            btn.setAttribute("aria-expanded", open ? "true" : "false");
            list.hidden = !open;
            treeState[box.getAttribute("data-nav-key")] = open;
        };
        var saveTree = function () { store(TREE_KEY, JSON.stringify(treeState)); };
        var visibleRows = function () {
            return Array.prototype.filter.call(tree.querySelectorAll(ROW), function (r) { return r.offsetParent !== null; });
        };
        tree.addEventListener("click", function (e) {
            var btn = e.target.closest ? e.target.closest(".sidebar-nav-heading, .nav-folder-btn") : null;
            if (!btn || !tree.contains(btn)) return;
            setBox(btn.parentElement, !isOpen(btn));
            saveTree();
        });
        var allBoxes = function (open) {
            Array.prototype.forEach.call(tree.querySelectorAll("[data-nav-key]"), function (box) { setBox(box, open); });
            saveTree();
        };
        var collapseAll = document.getElementById("nav-collapse-all");
        var expandAll = document.getElementById("nav-expand-all");
        if (collapseAll) collapseAll.addEventListener("click", function () { allBoxes(false); });
        if (expandAll) expandAll.addEventListener("click", function () { allBoxes(true); });
        tree.addEventListener("keydown", function (e) {
            var row = e.target.closest ? e.target.closest(ROW) : null;
            if (!row || e.altKey || e.ctrlKey || e.metaKey) return;
            var rows = visibleRows(), i = rows.indexOf(row), folder = row.matches(".sidebar-nav-heading, .nav-folder-btn");
            var target = null;
            if (e.key === "ArrowDown") target = rows[Math.min(rows.length - 1, i + 1)];
            else if (e.key === "ArrowUp") target = rows[Math.max(0, i - 1)];
            else if (e.key === "Home") target = rows[0];
            else if (e.key === "End") target = rows[rows.length - 1];
            else if (e.key === "ArrowRight" && folder) {
                if (!isOpen(row)) { setBox(row.parentElement, true); saveTree(); return e.preventDefault(); }
                target = rows[i + 1];
            } else if (e.key === "ArrowLeft") {
                if (folder && isOpen(row)) { setBox(row.parentElement, false); saveTree(); return e.preventDefault(); }
                var holder = row.closest("ul") && row.closest("ul").parentElement;
                target = holder ? boxButton(holder) : null;
            } else return;
            e.preventDefault();
            if (target) target.focus();
        });
    }

    /* ---- Command palette ---- */
    var dialog = document.getElementById("cmdk");
    var input = document.getElementById("cmdk-input");
    var list = document.getElementById("cmdk-list");
    var trigger = document.getElementById("cmdk-open");
    var items = [];
    try { items = JSON.parse(document.getElementById("cmdk-data").textContent || "[]"); } catch (e) { items = []; }
    // L'icône d'une entrée est copiée depuis la barre latérale (ou le bouton de la barre du haut) : elle n'est plus répétée dans les données de la page.
    function iconFor(it) {
        var src = document.querySelector('.sidebar-nav a[href="' + it.url + '"] svg') || document.querySelector("#nav-" + it.slug + " svg");
        return src ? src.cloneNode(true) : null;
    }
    var shown = [];
    var active = 0;
    var lastFocus = null;

    function normalize(s) {
        return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    }
    function score(item, q) {
        if (!q) return 1;
        var label = normalize(item.label), group = normalize(item.group), url = normalize(item.url);
        if (label.indexOf(q) === 0) return 4;
        if (label.indexOf(q) >= 0) return 3;
        if (url.indexOf(q) >= 0) return 2;
        if (group.indexOf(q) >= 0) return 1;
        // Subsequence match ("sim" -> "Simulateur", "hst" -> "Historique").
        var i = 0;
        for (var k = 0; k < label.length && i < q.length; k++) if (label[k] === q[i]) i++;
        return i === q.length ? 0.5 : 0;
    }
    function render() {
        var q = normalize(input.value.trim());
        shown = items
            .map(function (it, idx) { return { it: it, s: score(it, q), idx: idx }; })
            .filter(function (r) { return r.s > 0; })
            .sort(function (a, b) { return b.s - a.s || a.idx - b.idx; })
            .map(function (r) { return r.it; });
        if (active >= shown.length) active = Math.max(0, shown.length - 1);
        list.innerHTML = "";
        if (!shown.length) {
            var empty = document.createElement("li");
            empty.className = "cmdk-empty";
            empty.textContent = (window.I18N && window.I18N.cmdk_empty) || "Aucun résultat";
            list.appendChild(empty);
            return;
        }
        var lastGroup = null;
        shown.forEach(function (it, i) {
            if (!q && it.group !== lastGroup) {
                var g = document.createElement("li");
                g.className = "cmdk-group";
                g.setAttribute("role", "presentation");
                g.textContent = it.group;
                list.appendChild(g);
                lastGroup = it.group;
            }
            var li = document.createElement("li");
            li.className = "cmdk-item";
            li.id = "cmdk-item-" + i;
            li.setAttribute("role", "option");
            li.setAttribute("aria-selected", i === active ? "true" : "false");
            var icon = iconFor(it);
            if (icon) li.appendChild(icon);
            var label = document.createElement("span");
            label.textContent = it.label;
            var hint = document.createElement("span");
            hint.className = "cmdk-item-hint";
            hint.textContent = it.url;
            li.appendChild(label);
            li.appendChild(hint);
            li.addEventListener("mousemove", function () { if (active !== i) { active = i; highlight(); } });
            li.addEventListener("click", function () { go(it); });
            list.appendChild(li);
        });
        input.setAttribute("aria-activedescendant", "cmdk-item-" + active);
    }
    function highlight() {
        var nodes = list.querySelectorAll(".cmdk-item");
        for (var i = 0; i < nodes.length; i++) nodes[i].setAttribute("aria-selected", i === active ? "true" : "false");
        var cur = nodes[active];
        if (cur) { cur.scrollIntoView({ block: "nearest" }); input.setAttribute("aria-activedescendant", cur.id); }
    }
    function go(it) { if (it) window.location.href = it.url; }
    function open() {
        if (!dialog) return;
        lastFocus = document.activeElement;
        dialog.hidden = false;
        input.value = "";
        active = 0;
        render();
        input.focus();
    }
    function close() {
        if (!dialog || dialog.hidden) return;
        dialog.hidden = true;
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
    if (dialog && input && list) {
        if (trigger) trigger.addEventListener("click", open);
        input.addEventListener("input", function () { active = 0; render(); });
        dialog.addEventListener("click", function (e) { if (e.target === dialog) close(); });
        input.addEventListener("keydown", function (e) {
            if (e.key === "ArrowDown") { e.preventDefault(); if (shown.length) { active = (active + 1) % shown.length; highlight(); } }
            else if (e.key === "ArrowUp") { e.preventDefault(); if (shown.length) { active = (active - 1 + shown.length) % shown.length; highlight(); } }
            else if (e.key === "Enter") { e.preventDefault(); go(shown[active]); }
            else if (e.key === "Tab") { e.preventDefault(); }
        });
    }

    document.addEventListener("keydown", function (e) {
        var tag = (e.target && e.target.tagName) || "";
        var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || (e.target && e.target.isContentEditable);
        if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            if (dialog && dialog.hidden) open(); else close();
        } else if (e.key === "/" && !typing && dialog && dialog.hidden) {
            e.preventDefault();
            open();
        } else if (e.key === "Escape") {
            close();
            setDrawer(false);
        }
    });

    if (trigger && /Mac|iPhone|iPad/.test(navigator.platform || "")) {
        var kbd = trigger.querySelector(".kbd");
        if (kbd) kbd.textContent = "⌘K";
    }

    /* ---- Menu en blocs (barre du haut) ----
       Bouton à bascule (aria-expanded) : clic, Entrée / Espace, Échap (le focus revient au bouton), clic en dehors, sortie du focus.
       Sur un appareil à souris, il s'ouvre aussi au survol (avec un petit délai, pour qu'un passage de souris ne déclenche rien). */
    var mega = document.getElementById("mega");
    var megaBtn = document.getElementById("mega-trigger");
    var megaPanel = document.getElementById("mega-panel");
    var megaTimer = null;
    function setMega(open, focusBack) {
        if (!megaBtn || !megaPanel) return;
        window.clearTimeout(megaTimer);
        megaBtn.setAttribute("aria-expanded", open ? "true" : "false");
        megaPanel.hidden = !open;
        if (!open && focusBack) megaBtn.focus();
    }
    if (mega && megaBtn && megaPanel) {
        megaBtn.addEventListener("click", function () { setMega(megaPanel.hidden); });
        var hoverable = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
        if (hoverable) {
            mega.addEventListener("pointerenter", function () {
                window.clearTimeout(megaTimer);
                megaTimer = window.setTimeout(function () { setMega(true); }, 140);
            });
            mega.addEventListener("pointerleave", function () {
                window.clearTimeout(megaTimer);
                megaTimer = window.setTimeout(function () { setMega(false); }, 260);
            });
        }
        document.addEventListener("pointerdown", function (e) { if (!megaPanel.hidden && !mega.contains(e.target)) setMega(false); });
        mega.addEventListener("focusout", function (e) { if (!megaPanel.hidden && e.relatedTarget && !mega.contains(e.relatedTarget)) setMega(false); });
        mega.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && !megaPanel.hidden) { e.stopPropagation(); setMega(false, true); }
        });
        // Ouvert, un lien du menu est atteint par Tab depuis le bouton ; ↓ y entre directement.
        megaBtn.addEventListener("keydown", function (e) {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setMega(true);
                var first = megaPanel.querySelector("a[href]");
                if (first) first.focus();
            }
        });
    }

    /* ---- Retour en haut ----
       Le bouton apparaît après un écran de défilement ; respecte « réduire les animations ». */
    var toTop = document.getElementById("to-top");
    if (toTop) {
        var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        var shownTop = false, ticking = false;
        var syncTop = function () {
            ticking = false;
            var show = (window.pageYOffset || root.scrollTop) > Math.max(600, window.innerHeight * 0.7);
            if (show === shownTop) return;
            shownTop = show;
            if (show) { toTop.hidden = false; window.requestAnimationFrame(function () { toTop.classList.add("is-visible"); }); }
            else { toTop.classList.remove("is-visible"); window.setTimeout(function () { if (!shownTop) toTop.hidden = true; }, 320); }
        };
        window.addEventListener("scroll", function () { if (!ticking) { ticking = true; window.requestAnimationFrame(syncTop); } }, { passive: true });
        toTop.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
            var skip = document.querySelector("a.visually-hidden[href='#main']");
            if (skip) skip.focus({ preventScroll: true });
        });
        syncTop();
    }

    /* ---- Section en cours dans un index de sections ----
       `.section-index a[href^='#']` : le lien de la dernière section dont le haut a passé la barre collante porte aria-current="true"
       (soulignement, voir patrick.css). Recalculé au défilement, au plus une fois par image. */
    Array.prototype.forEach.call(document.querySelectorAll(".section-index"), function (index) {
        var links = Array.prototype.filter.call(index.querySelectorAll("a[href^='#']"), function (a) { return a.getAttribute("href").length > 1; });
        var targets = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
        if (!links.length) return;
        var pending = false;
        var mark = function () {
            pending = false;
            var line = index.getBoundingClientRect().bottom + 24, pick = -1;
            targets.forEach(function (el, i) { if (el && el.getBoundingClientRect().top <= line) pick = i; });
            if (window.innerHeight + (window.pageYOffset || 0) >= document.documentElement.scrollHeight - 4) {       // en bas de page : la dernière section, même courte
                targets.forEach(function (el, i) { if (el) pick = i; });
            }
            links.forEach(function (a, i) { if (i === pick) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); });
        };
        window.addEventListener("scroll", function () { if (!pending) { pending = true; window.requestAnimationFrame(mark); } }, { passive: true });
        mark();
    });
})();
