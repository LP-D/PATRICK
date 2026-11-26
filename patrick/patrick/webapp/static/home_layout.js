/* VI26 (26/11) : synthèse personnalisable. « Personnaliser » montre, sur chaque bloc de la Synthèse, des boutons Monter / Descendre /
   Masquer (au clavier comme à la souris : pas de glisser-déposer obligatoire) ; l'ordre et les blocs masqués sont gardés dans ce navigateur
   (localStorage), « Réinitialiser » revient à l'ordre d'origine. Un bloc masqué reste visible, grisé, en mode Personnaliser. */
(function () {
    "use strict";
    var KEY = "patrick-home-layout";
    var root = document.getElementById("home-layout");
    var toggle = document.getElementById("home-customize");
    var reset = document.getElementById("home-reset");
    if (!root || !toggle) return;
    function blocks() { return Array.prototype.slice.call(root.querySelectorAll(":scope > [data-home-block]")); }
    function load() {
        try { return JSON.parse(window.localStorage.getItem(KEY) || "null") || {}; } catch (e) { return {}; }
    }
    function save() {
        var state = { order: blocks().map(function (b) { return b.getAttribute("data-home-block"); }),
                      hidden: blocks().filter(function (b) { return b.classList.contains("home-hidden"); }).map(function (b) { return b.getAttribute("data-home-block"); }) };
        try { window.localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* stockage bloqué : la page reste utilisable */ }
    }
    function apply(state) {
        (state.order || []).forEach(function (key) {
            var b = root.querySelector(':scope > [data-home-block="' + key + '"]');
            if (b) root.appendChild(b);
        });
        blocks().forEach(function (b) { b.classList.toggle("home-hidden", (state.hidden || []).indexOf(b.getAttribute("data-home-block")) >= 0); });
    }
    function controls(b) {
        var bar = document.createElement("div");
        bar.className = "home-block-tools";
        var name = document.createElement("span");
        name.className = "home-block-name";
        name.textContent = b.getAttribute("data-home-label") || "";
        bar.appendChild(name);
        [["up", root.getAttribute("data-label-up")], ["down", root.getAttribute("data-label-down")], ["hide", ""]].forEach(function (spec) {
            var btn = document.createElement("button");
            btn.type = "button"; btn.className = "btn-ghost"; btn.setAttribute("data-act", spec[0]);
            btn.textContent = spec[0] === "hide"
                ? (b.classList.contains("home-hidden") ? root.getAttribute("data-label-show") : root.getAttribute("data-label-hide")) : spec[1];
            btn.addEventListener("click", function () {
                if (spec[0] === "up" && b.previousElementSibling) root.insertBefore(b, b.previousElementSibling);
                if (spec[0] === "down" && b.nextElementSibling) root.insertBefore(b.nextElementSibling, b);
                if (spec[0] === "hide") {
                    b.classList.toggle("home-hidden");
                    btn.textContent = b.classList.contains("home-hidden") ? root.getAttribute("data-label-show") : root.getAttribute("data-label-hide");
                }
                save();
                btn.focus();
            });
            bar.appendChild(btn);
        });
        return bar;
    }
    function edit(on) {
        root.classList.toggle("home-editing", on);
        toggle.setAttribute("aria-pressed", on ? "true" : "false");
        if (reset) reset.classList.toggle("hidden", !on);
        blocks().forEach(function (b) {
            var tools = b.querySelector(":scope > .home-block-tools");
            if (on && !tools) b.insertBefore(controls(b), b.firstChild);
            if (!on && tools) tools.remove();
        });
    }
    apply(load());
    toggle.addEventListener("click", function () { edit(!root.classList.contains("home-editing")); });
    if (reset) reset.addEventListener("click", function () {
        try { window.localStorage.removeItem(KEY); } catch (e) { /* rien */ }
        window.location.reload();
    });
})();
