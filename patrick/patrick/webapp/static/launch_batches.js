/* Lots prêts à lancer des pages Modèles (/ml, /dl, /rl) : les cartes arrivent par `lazy.js` (`/fragments/launch-batches`), le clic est
   délégué ici. Les cartes par classe d'actifs et « Horizons jamais lancés » pré-remplissent la sélection du formulaire (rien n'est lancé
   avant « Lancer ») ; « Runs conseillés » analyse à la demande, demande confirmation puis met en file. */
(function () {
    "use strict";
    var root = document.getElementById("batch-gallery");
    if (!root) return;
    var I18N = window.I18N || {};
    var status = document.getElementById("batch-status");
    var form = document.getElementById("run-form") || document.getElementById("rl-form");
    var onlyMissing = false;       // « horizons jamais lancés » : le serveur ne crée que les couples cible × horizon sans run

    function fmt(text, vars) {
        return String(text).replace(/\{(\w+)\}/g, function (_, k) { return vars[k] !== undefined ? vars[k] : "{" + k + "}"; });
    }
    function withLang(url) {
        var lang = new URLSearchParams(window.location.search).get("lang");
        return lang ? url + (url.indexOf("?") === -1 ? "?" : "&") + "lang=" + encodeURIComponent(lang) : url;
    }
    function say(text, kind) {
        status.textContent = text || "";
        status.hidden = !text;
        status.classList.toggle("banner-error", kind === "error");
    }
    function targetSelect() { return document.getElementById("target_symbols") || document.getElementById("rl-targets"); }
    function announce(select) { select.dispatchEvent(new Event("change", { bubbles: true })); }   // non fiable : `onlyMissing` reste

    function pick(select, wanted) {
        var n = 0;
        Array.prototype.forEach.call(select.options, function (opt) {
            opt.selected = !opt.disabled && wanted.has(opt.value);      // une cible grisée (historique trop court) n'est jamais cochée
            if (opt.selected) n += 1;
        });
        return n;
    }
    function reveal(select) { select.scrollIntoView({ behavior: "smooth", block: "center" }); }

    // Objectif que la carte prépare (`data-task` : direction ou valeur exacte, ADR 0032) : le formulaire bascule, et `app.js` affiche ou
    // masque le critère de la valeur exacte sur cet évènement. Renvoie le texte à ajouter au message quand l'objectif a changé.
    function applyTask(button) {
        var wanted = button.dataset.task, task = document.getElementById("task");
        if (!wanted || !task || task.value === wanted) return "";
        task.value = wanted;
        announce(task);
        return " " + (wanted === "value" ? I18N.batch_js_task_value : I18N.batch_js_task_direction);
    }

    function selectClass(button) {
        var select = targetSelect();
        if (!select) return;
        var n = pick(select, new Set(JSON.parse(button.dataset.symbols)));
        onlyMissing = false;
        var switched = applyTask(button);
        announce(select);
        say((n ? fmt(I18N.batch_js_selected, { n: n }) : I18N.batch_js_none) + switched);
        if (n) reveal(select);
    }

    function selectMissing(button) {
        var select = targetSelect(), horizons = document.getElementById("horizons");
        if (!select || !horizons) return;
        var switched = applyTask(button);
        var gaps = JSON.parse(button.dataset.gaps);
        var wantedHorizons = new Set();
        var n = pick(select, new Set(Object.keys(gaps)));
        Object.keys(gaps).forEach(function (symbol) { gaps[symbol].forEach(function (h) { wantedHorizons.add(String(h)); }); });
        Array.prototype.forEach.call(horizons.options, function (opt) { opt.selected = !opt.disabled && wantedHorizons.has(opt.value); });
        onlyMissing = n > 0;
        announce(select);
        announce(horizons);
        var list = Array.from(wantedHorizons).sort(function (a, b) { return a - b; }).join(", ");
        say((n ? fmt(I18N.batch_js_selected_missing, { n: n, h: list }) : I18N.batch_js_none) + switched);
        if (n) reveal(select);
    }

    // L'analyse de toutes les cibles dure plusieurs minutes : sans avancement affiché, le clic semblait ne rien faire.
    function watchProgress() {
        return setInterval(async function () {
            try {
                var res = await fetch("/api/launch-batches/recommended/progress", { credentials: "same-origin", cache: "no-store" });
                var p = await res.json();
                if (p.running && p.total) say(fmt(I18N.batch_js_progress, { done: p.done, total: p.total }));
            } catch (err) { /* le suivi n'est qu'un confort */ }
        }, 1500);
    }

    async function recommended(button) {
        button.disabled = true;
        say(I18N.batch_js_analysing);
        status.scrollIntoView({ behavior: "smooth", block: "nearest" });
        var timer = watchProgress();
        try {
            var res = await fetch(withLang("/api/launch-batches/recommended"), { credentials: "same-origin" });
            var plan = await res.json();
            clearInterval(timer);
            if (!res.ok) throw new Error((plan.errors || [res.status]).join(" · "));
            if (!plan.n) { say(I18N.batch_js_rec_none); return; }
            var yes = await window.patrickDialog.confirm(
                fmt(I18N.batch_js_rec_confirm, { n: plan.n, costs: plan.costs, lines: plan.lines }), fmt(I18N.batch_js_rec_launch, { n: plan.n }));
            if (!yes) { say(""); return; }
            say(fmt(I18N.batch_js_rec_queueing, { n: plan.n }));          // reconstruire chaque configuration prend environ une minute
            var post = await fetch("/api/launch-batches/recommended", {
                method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ items: plan.items.map(function (i) { return { run_id: i.run_id, key: i.key }; }) }),
            });
            var out = await post.json();
            if (!post.ok) throw new Error((out.errors || [post.status]).join(" · "));
            say(fmt(I18N.batch_js_rec_done, { n: out.runs.length }));
            if (window.PatrickMachine) window.PatrickMachine.refresh();
        } catch (err) {
            say(fmt(I18N.batch_js_error, { msg: err.message }), "error");
        } finally {
            clearInterval(timer);
            button.disabled = false;
        }
    }

    root.addEventListener("click", function (ev) {
        var button = ev.target.closest("[data-batch]");
        if (!button || button.disabled) return;
        if (button.dataset.batch === "class") selectClass(button);
        else if (button.dataset.batch === "missing") selectMissing(button);
        else if (button.dataset.batch === "recommended") recommended(button);
    });

    // Un choix fait à la main annule le lot « horizons jamais lancés » : sans cela, le serveur sauterait en silence des couples voulus.
    // Changer l'objectif à la main aussi : les couples manquants de la direction ne sont pas ceux de la valeur exacte.
    ["target_symbols", "horizons", "task"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener("change", function (ev) { if (ev.isTrusted && onlyMissing) { onlyMissing = false; say(""); } });
    });
    if (form) form.addEventListener("formdata", function (ev) { if (onlyMissing) ev.formData.set("only_missing", "1"); });
})();
