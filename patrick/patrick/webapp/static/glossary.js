(function () {
    "use strict";

    var dataEl = document.getElementById("glossary-data");
    var GLOSSARY = {};
    if (dataEl) {
        try { GLOSSARY = JSON.parse(dataEl.textContent || "{}"); } catch (e) { GLOSSARY = {}; }
    }

    var popover = document.getElementById("glossary-popover");
    var titleEl = document.getElementById("glossary-popover-title");
    var bodyEl = document.getElementById("glossary-popover-body");
    var closeBtn = document.getElementById("glossary-popover-close");
    if (!popover || !titleEl || !bodyEl) return;

    function hide() {
        popover.classList.add("hidden");
    }

    function showFor(anchorEl, term) {
        var text = GLOSSARY[term];
        if (!text) return;
        titleEl.textContent = anchorEl.getAttribute("data-term-label") || term;
        bodyEl.textContent = text;
        popover.classList.remove("hidden");

        var rect = anchorEl.getBoundingClientRect();
        var top = window.scrollY + rect.bottom + 6;
        var left = window.scrollX + rect.left;
        var maxLeft = window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - 12;
        if (left > maxLeft) left = Math.max(12, maxLeft);
        popover.style.top = top + "px";
        popover.style.left = left + "px";
    }

    document.addEventListener("click", function (ev) {
        var icon = ev.target.closest ? ev.target.closest(".info-icon") : null;
        if (icon) {
            ev.preventDefault();
            var term = icon.getAttribute("data-term");
            var alreadyOpenForThis = !popover.classList.contains("hidden") && popover.dataset.openTerm === term;
            if (alreadyOpenForThis) {
                hide();
                popover.dataset.openTerm = "";
            } else {
                showFor(icon, term);
                popover.dataset.openTerm = term;
            }
            return;
        }
        if (popover.contains(ev.target)) return;
        hide();
    });

    document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") hide();
    });

    if (closeBtn) closeBtn.addEventListener("click", hide);
    window.addEventListener("resize", hide);
    window.addEventListener("scroll", hide, true);
})();
