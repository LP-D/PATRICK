/* Page /vocabulary : filtre instantané des termes (accents et casse ignorés). */
(function () {
    "use strict";
    var input = document.getElementById("vocab-search");
    if (!input) return;
    var terms = Array.prototype.slice.call(document.querySelectorAll(".vocab-term"));
    var cats = Array.prototype.slice.call(document.querySelectorAll(".vocab-cat"));
    var count = document.getElementById("vocab-count");
    var none = document.getElementById("vocab-none");
    function norm(s) { return String(s || "").toLocaleLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
    terms.forEach(function (el) { el.dataset.norm = norm(el.dataset.search); });
    function apply() {
        var q = norm(input.value.trim());
        var shown = 0;
        terms.forEach(function (el) {
            var hit = !q || el.dataset.norm.indexOf(q) !== -1;
            el.hidden = !hit;
            if (hit) shown += 1;
        });
        cats.forEach(function (c) {
            var any = c.querySelector(".vocab-term:not([hidden])");
            c.hidden = !any;
            var chip = document.querySelector('[data-cat-chip="' + c.dataset.cat + '"]');
            if (chip) chip.hidden = !any;
        });
        if (count) {
            count.textContent = (count.dataset.template || "{n} / {total}")
                .replace("{n}", shown).replace("{total}", count.dataset.total);
        }
        if (none) none.classList.toggle("hidden", shown !== 0);
    }
    input.addEventListener("input", apply);
    apply();
})();
