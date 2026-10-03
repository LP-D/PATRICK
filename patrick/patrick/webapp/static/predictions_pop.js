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
        if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
        pop.style.left = left + "px";
        pop.style.top = top + "px";
    }

    function show(el) {
        var content = el.querySelector(".pop-content");
        if (!content) return;
        pop.innerHTML = content.innerHTML;
        pop.hidden = false;
        current = el;
        place(el);
    }

    function hide() {
        pop.hidden = true;
        current = null;
    }

    document.addEventListener("mouseover", function (e) {
        var t = e.target.closest(".pop-trigger");
        if (t) { if (t !== current) show(t); } else if (current) { hide(); }
    });
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
