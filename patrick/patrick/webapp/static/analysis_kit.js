/* Boîte à outils graphique des pages d'analyse (/runs/{id}/analyse, /analyses) : échelles, axes temporels, courbes, barres, nuages,
   histogrammes, tableaux de chaleur, info-bulle. SVG et DOM sans dépendance ; les couleurs viennent des variables CSS (thème clair /
   sombre sans redessin). Exposé : `window.PK`. Aucune donnée n'est calculée ici sauf la mise en forme : les nombres arrivent du serveur. */
(function () {
    "use strict";

    var NS = "http://www.w3.org/2000/svg";
    var I18N = window.I18N || {};
    var LANG = document.documentElement.lang || "fr";
    var STYLE_ATTRS = { fill: 1, stroke: 1, "stop-color": 1 };

    // ------------------------------------------------------------------ texte
    function T(key, params) {
        var text = I18N[key];
        if (text === undefined) text = key;
        if (!params) return text;
        return text.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined && params[k] !== null ? params[k] : m; });
    }

    // ------------------------------------------------------------------ formats
    function isNum(v) { return typeof v === "number" && isFinite(v); }
    function num(v, d) {
        if (!isNum(v)) return "—";
        d = d === undefined ? 2 : d;
        return v.toLocaleString(LANG, { minimumFractionDigits: d, maximumFractionDigits: d });
    }
    function signed(v, d) { return !isNum(v) ? "—" : (v > 0 ? "+" : "") + num(v, d); }
    function pct(v, d) { return !isNum(v) ? "—" : num(v * 100, d === undefined ? 1 : d) + " %"; }
    function spct(v, d) { return !isNum(v) ? "—" : (v > 0 ? "+" : "") + num(v * 100, d === undefined ? 1 : d) + " %"; }
    function int(v) { return !isNum(v) ? "—" : Math.round(v).toLocaleString(LANG); }
    function pval(p) { return !isNum(p) ? "—" : (p < 0.001 ? "< " + num(0.001, 3) : num(p, 3)); }
    function dateMs(s) { return Date.parse(s.length === 10 ? s + "T00:00:00Z" : s); }
    function dateStr(ms) { return new Date(ms).toISOString().slice(0, 10); }
    function shortDate(ms, span) {
        var d = new Date(ms), y = d.getUTCFullYear(), m = d.getUTCMonth() + 1;
        if (span > 4 * 365 * 864e5) return String(y);
        if (span > 400 * 864e5) return y + "-" + (m < 10 ? "0" : "") + m;
        return dateStr(ms).slice(5);
    }

    // ------------------------------------------------------------------ DOM / SVG
    function h(tag, attrs, children) {
        var el = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === null || v === undefined || v === false) return;
            if (k === "class") el.className = v;
            else if (k === "text") el.textContent = v;
            else if (k === "html") el.innerHTML = v;
            else if (k === "style" && typeof v === "object") Object.keys(v).forEach(function (p) { el.style.setProperty(p, v[p]); });
            else el.setAttribute(k, v === true ? "" : v);
        });
        [].concat(children === undefined ? [] : children).forEach(function (c) {
            if (c === null || c === undefined || c === false) return;
            el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
        });
        return el;
    }
    function s(tag, attrs, children) {
        var el = document.createElementNS(NS, tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === null || v === undefined) return;
            if (k === "text") el.textContent = v;
            else if (STYLE_ATTRS[k]) el.style[k === "stop-color" ? "stopColor" : k] = v;
            else el.setAttribute(k, v);
        });
        [].concat(children === undefined ? [] : children).forEach(function (c) { if (c) el.appendChild(c); });
        return el;
    }

    // ------------------------------------------------------------------ info-bulle
    var tipEl = null;
    function tip() {
        if (tipEl && document.body.contains(tipEl)) return tipEl;
        tipEl = h("div", { class: "ra-tip", role: "tooltip", hidden: true });
        document.body.appendChild(tipEl);
        return tipEl;
    }
    function showTip(ev, content) {
        var t = tip();
        t.textContent = "";
        [].concat(content).forEach(function (c) { t.appendChild(typeof c === "string" ? h("div", { text: c }) : c); });
        t.hidden = false;
        var x = ev.clientX + 14, y = ev.clientY + 14, w = t.offsetWidth, hgt = t.offsetHeight;
        if (x + w > window.innerWidth - 8) x = ev.clientX - w - 14;
        if (y + hgt > window.innerHeight - 8) y = ev.clientY - hgt - 14;
        t.style.left = Math.max(4, x) + "px";
        t.style.top = Math.max(4, y) + "px";
    }
    function hideTip() { if (tipEl) tipEl.hidden = true; }
    function hoverTip(node, content) {
        node.addEventListener("mousemove", function (ev) { showTip(ev, typeof content === "function" ? content() : content); });
        node.addEventListener("mouseleave", hideTip);
        return node;
    }

    // ------------------------------------------------------------------ échelles et graduations
    function linear(d0, d1, r0, r1) {
        var span = (d1 - d0) || 1, k = (r1 - r0) / span;
        var f = function (v) { return r0 + (v - d0) * k; };
        f.invert = function (px) { return d0 + (px - r0) / k; };
        f.domain = [d0, d1];
        return f;
    }
    function niceTicks(lo, hi, n) {
        if (!isNum(lo) || !isNum(hi)) return [];
        if (lo === hi) { lo -= 0.5; hi += 0.5; }
        var step0 = (hi - lo) / Math.max(1, n), mag = Math.pow(10, Math.floor(Math.log10(step0)));
        var norm = step0 / mag, step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
        var out = [];
        for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
        return out;
    }
    function timeTicks(lo, hi, maxTicks) {
        var span = hi - lo, day = 864e5, out = [], y0 = new Date(lo).getUTCFullYear(), y1 = new Date(hi).getUTCFullYear();
        if (span > 2.2 * 365 * day) {
            var step = Math.max(1, Math.ceil((y1 - y0) / maxTicks));
            if (step > 5 && step < 10) step = 10;
            else if (step === 3 || step === 4) step = 5;
            for (var y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
                var ms = Date.UTC(y, 0, 1);
                if (ms >= lo && ms <= hi) out.push({ v: ms, label: String(y) });
            }
            return out;
        }
        var months = Math.max(1, Math.ceil((span / (30.4 * day)) / maxTicks));
        var d = new Date(Date.UTC(new Date(lo).getUTCFullYear(), new Date(lo).getUTCMonth(), 1));
        while (d.getTime() <= hi) {
            if (d.getTime() >= lo) out.push({ v: d.getTime(), label: dateStr(d.getTime()).slice(0, 7) });
            d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + months, 1));
        }
        return out;
    }
    function extent(arrays, pad) {
        var lo = Infinity, hi = -Infinity;
        arrays.forEach(function (a) { a.forEach(function (v) { if (isNum(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }); });
        if (!isFinite(lo)) return [0, 1];
        if (lo === hi) { lo -= 0.5; hi += 0.5; }
        var p = (hi - lo) * (pad === undefined ? 0.06 : pad);
        return [lo - p, hi + p];
    }

    // ------------------------------------------------------------------ export PNG
    var INLINE_PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "fill-opacity", "stroke-opacity", "opacity", "font-family", "font-size", "font-weight", "text-anchor"];
    /* Image PNG d'un graphique : les couleurs des variables CSS sont résolues (le fichier exporté n'a pas la feuille de style). */
    function exportPng(svg, name) {
        var vb = svg.viewBox.baseVal, w = vb.width, hgt = vb.height, clone = svg.cloneNode(true);
        var src = svg.querySelectorAll("*"), dst = clone.querySelectorAll("*");
        for (var i = 0; i < src.length; i++) {
            var cs = window.getComputedStyle(src[i]), style = "";
            INLINE_PROPS.forEach(function (p) { var v = cs.getPropertyValue(p); if (v) style += p + ":" + v + ";"; });
            dst[i].setAttribute("style", style);
        }
        var bg = window.getComputedStyle(svg).backgroundColor || "#ffffff";
        clone.setAttribute("xmlns", NS);
        clone.setAttribute("width", w); clone.setAttribute("height", hgt);
        clone.setAttribute("style", "background:" + bg);
        var data = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
        var img = new Image();
        img.onload = function () {
            var k = 2, c = document.createElement("canvas");
            c.width = w * k; c.height = hgt * k;
            var ctx = c.getContext("2d");
            ctx.fillStyle = bg; ctx.fillRect(0, 0, c.width, c.height);
            ctx.drawImage(img, 0, 0, c.width, c.height);
            c.toBlob(function (blob) {
                var a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = (name || "graphique").replace(/[^\w.-]+/g, "_") + ".png";
                document.body.appendChild(a); a.click(); a.remove();
                setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
            }, "image/png");
        };
        img.src = data;
    }
    function pngButton(svg) {
        var b = h("button", { type: "button", class: "ra-png", title: T("ra_png"), "aria-label": T("ra_png"), text: "PNG" });
        b.addEventListener("click", function () { exportPng(svg, (window.RA_FILE_PREFIX ? window.RA_FILE_PREFIX + "_" : "") + (svg.getAttribute("aria-label") || "graphique")); });
        return b;
    }

    // ------------------------------------------------------------------ cadre d'un graphique
    /* o : { w, h, m:{l,r,t,b}, x:{type:'time'|'linear'|'band', domain:[a,b], fmt, ticks, label, bands:[…]}, y:{domain:[a,b], fmt, ticks, label, zero}, title } */
    function plot(o) {
        var W = o.w || 760, H = o.h || 260, m = { l: 54, r: 14, t: 12, b: 28 };
        if (o.y.label) m.l = 68;
        Object.keys(o.m || {}).forEach(function (k) { m[k] = o.m[k]; });
        var svg = s("svg", { viewBox: "0 0 " + W + " " + H, class: "ra-chart", role: "img", "aria-label": o.title || "", preserveAspectRatio: "xMidYMid meet" });
        var xd = o.x.domain, yd = o.y.domain;
        var X = linear(xd[0], xd[1], m.l, W - m.r), Y = linear(yd[0], yd[1], H - m.b, m.t);
        var yTicks = o.y.ticks || niceTicks(yd[0], yd[1], o.y.n || 5);
        yTicks.forEach(function (t) {
            if (t < yd[0] - 1e-12 || t > yd[1] + 1e-12) return;
            svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: "var(--chart-grid)" }));
            svg.appendChild(s("text", { x: m.l - 6, y: Y(t) + 3.5, "text-anchor": "end", class: "ra-axis", text: (o.y.fmt || function (v) { return num(v, 2); })(t) }));
        });
        var xTicks;
        if (o.x.type === "time") xTicks = o.x.ticks || timeTicks(xd[0], xd[1], Math.max(3, Math.floor((W - m.l - m.r) / 90)));
        else xTicks = (o.x.ticks || niceTicks(xd[0], xd[1], Math.max(3, Math.floor((W - m.l - m.r) / 80)))).map(function (v) { return { v: v, label: (o.x.fmt || function (q) { return num(q, 2); })(v) }; });
        xTicks.forEach(function (t) {
            svg.appendChild(s("line", { x1: X(t.v), x2: X(t.v), y1: m.t, y2: H - m.b, stroke: "var(--chart-grid)" }));
            svg.appendChild(s("text", { x: X(t.v), y: o.x.axisY !== undefined ? o.x.axisY : H - m.b + 15, "text-anchor": "middle", class: "ra-axis", text: t.label }));
        });
        if (o.y.zero !== false && yd[0] < 0 && yd[1] > 0) svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: "var(--line-strong)" }));
        if (o.x.label) svg.appendChild(s("text", { x: (m.l + W - m.r) / 2, y: H - 2, "text-anchor": "middle", class: "ra-axis ra-axis-label", text: o.x.label }));
        if (o.y.label) svg.appendChild(s("text", { x: 12, y: (m.t + H - m.b) / 2, "text-anchor": "middle", class: "ra-axis ra-axis-label", transform: "rotate(-90 12 " + (m.t + H - m.b) / 2 + ")", text: o.y.label }));
        var layer = s("g", {});
        svg.appendChild(layer);
        var P = { svg: svg, layer: layer, X: X, Y: Y, W: W, H: H, m: m, xDomain: xd, yDomain: yd };
        P.add = function (n) { if (n) layer.appendChild(n); return n; };
        P.node = h("div", { class: "ra-chart-wrap" }, [svg, pngButton(svg)]);
        return P;
    }

    function pathD(P, xs, ys, step) {
        var d = "", pen = false, lastY = null;
        for (var i = 0; i < xs.length; i++) {
            var v = ys[i];
            if (!isNum(v) || !isNum(xs[i])) { pen = false; continue; }
            var x = P.X(xs[i]), y = P.Y(v);
            if (!pen) { d += "M" + x.toFixed(1) + " " + y.toFixed(1); pen = true; }
            else if (step) d += "L" + x.toFixed(1) + " " + lastY.toFixed(1) + "L" + x.toFixed(1) + " " + y.toFixed(1);
            else d += "L" + x.toFixed(1) + " " + y.toFixed(1);
            lastY = y;
        }
        return d;
    }
    function line(P, xs, ys, o) {
        o = o || {};
        var d = pathD(P, xs, ys, o.step);
        if (!d) return null;
        var g = s("g", {});
        if (o.area) {
            var base = P.Y(Math.max(P.yDomain[0], Math.min(P.yDomain[1], o.areaBase === undefined ? 0 : o.areaBase)));
            var first = null, last = null;
            for (var i = 0; i < xs.length; i++) if (isNum(ys[i])) { if (first === null) first = P.X(xs[i]); last = P.X(xs[i]); }
            g.appendChild(s("path", { d: d + "L" + last.toFixed(1) + " " + base.toFixed(1) + "L" + first.toFixed(1) + " " + base.toFixed(1) + "Z", fill: o.color || "var(--brand)", "fill-opacity": o.areaOpacity || 0.12, stroke: "none" }));
        }
        g.appendChild(s("path", { d: d, fill: "none", stroke: o.color || "var(--brand)", "stroke-width": o.width || 1.6, "stroke-linejoin": "round", "stroke-dasharray": o.dash || null, "stroke-opacity": o.opacity || 1 }));
        return P.add(g);
    }
    function band(P, xs, lo, hi, o) {
        o = o || {};
        var up = "", dn = "", n = 0;
        for (var i = 0; i < xs.length; i++) {
            if (!isNum(lo[i]) || !isNum(hi[i])) continue;
            up += (n ? "L" : "M") + P.X(xs[i]).toFixed(1) + " " + P.Y(hi[i]).toFixed(1);
            dn = "L" + P.X(xs[i]).toFixed(1) + " " + P.Y(lo[i]).toFixed(1) + dn;
            n++;
        }
        if (!n) return null;
        return P.add(s("path", { d: up + dn + "Z", fill: o.color || "var(--brand)", "fill-opacity": o.opacity || 0.16, stroke: "none" }));
    }
    function points(P, xs, ys, o) {
        o = o || {};
        var g = s("g", {});
        for (var i = 0; i < xs.length; i++) {
            if (!isNum(xs[i]) || !isNum(ys[i])) continue;
            var c = typeof o.color === "function" ? o.color(i) : (o.color || "var(--brand)");
            g.appendChild(s("circle", { cx: P.X(xs[i]).toFixed(1), cy: P.Y(ys[i]).toFixed(1), r: typeof o.r === "function" ? o.r(i) : (o.r || 2.2), fill: c, "fill-opacity": o.opacity || 0.55, stroke: "none" }));
        }
        return P.add(g);
    }
    function bars(P, xs, ys, o) {
        o = o || {};
        var g = s("g", {}), base = P.Y(Math.max(P.yDomain[0], Math.min(P.yDomain[1], o.base === undefined ? 0 : o.base)));
        var w = o.width || Math.max(2, Math.min(40, (P.W - P.m.l - P.m.r) / Math.max(1, xs.length) * 0.7));
        for (var i = 0; i < xs.length; i++) {
            if (!isNum(ys[i])) continue;
            var y = P.Y(ys[i]), top = Math.min(y, base), hgt = Math.max(1, Math.abs(y - base));
            var r = s("rect", { x: (P.X(xs[i]) - w / 2).toFixed(1), y: top.toFixed(1), width: w.toFixed(1), height: hgt.toFixed(1),
                fill: typeof o.color === "function" ? o.color(ys[i], i) : (o.color || (ys[i] >= 0 ? "var(--brand)" : "var(--neg)")), "fill-opacity": o.opacity || 0.9 });
            if (o.title) r.appendChild(s("title", { text: o.title(i) }));
            g.appendChild(r);
        }
        return P.add(g);
    }
    function hline(P, y, o) {
        o = o || {};
        if (!isNum(y) || y < P.yDomain[0] || y > P.yDomain[1]) return null;
        var g = s("g", {});
        g.appendChild(s("line", { x1: P.m.l, x2: P.W - P.m.r, y1: P.Y(y), y2: P.Y(y), stroke: o.color || "var(--text-3)", "stroke-dasharray": o.dash || "4 4", "stroke-width": o.width || 1 }));
        if (o.label) g.appendChild(s("text", { x: P.W - P.m.r - 3, y: P.Y(y) - 3, "text-anchor": "end", class: "ra-axis", text: o.label }));
        return P.add(g);
    }
    function vline(P, x, o) {
        o = o || {};
        if (!isNum(x) || x < P.xDomain[0] || x > P.xDomain[1]) return null;
        var g = s("g", {});
        g.appendChild(s("line", { x1: P.X(x), x2: P.X(x), y1: P.m.t, y2: P.H - P.m.b, stroke: o.color || "var(--text-3)", "stroke-dasharray": o.dash || "3 3", "stroke-width": o.width || 1 }));
        if (o.label) g.appendChild(s("text", { x: P.X(x) + (o.anchor === "end" ? -3 : 3), y: P.m.t + 9 + (o.row || 0) * 11, "text-anchor": o.anchor === "end" ? "end" : "start", class: "ra-axis", text: o.label }));
        return P.add(g);
    }
    function xband(P, x0, x1, o) {
        o = o || {};
        var a = Math.max(P.xDomain[0], x0), b = Math.min(P.xDomain[1], x1);
        if (b <= a) return null;
        var g = s("g", {});
        g.appendChild(s("rect", { x: P.X(a), y: P.m.t, width: Math.max(0, P.X(b) - P.X(a)), height: P.H - P.m.t - P.m.b, fill: o.color || "var(--neutral-soft)", "fill-opacity": o.opacity || 1 }));
        if (o.label) g.appendChild(s("text", { x: P.X(a) + 3, y: P.m.t + 9, class: "ra-axis", text: o.label }));
        return P.layer.insertBefore(g, P.layer.firstChild);
    }
    function yband(P, y0, y1, o) {
        o = o || {};
        var a = Math.max(P.yDomain[0], Math.min(y0, y1)), b = Math.min(P.yDomain[1], Math.max(y0, y1));
        if (b <= a) return null;
        return P.layer.insertBefore(s("rect", { x: P.m.l, y: P.Y(b), width: P.W - P.m.l - P.m.r, height: P.Y(a) - P.Y(b), fill: o.color || "var(--neutral-soft)", "fill-opacity": o.opacity || 1 }), P.layer.firstChild);
    }

    /* Curseur vertical + info-bulle : `tip(xValue)` renvoie la liste de lignes de texte (ou null) pour la valeur de x survolée. */
    function hover(P, tipFn, snap) {
        var cur = s("line", { y1: P.m.t, y2: P.H - P.m.b, stroke: "var(--text-3)", "stroke-width": 1, visibility: "hidden" });
        var overlay = s("rect", { x: P.m.l, y: P.m.t, width: P.W - P.m.l - P.m.r, height: P.H - P.m.t - P.m.b, fill: "transparent" });
        P.svg.appendChild(cur);
        P.svg.appendChild(overlay);
        overlay.addEventListener("mousemove", function (ev) {
            var r = P.svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * P.W;
            var xv = P.X.invert(px), lines = tipFn(snap ? snap(xv) : xv);
            if (!lines) { cur.setAttribute("visibility", "hidden"); hideTip(); return; }
            var sx = snap ? P.X(snap(xv)) : px;
            cur.setAttribute("x1", sx); cur.setAttribute("x2", sx); cur.setAttribute("visibility", "visible");
            showTip(ev, lines);
        });
        overlay.addEventListener("mouseleave", function () { cur.setAttribute("visibility", "hidden"); hideTip(); });
        return overlay;
    }
    /* Sélection d'une plage de x à la souris : `onRange(x0, x1)` est appelé au relâchement (plage d'au moins 6 px). */
    function brush(P, onRange) {
        var overlay = P.svg.querySelector("rect[data-ra-overlay]") || s("rect", { x: P.m.l, y: P.m.t, width: P.W - P.m.l - P.m.r, height: P.H - P.m.t - P.m.b, fill: "transparent", "data-ra-overlay": "1" });
        var sel = s("rect", { y: P.m.t, height: P.H - P.m.t - P.m.b, fill: "var(--brand)", "fill-opacity": 0.18, visibility: "hidden" });
        P.svg.appendChild(sel);
        P.svg.appendChild(overlay);
        var start = null;
        function px(ev) { var r = P.svg.getBoundingClientRect(); return Math.max(P.m.l, Math.min(P.W - P.m.r, (ev.clientX - r.left) / r.width * P.W)); }
        overlay.addEventListener("mousedown", function (ev) { start = px(ev); sel.setAttribute("x", start); sel.setAttribute("width", 0); sel.setAttribute("visibility", "visible"); ev.preventDefault(); });
        window.addEventListener("mousemove", function (ev) {
            if (start === null) return;
            var p = px(ev); sel.setAttribute("x", Math.min(start, p)); sel.setAttribute("width", Math.abs(p - start));
        });
        window.addEventListener("mouseup", function (ev) {
            if (start === null) return;
            var p = px(ev), a = Math.min(start, p), b = Math.max(start, p);
            start = null; sel.setAttribute("visibility", "hidden");
            if (b - a >= 6) onRange(P.X.invert(a), P.X.invert(b));
        });
        return overlay;
    }

    // ------------------------------------------------------------------ éléments HTML
    function kpi(label, value, sub, state) {
        return h("div", { class: "metric ra-kpi" }, [
            h("div", { class: "metric-label", text: label }),
            h("div", { class: "metric-value pk-mono status-" + (state || "neutral"), text: value }),
            sub ? h("div", { class: "metric-reliability hint", "data-keep": "1", text: sub }) : null]);
    }
    function legend(items) {
        return h("div", { class: "ra-legend" }, items.map(function (it) {
            return h("span", { class: "ra-legend-item" }, [h("i", { class: "ra-swatch" + (it.line ? " ra-swatch-line" : ""), style: { background: it.color } }), it.label]);
        }));
    }
    function table(headers, rows, o) {
        o = o || {};
        var head = h("tr", {}, headers.map(function (t, i) { return h("th", { scope: "col", class: (o.num && o.num.indexOf(i) >= 0) ? "num pk-mono" : "", text: t }); }));
        var body = rows.map(function (r, ri) {
            var tr = h("tr", { class: (o.rowClass && o.rowClass(ri)) || "" }, r.map(function (c, i) {
                var cell = c !== null && typeof c === "object" && c.nodeType === undefined && c.cell !== undefined ? c : { cell: c };
                var td = h("td", { class: ((o.num && o.num.indexOf(i) >= 0) ? "num pk-mono " : "") + (cell.cls || "") });
                if (cell.cell !== null && typeof cell.cell === "object" && cell.cell.nodeType) td.appendChild(cell.cell);
                else td.textContent = cell.cell === null || cell.cell === undefined ? "—" : String(cell.cell);
                return td;
            }));
            return tr;
        });
        return h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [head]), h("tbody", {}, body)])]);
    }
    /* Tableau de chaleur HTML : lignes × colonnes ; `cellFn(r, c)` -> { text, intensity (0..1 ou null), color (css) }. */
    function heat(rowLabels, colLabels, cellFn, o) {
        o = o || {};
        var head = h("tr", {}, [h("th", { class: "ra-heat-corner", text: o.corner || "" })].concat(colLabels.map(function (c) { return h("th", { scope: "col", text: c }); })));
        var body = rowLabels.map(function (rl, ri) {
            return h("tr", {}, [h("th", { scope: "row", text: rl })].concat(colLabels.map(function (cl, ci) {
                var c = cellFn(ri, ci) || {};
                var td = h("td", { class: "pk-mono" + (c.cls ? " " + c.cls : ""), text: c.text === undefined || c.text === null ? "" : c.text });
                if (c.color) td.style.background = c.color;
                else if (isNum(c.intensity)) td.style.background = "color-mix(in srgb, " + (c.base || "var(--brand)") + " " + Math.round(Math.max(0, Math.min(1, c.intensity)) * 70) + "%, transparent)";
                if (c.title) td.title = c.title;
                if (c.href && c.text) { td.textContent = ""; td.appendChild(h("a", { href: c.href, text: c.text })); }
                return td;
            })));
        });
        return h("div", { class: "table-scroll" }, [h("table", { class: "ra-heat" }, [h("thead", {}, [head]), h("tbody", {}, body)])]);
    }
    // Texte d'aide : `help.js` replie les phrases longues derrière un « ? ». `info` = phrase qui porte une donnée : jamais repliée.
    function note(text, cls) { return h("p", { class: "hint " + (cls || ""), text: text }); }
    function info(text, cls) { return h("p", { class: "hint " + (cls || ""), "data-keep": "1", text: text }); }
    function empty(text) { return h("p", { class: "ra-empty hint", "data-keep": "1", text: text }); }
    function chip(text, kind) { return h("span", { class: "exp-chip exp-chip-" + (kind || "neutral"), text: text }); }
    function select(options, value, onChange, label) {
        var sel = h("select", { class: "ra-select" }, options.map(function (o) { return h("option", { value: o.value, text: o.label, selected: String(o.value) === String(value) }); }));
        sel.addEventListener("change", function () { onChange(sel.value); });
        return label ? h("label", { class: "ra-control" }, [h("span", { text: label }), sel]) : sel;
    }
    function segmented(options, value, onChange) {
        var box = h("div", { class: "ra-seg", role: "group" });
        options.forEach(function (o) {
            var b = h("button", { type: "button", class: "range-btn" + (String(o.value) === String(value) ? " active" : ""), text: o.label });
            b.addEventListener("click", function () {
                [].forEach.call(box.children, function (c) { c.classList.remove("active"); });
                b.classList.add("active");
                onChange(o.value);
            });
            box.appendChild(b);
        });
        return box;
    }
    function fetchJSON(url) {
        return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
            if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.detail || b.error || ("HTTP " + r.status)); });
            return r.json();
        });
    }
    function qs(params) {
        return Object.keys(params || {}).filter(function (k) { return params[k] !== undefined && params[k] !== null && params[k] !== ""; })
            .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]); }).join("&");
    }
    /* Notes du serveur : `code` ou `code:détail` ; le texte vient de la clé `ra_note_<code>` (le détail est affiché tel quel). */
    function noteText(n) {
        var i = String(n).indexOf(":"), code = i < 0 ? String(n) : String(n).slice(0, i), detail = i < 0 ? "" : String(n).slice(i + 1);
        var key = "ra_note_" + code, text = T(key, { d: detail });
        return text === key ? String(n) : text;
    }
    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

    var CLASS_COLORS = ["var(--neg)", "color-mix(in srgb, var(--neg) 50%, var(--text-3))", "color-mix(in srgb, var(--pos) 50%, var(--text-3))", "var(--pos)"];
    var CAT_COLORS = ["var(--ra-c1)", "var(--ra-c2)", "var(--ra-c3)", "var(--ra-c4)", "var(--ra-c5)", "var(--ra-c6)", "var(--ra-c7)", "var(--ra-c8)"];

    window.PK = {
        T: T, num: num, signed: signed, pct: pct, spct: spct, int: int, pval: pval, isNum: isNum, dateMs: dateMs, dateStr: dateStr, shortDate: shortDate,
        h: h, s: s, showTip: showTip, hideTip: hideTip, hoverTip: hoverTip, linear: linear, niceTicks: niceTicks, timeTicks: timeTicks, extent: extent,
        plot: plot, line: line, band: band, points: points, bars: bars, hline: hline, vline: vline, xband: xband, yband: yband, hover: hover, brush: brush,
        kpi: kpi, legend: legend, table: table, heat: heat, note: note, info: info, empty: empty, chip: chip, select: select, segmented: segmented,
        fetchJSON: fetchJSON, qs: qs, clear: clear, noteText: noteText, exportPng: exportPng, CLASS_COLORS: CLASS_COLORS, CAT_COLORS: CAT_COLORS,
    };
})();
