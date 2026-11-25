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
    var themeSwaps = 0;
    if (themeBtn) {
        themeBtn.addEventListener("click", function (e) {
            var next = effectiveTheme() === "dark" ? "light" : "dark";
            var apply = function () {
                root.setAttribute("data-theme", next);
                store("patrick-theme", next);
                announceTheme();
            };
            // Ancien et nouveau thème mêlés : la nouvelle palette se révèle en cercle depuis le bouton (patrick.css,
            // `data-vt="theme"`). Jamais au clavier (`detail === 0`) ni avec prefers-reduced-motion.
            var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            if (!document.startViewTransition || still || e.detail === 0) { apply(); return; }
            var r = themeBtn.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
            var radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
            root.style.setProperty("--vt-x", x.toFixed(0) + "px");
            root.style.setProperty("--vt-y", y.toFixed(0) + "px");
            root.style.setProperty("--vt-r", radius.toFixed(0) + "px");
            root.setAttribute("data-vt", "theme");
            var mine = ++themeSwaps;
            var done = function () { if (mine === themeSwaps) root.removeAttribute("data-vt"); };
            window.setTimeout(done, 1200);              // filet : une transition jamais terminée ne fige pas l'attribut
            try { document.startViewTransition(apply).finished.then(done, done); }
            catch (err) { done(); apply(); }
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
            window.setTimeout(function () { window.dispatchEvent(new Event("resize")); }, 280);    // après la transition de 260 ms
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

    /* ---- Actifs : la palette ouvre aussi la fiche d'un actif (/targets/{symbole}) ----
       L'index (symbole, nom affiché, classe) vient de /api/asset-index, chargé une seule fois à la première ouverture (ou au survol du
       bouton) puis gardé dans sessionStorage 10 minutes. Sans saisie, la liste reste celle des pages : les actifs n'apparaissent que
       quand on tape (il y en a plusieurs centaines). */
    var ASSET_LIMIT = 30, ASSET_TTL_MS = 600000;
    var assets = null, assetsLoading = false;
    function toAssetItems(rows) {
        return rows.map(function (a) {
            var shown = a.n || a.s, cut = shown.indexOf(" · ");
            return { url: "/targets/" + encodeURIComponent(a.s), label: shown, group: a.g, slug: "asset", asset: true, hint: a.s + " · " + a.g,
                     sym: normalize(a.s), full: normalize(shown), bare: normalize(cut >= 0 ? shown.slice(cut + 3) : shown) };
        });
    }
    /* AM13 (25/11) : notions du dictionnaire, cours et derniers runs (/api/search-index), chargés comme les actifs, jamais avant la saisie. */
    var extra = null, extraLoading = false;
    function loadExtra() {
        if (extra !== null || extraLoading) return;
        extraLoading = true;
        fetch("/api/search-index", { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (rows) {
                extra = rows.map(function (x) {
                    return { url: x.u, label: x.l, group: x.g, slug: x.k, asset: true, hint: x.g,
                             sym: normalize(x.a || ""), full: normalize(x.l), bare: normalize(x.l) };
                });
                if (dialog && !dialog.hidden) render();
            })
            .catch(function () { extra = []; })
            .then(function () { extraLoading = false; });
    }
    function loadAssets() {
        loadExtra();
        if (assets !== null || assetsLoading) return;
        var key = "patrick.asset-index." + (document.documentElement.lang || "fr");
        try {
            var saved = JSON.parse(window.sessionStorage.getItem(key) || "null");
            if (saved && Date.now() - saved.at < ASSET_TTL_MS && saved.rows && saved.rows.length) { assets = toAssetItems(saved.rows); return; }
        } catch (e) { /* stockage indisponible : on recharge */ }
        assetsLoading = true;
        fetch("/api/asset-index", { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (rows) {
                assets = toAssetItems(rows);
                try { window.sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), rows: rows })); } catch (e) { /* quota ou mode privé */ }
                if (dialog && !dialog.hidden) render();
            })
            .catch(function () { assets = []; })
            .then(function () { assetsLoading = false; });
    }
    // Un actif correspond par son symbole (exact > début > contient) ou par son nom ; pas de correspondance « sous-suite » (trop de bruit).
    function assetScore(item, q) {
        if (item.sym === q) return 5;
        if (item.sym.indexOf(q) === 0) return 4.5;
        if (item.bare.indexOf(q) === 0) return 4;
        if (item.full.indexOf(q) >= 0) return 3;
        if (item.sym.indexOf(q) >= 0) return 2.5;
        return 0;
    }

    function score(item, q) {
        if (!q) return 1;
        if (item.asset) return assetScore(item, q);
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
        var pool = (q && assets) ? items.concat(assets) : items;
        if (q && extra) pool = pool.concat(extra);
        var assetCount = 0;
        shown = pool
            .map(function (it, idx) { return { it: it, s: score(it, q), idx: idx }; })
            .filter(function (r) { return r.s > 0; })
            .sort(function (a, b) { return b.s - a.s || a.idx - b.idx; })
            .filter(function (r) { return !r.it.asset || ++assetCount <= ASSET_LIMIT; })
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
            hint.textContent = it.hint || it.url;
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
        // Les premières lignes entrent à 30 ms d'écart à l'ouverture seulement : jamais pendant la frappe (patrick.css).
        dialog.setAttribute("data-opening", "");
        window.clearTimeout(openingTimer);
        openingTimer = window.setTimeout(function () { dialog.removeAttribute("data-opening"); }, 500);
        dialog.hidden = false;
        input.value = "";
        active = 0;
        loadAssets();
        render();
        input.focus();
    }
    var openingTimer = null;
    function close() {
        if (!dialog || dialog.hidden) return;
        dialog.hidden = true;
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
    if (dialog && input && list) {
        if (trigger) {
            trigger.addEventListener("click", open);
            trigger.addEventListener("pointerenter", loadAssets, { once: true });   // l'index est prêt avant la première frappe
        }
        input.addEventListener("input", function () { dialog.removeAttribute("data-opening"); active = 0; render(); });
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

    /* ---- Menu « Plus d'actions » (barre du haut, ≤ 640 px) ----
       Même bouton à bascule que le menu en blocs : clic, ↓ pour y entrer, Échap (le focus revient au bouton), clic en dehors, sortie
       du focus. Au-delà de 640 px le bouton est masqué et l'enveloppe en `display: contents` : la classe `is-open` n'y change rien. */
    var moreBtn = document.getElementById("topbar-more-btn");
    var morePanel = document.getElementById("topbar-more");
    if (moreBtn && morePanel) {
        var inMore = function (el) { return !!el && (moreBtn.contains(el) || morePanel.contains(el)); };
        var moreOpen = function () { return moreBtn.getAttribute("aria-expanded") === "true"; };
        var setMore = function (open, focusBack) {
            moreBtn.setAttribute("aria-expanded", open ? "true" : "false");
            morePanel.classList.toggle("is-open", open);
            if (!open && focusBack) moreBtn.focus();
        };
        moreBtn.addEventListener("click", function () { setMore(!moreOpen()); });
        moreBtn.addEventListener("keydown", function (e) {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setMore(true);
                var first = morePanel.querySelector("a[href], button");
                if (first) first.focus();
            }
        });
        document.addEventListener("pointerdown", function (e) { if (moreOpen() && !inMore(e.target)) setMore(false); });
        [moreBtn, morePanel].forEach(function (el) {
            el.addEventListener("focusout", function (e) { if (moreOpen() && e.relatedTarget && !inMore(e.relatedTarget)) setMore(false); });
            el.addEventListener("keydown", function (e) {
                if (e.key === "Escape" && moreOpen()) { e.stopPropagation(); setMore(false, true); }
            });
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

    /* ---- Épingles et pages récentes (2026-11-23) ----
       N'importe quelle page s'épingle (étoile de la barre du haut ou touche « p ») : fiche d'un actif, run, page d'analyse... avec ses
       paramètres d'adresse. Les épingles s'affichent en tête de la barre latérale et de la palette Ctrl K ; les dernières pages visitées
       aussi, dans la palette. Rangées dans ce navigateur (localStorage) : une commodité, pas une donnée. */
    var PINS_KEY = "patrick-pins", RECENT_KEY = "patrick-recent", RECENT_MAX = 8, PINS_MAX = 30;
    function T(key, fallback) { return (window.I18N && window.I18N[key]) || fallback; }
    function readList(key) {
        try { var v = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(v) ? v.filter(function (x) { return x && typeof x.url === "string"; }) : []; }
        catch (e) { return []; }
    }
    function here() { return window.location.pathname + window.location.search; }
    function pageTitle() {
        var crumb = document.querySelector(".topbar-crumbs .crumb-current") || document.querySelector(".topbar-crumbs .crumb-entry:last-of-type");
        var h1 = document.querySelector("main h1");
        var title = (h1 && h1.textContent.trim()) || (crumb && crumb.textContent.trim()) || document.title.replace(/^PATRICK\s*[—-]\s*/, "");
        return title.replace(/\s+/g, " ").slice(0, 80);
    }
    function isPinned(url) { return readList(PINS_KEY).some(function (p) { return p.url === url; }); }
    function setPins(list) { store(PINS_KEY, JSON.stringify(list.slice(0, PINS_MAX))); renderPins(); syncPinButton(); }
    function togglePin(url, title) {
        var pins = readList(PINS_KEY);
        var idx = pins.findIndex(function (p) { return p.url === url; });
        if (idx >= 0) pins.splice(idx, 1); else pins.unshift({ url: url, title: title || url });
        setPins(pins);
    }

    var pinBtn = document.getElementById("pin-toggle");
    function syncPinButton() {
        if (!pinBtn) return;
        var on = isPinned(here());
        pinBtn.setAttribute("aria-pressed", on ? "true" : "false");
        var label = on ? T("pin_remove", "Unpin this page") : T("pin_add", "Pin this page");
        pinBtn.setAttribute("aria-label", label + " (P)");
        pinBtn.title = label + " (P)";
    }
    if (pinBtn) pinBtn.addEventListener("click", function () { togglePin(here(), pageTitle()); });

    var pinsBox = document.getElementById("sidebar-pins"), pinsList = document.getElementById("pins-list");
    function renderPins() {
        if (!pinsBox || !pinsList) return;
        var pins = readList(PINS_KEY), cur = here();
        pinsList.textContent = "";
        pins.forEach(function (p) {
            var li = document.createElement("li");
            li.className = "nav-leaf nav-pin";
            var a = document.createElement("a");
            a.href = p.url;
            a.title = p.title;
            if (p.url === cur) a.setAttribute("aria-current", "page");
            var label = document.createElement("span");
            label.className = "nav-label";
            label.textContent = p.title;
            a.appendChild(label);
            var rm = document.createElement("button");
            rm.type = "button";
            rm.className = "nav-pin-remove";
            rm.setAttribute("aria-label", T("pin_remove", "Unpin") + " : " + p.title);
            rm.title = T("pin_remove", "Unpin");
            rm.textContent = "×";
            rm.addEventListener("click", function (e) { e.preventDefault(); togglePin(p.url); });
            li.appendChild(a);
            li.appendChild(rm);
            pinsList.appendChild(li);
        });
        pinsBox.hidden = !pins.length;
    }

    // Page récente : notée à chaque affichage (la page courante en tête, sans doublon).
    (function noteRecent() {
        if (document.documentElement.hasAttribute("data-embed")) return;            // volet de /split : pas une visite
        var url = here();
        var recent = readList(RECENT_KEY).filter(function (r) { return r.url !== url; });
        recent.unshift({ url: url, title: pageTitle() });
        store(RECENT_KEY, JSON.stringify(recent.slice(0, RECENT_MAX)));
    })();

    // Palette Ctrl K : épingles puis pages récentes en tête quand rien n'est tapé ; les épingles restent cherchables.
    if (typeof render === "function" && list) {
        var baseItems = items.slice();
        var refreshPaletteItems = function () {
            var known = {};
            baseItems.forEach(function (it) { known[it.url] = it; });
            var pins = readList(PINS_KEY).map(function (p) {
                return { url: p.url, label: p.title, group: T("pins_title", "Pinned"), slug: (known[p.url] || {}).slug || "pin", hint: p.url, pin: true,
                         dup: !!known[p.url] };
            });
            var cur = here();
            var recents = readList(RECENT_KEY).filter(function (r) { return r.url !== cur; }).slice(0, 5).map(function (r) {
                return { url: r.url, label: r.title, group: T("recent_title", "Recent"), slug: (known[r.url] || {}).slug || "recent", hint: r.url, recent: true };
            });
            items.length = 0;
            pins.concat(recents, baseItems).forEach(function (it) { items.push(it); });
        };
        var baseScore = score;
        score = function (item, q) {
            if (item.recent && q) return 0;                                   // en recherche : les pages, pas l'historique de navigation
            if (item.pin && q) return item.dup ? 0 : baseScore(item, q) + 0.25;   // la page est déjà dans la liste ; sinon l'épingle passe devant
            return baseScore(item, q);
        };
        if (trigger) trigger.addEventListener("click", refreshPaletteItems, true);
        document.addEventListener("keydown", function (e) { if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) refreshPaletteItems(); }, true);
        document.addEventListener("keydown", function (e) {
            var tag = (e.target && e.target.tagName) || "";
            if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) refreshPaletteItems();
        }, true);
    }

    /* ---- Raccourcis clavier : « ? » les liste, « p » épingle, « [ » replie la barre latérale, « t » change de thème ---- */
    var kbdHelp = document.getElementById("kbd-help");
    function setKbdHelp(open) {
        if (!kbdHelp) return;
        kbdHelp.hidden = !open;
        if (open) { var c = kbdHelp.querySelector("button"); if (c) c.focus(); }
    }
    if (kbdHelp) {
        kbdHelp.addEventListener("click", function (e) { if (e.target === kbdHelp || e.target.closest("[data-kbd-close]")) setKbdHelp(false); });
    }
    document.addEventListener("keydown", function (e) {
        var tag = (e.target && e.target.tagName) || "";
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || (e.target && e.target.isContentEditable) || e.metaKey || e.ctrlKey || e.altKey) return;
        if (dialog && !dialog.hidden) return;
        if (e.key === "Escape") { setKbdHelp(false); return; }
        if (e.key === "?") { e.preventDefault(); setKbdHelp(kbdHelp && kbdHelp.hidden); }
        else if (e.key === "p" || e.key === "P") { e.preventDefault(); togglePin(here(), pageTitle()); }
        else if (e.key === "[") { var sb = document.getElementById("sidebar-toggle"); if (sb && sb.offsetParent !== null) { e.preventDefault(); sb.click(); } }
        else if (e.key === "t" || e.key === "T") { var th = document.getElementById("theme-toggle"); if (th) { e.preventDefault(); th.click(); } }
    });

    /* ---- Puce « machine » de la barre du haut, sur toutes les pages : run en cours, avancement, temps pour vider la file ----
       Sur /ml, /dl et /rl la carte « File d'attente » lit déjà l'état : on s'y abonne au lieu de le relire. Ailleurs, une lecture toutes
       les 20 s, seulement quand l'onglet est visible. */
    var chip = document.getElementById("machine-chip");
    function shortDur(seconds) {
        var min = Math.round(Math.max(0, seconds || 0) / 60);
        if (min < 1) return T("dur_short_lt", "< 1 min");
        if (min < 60) return T("dur_short_min", "{m} min").replace("{m}", min);
        var hh = Math.floor(min / 60), mm = min % 60;
        if (hh >= 48) return T("dur_short_d", "{d} d {h} h").replace("{d}", Math.floor(hh / 24)).replace("{h}", hh % 24);
        return T("dur_short_h", "{h} h {m}").replace("{h}", hh).replace("{m}", (mm < 10 ? "0" : "") + mm);
    }
    function renderChip(state) {
        if (!chip) return;
        var active = state && (state.active_run || state.active), queue = (state && state.queue) || [], eta = state && state.queue_eta;
        if (!active && !queue.length) { chip.hidden = true; return; }
        var parts = [];
        if (active) {
            var done = (active.progress && active.progress.done) || 0, total = (active.progress && active.progress.total) || 0;
            parts.push((active.status === "paused" ? "❚❚ " : "▶ ") + (active.name || "") + (total ? " · " + Math.round(100 * done / total) + " %" : ""));
            chip.href = active.kind === "rl" ? "/rl#machine-card" : active.kind === "dl" ? "/dl#machine-card" : "/ml#machine-card";
        } else {
            chip.href = "/ml#machine-card";
        }
        if (queue.length) parts.push(T("chip_queue", "queue {n}").replace("{n}", queue.length));
        if (eta && eta.total_s) parts.push("≈ " + shortDur(eta.total_s));
        var text = chip.querySelector(".machine-chip-text");
        if (text) text.textContent = parts.join(" · ");
        chip.title = T("chip_title", "Training machine: current run, queue and time to finish everything");
        chip.classList.toggle("is-paused", !!(active && active.status === "paused"));
        chip.hidden = false;
    }
    if (chip) {
        if (window.PatrickMachine) {
            window.PatrickMachine.subscribe(function (s) {
                // la carte ne publie que { active, queue } : l'estimation de la file vient du dernier état complet lu
                renderChip({ active_run: s.active, queue: s.queue, queue_eta: lastChipState && lastChipState.queue_eta });
            });
        }
        var lastChipState = null;
        var readChip = function () {
            if (document.hidden) return;
            fetch("/api/run-state", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; })
                .then(function (s) { if (s) { lastChipState = s; renderChip(s); } }).catch(function () { /* hors ligne : la puce garde son état */ });
        };
        readChip();
        window.setInterval(readChip, window.PatrickMachine ? 60000 : 20000);
        document.addEventListener("visibilitychange", function () { if (!document.hidden) readChip(); });
    }

    /* ---- Puce « nuit » (D21) : visible seulement quand la dernière tâche de nuit a échoué, été partielle ou manquée. Lue au chargement
       puis toutes les 10 minutes (la nuit ne change pas plus vite). ---- */
    var nightChip = document.getElementById("night-chip");
    function readNight() {
        if (!nightChip || document.hidden) return;
        fetch("/api/night-status", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (n) {
            var label = n && { failed: T("night_chip_failed", "Night: funds not done"), partial: T("night_chip_partial", "Night: partial"),
                               missed: T("night_chip_missed", "Night: missed") }[n.status];
            if (!label) { nightChip.hidden = true; return; }
            nightChip.querySelector(".machine-chip-text").textContent = label;
            nightChip.title = T("night_chip_title", "Last night task started {start}; failed steps: {steps}")
                .replace("{start}", (n.started || "?").replace("T", " "))
                .replace("{steps}", (n.failed_steps && n.failed_steps.length) ? n.failed_steps.join(", ") : T("night_chip_none", "none"));
            nightChip.classList.toggle("is-alert", n.status === "failed" || n.status === "missed");
            nightChip.hidden = false;
        }).catch(function () { /* hors ligne : la puce garde son état */ });
    }
    readNight();
    window.setInterval(readNight, 600000);

    renderPins();
    syncPinButton();

    /* ---- Dates relatives (D18) : <time class="rel-time" datetime="…Z"> -> « il y a 3 h », date exacte locale au survol.
       Refait toutes les minutes (les fragments chargés plus tard sont pris au passage suivant). ---- */
    var REL_UNITS = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
    function relTimes() {
        if (!window.Intl || !Intl.RelativeTimeFormat) return;
        var lang = root.getAttribute("lang") || "fr";
        var rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
        var now = Date.now();
        document.querySelectorAll("time.rel-time[datetime]").forEach(function (el) {
            var t = Date.parse(el.getAttribute("datetime"));
            if (isNaN(t)) return;
            var secs = (t - now) / 1000, abs = Math.abs(secs), text = null;
            for (var i = 0; i < REL_UNITS.length; i++) {
                if (abs >= REL_UNITS[i][1]) { text = rtf.format(Math.round(secs / REL_UNITS[i][1]), REL_UNITS[i][0]); break; }
            }
            el.textContent = text || rtf.format(0, "second");       // moins d'une minute : « maintenant »
            if (!el.dataset.exact) {
                el.dataset.exact = "1";
                el.title = new Date(t).toLocaleString(lang);
            }
        });
    }
    relTimes();
    window.setInterval(relTimes, 60000);
    document.addEventListener("patrick:content", relTimes);           // fragment chargé par lazy.js
})();
