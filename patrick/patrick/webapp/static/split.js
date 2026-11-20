/* Page « Écrans côte à côte » (/split) : plusieurs pages de PATRICK affichées en même temps, dans des volets, comme les dispositions d'écran de
   Windows. Chaque volet est une `<iframe>` de la même origine ; les pages s'y affichent sans barre latérale ni barre du haut (mode intégré,
   posé par le petit script de base_v2.html quand la fenêtre parente est /split).

   Deux parties dans ce fichier :
     - des fonctions PURES (géométrie des dispositions, bornes des séparateurs, état <-> lien) : testées sous Node (tests/js/split.test.js) ;
     - l'interface (volets, sélecteur de page ou d'actif, séparateurs glissants, mémoire locale), lancée seulement si la page /split est là.
   L'état tient dans le fragment d'adresse (`#l=g4&x=0.5&y=0.5&p=…`) : un lien partage la vue, et c'est aussi ce que garde le navigateur. */
(function (root) {
    "use strict";

    var MIN = 0.12;                       // fraction minimale d'un volet
    var MAX_PANES = 4;
    var STORAGE_KEY = "patrick.split.v1";
    var LAYOUTS = {
        s1:  { n: 1, defaults: {} },
        c2:  { n: 2, defaults: { x: 0.5 } },
        c3:  { n: 3, defaults: { x: 1 / 3, x2: 2 / 3 } },
        r2:  { n: 2, defaults: { y: 0.5 } },
        g4:  { n: 4, defaults: { x: 0.5, y: 0.5 } },
        l12: { n: 3, defaults: { x: 0.6, y: 0.5 } },     // un grand volet à gauche, deux empilés à droite
        t12: { n: 3, defaults: { x: 0.5, y: 0.6 } }      // un grand volet en haut, deux côte à côte en bas
    };

    // ------------------------------------------------------------------ fonctions pures
    function defaultsFor(layout) {
        var spec = LAYOUTS[layout] || LAYOUTS.c2, out = {};
        Object.keys(spec.defaults).forEach(function (k) { out[k] = spec.defaults[k]; });
        return out;
    }

    function ratios(layout, r) {
        var d = defaultsFor(layout), out = {};
        Object.keys(d).forEach(function (k) { out[k] = (r && typeof r[k] === "number" && isFinite(r[k])) ? r[k] : d[k]; });
        return out;
    }

    // Bornes d'un séparateur : jamais de volet plus étroit que MIN, et x2 reste à droite de x.
    function clampRatio(layout, key, value, r) {
        var lo = MIN, hi = 1 - MIN;
        if (layout === "c3") {
            if (key === "x") hi = (r.x2 !== undefined ? r.x2 : 2 / 3) - MIN;
            if (key === "x2") lo = (r.x !== undefined ? r.x : 1 / 3) + MIN;
        }
        return Math.min(hi, Math.max(lo, value));
    }

    // Rectangles des volets et séparateurs, en fractions de la scène (0..1). Un séparateur : `axis` = 'x' (trait vertical à x = pos) ou 'y'
    // (trait horizontal à y = pos), de `from` à `to` sur l'autre axe ; `key` = le réglage qu'il déplace.
    function geometry(layout, r) {
        var v = ratios(layout, r), x = v.x, y = v.y, x2 = v.x2;
        switch (layout) {
            case "s1":
                return { panes: [{ x: 0, y: 0, w: 1, h: 1 }], gutters: [] };
            case "c3":
                return { panes: [{ x: 0, y: 0, w: x, h: 1 }, { x: x, y: 0, w: x2 - x, h: 1 }, { x: x2, y: 0, w: 1 - x2, h: 1 }],
                         gutters: [{ key: "x", axis: "x", pos: x, from: 0, to: 1 }, { key: "x2", axis: "x", pos: x2, from: 0, to: 1 }] };
            case "r2":
                return { panes: [{ x: 0, y: 0, w: 1, h: y }, { x: 0, y: y, w: 1, h: 1 - y }],
                         gutters: [{ key: "y", axis: "y", pos: y, from: 0, to: 1 }] };
            case "g4":
                return { panes: [{ x: 0, y: 0, w: x, h: y }, { x: x, y: 0, w: 1 - x, h: y }, { x: 0, y: y, w: x, h: 1 - y }, { x: x, y: y, w: 1 - x, h: 1 - y }],
                         gutters: [{ key: "x", axis: "x", pos: x, from: 0, to: 1 }, { key: "y", axis: "y", pos: y, from: 0, to: 1 }] };
            case "l12":
                return { panes: [{ x: 0, y: 0, w: x, h: 1 }, { x: x, y: 0, w: 1 - x, h: y }, { x: x, y: y, w: 1 - x, h: 1 - y }],
                         gutters: [{ key: "x", axis: "x", pos: x, from: 0, to: 1 }, { key: "y", axis: "y", pos: y, from: x, to: 1 }] };
            case "t12":
                return { panes: [{ x: 0, y: 0, w: 1, h: y }, { x: 0, y: y, w: x, h: 1 - y }, { x: x, y: y, w: 1 - x, h: 1 - y }],
                         gutters: [{ key: "y", axis: "y", pos: y, from: 0, to: 1 }, { key: "x", axis: "x", pos: x, from: y, to: 1 }] };
            default: // c2
                return { panes: [{ x: 0, y: 0, w: x, h: 1 }, { x: x, y: 0, w: 1 - x, h: 1 }],
                         gutters: [{ key: "x", axis: "x", pos: x, from: 0, to: 1 }] };
        }
    }

    // Seules des pages de l'application, à l'intérieur de la même origine : jamais d'adresse absolue, d'API ni de /split lui-même (récursion).
    function sanitizeUrl(u) {
        if (typeof u !== "string") return "";
        u = u.trim();
        if (u.charAt(0) !== "/" || u.charAt(1) === "/" || u.charAt(1) === "\\") return "";
        if (/^\/(split|api|static|fragments)(\/|\?|#|$)/.test(u)) return "";
        if (/[\u0000-\u001f]/.test(u)) return "";
        return u.slice(0, 600);
    }

    function numberOr(value, fallback) {
        var n = parseFloat(value);
        return isFinite(n) ? n : fallback;
    }

    // État <-> fragment d'adresse. Les adresses des volets sont séparées par « , » après encodage.
    function encodeState(state) {
        var r = ratios(state.layout, state.ratios), parts = ["l=" + state.layout];
        Object.keys(r).forEach(function (k) { parts.push(k + "=" + (Math.round(r[k] * 1000) / 1000)); });
        var urls = (state.panes || []).map(function (u) { return encodeURIComponent(sanitizeUrl(u)); });
        while (urls.length && urls[urls.length - 1] === "") urls.pop();            // pas de virgules vides en fin de lien
        parts.push("p=" + urls.join(","));
        return parts.join("&");
    }

    function decodeState(text) {
        var raw = {};
        String(text || "").replace(/^#/, "").split("&").forEach(function (kv) {
            var i = kv.indexOf("=");
            if (i > 0) raw[kv.slice(0, i)] = kv.slice(i + 1);
        });
        var layout = LAYOUTS[raw.l] ? raw.l : null;
        if (!layout) return null;
        var d = defaultsFor(layout), r = {};
        Object.keys(d).forEach(function (k) { r[k] = numberOr(raw[k], d[k]); });
        Object.keys(r).forEach(function (k) { r[k] = clampRatio(layout, k, r[k], r); });
        var panes = (raw.p === undefined || raw.p === "") ? [] : raw.p.split(",").map(function (s) {
            try { return sanitizeUrl(decodeURIComponent(s)); } catch (e) { return ""; }
        });
        return normalize({ layout: layout, ratios: r, panes: panes });
    }

    // Autant de volets que la disposition en demande (les volets en trop sont gardés en mémoire, jamais perdus).
    function normalize(state) {
        var n = LAYOUTS[state.layout].n, panes = (state.panes || []).slice(0, MAX_PANES);
        while (panes.length < MAX_PANES) panes.push("");
        return { layout: state.layout, ratios: ratios(state.layout, state.ratios), panes: panes, shown: n };
    }

    function titleOf(rawTitle) {
        return String(rawTitle || "").replace(/^PATRICK\s*[—-]\s*/, "").trim();
    }

    var api = { LAYOUTS: LAYOUTS, MIN: MIN, MAX_PANES: MAX_PANES, defaultsFor: defaultsFor, ratios: ratios, clampRatio: clampRatio, geometry: geometry,
                sanitizeUrl: sanitizeUrl, encodeState: encodeState, decodeState: decodeState, normalize: normalize, titleOf: titleOf };
    if (typeof module === "object" && module.exports) module.exports = api;
    root.PatrickSplit = api;

    // ------------------------------------------------------------------ interface
    var doc = root.document;
    if (!doc || !doc.getElementById("split-app")) return;

    var GAP = 6;                                            // px entre deux volets (la moitié de chaque côté)
    var app = doc.getElementById("split-app");
    var stage = doc.getElementById("split-stage");
    var I18N = root.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback; }
    function norm(s) { return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }

    // Une page affichée dans un volet ne peut pas elle-même être /split.
    if (root.self !== root.top) {
        app.innerHTML = "<p class=\"hint\">" + tr("sp_nested", "Cette page ne peut pas s'afficher dans un volet.") + "</p>";
        return;
    }

    var pages = [];
    try { pages = JSON.parse(doc.getElementById("split-pages").textContent || "[]"); } catch (e) { pages = []; }
    var assets = null;
    var state = null;
    var maximized = -1;
    var picker = null;

    function loadState() {
        var fromHash = decodeState(root.location.hash);
        if (fromHash) return fromHash;
        try {
            var saved = JSON.parse(root.localStorage.getItem(STORAGE_KEY) || "null");
            if (saved && LAYOUTS[saved.layout]) return normalize(saved);
        } catch (e) { /* stockage indisponible */ }
        return normalize({ layout: "c2", ratios: {}, panes: ["/predictions?view=horizon", ""] });
    }
    function saveState() {
        var text = encodeState(state);
        try { root.history.replaceState(null, "", root.location.pathname + "#" + text); } catch (e) { /* aperçu intégré */ }
        try { root.localStorage.setItem(STORAGE_KEY, JSON.stringify({ layout: state.layout, ratios: state.ratios, panes: state.panes })); } catch (e) { /* quota */ }
    }

    // ---- sélection d'une page ou d'un actif
    function loadAssets(done) {
        if (assets !== null) { done(); return; }
        var key = "patrick.asset-index." + (doc.documentElement.lang || "fr");
        try {
            var saved = JSON.parse(root.sessionStorage.getItem(key) || "null");
            if (saved && saved.rows && saved.rows.length) { assets = saved.rows; done(); return; }
        } catch (e) { /* on recharge */ }
        root.fetch("/api/asset-index", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : []; }).then(function (rows) {
            assets = rows;
            try { root.sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), rows: rows })); } catch (e) { /* quota */ }
        }).catch(function () { assets = []; }).then(done);
    }

    function candidates(query) {
        var q = norm(query.trim()), out = [];
        if (q.charAt(0) === "/") {
            var path = sanitizeUrl(query.trim());
            if (path) out.push({ url: path, label: path, hint: tr("sp_open_path", "Ouvrir cette adresse") });
            return out;
        }
        pages.forEach(function (p) {
            if (!q || norm(p.label).indexOf(q) >= 0 || norm(p.group).indexOf(q) >= 0) out.push({ url: p.url, label: p.label, hint: p.group });
        });
        if (q && assets) {
            var n = 0;
            assets.forEach(function (a) {
                if (n >= 20) return;
                if (norm(a.s).indexOf(q) >= 0 || norm(a.n).indexOf(q) >= 0) {
                    n++;
                    out.push({ url: "/targets/" + encodeURIComponent(a.s), label: a.n, hint: a.s + " · " + a.g });
                }
            });
        }
        return out;
    }

    // Sélecteur : un champ de recherche et une liste (pages d'abord, actifs dès qu'on tape). Rendu dans `host`.
    function mountPicker(host, onPick) {
        host.innerHTML = "";
        var input = doc.createElement("input");
        input.type = "search";
        input.className = "split-picker-input";
        input.placeholder = tr("sp_search_ph", "Page ou actif…");
        input.setAttribute("aria-label", tr("sp_search_ph", "Page ou actif…"));
        input.autocomplete = "off";
        var list = doc.createElement("ul");
        list.className = "split-picker-list";
        list.setAttribute("role", "listbox");
        host.appendChild(input);
        host.appendChild(list);
        var active = 0, shown = [];
        function render() {
            shown = candidates(input.value);
            list.innerHTML = "";
            shown.slice(0, 60).forEach(function (c, i) {
                var li = doc.createElement("li");
                li.setAttribute("role", "option");
                li.className = "split-picker-item" + (i === active ? " is-active" : "");
                var label = doc.createElement("span"); label.textContent = c.label;
                var hint = doc.createElement("span"); hint.className = "split-picker-hint"; hint.textContent = c.hint;
                li.appendChild(label); li.appendChild(hint);
                li.addEventListener("mousemove", function () { active = i; render_active(); });
                li.addEventListener("click", function () { onPick(c.url); });
                list.appendChild(li);
            });
        }
        function render_active() {
            Array.prototype.forEach.call(list.children, function (li, i) { li.classList.toggle("is-active", i === active); });
        }
        input.addEventListener("input", function () { active = 0; render(); });
        input.addEventListener("keydown", function (e) {
            if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); render_active(); }
            else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render_active(); }
            else if (e.key === "Enter" && shown[active]) { e.preventDefault(); onPick(shown[active].url); }
        });
        loadAssets(function () { if (doc.body.contains(input)) render(); });
        render();
        return input;
    }

    function closePicker() {
        if (picker) { picker.remove(); picker = null; }
    }
    function openPicker(i, anchor) {
        closePicker();
        picker = doc.createElement("div");
        picker.className = "split-picker split-picker-pop";
        var rect = anchor.getBoundingClientRect(), box = stage.getBoundingClientRect();
        picker.style.left = Math.max(0, Math.min(rect.left - box.left, box.width - 340)) + "px";
        picker.style.top = (rect.bottom - box.top + 4) + "px";
        stage.appendChild(picker);
        mountPicker(picker, function (url) { closePicker(); setPane(i, url); }).focus();
    }

    // ---- volets
    var paneEls = [];
    function setPane(i, url) {
        state.panes[i] = sanitizeUrl(url);
        saveState();
        renderPane(i, true);
    }

    function buildPane(i) {
        var pane = doc.createElement("section");
        pane.className = "split-pane";
        pane.dataset.i = String(i);
        pane.innerHTML =
            "<header class=\"split-pane-bar\">" +
            "<button type=\"button\" class=\"split-pane-title\" aria-haspopup=\"listbox\"></button>" +
            "<span class=\"split-pane-tools\">" +
            "<button type=\"button\" class=\"split-tool\" data-act=\"reload\"></button>" +
            "<button type=\"button\" class=\"split-tool\" data-act=\"max\"></button>" +
            "<a class=\"split-tool\" data-act=\"open\" target=\"_blank\" rel=\"noopener\"></a>" +
            "<button type=\"button\" class=\"split-tool\" data-act=\"close\"></button>" +
            "</span></header><div class=\"split-pane-body\"></div>";
        var tools = {
            reload: ["⟳", tr("sp_reload", "Recharger")], max: ["⤢", tr("sp_maximize", "Agrandir")],
            open: ["↗", tr("sp_open_tab", "Ouvrir en pleine page")], close: ["✕", tr("sp_close", "Vider ce volet")]
        };
        Object.keys(tools).forEach(function (act) {
            var el = pane.querySelector("[data-act=" + act + "]");
            el.textContent = tools[act][0];
            el.title = tools[act][1];
            el.setAttribute("aria-label", tools[act][1]);
        });
        pane.querySelector(".split-pane-title").addEventListener("click", function (e) { openPicker(i, e.currentTarget); });
        pane.querySelector("[data-act=reload]").addEventListener("click", function () { renderPane(i, true); });
        pane.querySelector("[data-act=close]").addEventListener("click", function () { setPane(i, ""); });
        pane.querySelector("[data-act=max]").addEventListener("click", function () { maximized = (maximized === i) ? -1 : i; layout(); });
        return pane;
    }

    function renderPane(i, force) {
        var pane = paneEls[i];
        var url = state.panes[i];
        var body = pane.querySelector(".split-pane-body");
        var title = pane.querySelector(".split-pane-title");
        var open = pane.querySelector("[data-act=open]");
        var frame = body.querySelector("iframe");
        if (!url) {
            body.innerHTML = "";
            body.classList.add("is-empty");
            var lead = doc.createElement("p");
            lead.className = "hint";
            lead.textContent = tr("sp_empty", "Choisissez une page ou un actif à afficher ici.");
            var host = doc.createElement("div");
            host.className = "split-picker";
            body.appendChild(lead);
            body.appendChild(host);
            mountPicker(host, function (u) { setPane(i, u); });
            title.textContent = tr("sp_untitled", "Volet vide") + " ▾";
            open.removeAttribute("href");
            open.hidden = true;
            return;
        }
        open.hidden = false;
        open.href = url;
        body.classList.remove("is-empty");
        if (!frame || force || frame.dataset.url !== url) {
            body.innerHTML = "";
            frame = doc.createElement("iframe");
            frame.title = url;
            frame.dataset.url = url;
            frame.loading = "lazy";
            frame.addEventListener("load", function () { onFrameLoad(i, frame); });
            frame.src = url;
            body.appendChild(frame);
        }
        title.textContent = url + " ▾";
    }

    // La page d'un volet peut naviguer toute seule (un lien, un onglet) : on relit son adresse et son titre pour que la mémoire et le lien
    // de partage suivent. Même origine, donc lisible ; si ce n'est plus le cas (redirection externe), on garde l'ancienne adresse.
    function onFrameLoad(i, frame) {
        try {
            var loc = frame.contentWindow.location;
            var here = loc.pathname + loc.search + loc.hash;
            var shownTitle = titleOf(frame.contentDocument.title);
            var pane = paneEls[i];
            if (shownTitle) pane.querySelector(".split-pane-title").textContent = shownTitle + " ▾";
            if (/^\/split(\/|$)/.test(loc.pathname)) { state.panes[i] = ""; saveState(); renderPane(i, true); return; }
            if (here && here !== state.panes[i]) {
                state.panes[i] = sanitizeUrl(here) || state.panes[i];
                frame.dataset.url = state.panes[i];
                pane.querySelector("[data-act=open]").href = state.panes[i];
                saveState();
            }
            syncTheme(frame);
        } catch (e) { /* page d'une autre origine : rien à relire */ }
    }

    // Le thème choisi dans la fenêtre parente s'applique aux volets déjà ouverts (les nouveaux le lisent eux-mêmes dans localStorage).
    function syncTheme(frame) {
        try {
            var theme = doc.documentElement.getAttribute("data-theme");
            var d = frame.contentDocument.documentElement;
            if (theme) d.setAttribute("data-theme", theme); else d.removeAttribute("data-theme");
            frame.contentWindow.dispatchEvent(new CustomEvent("patrick:themechange", { detail: { theme: theme } }));
        } catch (e) { /* volet pas encore chargé */ }
    }
    root.addEventListener("patrick:themechange", function () {
        Array.prototype.forEach.call(stage.querySelectorAll("iframe"), syncTheme);
    });

    // ---- disposition
    var gutterEls = [];
    function percent(v) { return (v * 100) + "%"; }
    function placePane(el, r) {
        var h = GAP / 2;
        el.style.left = "calc(" + percent(r.x) + " + " + (r.x === 0 ? 0 : h) + "px)";
        el.style.top = "calc(" + percent(r.y) + " + " + (r.y === 0 ? 0 : h) + "px)";
        el.style.width = "calc(" + percent(r.w) + " - " + ((r.x === 0 ? 0 : h) + (r.x + r.w >= 0.9999 ? 0 : h)) + "px)";
        el.style.height = "calc(" + percent(r.h) + " - " + ((r.y === 0 ? 0 : h) + (r.y + r.h >= 0.9999 ? 0 : h)) + "px)";
    }

    function layout() {
        var spec = LAYOUTS[state.layout];
        var geo = geometry(state.layout, state.ratios);
        var stacked = root.matchMedia && root.matchMedia("(max-width: 899px)").matches;
        stage.classList.toggle("is-stacked", !!stacked);
        paneEls.forEach(function (el, i) {
            var visible = i < spec.n && (maximized < 0 || maximized === i);
            el.hidden = !visible;
            if (!visible) return;
            el.classList.toggle("is-max", maximized === i);
            el.querySelector("[data-act=max]").textContent = maximized === i ? "⤡" : "⤢";
            if (stacked) { el.style.cssText = ""; return; }
            placePane(el, maximized === i ? { x: 0, y: 0, w: 1, h: 1 } : geo.panes[i]);
        });
        gutterEls.forEach(function (g) { g.remove(); });
        gutterEls = [];
        if (!stacked && maximized < 0) {
            geo.gutters.forEach(function (g) {
                var el = doc.createElement("div");
                el.className = "split-gutter split-gutter-" + g.axis;
                el.setAttribute("role", "separator");
                el.setAttribute("aria-orientation", g.axis === "x" ? "vertical" : "horizontal");
                el.tabIndex = 0;
                if (g.axis === "x") { el.style.left = "calc(" + percent(g.pos) + " - " + (GAP / 2) + "px)"; el.style.width = GAP + "px"; el.style.top = percent(g.from); el.style.height = percent(g.to - g.from); }
                else { el.style.top = "calc(" + percent(g.pos) + " - " + (GAP / 2) + "px)"; el.style.height = GAP + "px"; el.style.left = percent(g.from); el.style.width = percent(g.to - g.from); }
                bindGutter(el, g);
                stage.appendChild(el);
                gutterEls.push(el);
            });
        }
        Array.prototype.forEach.call(app.querySelectorAll(".split-layout-btn"), function (b) {
            b.setAttribute("aria-pressed", b.dataset.layout === state.layout ? "true" : "false");
        });
    }

    function bindGutter(el, g) {
        function moveTo(value) {
            state.ratios[g.key] = clampRatio(state.layout, g.key, value, state.ratios);
            layout();
        }
        el.addEventListener("pointerdown", function (e) {
            e.preventDefault();
            stage.classList.add("is-dragging");               // les volets ne captent plus la souris pendant le glissement
            var box = stage.getBoundingClientRect();
            var move = function (ev) {
                var v = g.axis === "x" ? (ev.clientX - box.left) / box.width : (ev.clientY - box.top) / box.height;
                moveTo(v);
            };
            var up = function () {
                root.removeEventListener("pointermove", move);
                root.removeEventListener("pointerup", up);
                stage.classList.remove("is-dragging");
                saveState();
            };
            root.addEventListener("pointermove", move);
            root.addEventListener("pointerup", up);
        });
        el.addEventListener("keydown", function (e) {
            var step = e.shiftKey ? 0.05 : 0.02, dir = (e.key === "ArrowRight" || e.key === "ArrowDown") ? 1 : (e.key === "ArrowLeft" || e.key === "ArrowUp") ? -1 : 0;
            if (!dir) return;
            e.preventDefault();
            moveTo(state.ratios[g.key] + dir * step);
            saveState();
        });
        el.addEventListener("dblclick", function () { state.ratios[g.key] = defaultsFor(state.layout)[g.key]; layout(); saveState(); });
    }

    function setLayout(next) {
        if (!LAYOUTS[next]) return;
        state = normalize({ layout: next, ratios: defaultsFor(next), panes: state.panes });
        maximized = -1;
        closePicker();
        layout();
        saveState();
    }

    function boot() {
        state = loadState();
        for (var i = 0; i < MAX_PANES; i++) { var el = buildPane(i); paneEls.push(el); stage.appendChild(el); }
        paneEls.forEach(function (_el, i) { renderPane(i, false); });
        layout();
        saveState();
        Array.prototype.forEach.call(app.querySelectorAll(".split-layout-btn"), function (b) {
            b.addEventListener("click", function () { setLayout(b.dataset.layout); });
        });
        var reset = doc.getElementById("split-reset");
        if (reset) reset.addEventListener("click", function () {
            state = normalize({ layout: "c2", ratios: {}, panes: ["/predictions?view=horizon", ""] });
            maximized = -1;
            paneEls.forEach(function (_el, i) { renderPane(i, true); });
            layout();
            saveState();
        });
        var copy = doc.getElementById("split-copy");
        if (copy) copy.addEventListener("click", function () {
            var link = root.location.origin + root.location.pathname + "#" + encodeState(state);
            var done = function () { copy.textContent = tr("sp_copied", "Lien copié"); root.setTimeout(function () { copy.textContent = copy.dataset.label; }, 1800); };
            copy.dataset.label = copy.dataset.label || copy.textContent;
            if (root.navigator.clipboard) root.navigator.clipboard.writeText(link).then(done, function () { root.prompt("", link); });
            else root.prompt("", link);
        });
        doc.addEventListener("keydown", function (e) {
            if (e.key === "Escape") { if (picker) closePicker(); else if (maximized >= 0) { maximized = -1; layout(); } }
        });
        doc.addEventListener("click", function (e) { if (picker && !picker.contains(e.target) && !e.target.classList.contains("split-pane-title")) closePicker(); });
        root.addEventListener("hashchange", function () {
            var fromHash = decodeState(root.location.hash);
            if (fromHash && encodeState(fromHash) !== encodeState(state)) {
                state = fromHash;
                paneEls.forEach(function (_el, i) { renderPane(i, false); });
                layout();
            }
        });
        if (root.matchMedia) root.matchMedia("(max-width: 899px)").addEventListener("change", layout);
        root.addEventListener("resize", function () { if (picker) closePicker(); });
    }
    boot();
})(typeof window !== "undefined" ? window : globalThis);
