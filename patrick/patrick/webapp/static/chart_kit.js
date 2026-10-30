/* Moteur de graphiques commun : courbes (axe du temps ou axe d'indices) et barres, sur toile HiDPI, sans dépendance. Exposé :
   `window.PatrickPlot.create(hôte, options)` — utilisé par l'aperçu de cible, les statistiques par actif, la dérive des phases, le
   fonds, le patrimoine et, via `PatrickCharts.lineChart/barChart`, les pages Exploration et Reinforcement learning.

   Interactions (toutes équivalentes au clavier et au tactile) :
     - glisser sur la zone de tracé : sélection rectangulaire puis zoom sur cette période ;
     - Maj + glisser, glissement d'un doigt (tactile) ou ← → : déplacer la fenêtre zoomée ;
     - Ctrl/⌘ + molette (ou pincement du pavé tactile), pincement à deux doigts, + / − : zoom centré sur le curseur ;
     - double-clic, Échap, Origine ou le bouton « Tout » : retour à la vue initiale.
   L'axe vertical est recalculé sur les points VISIBLES à chaque zoom ; la molette seule défile toujours la page.
   Les couleurs viennent des jetons CSS au moment du tracé (thème clair/sombre : redessin sur `patrick:themechange`). */
(function (root) {
    "use strict";

    var DAY = 86400000;
    // Rendu « finance » (défaut des courbes) : axe des valeurs à droite, grille horizontale en pointillés, aire dégradée sous une courbe seule,
    // étiquette du dernier point, réticule à pastilles. `trend` colore la courbe en vert / rouge selon la variation de la fenêtre ;
    // `quote` ajoute l'en-tête de cotation (valeur, variation) ; `ohlc` + `candles` : bougies ; `volume` : barres sous la courbe.
    var DEFAULTS = { type: "line", height: 240, zoomable: true, markers: "auto", legend: "auto", compact: false, connectGaps: false, ranges: false,
                     finance: true, area: "auto", trend: false, baseline: false, quote: false, candles: false };
    var syncGroups = {};      // `options.sync` : nom de groupe -> graphiques qui partagent leur réticule
    var live = [];            // graphiques montés (redessinés au changement de thème, élagués une fois détachés du document)

    // ------------------------------------------------------------------ outils purs (testés sous Node)
    function lowerBound(a, v) {            // premier indice dont a[i] >= v (a croissant)
        var lo = 0, hi = a.length;
        while (lo < hi) { var m = (lo + hi) >> 1; if (a[m] < v) lo = m + 1; else hi = m; }
        return lo;
    }
    function nearestIndex(a, v) {
        var i = lowerBound(a, v);
        if (i <= 0) return 0;
        if (i >= a.length) return a.length - 1;
        return (v - a[i - 1] <= a[i] - v) ? i - 1 : i;
    }

    function niceTicks(lo, hi, n) {
        if (!(hi > lo)) { lo -= 1; hi += 1; }
        var span = hi - lo, base = Math.pow(10, Math.floor(Math.log10(span / n))), step = base;
        // plus petit pas « rond » (1, 2, 5 × 10^k) dont le NOMBRE DE GRADUATIONS visibles tient dans n (et non span/pas, qui en perdait une ou deux)
        [1, 2, 5, 10].some(function (m) {
            step = base * m;
            return Math.floor(hi / step + 1e-9) - Math.ceil(lo / step - 1e-9) + 1 <= n;
        });
        var out = [], start = Math.ceil(lo / step - 1e-9) * step;
        for (var v = start; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : +v.toPrecision(12));
        out.step = step;
        return out;
    }
    function visibleMarkers(list, x0, x1) {   // repères verticaux dont x tombe dans la fenêtre visible
        return (list || []).filter(function (l) { return l && l.x >= x0 && l.x <= x1; });
    }
    function peersOf(groups, name, self) {    // les autres graphiques encore montés du groupe `name`
        return ((name && groups[name]) || []).filter(function (c) { return c !== self && !c.isStale(); });
    }

    function decimalsFor(step) { return step >= 1 ? 0 : Math.min(8, Math.max(0, -Math.floor(Math.log10(step) + 1e-9))); }

    function parseDate(s) {                // « AAAA-MM-JJ », « AAAA-MM », « AAAA-MM-JJTHH:MM:SS » → ms UTC (NaN si illisible)
        if (typeof s === "number") return s;
        if (typeof s !== "string") return NaN;
        var m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(s);
        if (m) return Date.UTC(+m[1], +m[2] - 1, m[3] ? +m[3] : 1);
        return Date.parse(s);
    }

    var TIME_STEPS = [["d", 1], ["d", 2], ["d", 5], ["d", 7], ["d", 14], ["m", 1], ["m", 2], ["m", 3], ["m", 6], ["y", 1], ["y", 2], ["y", 5], ["y", 10], ["y", 20], ["y", 50]];
    function genTimeTicks(t0, t1, unit, n) {
        var out = [], d;
        if (unit === "d") {
            var span = n * DAY, off = n >= 7 ? 4 * DAY : 0;          // semaines alignées sur le lundi (1970-01-05)
            for (var t = Math.ceil((t0 - off) / span) * span + off; t <= t1; t += span) out.push(t);
        } else if (unit === "m") {
            d = new Date(t0);
            var mi = d.getUTCFullYear() * 12 + d.getUTCMonth();
            mi = Math.ceil(mi / n) * n;
            for (;; mi += n) { var tm = Date.UTC(Math.floor(mi / 12), mi % 12, 1); if (tm > t1) break; if (tm >= t0) out.push(tm); }
        } else {
            var y = Math.ceil(new Date(t0).getUTCFullYear() / n) * n;
            for (;; y += n) { var ty = Date.UTC(y, 0, 1); if (ty > t1) break; if (ty >= t0) out.push(ty); }
        }
        return out;
    }
    function timeTicks(t0, t1, maxTicks) {
        var best = null;
        for (var i = 0; i < TIME_STEPS.length; i++) {
            var ticks = genTimeTicks(t0, t1, TIME_STEPS[i][0], TIME_STEPS[i][1]);
            best = { ticks: ticks, unit: TIME_STEPS[i][0], n: TIME_STEPS[i][1] };
            if (ticks.length <= maxTicks) return best;
        }
        return best;
    }

    // Réduit une série à ≤ 4 points par colonne de pixels (premier, min, max, dernier) : le tracé reste fidèle, le coût devient borné.
    function decimate(xs, ys, i0, i1, X, plotW) {
        var n = i1 - i0 + 1;
        if (n <= plotW * 2) { var all = []; for (var i = i0; i <= i1; i++) all.push(i); return all; }
        var out = [], col = null, first = 0, last = 0, mn = 0, mx = 0;
        function flush() {
            var idx = [first, mn, mx, last].sort(function (a, b) { return a - b; });
            for (var k = 0; k < idx.length; k++) if (k === 0 || idx[k] !== idx[k - 1]) out.push(idx[k]);
        }
        for (var j = i0; j <= i1; j++) {
            var y = ys[j];
            if (y === null || y === undefined || !isFinite(y)) { if (col !== null) { flush(); col = null; } out.push(j); continue; }
            var c = Math.floor(X(xs[j]));
            if (c !== col) { if (col !== null) flush(); col = c; first = last = mn = mx = j; }
            else { last = j; if (y < ys[mn]) mn = j; if (y > ys[mx]) mx = j; }
        }
        if (col !== null) flush();
        return out;
    }

    // Bornes verticales d'une fenêtre [x0,x1] : points visibles seulement (les repères n'entrent que s'ils sont proches des données).
    function yExtent(series, x0, x1, extras, floors) {
        var lo = Infinity, hi = -Infinity;
        series.forEach(function (s) {
            if (s.hidden) return;
            var i0 = lowerBound(s.xs, x0), i1 = lowerBound(s.xs, x1 + 1e-9);
            for (var i = i0; i < i1; i++) { var v = s.ys[i]; if (v !== null && v !== undefined && isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }
        });
        if (!isFinite(lo)) return null;
        var span = (hi - lo) || Math.abs(hi) * 0.1 || 1;
        (extras || []).forEach(function (v) { if (v >= lo - span * 0.5 && v <= hi + span * 0.5) { if (v < lo) lo = v; if (v > hi) hi = v; } });
        (floors || []).forEach(function (v) { if (v < lo) lo = v; if (v > hi) hi = v; });
        return [lo, hi];
    }

    // Couleur (jeton résolu : « #rrggbb », « #rgb » ou « rgb(...) ») avec une opacité ; toute autre forme est rendue telle quelle.
    function withAlpha(c, a) {
        var m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c || "");
        if (m) {
            var h = m[1].length === 3 ? m[1].replace(/./g, "$&$&") : m[1], n = parseInt(h, 16);
            return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
        }
        var r = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/.exec(c || "");
        return r ? "rgba(" + r[1] + "," + r[2] + "," + r[3] + "," + a + ")" : c;
    }

    // Variation sur la fenêtre [x0, x1] : premier et dernier points valides visibles → { i0, i1, first, last, abs, pct } (null si aucun).
    function windowChange(xs, ys, x0, x1) {
        var lo = lowerBound(xs, x0), hi = lowerBound(xs, x1 + 1e-9) - 1, a = -1, b = -1, i;
        function ok(v) { return v !== null && v !== undefined && isFinite(v); }
        for (i = lo; i <= hi; i++) if (ok(ys[i])) { a = i; break; }
        for (i = hi; i >= lo; i--) if (ok(ys[i])) { b = i; break; }
        if (a < 0 || b < 0) return null;
        var first = ys[a], last = ys[b], abs = last - first;
        return { i0: a, i1: b, first: first, last: last, abs: abs, pct: first !== 0 ? abs / Math.abs(first) * 100 : null };
    }

    // Bornes verticales d'une fenêtre pour des bougies : plus bas des « bas », plus haut des « hauts ».
    function candleExtent(xs, highs, lows, x0, x1) {
        var lo = Infinity, hi = -Infinity, i0 = lowerBound(xs, x0), i1 = lowerBound(xs, x1 + 1e-9);
        for (var i = i0; i < i1; i++) {
            var h = highs[i], l = lows[i];
            if (h !== null && h !== undefined && isFinite(h) && h > hi) hi = h;
            if (l !== null && l !== undefined && isFinite(l) && l < lo) lo = l;
        }
        return isFinite(lo) && isFinite(hi) ? [lo, hi] : null;
    }

    // Début d'année civile (ms UTC) de la dernière date : borne de la période « YTD ».
    function yearStart(t) { return Date.UTC(new Date(t).getUTCFullYear(), 0, 1); }

    // ------------------------------------------------------------------ utilitaires d'environnement
    function lang() { return (root.document && root.document.documentElement.lang) || "fr"; }
    function tr(key, fallback) { var I = root.I18N || {}; return I[key] || fallback || key; }
    function fmtStr(text, params) { return text.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; }); }
    var cssCache = null;
    function token(name) {
        if (!cssCache) cssCache = getComputedStyle(root.document.documentElement);
        return cssCache.getPropertyValue(name).trim();
    }
    function color(c) {
        if (!c) return token("--brand");
        var m = /^var\((--[\w-]+)\)$/.exec(c);
        if (m) return token(m[1]);
        return c.indexOf("--") === 0 ? token(c) : c;
    }
    function numFmt(v, d) {
        if (v === null || v === undefined || !isFinite(v)) return "—";
        return v.toLocaleString(lang(), { minimumFractionDigits: d, maximumFractionDigits: d });
    }
    function valFmt(v) { return numFmt(v, Math.abs(v) >= 1 ? 2 : 4); }
    function dateFmt(opts) { return new Intl.DateTimeFormat(lang(), Object.assign({ timeZone: "UTC" }, opts)); }
    function el(tag, cls, attrs) {
        var e = root.document.createElement(tag);
        if (cls) e.className = cls;
        Object.keys(attrs || {}).forEach(function (k) { if (k === "text") e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]); });
        return e;
    }
    var ICONS = {
        in: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3M11 8v6M8 11h6"/>',
        out: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3M8 11h6"/>',
        reset: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
        left: '<path d="m15 18-6-6 6-6"/>',
        right: '<path d="m9 18 6-6-6-6"/>',
    };
    function iconBtn(kind, label) {
        var b = el("button", "pp-btn", { type: "button", "aria-label": label, title: label });
        b.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + ICONS[kind] + "</svg>";
        return b;
    }

    // ------------------------------------------------------------------ graphique
    function create(host, userOpts) {
        var o = Object.assign({}, DEFAULTS, userOpts || {});
        var isBar = o.type === "bar";
        var series = normalise(o, isBar);
        var timeAxis = !isBar && o.xKind === "time";
        var ext = extent(series, isBar);                  // [xmin, xmax] de la vue initiale
        var view = null;                                  // null = vue initiale, sinon [x0, x1]
        var minSpan = 1;
        var geo = null;                                   // géométrie du dernier tracé (pour la surcouche)
        var hover = null, drag = null, raf = 0, destroyed = false, pointers = {}, pinch = null;
        var guideX = null;                                // réticule venu d'un autre graphique du même groupe `sync` (valeur de x, pas un pixel)
        var fin = o.finance !== false && !isBar;                                   // rendu « finance » (cf. DEFAULTS)
        var hasOhlc = !!(o.ohlc && o.ohlc.open && o.ohlc.high && o.ohlc.low && series[0] && timeAxis);
        var hasVol = !!(o.volume && o.volume.length && series[0] && timeAxis);
        var mode = hasOhlc && o.candles ? "candle" : "line";

        host.classList.add("pp");
        host.textContent = "";
        var bar = el("div", "pp-ranges");
        var stage = el("div", "pp-stage");
        var base = el("canvas", "pp-base");
        var over = el("canvas", "pp-over", { tabindex: "0", role: "img" });
        var tip = el("div", "chart-tooltip pp-tip hidden", { role: "presentation" });
        var tools = el("div", "pp-tools");
        var bOut = iconBtn("out", tr("chart_zoom_out", "Zoom out")), bIn = iconBtn("in", tr("chart_zoom_in", "Zoom in")), bReset = iconBtn("reset", tr("chart_reset", "Reset zoom"));
        if (o.zoomable) {
            tools.appendChild(el("span", "pp-hint", { text: tr("chart_hint", "Drag to zoom · double-click to reset") }));
            tools.appendChild(bOut); tools.appendChild(bIn); tools.appendChild(bReset);
        }
        stage.appendChild(base); stage.appendChild(over); stage.appendChild(tip); stage.appendChild(tools);
        var legend = el("div", "pp-legend");
        var quoteEl = null, qVal = null, qChg = null, qDate = null;
        if (o.quote && fin && timeAxis) {
            quoteEl = el("div", "pp-quote");
            var qId = el("div", "pp-quote-id");
            if (o.title && o.quoteTitle !== false) qId.appendChild(el("strong", "pp-quote-title", { text: o.title }));
            if (o.subtitle) qId.appendChild(el("span", "pp-quote-sub", { text: o.subtitle }));
            var qNum = el("div", "pp-quote-num");
            qVal = el("span", "pp-quote-val"); qChg = el("span", "pp-quote-chg"); qDate = el("span", "pp-quote-date");
            qNum.appendChild(qVal); qNum.appendChild(qChg); qNum.appendChild(qDate);
            quoteEl.appendChild(qId); quoteEl.appendChild(qNum);
            host.appendChild(quoteEl);
        }
        if ((o.ranges || hasOhlc) && timeAxis) host.appendChild(bar);
        host.appendChild(stage);
        host.appendChild(legend);
        if (o.compact) host.classList.add("pp-compact");
        if (fin) host.classList.add("pp-fin");                  // axe à droite : les outils de zoom passent à gauche
        stage.style.height = o.height + "px";
        stage.setAttribute("data-zoomed", "false");

        // ----- état dérivé
        function span() { return ext[1] - ext[0]; }
        function computeMinSpan() {
            var best = Infinity;
            series.forEach(function (s) {
                var n = s.xs.length;
                if (n < 2) return;
                var d = (s.xs[n - 1] - s.xs[0]) / (n - 1);
                if (d > 0 && d < best) best = d;
            });
            minSpan = isBar ? 3 : (isFinite(best) ? best * 4 : span() / 10 || 1);
            if (minSpan > span()) minSpan = span();
        }
        computeMinSpan();

        function cur() { return view || ext; }
        function setView(x0, x1, keepWidth) {
            var w = x1 - x0;
            if (w < minSpan) { var c = (x0 + x1) / 2; x0 = c - minSpan / 2; x1 = c + minSpan / 2; w = minSpan; }
            if (w >= span() * 0.999) { view = null; }
            else {
                if (x0 < ext[0]) { x0 = ext[0]; if (keepWidth) x1 = x0 + w; }
                if (x1 > ext[1]) { x1 = ext[1]; if (keepWidth) x0 = x1 - w; }
                x0 = Math.max(ext[0], x0); x1 = Math.min(ext[1], x1);
                view = [x0, x1];
            }
            hover = null;
            schedule();
        }
        function zoomBy(factor, centre) {
            var v = cur(), c = centre === undefined ? (v[0] + v[1]) / 2 : centre;
            var f = (c - v[0]) / ((v[1] - v[0]) || 1);
            var w = (v[1] - v[0]) * factor;
            setView(c - w * f, c + w * (1 - f), true);
        }
        function panBy(frac) { var v = cur(), d = (v[1] - v[0]) * frac; if (view) setView(v[0] + d, v[1] + d, true); }
        function resetView() { view = null; hover = null; schedule(); }

        // ----- tracé
        var W = 0, H = 0, ratio = 1;
        function sizeCanvases() {
            var w = Math.round(stage.clientWidth), h = Math.round(stage.clientHeight);
            if (!w) return false;
            ratio = root.devicePixelRatio || 1;
            if (w === W && h === H && base.width === Math.round(w * ratio)) return true;
            W = w; H = h;
            [base, over].forEach(function (c) { c.width = Math.round(W * ratio); c.height = Math.round(H * ratio); c.style.width = W + "px"; c.style.height = H + "px"; });
            return true;
        }
        function schedule() { if (!raf && !destroyed) raf = root.requestAnimationFrame(function () { raf = 0; draw(); }); }

        var shown = false;                                // vrai dès que le graphique a été tracé dans le document
        function inkFor(bg) {                             // encre lisible (claire ou sombre) sur une pastille de couleur `bg`
            var m = /^#([0-9a-f]{6})$/i.exec(bg || ""), n = m ? parseInt(m[1], 16) : 0x5b8def;
            var lum = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
            return lum > 0.6 ? "#0a0c10" : "#ffffff";
        }
        function chip(ctx, text, x, y, bg, fg, align) {   // pastille arrondie (valeur de l'axe, dernier point, date du réticule)
            ctx.save();
            ctx.font = '600 11px ' + (token("--mono") || "monospace");
            var w = Math.ceil(ctx.measureText(text).width) + 12, h = 18, left = align === "center" ? x - w / 2 : (align === "right" ? x - w : x);
            left = Math.max(1, Math.min(left, W - w - 1));
            var top = Math.max(1, Math.min(y - h / 2, H - h - 1)), r = 4;
            ctx.fillStyle = bg; ctx.beginPath();
            ctx.moveTo(left + r, top); ctx.lineTo(left + w - r, top); ctx.quadraticCurveTo(left + w, top, left + w, top + r);
            ctx.lineTo(left + w, top + h - r); ctx.quadraticCurveTo(left + w, top + h, left + w - r, top + h);
            ctx.lineTo(left + r, top + h); ctx.quadraticCurveTo(left, top + h, left, top + h - r);
            ctx.lineTo(left, top + r); ctx.quadraticCurveTo(left, top, left + r, top); ctx.closePath(); ctx.fill();
            ctx.fillStyle = fg; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(text, left + 6, top + h / 2 + 0.5);
            ctx.restore();
        }
        function draw() {
            if (destroyed || !sizeCanvases()) return;
            if (host.isConnected) shown = true;
            var ctx = base.getContext("2d");
            ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            ctx.clearRect(0, 0, W, H);
            var v = cur(), vx0 = v[0], vx1 = v[1];
            var visible = series.filter(function (s) { return !s.hidden; });
            var candle = mode === "candle" && hasOhlc;
            // Repères (lignes, bande, seuils) : toujours inclus à la vue initiale ; une fois zoomé, seuls ceux proches des données comptent,
            // sinon un repère lointain empêcherait le recalcul de l'échelle. Bornes imposées (yMin/yMax) : vue initiale seulement.
            var marks = (o.hlines || []).map(function (l) { return l.y; });
            if (o.band) marks = marks.concat(isBar ? [o.band, -o.band] : o.band);
            var always = isBar ? [0] : [];
            if (!view) {
                always = always.concat(marks);
                if (o.yMin !== undefined) always.push(o.yMin);
                if (o.yMax !== undefined) always.push(o.yMax);
            }
            var ye = candle ? candleExtent(series[0].xs, o.ohlc.high, o.ohlc.low, vx0, vx1) : yExtent(series, vx0, vx1, view ? marks : [], always);
            var muted = token("--text-3"), grid = token("--chart-grid"), line = token("--line-strong"), font = '11px ' + (token("--mono") || "monospace");
            if (!ye || !visible.length) {
                ctx.fillStyle = muted; ctx.font = font; ctx.textAlign = "left";
                ctx.fillText(o.empty || tr("chart_empty", "No data to plot."), 14, H / 2);
                geo = null; setAria(null); overClear(); updateChrome(); tip.classList.add("hidden"); return;
            }
            var lo = ye[0], hi = ye[1], pad = (hi - lo) * 0.06 || 0.5;
            lo -= (isBar && lo >= 0) ? 0 : pad; hi += pad;
            var padT = 10, padB = 24, padR = 14, padL = 12;
            var volOn = fin && hasVol, fullH = H - padT - padB, volH = volOn ? Math.max(30, Math.round(fullH * 0.2)) : 0;
            var ph = fullH - (volOn ? volH + 8 : 0);                              // hauteur de la zone de prix (le volume est dessous)
            var yTicks = niceTicks(lo, hi, Math.max(2, Math.min(7, Math.floor(ph / 44))));
            var dec = decimalsFor(yTicks.step), yFmt = o.yFmt ? function (x) { return o.yFmt(x, dec); } : function (x) { return numFmt(x, dec); };
            ctx.font = font;
            var labelW = 12;
            yTicks.forEach(function (t) { labelW = Math.max(labelW, ctx.measureText(yFmt(t)).width + 14); });
            if (fin) { padL = 8; padR = Math.min(Math.max(labelW + 6, 54), W * 0.4); } else padL = Math.min(labelW, W * 0.4);
            var pw = W - padL - padR;
            function X(x) { return padL + (x - vx0) / (vx1 - vx0) * pw; }
            function Y(y) { return padT + (1 - (y - lo) / (hi - lo)) * ph; }
            // variation de la fenêtre (en-tête, couleur de tendance, ligne de départ) sur la première série visible
            var ref0 = visible[0], ch = (fin && ref0) ? windowChange(ref0.xs, ref0.ys, vx0, vx1) : null;
            var trendCol = (fin && o.trend && ch) ? token(ch.abs >= 0 ? "--pos" : "--neg") : null;
            // grille et axe Y (à droite en rendu finance : grille horizontale en pointillés, rien de vertical)
            ctx.lineWidth = 1; ctx.textBaseline = "middle";
            yTicks.forEach(function (t) {
                var yy = Math.round(Y(t)) + 0.5;
                ctx.strokeStyle = grid; if (fin) ctx.setLineDash([2, 4]);
                ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke(); ctx.setLineDash([]);
                ctx.fillStyle = muted;
                if (fin) { ctx.textAlign = "left"; ctx.fillText(yFmt(t), W - padR + 8, yy); }
                else { ctx.textAlign = "right"; ctx.fillText(yFmt(t), padL - 8, yy); }
            });
            // axe X
            ctx.textBaseline = "alphabetic"; ctx.textAlign = "center";
            var xTicks = axisX(vx0, vx1, pw, ctx);
            if (fin) { ctx.strokeStyle = line; ctx.beginPath(); ctx.moveTo(padL, padT + fullH + 0.5); ctx.lineTo(W - padR, padT + fullH + 0.5); ctx.stroke(); }
            xTicks.forEach(function (tk) {
                var xx = Math.round(X(tk.x)) + 0.5;
                ctx.strokeStyle = grid;
                ctx.beginPath(); ctx.moveTo(xx, fin ? padT + fullH : padT); ctx.lineTo(xx, fin ? padT + fullH + 4 : padT + ph); ctx.stroke();
                ctx.fillStyle = muted; ctx.fillText(tk.label, Math.min(Math.max(xx, padL + 14), W - padR - 14), H - 7);
            });
            ctx.save(); ctx.beginPath(); ctx.rect(padL, padT - 1, pw, fullH + 2); ctx.clip();
            if (o.band) { ctx.fillStyle = token("--neutral-soft"); ctx.fillRect(padL, Y(o.band[1]), pw, Math.max(0, Y(o.band[0]) - Y(o.band[1]))); }
            if (isBar && o.band) {
                [o.band, -o.band].forEach(function (b) { ctx.strokeStyle = muted; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(padL, Y(b)); ctx.lineTo(W - padR, Y(b)); ctx.stroke(); ctx.setLineDash([]); });
            }
            (o.hlines || []).forEach(function (l) {
                ctx.strokeStyle = color(l.color || "--text-3"); ctx.lineWidth = l.width || 1;
                ctx.setLineDash(dashOf(l.dash, [4, 4])); ctx.beginPath(); ctx.moveTo(padL, Y(l.y)); ctx.lineTo(W - padR, Y(l.y)); ctx.stroke(); ctx.setLineDash([]);
                if (l.label) { ctx.fillStyle = muted; ctx.font = font; ctx.textAlign = "right"; ctx.textBaseline = "bottom"; ctx.fillText(l.label, W - padR - 6, Y(l.y) - 3); ctx.textBaseline = "alphabetic"; }
            });
            visibleMarkers(o.vlines, vx0, vx1).forEach(function (l) {             // événements datés (frontière de pli, début du holdout, promotion...) : x dans l'unité de l'axe
                var px = Math.round(X(l.x)) + 0.5;
                ctx.strokeStyle = color(l.color || "--text-3"); ctx.lineWidth = l.width || 1;
                ctx.setLineDash(dashOf(l.dash, [2, 3])); ctx.beginPath(); ctx.moveTo(px, padT); ctx.lineTo(px, padT + ph); ctx.stroke(); ctx.setLineDash([]);
                if (l.label) { ctx.fillStyle = muted; ctx.font = font; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText(l.label, px + 4, padT + 2); ctx.textBaseline = "alphabetic"; }
            });
            if (fin && ch && (o.baseline || o.trend)) {                           // niveau de départ de la période (comme la « clôture précédente »)
                ctx.strokeStyle = withAlpha(muted, 0.8); ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
                ctx.beginPath(); ctx.moveTo(padL, Math.round(Y(ch.first)) + 0.5); ctx.lineTo(W - padR, Math.round(Y(ch.first)) + 0.5); ctx.stroke(); ctx.setLineDash([]);
            }
            if (volOn) drawVolume(ctx, X, vx0, vx1, padT + fullH, volH);
            if (isBar) drawBars(ctx, X, Y, vx0, vx1, pw);
            else if (candle) drawCandles(ctx, X, Y, vx0, vx1);
            else {
                var wantArea = fin && o.area !== false && (o.area === true || visible.length === 1);
                visible.forEach(function (s, k) { drawLine(ctx, s, X, Y, vx0, vx1, pw, k === 0 ? trendCol : null, wantArea && k === 0, padT + ph); });
            }
            ctx.restore();
            if (isBar) { ctx.strokeStyle = line; ctx.beginPath(); ctx.moveTo(padL, Math.round(Y(0)) + 0.5); ctx.lineTo(W - padR, Math.round(Y(0)) + 0.5); ctx.stroke(); }
            // étiquette du dernier point visible de chaque courbe (≤ 3), sur l'axe de droite, avec un fil pointillé jusqu'à elle
            var lastTags = [];
            if (fin && visible.length <= 3) {
                visible.forEach(function (s, k) {
                    var wc = windowChange(s.xs, s.ys, vx0, vx1);
                    if (!wc) return;
                    var col = (k === 0 && trendCol) ? trendCol : color(s.color);
                    lastTags.push({ y: Y(wc.last), v: wc.last, x: X(s.xs[wc.i1]), col: col });
                });
                lastTags.forEach(function (tg) {
                    ctx.save(); ctx.beginPath(); ctx.rect(padL, padT - 1, pw + 1, fullH + 2); ctx.clip();
                    ctx.strokeStyle = withAlpha(tg.col, 0.55); ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
                    ctx.beginPath(); ctx.moveTo(Math.max(padL, tg.x), Math.round(tg.y) + 0.5); ctx.lineTo(W - padR, Math.round(tg.y) + 0.5); ctx.stroke();
                    ctx.restore();
                });
                lastTags.sort(function (a, b) { return a.y - b.y; });
                for (var q = 1; q < lastTags.length; q++) if (lastTags[q].ty === undefined && lastTags[q].y - (lastTags[q - 1].ty !== undefined ? lastTags[q - 1].ty : lastTags[q - 1].y) < 19) lastTags[q].ty = (lastTags[q - 1].ty !== undefined ? lastTags[q - 1].ty : lastTags[q - 1].y) + 19;
                lastTags.forEach(function (tg) { chip(ctx, (o.tipFmt || valFmt)(tg.v), W - padR + 3, tg.ty !== undefined ? tg.ty : tg.y, tg.col, inkFor(tg.col), "left"); });
            }
            geo = { padL: padL, padR: padR, padT: padT, pw: pw, ph: ph, hit: fullH, X: X, Y: Y, vx0: vx0, vx1: vx1, lo: lo, hi: hi, yFmt: yFmt, ch: ch, trendCol: trendCol, candle: candle, vol: volOn };
            setAria(ye);
            updateChrome(); drawOver();
        }

        function dashOf(d, fallback) {
            if (d === undefined || d === null) return fallback;
            if (Array.isArray(d)) return d;
            var a = String(d).split(/\s+/).map(Number).filter(function (x) { return isFinite(x); });
            return (a.length === 1 && a[0] === 0) ? [] : (a.length ? a : fallback);
        }

        function axisX(vx0, vx1, pw, ctx) {
            var out = [];
            if (timeAxis) {
                var tk = timeTicks(vx0, vx1, Math.max(2, Math.floor(pw / 88)));
                var fmt = tk.unit === "y" ? dateFmt({ year: "numeric" }) : tk.unit === "m" ? dateFmt({ month: "short", year: "numeric" }) : dateFmt({ day: "numeric", month: "short" });
                var crossYear = tk.unit === "d" && new Date(vx0).getUTCFullYear() !== new Date(vx1).getUTCFullYear();
                var fmtY = dateFmt({ day: "numeric", month: "short", year: "2-digit" });
                tk.ticks.forEach(function (t) { out.push({ x: t, label: (crossYear ? fmtY : fmt).format(t) }); });
                return out;
            }
            var n = series[0].xs.length, labelOf = o.xLabel || function (i) { return String(i); };
            var lo = Math.max(0, Math.ceil(vx0 - 1e-9)), hi = Math.min(n - 1, Math.floor(vx1 + 1e-9));
            if (hi < lo) return out;
            var widest = 0, probe = Math.max(1, Math.ceil((hi - lo + 1) / 12));
            for (var q = lo; q <= hi; q += probe) widest = Math.max(widest, ctx.measureText(String(labelOf(q))).width);
            var maxT = Math.max(2, Math.floor(pw / (widest + 16))), stride = Math.max(1, Math.ceil((hi - lo + 1) / maxT));
            if (!isBar) stride = Math.max(1, Math.round(niceTicks(lo, hi, maxT).step));          // pas « rond » : 5, 10, 20…
            var first = isBar ? lo : Math.ceil(lo / stride) * stride;
            for (var b = first; b <= hi; b += stride) out.push({ x: b, label: String(labelOf(b)) });
            return out;
        }

        function drawLine(ctx, s, X, Y, vx0, vx1, pw, override, area, baseY) {
            var n = s.xs.length;
            if (!n) return;
            var i0 = Math.max(0, lowerBound(s.xs, vx0) - 1), i1 = Math.min(n - 1, lowerBound(s.xs, vx1));
            var idx = decimate(s.xs, s.ys, i0, i1, X, pw), col = override || color(s.color);
            var segs = [], seg = null;
            for (var k = 0; k < idx.length; k++) {
                var j = idx[k], yv = s.ys[j];
                if (yv === null || yv === undefined || !isFinite(yv)) { if (!o.connectGaps) seg = null; continue; }   // trou honnête : jamais de valeur inventée
                if (!seg) { seg = []; segs.push(seg); }
                seg.push([X(s.xs[j]), Y(yv)]);
            }
            if (area) {                                                             // aire sous la courbe : dégradé de la couleur vers le transparent
                var gr = ctx.createLinearGradient(0, 0, 0, baseY);
                gr.addColorStop(0, withAlpha(col, 0.30)); gr.addColorStop(1, withAlpha(col, 0));
                ctx.fillStyle = gr;
                segs.forEach(function (sg) {
                    if (sg.length < 2) return;
                    ctx.beginPath(); ctx.moveTo(sg[0][0], baseY);
                    sg.forEach(function (pt) { ctx.lineTo(pt[0], pt[1]); });
                    ctx.lineTo(sg[sg.length - 1][0], baseY); ctx.closePath(); ctx.fill();
                });
            }
            ctx.strokeStyle = col; ctx.lineWidth = s.width; ctx.lineJoin = "round"; ctx.lineCap = "round";
            ctx.setLineDash(dashOf(s.dash, []));
            ctx.beginPath();
            segs.forEach(function (sg) { sg.forEach(function (pt, m) { if (m === 0) ctx.moveTo(pt[0], pt[1]); else ctx.lineTo(pt[0], pt[1]); }); });
            ctx.stroke(); ctx.setLineDash([]);
            if (o.markers === true || (o.markers === "auto" && i1 - i0 < 60 && pw / Math.max(1, i1 - i0) > 14)) {   // points marqués quand ils sont espacés
                ctx.fillStyle = col;
                for (var m = i0; m <= i1; m++) {
                    var mv = s.ys[m];
                    if (mv === null || mv === undefined || !isFinite(mv)) continue;
                    ctx.beginPath(); ctx.arc(X(s.xs[m]), Y(mv), 2.4, 0, Math.PI * 2); ctx.fill();
                }
            }
        }

        // Largeur d'une barre / d'une bougie : 70 % de l'écart en pixels entre deux points voisins de la fenêtre.
        function slotWidth(X, xs, i0, i1) {
            var a = Math.max(0, i0), b = Math.min(xs.length - 1, Math.max(a + 1, i1));
            return b > a ? Math.abs(X(xs[b]) - X(xs[a])) / (b - a) : 6;
        }
        function drawCandles(ctx, X, Y, vx0, vx1) {
            var xs = series[0].xs, cl = series[0].ys, O = o.ohlc.open, Hh = o.ohlc.high, L = o.ohlc.low;
            var i0 = Math.max(0, lowerBound(xs, vx0) - 1), i1 = Math.min(xs.length - 1, lowerBound(xs, vx1));
            var slot = slotWidth(X, xs, i0, i1), bw = Math.max(1, Math.min(18, slot * 0.7));
            var up = token("--pos"), down = token("--neg");
            for (var i = i0; i <= i1; i++) {
                var op = O[i], hh = Hh[i], ll = L[i], c = cl[i];
                if ([op, hh, ll, c].some(function (z) { return z === null || z === undefined || !isFinite(z); })) continue;
                var col = c >= op ? up : down, x = X(xs[i]);
                ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1;
                var xm = Math.round(x) + 0.5;
                ctx.beginPath(); ctx.moveTo(xm, Y(hh)); ctx.lineTo(xm, Y(ll)); ctx.stroke();
                if (bw > 1.6) { var top = Math.min(Y(op), Y(c)); ctx.fillRect(Math.round(x - bw / 2), top, Math.max(1, Math.round(bw)), Math.max(1, Math.abs(Y(op) - Y(c)))); }
            }
        }
        function drawVolume(ctx, X, vx0, vx1, bottom, vh) {
            var xs = series[0].xs, vol = o.volume, cl = series[0].ys;
            var i0 = Math.max(0, lowerBound(xs, vx0) - 1), i1 = Math.min(xs.length - 1, lowerBound(xs, vx1)), vmax = 0, i;
            for (i = i0; i <= i1; i++) if (isFinite(vol[i]) && vol[i] > vmax) vmax = vol[i];
            if (!(vmax > 0)) return;
            var slot = slotWidth(X, xs, i0, i1), bw = Math.max(1, Math.min(18, slot * 0.7)), up = token("--pos"), down = token("--neg");
            for (i = i0; i <= i1; i++) {
                var vv = vol[i];
                if (vv === null || vv === undefined || !isFinite(vv) || vv <= 0) continue;
                var prev = i > 0 ? cl[i - 1] : cl[i], rising = hasOhlc ? cl[i] >= o.ohlc.open[i] : cl[i] >= prev;
                ctx.fillStyle = withAlpha(rising ? up : down, 0.42);
                var h = Math.max(1, vv / vmax * vh);
                ctx.fillRect(Math.round(X(xs[i]) - bw / 2), bottom - h, Math.max(1, Math.round(bw)), h);
            }
        }

        function drawBars(ctx, X, Y, vx0, vx1, pw) {
            var s = series[0], slot = pw / (vx1 - vx0), bw = Math.max(2, Math.min(40, slot * 0.7)), y0 = Y(0);
            var from = Math.max(0, Math.ceil(vx0 - 0.5)), to = Math.min(s.xs.length - 1, Math.floor(vx1 + 0.5));
            for (var i = from; i <= to; i++) {
                var vv = s.ys[i];
                if (vv === null || vv === undefined || !isFinite(vv)) continue;
                var strong = o.strong ? o.strong[i] : true;
                var col = o.color ? o.color(vv, i) : (vv >= 0 ? "--brand" : "--neg");
                ctx.globalAlpha = strong ? 0.95 : 0.4; ctx.fillStyle = color(col);
                var yy = Y(vv);
                ctx.fillRect(X(i) - bw / 2, Math.min(y0, yy), bw, Math.max(1, Math.abs(yy - y0)));
            }
            ctx.globalAlpha = 1;
        }

        // ----- surcouche : repère, points survolés, sélection
        function overClear() { var c = over.getContext("2d"); c.setTransform(ratio, 0, 0, ratio, 0, 0); c.clearRect(0, 0, W, H); }
        function drawOver() {
            if (!geo) { tip.classList.add("hidden"); return; }
            overClear();
            var c = over.getContext("2d"), hitH = geo.hit || geo.ph;
            if (drag && drag.mode === "select") {
                var a = Math.max(geo.padL, Math.min(drag.x0, drag.x1)), b = Math.min(geo.padL + geo.pw, Math.max(drag.x0, drag.x1));
                c.fillStyle = token("--brand-soft"); c.strokeStyle = token("--brand"); c.lineWidth = 1;
                c.fillRect(a, geo.padT, b - a, hitH); c.strokeRect(a + 0.5, geo.padT + 0.5, b - a, hitH);
                tip.classList.add("hidden");
                return;
            }
            if (!hover) {
                tip.classList.add("hidden"); paintQuote(null);
                if (guideX !== null && guideX >= geo.vx0 && guideX <= geo.vx1) {         // le curseur est sur un autre graphique du groupe : même date, ici
                    var gx = Math.round(geo.X(guideX)) + 0.5;
                    c.strokeStyle = token("--text-3"); c.lineWidth = 1; c.setLineDash([3, 3]);
                    c.beginPath(); c.moveTo(gx, geo.padT); c.lineTo(gx, geo.padT + hitH); c.stroke(); c.setLineDash([]);
                }
                return;
            }
            var hx = hover.px;
            var vis = series.filter(function (s) { return !s.hidden && s.xs.length; });
            if (!vis.length) return;
            var xv = geo.vx0 + (hx - geo.padL) / geo.pw * (geo.vx1 - geo.vx0);
            var ref = vis[0], ri = nearestIndex(ref.xs, xv), rx = ref.xs[ri];
            var sx = geo.X(rx);
            var guide = token("--text-3");
            c.strokeStyle = fin ? withAlpha(guide, 0.9) : guide; c.lineWidth = 1; c.setLineDash(fin ? [] : [3, 3]);
            c.beginPath(); c.moveTo(Math.round(sx) + 0.5, geo.padT); c.lineTo(Math.round(sx) + 0.5, geo.padT + hitH); c.stroke(); c.setLineDash([]);
            var rows = [];
            vis.forEach(function (s) {
                var i = nearestIndex(s.xs, rx), yv = s.ys[i];
                if (yv === null || yv === undefined || !isFinite(yv)) return;
                rows.push({ s: s, v: yv, i: i });
                if (!isBar) {
                    c.fillStyle = (rows.length === 1 && geo.trendCol) ? geo.trendCol : color(s.color);
                    c.beginPath(); c.arc(geo.X(s.xs[i]), geo.Y(yv), 3.4, 0, Math.PI * 2); c.fill();
                    if (fin) { c.strokeStyle = token("--chart-bg"); c.lineWidth = 1.5; c.stroke(); }
                }
            });
            if (isBar && rows.length) {                      // la barre survolée
                var r0 = rows[0], bw = Math.max(2, Math.min(40, geo.pw / (geo.vx1 - geo.vx0) * 0.7));
                c.strokeStyle = token("--text"); c.lineWidth = 1.2;
                c.strokeRect(geo.X(r0.i) - bw / 2 + 0.5, Math.min(geo.Y(0), geo.Y(r0.v)), bw, Math.max(1, Math.abs(geo.Y(r0.v) - geo.Y(0))));
            }
            if (fin && rows.length) {                        // réticule : fil horizontal + pastilles sur l'axe des valeurs et sur l'axe du temps
                var rr = rows[0], ry = geo.Y(rr.v), chipBg = token("--text"), chipFg = token("--bg");
                c.strokeStyle = withAlpha(guide, 0.6); c.lineWidth = 1; c.setLineDash([3, 3]);
                c.beginPath(); c.moveTo(geo.padL, Math.round(ry) + 0.5); c.lineTo(W - geo.padR, Math.round(ry) + 0.5); c.stroke(); c.setLineDash([]);
                drawChipOn(c, (o.tipFmt || valFmt)(rr.v), W - geo.padR + 3, ry, chipBg, chipFg, "left");
                drawChipOn(c, xText(rx, ri), sx, geo.padT + geo.hit + 12, chipBg, chipFg, "center");
            }
            paintQuote(rows.length ? rows[0] : null);
            // infobulle (nœuds texte : jamais d'innerHTML sur des données) ; l'en-tête de cotation la remplace pour une courbe seule
            if (quoteEl && !geo.candle && vis.length === 1) { tip.classList.add("hidden"); return; }
            tip.textContent = "";
            var headTxt = isBar ? ((o.labels && o.labels[ri]) || String(ri)) : xText(rx, ri);
            tip.appendChild(el("strong", "pp-tip-head", { text: headTxt }));
            if (geo.candle) {                                // bougie survolée : ouverture, plus haut, plus bas, clôture, volume
                [["O", o.ohlc.open[ri]], ["H", o.ohlc.high[ri]], ["L", o.ohlc.low[ri]], ["C", ref.ys[ri]]].forEach(function (kv) {
                    var row = el("div", "pp-tip-row");
                    row.appendChild(el("span", "pp-tip-k", { text: kv[0] })); row.appendChild(el("span", null, { text: (o.tipFmt || valFmt)(kv[1]) }));
                    tip.appendChild(row);
                });
            } else rows.forEach(function (r) {
                var row = el("div", "pp-tip-row");
                if (!isBar && (series.length > 1 || r.s.name)) { var sw = el("span", "pp-dot"); sw.style.background = color(r.s.color); row.appendChild(sw); }
                var label = r.s.name ? r.s.name + " " : "";
                row.appendChild(el("span", null, { text: label + (o.tipFmt || o.yFmt || valFmt)(r.v) }));
                tip.appendChild(row);
            });
            if (hasVol && o.volume[ri] !== null && o.volume[ri] !== undefined && isFinite(o.volume[ri])) {
                var vr = el("div", "pp-tip-row");
                vr.appendChild(el("span", "pp-tip-k", { text: tr("chart_volume", "Vol.") })); vr.appendChild(el("span", null, { text: numFmt(o.volume[ri], 0) }));
                tip.appendChild(vr);
            }
            tip.classList.remove("hidden");
            var tw = tip.offsetWidth, th = tip.offsetHeight;
            var left = sx + 12; if (left + tw > W - geo.padR - 4) left = sx - tw - 12;
            var top = Math.max(4, Math.min(hover.py - th - 10, H - th - 4)); if (top < 4) top = 4;
            tip.style.left = Math.max(4, left) + "px"; tip.style.top = top + "px";
        }

        // Pastille dessinée sur la surcouche (même dessin que sur la toile de base).
        function drawChipOn(c, text, x, y, bg, fg, align) {
            c.save();
            c.font = '600 11px ' + (token("--mono") || "monospace");
            var w = Math.ceil(c.measureText(text).width) + 12, h = 18, left = align === "center" ? x - w / 2 : x;
            left = Math.max(1, Math.min(left, W - w - 1));
            var top = Math.max(1, Math.min(y - h / 2, H - h - 1)), r = 4;
            c.fillStyle = bg; c.beginPath();
            c.moveTo(left + r, top); c.lineTo(left + w - r, top); c.quadraticCurveTo(left + w, top, left + w, top + r);
            c.lineTo(left + w, top + h - r); c.quadraticCurveTo(left + w, top + h, left + w - r, top + h);
            c.lineTo(left + r, top + h); c.quadraticCurveTo(left, top + h, left, top + h - r);
            c.lineTo(left, top + r); c.quadraticCurveTo(left, top, left + r, top); c.closePath(); c.fill();
            c.fillStyle = fg; c.textAlign = "left"; c.textBaseline = "middle"; c.fillText(text, left + 6, top + h / 2 + 0.5);
            c.restore();
        }

        // En-tête de cotation : dernière valeur de la fenêtre et variation depuis son début ; au survol, la valeur du point survolé.
        function paintQuote(point) {
            if (!quoteEl || !geo || !geo.ch) return;
            var ch = geo.ch, ref = series.filter(function (s) { return !s.hidden && s.xs.length; })[0];
            if (!ref) return;
            var val = point ? point.v : ch.last, at = point ? ref.xs[point.i] : ref.xs[ch.i1];
            var abs = val - ch.first, pct = ch.first !== 0 ? abs / Math.abs(ch.first) * 100 : null;
            qVal.textContent = (o.tipFmt || valFmt)(val);
            var sign = abs > 0 ? "+" : "";
            qChg.textContent = sign + numFmt(abs, Math.abs(abs) >= 1 ? 2 : 4) + (pct === null ? "" : "  (" + sign + numFmt(pct, 2) + " %)");
            qChg.className = "pp-quote-chg " + (abs > 0 ? "pp-up" : abs < 0 ? "pp-down" : "pp-flat");
            qDate.textContent = dateFmt({ day: "numeric", month: "short", year: "numeric" }).format(at);
        }

        function xText(x, i) {
            if (o.xFmt) return o.xFmt(x, i);
            if (timeAxis) return dateFmt({ day: "numeric", month: "short", year: "numeric" }).format(x);
            return o.xLabel ? String(o.xLabel(Math.round(x))) : String(x);
        }

        // ----- accessibilité et chrome
        function setAria(ye) {
            var s0 = series.find(function (s) { return !s.hidden && s.xs.length; });
            if (!ye || !s0) { over.setAttribute("aria-label", (o.title || "") + " — " + tr("chart_empty", "No data to plot.")); return; }
            var n = s0.xs.length, v = cur();
            var i0 = Math.max(0, lowerBound(s0.xs, v[0])), i1 = Math.min(n - 1, lowerBound(s0.xs, v[1] + 1e-9) - 1);
            over.setAttribute("aria-label", fmtStr(tr("chart_aria", "{title}: {n} points from {from} to {to}, from {min} to {max}. Drag to zoom; double-click to reset."), {
                title: o.title || "", n: Math.max(0, i1 - i0 + 1),
                from: xText(s0.xs[i0], i0), to: xText(s0.xs[Math.max(i0, i1)], Math.max(i0, i1)),
                min: valFmt(ye[0]), max: valFmt(ye[1]) }));
        }
        function updateChrome() {
            var zoomed = !!view;
            stage.setAttribute("data-zoomed", zoomed ? "true" : "false");
            bReset.disabled = !zoomed; bOut.disabled = !zoomed; bIn.disabled = !!(view && (view[1] - view[0]) <= minSpan * 1.001);
            bar.querySelectorAll("button[data-ytd]").forEach(function (b) {
                b.classList.toggle("active", !!(zoomed && Math.abs(view[1] - ext[1]) < DAY * 2 && Math.abs(view[0] - yearStart(ext[1])) < DAY * 4));
            });
            bar.querySelectorAll("button[data-days]").forEach(function (b) {
                var d = b.getAttribute("data-days"), on = d === "all" ? !zoomed : (zoomed && Math.abs(view[1] - ext[1]) < DAY * 2 && Math.abs((view[1] - view[0]) - (+d) * DAY) < DAY * 3);
                b.classList.toggle("active", on);
            });
            if (o.onview) o.onview(view ? view.slice() : null);
        }

        // ----- barre de périodes (axe du temps seulement)
        function syncMode() {
            bar.querySelectorAll("button[data-mode]").forEach(function (b) {
                var on = b.getAttribute("data-mode") === mode;
                b.classList.toggle("active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
            });
        }
        function buildRanges() {
            if (!(timeAxis && (o.ranges || hasOhlc))) return;
            bar.textContent = "";
            bar.className = "pp-ranges";
            if (o.ranges) {
                var box = el("div", "preview-range-buttons"), total = span() / DAY;
                [["1m", 30], ["3m", 91], ["6m", 182], ["ytd", 0], ["1y", 365], ["5y", 1826]].forEach(function (r) {
                    if (r[0] === "ytd") {
                        var from = yearStart(ext[1]);
                        if (total < 100 || from <= ext[0]) return;
                        var by = el("button", "range-btn", { type: "button", "data-ytd": "1", text: tr("chart_range_ytd", "YTD") });
                        by.addEventListener("click", function () { setView(from, ext[1], false); });
                        box.appendChild(by);
                        return;
                    }
                    if (r[1] >= total * 0.9) return;
                    var b = el("button", "range-btn", { type: "button", "data-days": String(r[1]), text: tr("chart_range_" + r[0], r[0].toUpperCase()) });
                    b.addEventListener("click", function () { setView(ext[1] - r[1] * DAY, ext[1], false); });
                    box.appendChild(b);
                });
                var all = el("button", "range-btn", { type: "button", "data-days": "all", text: tr("chart_range_all", "All") });
                all.addEventListener("click", resetView);
                box.appendChild(all);
                bar.appendChild(box);
            }
            if (hasOhlc) {
                var modeBox = el("div", "segmented pp-mode", { role: "group", "aria-label": tr("chart_mode", "Display") });
                [["line", tr("chart_mode_line", "Line")], ["candle", tr("chart_mode_candle", "Candles")]].forEach(function (m) {
                    var bm = el("button", "range-btn", { type: "button", "data-mode": m[0], text: m[1] });
                    bm.addEventListener("click", function () { mode = m[0]; syncMode(); schedule(); });
                    modeBox.appendChild(bm);
                });
                bar.appendChild(modeBox);
                syncMode();
            }
        }
        buildRanges();

        function buildLegend() {
            legend.textContent = "";
            var show = o.legend === true || (o.legend === "auto" && !isBar && series.length > 1 && series.every(function (s) { return s.name; }));
            legend.hidden = !show;
            if (!show) return;
            series.forEach(function (s) {
                var b = el("button", "pp-legend-item", { type: "button", "aria-pressed": s.hidden ? "false" : "true", title: tr("chart_toggle_series", "Show / hide this series") });
                var sw = el("span", "pp-dot"); sw.style.background = color(s.color);
                b.appendChild(sw); b.appendChild(el("span", null, { text: s.name }));
                b.addEventListener("click", function () { s.hidden = !s.hidden; b.setAttribute("aria-pressed", s.hidden ? "false" : "true"); schedule(); });
                legend.appendChild(b);
            });
        }
        buildLegend();

        // ----- interactions
        function pos(ev) { var r = over.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; }
        function inPlot(p) { return geo && p.x >= geo.padL && p.x <= geo.padL + geo.pw && p.y >= geo.padT && p.y <= geo.padT + (geo.hit || geo.ph); }
        function xAt(px) { return geo.vx0 + (px - geo.padL) / geo.pw * (geo.vx1 - geo.vx0); }
        function broadcast(x) {                           // groupe `sync` : tous les graphiques qui le portent montrent la même date sous le curseur
            peersOf(syncGroups, o.sync, api).forEach(function (peer) { peer.setGuide(x); });
        }

        over.addEventListener("pointermove", function (ev) {
            var p = pos(ev);
            if (ev.pointerType === "touch") { touchMove(ev, p); return; }
            if (drag) {
                if (drag.mode === "pan") {
                    var dx = (p.x - drag.last) / geo.pw * (geo.vx1 - geo.vx0);
                    drag.last = p.x; setView(geo.vx0 - dx, geo.vx1 - dx, true);
                } else { drag.x1 = p.x; if (Math.abs(drag.x1 - drag.x0) > 4) drag.moved = true; drawOver(); }
                return;
            }
            hover = inPlot(p) ? { px: p.x, py: p.y } : null; drawOver();
            broadcast(hover ? xAt(p.x) : null);
        });
        over.addEventListener("pointerdown", function (ev) {
            if (!o.zoomable || !geo) return;
            var p = pos(ev);
            if (ev.pointerType === "touch") { touchDown(ev, p); return; }
            if (ev.button !== 0 || !inPlot(p)) return;
            over.setPointerCapture(ev.pointerId);
            drag = ev.shiftKey && view ? { mode: "pan", last: p.x } : { mode: "select", x0: p.x, x1: p.x, moved: false };
            hover = null;
        });
        over.addEventListener("pointerup", function (ev) {
            if (ev.pointerType === "touch") { touchUp(ev); return; }
            if (!drag) return;
            var d = drag; drag = null;
            if (d.mode === "select" && d.moved && geo) {
                var a = Math.max(geo.padL, Math.min(d.x0, d.x1)), b = Math.min(geo.padL + geo.pw, Math.max(d.x0, d.x1));
                if (b - a > 6) { setView(xAt(a), xAt(b), false); return; }
            }
            drawOver();
        });
        over.addEventListener("pointercancel", function (ev) { delete pointers[ev.pointerId]; pinch = null; drag = null; drawOver(); });
        over.addEventListener("pointerleave", function (ev) { if (ev.pointerType !== "touch" && !drag) { hover = null; drawOver(); broadcast(null); } });
        over.addEventListener("dblclick", function () { if (o.zoomable) resetView(); });
        over.addEventListener("wheel", function (ev) {
            if (!o.zoomable || !geo) return;
            var p = pos(ev);
            if (ev.ctrlKey || ev.metaKey) {
                ev.preventDefault();
                zoomBy(ev.deltaY < 0 ? 0.8 : 1.25, inPlot(p) ? xAt(p.x) : undefined);
            } else if (ev.shiftKey || Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) {
                if (!view) return;                                    // rien à déplacer : la page défile
                ev.preventDefault();
                panBy((ev.deltaX || ev.deltaY) > 0 ? 0.15 : -0.15);
            }
        }, { passive: false });
        over.addEventListener("keydown", function (ev) {
            if (!o.zoomable) return;
            var k = ev.key, handled = true;
            if (k === "+" || k === "=") zoomBy(0.7);
            else if (k === "-" || k === "_") zoomBy(1 / 0.7);
            else if (k === "ArrowLeft") panBy(-0.2);
            else if (k === "ArrowRight") panBy(0.2);
            else if (k === "Home" || k === "Escape" || k === "0") resetView();
            else handled = false;
            if (handled) ev.preventDefault();
        });
        // tactile : un doigt déplace la fenêtre zoomée (le défilement vertical de la page reste libre : touch-action: pan-y), deux doigts pincent
        function touchDown(ev, p) {
            pointers[ev.pointerId] = p;
            var ids = Object.keys(pointers);
            if (ids.length === 2) { var a = pointers[ids[0]], b = pointers[ids[1]]; pinch = { d: Math.abs(a.x - b.x) || 1, c: (a.x + b.x) / 2 }; }
            else hover = inPlot(p) ? { px: p.x, py: p.y } : null;
            if (ids.length === 1) { try { over.setPointerCapture(ev.pointerId); } catch (e) { /* pointeur déjà relâché */ } pointers[ev.pointerId].last = p.x; }
            drawOver();
        }
        function touchMove(ev, p) {
            if (!pointers[ev.pointerId]) return;
            var prev = pointers[ev.pointerId]; pointers[ev.pointerId] = { x: p.x, y: p.y, last: prev.x };
            var ids = Object.keys(pointers);
            if (ids.length === 2 && pinch) {
                var a = pointers[ids[0]], b = pointers[ids[1]], d = Math.abs(a.x - b.x) || 1;
                zoomBy(pinch.d / d, xAt((a.x + b.x) / 2)); pinch.d = d;
            } else if (ids.length === 1) {
                if (view && Math.abs(p.x - prev.x) > 0) { var dx = (p.x - prev.x) / geo.pw * (geo.vx1 - geo.vx0); setView(geo.vx0 - dx, geo.vx1 - dx, true); }
                else { hover = inPlot(p) ? { px: p.x, py: p.y } : null; drawOver(); }
            }
        }
        function touchUp(ev) { delete pointers[ev.pointerId]; pinch = null; }
        over.style.touchAction = "pan-y";

        bIn.addEventListener("click", function () { zoomBy(0.6); });
        bOut.addEventListener("click", function () { zoomBy(1 / 0.6); });
        bReset.addEventListener("click", resetView);

        var ro = root.ResizeObserver ? new root.ResizeObserver(function () { schedule(); }) : null;
        if (ro) ro.observe(stage);
        else root.addEventListener("resize", schedule);

        var api = {
            redraw: schedule,
            reset: resetView,
            getView: function () { return view ? view.slice() : null; },
            setView: function (a, b) { setView(a, b, false); },
            extent: function () { return ext.slice(); },
            zoomBy: zoomBy,
            setMode: function (m) { if (hasOhlc && (m === "line" || m === "candle")) { mode = m; syncMode(); schedule(); } },
            destroy: function () { destroyed = true; if (ro) ro.disconnect(); },
            setGuide: function (x) { guideX = x; if (!hover) drawOver(); },
            isStale: function () { return destroyed || (shown && !host.isConnected); },
            host: host,
        };
        if (o.initialDays && timeAxis && span() > o.initialDays * DAY * 1.15) setView(ext[1] - o.initialDays * DAY, ext[1], false);   // vue de départ : les N derniers jours
        live = live.filter(function (c) { return !c.isStale(); });      // élague les graphiques d'une analyse remplacée (détachés après avoir été affichés)
        live.push(api);
        if (o.sync) { syncGroups[o.sync] = (syncGroups[o.sync] || []).filter(function (c) { return !c.isStale(); }); syncGroups[o.sync].push(api); }
        schedule();
        return api;
    }

    function normalise(o, isBar) {
        if (isBar) {
            var n = o.values.length, xs = [];
            for (var i = 0; i < n; i++) xs.push(i);
            return [{ name: o.name || "", color: "--brand", width: 1, xs: xs, ys: o.values, hidden: false }];
        }
        return (o.series || []).map(function (s) {
            return { name: s.name || "", color: s.color || "--brand", width: s.width || 1.8, dash: s.dash || null, hidden: false,
                     xs: s.xs || o.xs, ys: s.ys || s.values };
        });
    }
    function extent(series, isBar) {
        if (isBar) return [-0.5, series[0].xs.length - 0.5];
        var lo = Infinity, hi = -Infinity;
        series.forEach(function (s) {
            for (var i = 0; i < s.xs.length; i++) {
                var yv = s.ys[i];
                if (yv === null || yv === undefined || !isFinite(yv)) continue;
                if (s.xs[i] < lo) lo = s.xs[i];
                break;
            }
            for (var j = s.xs.length - 1; j >= 0; j--) {
                var yw = s.ys[j];
                if (yw === null || yw === undefined || !isFinite(yw)) continue;
                if (s.xs[j] > hi) hi = s.xs[j];
                break;
            }
        });
        if (!isFinite(lo)) return [0, 1];
        if (lo === hi) { lo -= 1; hi += 1; }
        return [lo, hi];
    }

    if (root.addEventListener) {
        root.addEventListener("patrick:themechange", function () {
            live = live.filter(function (c) { return !c.isStale(); });
            live.forEach(function (c) { c.redraw(); });
        });
    }

    var api = { create: create, parseDate: parseDate, _internals: { visibleMarkers: visibleMarkers, peersOf: peersOf, lowerBound: lowerBound, nearestIndex: nearestIndex, niceTicks: niceTicks, decimalsFor: decimalsFor, timeTicks: timeTicks, decimate: decimate, yExtent: yExtent, withAlpha: withAlpha, windowChange: windowChange, candleExtent: candleExtent, yearStart: yearStart } };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    root.PatrickPlot = api;
})(typeof window !== "undefined" ? window : globalThis);
