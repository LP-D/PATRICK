/* Page /predictions : popover flottant au survol (ou au focus clavier) de tout
   élément `.pop-trigger` ; le contenu est le `.pop-content` (HTML rendu et
   échappé côté serveur) du déclencheur. Positionné en `fixed` : le tableau
   défile dans son propre conteneur, un tooltip CSS absolu y serait rogné. */
(function () {
    "use strict";
    var pop = document.createElement("div");
    pop.className = "pred-pop";
    pop.setAttribute("role", "tooltip");
    pop.hidden = true;
    document.body.appendChild(pop);
    var current = null;

    function place(el) {
        var r = el.getBoundingClientRect();
        pop.style.left = "0px";
        pop.style.top = "0px";
        var w = pop.offsetWidth, h = pop.offsetHeight;
        var left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 8));
        var top = r.bottom + 8;
        if (top + h > window.innerHeight - 8) top = r.top - h - 8;
        // Bulle haute (suivi par mouvement) : ni sous la case ni au-dessus ne suffit, elle reste entière à l'écran.
        top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
        pop.style.left = left + "px";
        pop.style.top = top + "px";
    }

    var reliabilityCache = {};

    function svgEl(name, attrs) {
        var e = document.createElementNS("http://www.w3.org/2000/svg", name);
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        return e;
    }

    /* Diagramme de fiabilité de P(hausse) : un point par tranche (probabilité annoncée en x, fréquence observée en y), la diagonale = calibration parfaite. */
    function reliabilityBlock(data) {
        var box = document.createElement("div");
        box.className = "pop-rel";
        var title = document.createElement("strong");
        title.textContent = data.title;
        box.appendChild(title);
        if (!data.bins.length) {
            var none = document.createElement("span");
            none.className = "hint";
            none.textContent = data.none;
            box.appendChild(none);
            return box;
        }
        var S = 110, P = 6;
        var svg = svgEl("svg", { width: S + 2 * P, height: S + 2 * P, viewBox: "0 0 " + (S + 2 * P) + " " + (S + 2 * P), role: "img", "aria-label": data.title });
        function X(v) { return P + v * S; }
        function Y(v) { return P + (1 - v) * S; }
        svg.appendChild(svgEl("rect", { x: P, y: P, width: S, height: S, fill: "none", stroke: "currentColor", "stroke-opacity": "0.25" }));
        svg.appendChild(svgEl("line", { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1), stroke: "currentColor", "stroke-opacity": "0.45", "stroke-dasharray": "3 3" }));
        var pts = data.bins.map(function (b) { return X(b.p) + "," + Y(b.freq); }).join(" ");
        svg.appendChild(svgEl("polyline", { points: pts, fill: "none", stroke: "var(--brand, #2563eb)", "stroke-width": "1.5" }));
        var nmax = Math.max.apply(null, data.bins.map(function (b) { return b.n; }));
        data.bins.forEach(function (b) {
            svg.appendChild(svgEl("circle", { cx: X(b.p), cy: Y(b.freq), r: 2 + 3 * Math.sqrt(b.n / nmax), fill: "var(--brand, #2563eb)" }));
        });
        box.appendChild(svg);
        var axes = document.createElement("span");
        axes.className = "hint";
        axes.textContent = data.axes;
        box.appendChild(axes);
        var cap = document.createElement("span");
        cap.className = "hint";
        cap.textContent = data.caption;
        box.appendChild(cap);
        return box;
    }

    function loadReliability(el) {
        var target = el.dataset.relTarget, horizon = el.dataset.relHorizon;
        if (!target || !horizon) return;
        var url = "/api/predictions/reliability?target=" + encodeURIComponent(target) + "&horizon=" + encodeURIComponent(horizon);
        var ready = reliabilityCache[url] || (reliabilityCache[url] = fetch(url).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }));
        ready.then(function (data) {
            if (data && current === el && !pop.querySelector(".pop-rel")) { pop.appendChild(reliabilityBlock(data)); place(el); }
        });
    }

    function show(el) {
        var content = el.querySelector(".pop-content");
        if (!content) return;
        pop.innerHTML = content.innerHTML;
        pop.hidden = false;
        current = el;
        place(el);
        loadReliability(el);
    }

    function hide() {
        pop.hidden = true;
        current = null;
    }

    document.addEventListener("mouseover", function (e) {
        var t = e.target.closest(".pop-trigger");
        if (t) { if (t !== current) show(t); } else if (current) { hide(); }
    });
    /* Dès que le pointeur quitte la prédiction, la bulle disparaît -- y compris quand il sort de la fenêtre (aucun
       `mouseover` ne part alors : `relatedTarget` est nul) ou qu'il passe sur une case voisine (elle affichera la sienne). */
    document.addEventListener("mouseout", function (e) {
        if (!current || e.target.closest(".pop-trigger") !== current) return;
        if (!e.relatedTarget || !current.contains(e.relatedTarget)) hide();
    });
    document.documentElement.addEventListener("mouseleave", hide);
    window.addEventListener("blur", hide);
    document.addEventListener("focusin", function (e) {
        var t = e.target.closest(".pop-trigger");
        if (t) show(t);
    });
    document.addEventListener("focusout", hide);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") hide(); });
    document.addEventListener("scroll", hide, true);
    document.addEventListener("click", function (e) {
        var t = e.target.closest(".pop-trigger");
        if (t && t !== current) show(t);   // tactile : pas de survol
        else if (!t) hide();
    });
})();
