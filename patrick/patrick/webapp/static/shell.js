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

    /* ---- Command palette ---- */
    var dialog = document.getElementById("cmdk");
    var input = document.getElementById("cmdk-input");
    var list = document.getElementById("cmdk-list");
    var trigger = document.getElementById("cmdk-open");
    var items = [];
    try { items = JSON.parse(document.getElementById("cmdk-data").textContent || "[]"); } catch (e) { items = []; }
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
            li.innerHTML = it.icon;  // server-rendered SVG (icons.py), not user data
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
})();
