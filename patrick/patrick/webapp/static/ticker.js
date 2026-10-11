/* Bandeau défilant des plus fortes variations (5 jours), en haut de TOUTES les pages (`base_v2.html`), comme les écrans de cours d'une
   salle de marché. Données : `/api/movers` (calculées côté serveur toutes les 30 min). Le gabarit pose une première copie de la liste ;
   ce script la double pour une boucle sans coupure, règle la vitesse selon la largeur réelle, et ne reconstruit le bandeau que si le
   classement a changé (un rafraîchissement qui le reconstruirait à chaque fois relancerait l'animation depuis le début).

   Un clic sur un symbole : sur /ml, /dl et /rl il AJOUTE la cible à la sélection en cours (on compose un lot depuis le bandeau) ;
   ailleurs le lien ouvre la fiche de la cible. */
(function () {
    "use strict";
    var bar = document.getElementById("market-ticker");
    if (!bar) return;
    var viewport = bar.querySelector(".ticker-viewport");
    var track = document.getElementById("ticker-track");

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; });
    }

    var SPEED_PX_S = 45;            // vitesse de défilement (px par seconde) : lisible, sans fatigue
    var REFRESH_MS = 5 * 60 * 1000;
    var RETRY_MS = 30 * 1000;       // le classement peut ne pas être encore calculé au démarrage du serveur
    var signature = null;

    function itemFor(row, sign) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.className = "ticker-item movers-pick";
        a.href = "/targets/" + encodeURIComponent(row.symbol);
        a.dataset.symbol = row.symbol;
        a.title = row.label || row.symbol;
        var sym = document.createElement("span");
        sym.className = "ticker-sym";
        sym.textContent = row.symbol;
        var pct = document.createElement("span");
        pct.className = "ticker-pct " + (sign > 0 ? "movers-up" : "movers-down");
        var value = Number(row.pct);
        pct.textContent = (sign > 0 ? "▲ +" : "▼ ") + value.toFixed(2) + "%";
        a.append(sym, pct);
        li.appendChild(a);
        return li;
    }

    function groupFor(data, hidden) {
        var ul = document.createElement("ul");
        ul.className = "ticker-group";
        if (hidden) ul.setAttribute("aria-hidden", "true");
        (data.gainers || []).forEach(function (r) { ul.appendChild(itemFor(r, 1)); });
        (data.losers || []).forEach(function (r) { ul.appendChild(itemFor(r, -1)); });
        if (hidden) Array.prototype.forEach.call(ul.querySelectorAll("a"), function (a) { a.tabIndex = -1; });
        return ul;
    }

    // Une seule copie ne remplit pas toujours la largeur de l'écran : on répète jusqu'à la dépasser, sinon la boucle laisserait un vide.
    function fill(data) {
        track.replaceChildren();
        var first = groupFor(data, false);
        track.appendChild(first);
        var guard = 0;
        var base = first.cloneNode(true);
        while (first.scrollWidth < viewport.clientWidth && guard++ < 8) {
            Array.prototype.forEach.call(base.children, function (li) { first.appendChild(li.cloneNode(true)); });
        }
        var second = first.cloneNode(true);
        second.setAttribute("aria-hidden", "true");
        Array.prototype.forEach.call(second.querySelectorAll("a"), function (a) { a.tabIndex = -1; });
        track.appendChild(second);
        var width = first.scrollWidth || 1;
        bar.style.setProperty("--ticker-duration", Math.max(20, Math.round(width / SPEED_PX_S)) + "s");
    }

    function apply(data) {
        var has = (data.gainers && data.gainers.length) || (data.losers && data.losers.length);
        bar.hidden = !has;
        if (!has) return false;
        viewport.title = data.updated_at ? fmtStr(tr("movers_updated_at", "Updated at {time}"), { time: data.updated_at }) : "";
        var next = (data.gainers || []).concat(data.losers || []).map(function (r) { return r.symbol + ":" + r.pct; }).join("|");
        if (next !== signature) {
            signature = next;
            fill(data);
        }
        return true;
    }

    function refresh() {
        fetch("/api/movers").then(function (r) { return r.json(); }).then(function (data) {
            setTimeout(refresh, apply(data) ? REFRESH_MS : RETRY_MS);
        }).catch(function () { setTimeout(refresh, RETRY_MS); });
    }

    // Clic : sur une page de lancement, ajouter la cible à la sélection (additif, jamais un remplacement) ; sinon le lien fait son travail.
    bar.addEventListener("click", function (ev) {
        var link = ev.target.closest ? ev.target.closest(".ticker-item") : null;
        if (!link) return;
        var select = document.getElementById("target_symbols") || document.getElementById("rl-targets");
        if (!select) return;
        var symbol = link.dataset.symbol;
        var option = Array.prototype.find.call(select.options, function (o) { return o.value === symbol; });
        if (!option || option.disabled) return;
        ev.preventDefault();
        option.selected = true;
        // `change` : recharge l'aperçu de marché, le récapitulatif et l'aperçu du nom ; poser `.selected` seul ne prévient personne.
        select.dispatchEvent(new Event("change", { bubbles: true }));
        select.focus({ preventScroll: false });
    });

    // Le gabarit pose déjà une copie de la liste (premier affichage sans attente) ; l'API la remplace par la version en boucle.
    refresh();
})();
