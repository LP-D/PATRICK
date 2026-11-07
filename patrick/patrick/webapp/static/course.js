/* Lecture d'un cours : le plan à gauche suit la section visible. Sans IntersectionObserver, le plan reste un simple sommaire à liens. */
(function () {
    "use strict";
    var links = Array.prototype.slice.call(document.querySelectorAll("[data-toc]"));
    if (!links.length || !("IntersectionObserver" in window)) return;
    var byId = {};
    links.forEach(function (a) { byId[a.dataset.toc] = a; });
    var headings = links.map(function (a) { return document.getElementById(a.dataset.toc); }).filter(Boolean);
    var current = null;
    function setCurrent(id) {
        if (id === current || !byId[id]) return;
        if (current && byId[current]) byId[current].classList.remove("is-current");
        byId[id].classList.add("is-current");
        current = id;
        var box = byId[id].closest(".kb-toc");
        if (box) {
            var r = byId[id].getBoundingClientRect(), b = box.getBoundingClientRect();
            if (r.top < b.top + 40 || r.bottom > b.bottom - 40) byId[id].scrollIntoView({ block: "center" });
        }
    }
    var visible = new Set();
    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) visible.add(e.target.id); else visible.delete(e.target.id); });
        var first = headings.find(function (h) { return visible.has(h.id); });
        if (first) setCurrent(first.id);
    }, { rootMargin: "-70px 0px -65% 0px", threshold: 0 });
    headings.forEach(function (h) { observer.observe(h); });
    if (window.location.hash && byId[decodeURIComponent(window.location.hash.slice(1))]) setCurrent(decodeURIComponent(window.location.hash.slice(1)));
})();
