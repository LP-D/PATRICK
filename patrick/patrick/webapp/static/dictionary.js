/* Dictionnaire du quant : filtre instantané (texte, niveau, thème), index alphabétique, état dans l'adresse (?q=&theme=&niveau=), ancres #term-… toujours visibles.
   Accents et casse ignorés ; plusieurs mots = tous doivent apparaître. Tout le contenu est déjà dans la page : aucun appel serveur. */
(function () {
    "use strict";
    var input = document.getElementById("kb-search");
    if (!input) return;
    var terms = Array.prototype.slice.call(document.querySelectorAll(".kb-term"));
    var sections = Array.prototype.slice.call(document.querySelectorAll(".kb-letter"));
    var letterLinks = Array.prototype.slice.call(document.querySelectorAll("[data-letter-link]"));
    var levelButtons = Array.prototype.slice.call(document.querySelectorAll(".kb-chip[data-level]"));
    var theme = document.getElementById("kb-theme");
    var reset = document.getElementById("kb-reset");
    var count = document.getElementById("kb-count");
    var none = document.getElementById("kb-none");
    var state = { q: "", theme: "", level: "" };

    function norm(s) { return String(s || "").toLocaleLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
    terms.forEach(function (el) { el._n = norm(el.textContent + " " + (el.dataset.alias || "") + " " + (el.dataset.other || "")); });

    function readUrl() {
        var p = new URLSearchParams(window.location.search);
        state.q = p.get("q") || "";
        state.theme = p.get("theme") || "";
        state.level = p.get("niveau") || "";
        input.value = state.q;
        if (theme) theme.value = state.theme;
    }
    function writeUrl() {
        var p = new URLSearchParams();
        if (state.q) p.set("q", state.q);
        if (state.theme) p.set("theme", state.theme);
        if (state.level) p.set("niveau", state.level);
        var qs = p.toString();
        window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : "") + window.location.hash);
    }

    function apply() {
        var tokens = norm(state.q).split(/\s+/).filter(Boolean);
        var shown = 0;
        terms.forEach(function (el) {
            var ok = (!state.theme || el.dataset.theme === state.theme) && (!state.level || el.dataset.level === state.level) &&
                tokens.every(function (t) { return el._n.indexOf(t) !== -1; });
            el.hidden = !ok;
            if (ok) shown += 1;
        });
        var live = {};
        sections.forEach(function (sec) {
            var any = !!sec.querySelector(".kb-term:not([hidden])");
            sec.hidden = !any;
            live[sec.dataset.letter] = any;
        });
        letterLinks.forEach(function (a) { a.hidden = !live[a.dataset.letterLink]; });
        levelButtons.forEach(function (b) { b.classList.toggle("is-active", b.dataset.level === state.level); });
        if (count) count.textContent = (count.dataset.template || "{n} / {total}").replace("{n}", shown).replace("{total}", count.dataset.total);
        if (none) none.classList.toggle("hidden", shown !== 0);
        writeUrl();
    }

    function revealHash() {
        var id = window.location.hash;
        if (id.indexOf("#term-") !== 0) return;
        var el = document.getElementById(decodeURIComponent(id.slice(1)));
        if (!el) return;
        if (el.hidden) { state = { q: "", theme: "", level: "" }; input.value = ""; if (theme) theme.value = ""; apply(); }
        el.scrollIntoView({ block: "start" });
    }

    input.addEventListener("input", function () { state.q = input.value.trim(); apply(); });
    if (theme) theme.addEventListener("change", function () { state.theme = theme.value; apply(); });
    levelButtons.forEach(function (b) { b.addEventListener("click", function () { state.level = b.dataset.level; apply(); }); });
    if (reset) reset.addEventListener("click", function () { state = { q: "", theme: "", level: "" }; input.value = ""; if (theme) theme.value = ""; apply(); input.focus(); });
    window.addEventListener("hashchange", revealHash);

    readUrl();
    apply();
    revealHash();
})();
