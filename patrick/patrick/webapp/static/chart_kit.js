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
    var DEFAULTS = { type: "line", height: 240, zoomable: true, markers: "auto", legend: "auto", compact: false, connectGaps: false, ranges: false };
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
        if (o.ranges && timeAxis) host.appendChild(bar);
        host.appendChild(stage);
        host.appendChild(legend);
        if (o.compact) host.classList.add("pp-compact");
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
        function draw() {
            if (destroyed || !sizeCanvases()) return;
            if (host.isConnected) shown = true;
            var ctx = base.getContext("2d");
            ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            ctx.clearRect(0, 0, W, H);
            var v = cur(), vx0 = v[0], vx1 = v[1];
            var visible = series.filter(function (s) { return !s.hidden; });
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
            var ye = yExtent(series, vx0, vx1, view ? marks : [], always);
            var muted = token("--text-3"), grid = token("--chart-grid"), line = token("--line-strong"), font = '11px ' + (token("--mono") || "monospace");
            if (!ye || !visible.length) {
                ctx.fillStyle = muted; ctx.font = font; ctx.textAlign = "left";
                ctx.fillText(o.empty || tr("chart_empty", "No data to plot."), 14, H / 2);
                geo = null; setAria(null); overClear(); updateChrome(); tip.classList.add("hidden"); return;
            }
            var lo = ye[0], hi = ye[1], pad = (hi - lo) * 0.06 || 0.5;
            lo -= (isBar && lo >= 0) ? 0 : pad; hi += pad;
            var padT = 10, padB = 24, padR = 14;
            var yTicks = niceTicks(lo, hi, Math.max(2, Math.min(7, Math.floor((H - padT - padB) / 44))));
            var dec = decimalsFor(yTicks.step), yFmt = o.yFmt ? function (x) { return o.yFmt(x, dec); } : function (x) { return numFmt(x, dec); };
            ctx.font = font;
            var padL = 12;
            yTicks.forEach(function (t) { padL = Math.max(padL, ctx.measureText(yFmt(t)).width + 14); });
            padL = Math.min(padL, W * 0.4);
            var pw = W - padL - padR, ph = H - padT - padB;
            function X(x) { return padL + (x - vx0) / (vx1 - vx0) * pw; }
            function Y(y) { return padT + (1 - (y - lo) / (hi - lo)) * ph; }
            // grille et axe Y
            ctx.lineWidth = 1; ctx.textBaseline = "middle"; ctx.textAlign = "right";
            yTicks.forEach(function (t) {
                var yy = Math.round(Y(t)) + 0.5;
                ctx.strokeStyle = grid; ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
                ctx.fillStyle = muted; ctx.fillText(yFmt(t), padL - 8, yy);
            });
            // axe X
            ctx.textBaseline = "alphabetic"; ctx.textAlign = "center";
            var xTicks = axisX(vx0, vx1, pw, ctx);
            xTicks.forEach(function (tk) {
                var xx = Math.round(X(tk.x)) + 0.5;
                ctx.strokeStyle = grid; ctx.beginPath(); ctx.moveTo(xx, padT); ctx.lineTo(xx, padT + ph); ctx.stroke();
                ctx.fillStyle = muted; ctx.fillText(tk.label, Math.min(Math.max(xx, padL + 14), W - padR - 14), H - 7);
            });
            ctx.save(); ctx.beginPath(); ctx.rect(padL, padT - 1, pw, ph + 2); ctx.clip();
            if (o.band) { ctx.fillStyle = token("--neutral-soft"); ctx.fillRect(padL, Y(o.band[1]), pw, Math.max(0, Y(o.band[0]) - Y(o.band[1]))); }
            if (isBar && o.band) {
                [o.band, -o.band].forEach(function (b) { ctx.strokeStyle = muted; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(padL, Y(b)); ctx.lineTo(W - padR, Y(b)); ctx.stroke(); ctx.setLineDash([]); });
            }
            (o.hlines || []).forEach(function (l) {
                ctx.strokeStyle = color(l.color || "--text-3"); ctx.lineWidth = l.width || 1;
                ctx.setLineDash(dashOf(l.dash, [4, 4])); ctx.beginPath(); ctx.moveTo(padL, Y(l.y)); ctx.lineTo(W - padR, Y(l.y)); ctx.stroke(); ctx.setLineDash([]);
                if (l.label) { ctx.fillStyle = muted; ctx.font = font; ctx.textAlign = "right"; ctx.textBaseline = "bottom"; ctx.fillText(l.label, W - padR - 6, Y(l.y) - 3); ctx.textBaseline = "alphabetic"; }
            });
            if (isBar) drawBars(ctx, X, Y, vx0, vx1, pw);
            else visible.forEach(function (s) { drawLine(ctx, s, X, Y, vx0, vx1, pw); });
            ctx.restore();
            if (isBar) { ctx.strokeStyle = line; ctx.beginPath(); ctx.moveTo(padL, Math.round(Y(0)) + 0.5); ctx.lineTo(W - padR, Math.round(Y(0)) + 0.5); ctx.stroke(); }
            geo = { padL: padL, padT: padT, pw: pw, ph: ph, X: X, Y: Y, vx0: vx0, vx1: vx1, lo: lo, hi: hi, yFmt: yFmt };
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

        function drawLine(ctx, s, X, Y, vx0, vx1, pw) {
            var n = s.xs.length;
            if (!n) return;
            var i0 = Math.max(0, lowerBound(s.xs, vx0) - 1), i1 = Math.min(n - 1, lowerBound(s.xs, vx1));
            var idx = decimate(s.xs, s.ys, i0, i1, X, pw);
            ctx.strokeStyle = color(s.color); ctx.lineWidth = s.width; ctx.lineJoin = "round"; ctx.lineCap = "round";
            ctx.setLineDash(dashOf(s.dash, []));
            ctx.beginPath();
            var pen = false;
            for (var k = 0; k < idx.length; k++) {
                var j = idx[k], yv = s.ys[j];
                if (yv === null || yv === undefined || !isFinite(yv)) { if (!o.connectGaps) pen = false; continue; }   // trou honnête : jamais de valeur inventée
                if (!pen) { ctx.moveTo(X(s.xs[j]), Y(yv)); pen = true; } else ctx.lineTo(X(s.xs[j]), Y(yv));
            }
            ctx.stroke(); ctx.setLineDash([]);
            if (o.markers === true || (o.markers === "auto" && i1 - i0 < 60 && pw / Math.max(1, i1 - i0) > 14)) {   // points marqués quand ils sont espacés
                ctx.fillStyle = color(s.color);
                for (var m = i0; m <= i1; m++) {
                    var mv = s.ys[m];
                    if (mv === null || mv === undefined || !isFinite(mv)) continue;
                    ctx.beginPath(); ctx.arc(X(s.xs[m]), Y(mv), 2.4, 0, Math.PI * 2); ctx.fill();
                }
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
            var c = over.getContext("2d");
            if (drag && drag.mode === "select") {
                var a = Math.max(geo.padL, Math.min(drag.x0, drag.x1)), b = Math.min(geo.padL + geo.pw, Math.max(drag.x0, drag.x1));
                c.fillStyle = token("--brand-soft"); c.strokeStyle = token("--brand"); c.lineWidth = 1;
                c.fillRect(a, geo.padT, b - a, geo.ph); c.strokeRect(a + 0.5, geo.padT + 0.5, b - a, geo.ph);
                tip.classList.add("hidden");
                return;
            }
            if (!hover) { tip.classList.add("hidden"); return; }
            var hx = hover.px;
            var vis = series.filter(function (s) { return !s.hidden && s.xs.length; });
            if (!vis.length) return;
            var xv = geo.vx0 + (hx - geo.padL) / geo.pw * (geo.vx1 - geo.vx0);
            var ref = vis[0], ri = nearestIndex(ref.xs, xv), rx = ref.xs[ri];
            var sx = geo.X(rx);
            c.strokeStyle = token("--text-3"); c.lineWidth = 1; c.setLineDash([3, 3]);
            c.beginPath(); c.moveTo(Math.round(sx) + 0.5, geo.padT); c.lineTo(Math.round(sx) + 0.5, geo.padT + geo.ph); c.stroke(); c.setLineDash([]);
            var rows = [];
            vis.forEach(function (s) {
                var i = nearestIndex(s.xs, rx), yv = s.ys[i];
                if (yv === null || yv === undefined || !isFinite(yv)) return;
                rows.push({ s: s, v: yv, i: i });
                if (!isBar) { c.fillStyle = color(s.color); c.beginPath(); c.arc(geo.X(s.xs[i]), geo.Y(yv), 3.2, 0, Math.PI * 2); c.fill(); }
            });
            if (isBar && rows.length) {                      // la barre survolée
                var r0 = rows[0], bw = Math.max(2, Math.min(40, geo.pw / (geo.vx1 - geo.vx0) * 0.7));
                c.strokeStyle = token("--text"); c.lineWidth = 1.2;
                c.strokeRect(geo.X(r0.i) - bw / 2 + 0.5, Math.min(geo.Y(0), geo.Y(r0.v)), bw, Math.max(1, Math.abs(geo.Y(r0.v) - geo.Y(0))));
            }
            // infobulle (nœuds texte : jamais d'innerHTML sur des données)
            tip.textContent = "";
            var headTxt = isBar ? ((o.labels && o.labels[ri]) || String(ri)) : xText(rx, ri);
            tip.appendChild(el("strong", "pp-tip-head", { text: headTxt }));
            rows.forEach(function (r) {
                var row = el("div", "pp-tip-row");
                if (!isBar && (series.length > 1 || r.s.name)) { var sw = el("span", "pp-dot"); sw.style.background = color(r.s.color); row.appendChild(sw); }
                var label = r.s.name ? r.s.name + " " : "";
                row.appendChild(el("span", null, { text: label + (o.tipFmt || o.yFmt || valFmt)(r.v) }));
                tip.appendChild(row);
            });
            tip.classList.remove("hidden");
            var tw = tip.offsetWidth, th = tip.offsetHeight;
            var left = sx + 12; if (left + tw > W - 4) left = sx - tw - 12;
            var top = Math.max(4, Math.min(hover.py - th - 10, H - th - 4)); if (top < 4) top = 4;
            tip.style.left = Math.max(4, left) + "px"; tip.style.top = top + "px";
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
            bar.querySelectorAll("button[data-days]").forEach(function (b) {
                var d = b.getAttribute("data-days"), on = d === "all" ? !zoomed : (zoomed && Math.abs(view[1] - ext[1]) < DAY * 2 && Math.abs((view[1] - view[0]) - (+d) * DAY) < DAY * 3);
                b.classList.toggle("active", on);
            });
            if (o.onview) o.onview(view ? view.slice() : null);
        }

        // ----- barre de périodes (axe du temps seulement)
        function buildRanges() {
            if (!(o.ranges && timeAxis)) return;
            bar.textContent = "";
            bar.className = "pp-ranges preview-range-buttons";
            var total = span() / DAY;
            [["1m", 30], ["3m", 91], ["6m", 182], ["1y", 365], ["5y", 1826]].forEach(function (r) {
                if (r[1] >= total * 0.9) return;
                var b = el("button", "range-btn", { type: "button", "data-days": String(r[1]), text: tr("chart_range_" + r[0], r[0].toUpperCase()) });
                b.addEventListener("click", function () { setView(ext[1] - r[1] * DAY, ext[1], false); });
                bar.appendChild(b);
            });
            var all = el("button", "range-btn", { type: "button", "data-days": "all", text: tr("chart_range_all", "All") });
            all.addEventListener("click", resetView);
            bar.appendChild(all);
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
        function inPlot(p) { return geo && p.x >= geo.padL && p.x <= geo.padL + geo.pw && p.y >= geo.padT && p.y <= geo.padT + geo.ph; }
        function xAt(px) { return geo.vx0 + (px - geo.padL) / geo.pw * (geo.vx1 - geo.vx0); }

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
        over.addEventListener("pointerleave", function (ev) { if (ev.pointerType !== "touch" && !drag) { hover = null; drawOver(); } });
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
            destroy: function () { destroyed = true; if (ro) ro.disconnect(); },
            isStale: function () { return destroyed || (shown && !host.isConnected); },
            host: host,
        };
        live = live.filter(function (c) { return !c.isStale(); });      // élague les graphiques d'une analyse remplacée (détachés après avoir été affichés)
        live.push(api);
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

    var api = { create: create, parseDate: parseDate, _internals: { lowerBound: lowerBound, nearestIndex: nearestIndex, niceTicks: niceTicks, decimalsFor: decimalsFor, timeTicks: timeTicks, decimate: decimate, yExtent: yExtent } };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    root.PatrickPlot = api;
})(typeof window !== "undefined" ? window : globalThis);
