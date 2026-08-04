/* PATRICK — le boîtier de la station : bascule de thème + bande
   d'enregistrement. Chargé par `base.html` sur TOUTES les pages ; ne dépend
   d'aucun autre script et ne suppose la présence d'aucun élément.

   La bande est la signature du monde visuel « Station d'observation » : un
   héliocorder trace en continu, donc la station montre son activité avant
   qu'on lui demande quoi que ce soit. Une marque = un run.

   Ce qu'elle refuse de faire, et qui n'est pas un oubli :
   - Elle ne trace pas de courbe lissée entre les runs : les runs sont des
     événements ponctuels, pas une série continue, et les relier inventerait
     une continuité que les données n'ont pas.
   - Elle n'invente pas de hauteur pour un run sans compte d'essais : la
     marque tombe alors à la hauteur plancher et le run est compté dans
     « n essais inconnu » de la légende, jamais fondu dans le reste.
   - La légende porte toujours le plafond de l'échelle et l'étendue
     temporelle : une hauteur sans son maximum n'est pas une mesure. */
(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) {
            return params[k] !== undefined ? params[k] : m;
        });
    }

    // Lecture des jetons sans repli codé en dur : un repli survit à un
    // remplacement d'identité et repeint silencieusement l'ancien monde.
    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    /* ---------------------------------------------------------------------
       Bascule de thème. Le choix explicite est mémorisé et gagne toujours sur
       la préférence système ; sans choix, on suit le système ET on continue à
       le suivre s'il change en cours de session (une pièce qui s'assombrit ne
       doit pas laisser l'écran en clair).
       --------------------------------------------------------------------- */
    var toggle = document.getElementById("theme-toggle");
    var mq = window.matchMedia("(prefers-color-scheme: dark)");

    function isDark() { return document.documentElement.dataset.theme === "dark"; }

    function syncToggleLabel() {
        if (!toggle) return;
        // Le bouton nomme l'état COURANT (pas l'action) : c'est un indicateur
        // avec pastille, pas un verbe. `aria-pressed` porte la bascule.
        var dark = isDark();
        toggle.textContent = dark ? (toggle.dataset.labelDark || "Nuit")
                                  : (toggle.dataset.labelLight || "Jour");
        toggle.setAttribute("aria-pressed", dark ? "true" : "false");
    }

    function applyTheme(dark, persist) {
        if (dark) document.documentElement.dataset.theme = "dark";
        else delete document.documentElement.dataset.theme;
        if (persist) {
            try { localStorage.setItem("patrick-theme", dark ? "dark" : "light"); }
            catch (e) { /* stockage refusé : le thème vaut pour la session */ }
        }
        syncToggleLabel();
        // Les toiles lisent les jetons au tracé : après une bascule il faut
        // les redessiner, sinon l'ancien thème reste peint dessus.
        window.dispatchEvent(new CustomEvent("patrick:theme"));
    }

    if (toggle) {
        syncToggleLabel();
        toggle.addEventListener("click", function () { applyTheme(!isDark(), true); });
    }
    if (mq.addEventListener) {
        mq.addEventListener("change", function (ev) {
            var saved = null;
            try { saved = localStorage.getItem("patrick-theme"); } catch (e) { /* ignoré */ }
            if (!saved) applyTheme(ev.matches, false);
        });
    }

    /* ---------------------------------------------------------------------
       La bande d'enregistrement.
       --------------------------------------------------------------------- */
    var canvas = document.getElementById("record-canvas");
    var caption = document.getElementById("record-caption");
    var tooltip = document.getElementById("record-tooltip");
    if (!canvas) return;

    var PAD_X = 12;      // marge horizontale du tracé
    var BASE_Y = 20;     // ligne de base : au-dessus de la bande d'étiquettes
    var FLOOR_H = 6;     // hauteur plancher : un run existe même sans essais
    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var marks = [];      // [{x, h, color, run}]
    var state = { runs: [], available: true, loaded: false };
    var reveal = reduceMotion ? 1 : 0;

    function parseTime(s) {
        if (!s) return null;
        // SQLite écrit « YYYY-MM-DD HH:MM:SS » en UTC (datetime('now')) :
        // sans le marqueur explicite, Safari le refuse et Chrome le lit en
        // heure locale -- deux décalages différents pour la même bande.
        var iso = String(s).trim().replace(" ", "T");
        if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)) iso += "Z";
        var t = Date.parse(iso);
        return isNaN(t) ? null : t;
    }

    function fmtDate(ms) {
        var d = new Date(ms);
        return d.toLocaleDateString(document.documentElement.lang || "fr",
            { day: "2-digit", month: "short" });
    }
    function fmtDateTime(ms) {
        var d = new Date(ms);
        return d.toLocaleString(document.documentElement.lang || "fr",
            { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    }

    function colorFor(status) {
        if (status === "done") return token("--ok-ink");
        if (status === "running" || status === "queued") return token("--accent-ink");
        if (status === "failed" || status === "error") return token("--error-ink");
        return token("--ink-text-2");
    }

    function layout() {
        var cssW = canvas.clientWidth || 600;
        var cssH = canvas.clientHeight || 54;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = Math.round(cssW * dpr);
        canvas.height = Math.round(cssH * dpr);
        var ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return { ctx: ctx, w: cssW, h: cssH };
    }

    /* LA COORDONNÉE EST LA SÉQUENCE, PLUS LE TEMPS ÉCOULÉ.

       C'est la coupe de cette passe, et elle est structurelle. Un axe de temps
       absolu était le choix intuitif — une station enregistre dans le temps —
       mais il dépensait toute la largeur en durée plutôt qu'en runs. Mesuré
       sur la bande réelle : 18 runs concentrés sur ~90 secondes, étalés sur
       une échelle de 6 jours, soit deux amas dans 3 % de la surface et 97 %
       d'encre vide. Le survol ne répondait que sur 12px de 1392, et neuf runs
       superposés se résumaient à une seule infobulle.

       Une colonne par run supprime le problème au lieu de le compenser :
       aucune superposition à regrouper, une cible de survol qui vaut la
       largeur d'une colonne, et une lecture qui répond à la question qu'on se
       pose vraiment en arrivant — qu'est-ce qui a tourné, dans quel état, avec
       quel effort.

       Ce que la coupe abandonne, et c'est assumé : l'axe daté et la lecture du
       SILENCE (« rien depuis quatre jours »). L'information n'est pas perdue,
       elle change de porteur — l'étendue va dans la légende, l'horodatage
       exact dans l'infobulle, là où ils coûtent zéro pixel de tracé. */
    var MAX_MARKS = 40;

    function computeMarks(w, h) {
        marks = [];
        var all = state.runs;
        if (!all.length) return null;

        /* Au-delà de 40 colonnes, chaque run vaut moins de 3px et la bande
           redevient un aplat. On garde les plus récents — ce sont eux qu'on
           vient voir — et la légende dit combien sont hors champ. */
        var runs = all.slice(0, MAX_MARKS);
        var hidden = all.length - runs.length;

        var times = [];
        for (var i = 0; i < all.length; i++) {
            var t = parseTime(all[i].started_at);
            if (t !== null) times.push(t);
        }

        var maxTrials = 0;
        for (i = 0; i < runs.length; i++) {
            if (typeof runs[i].n_trials === "number") maxTrials = Math.max(maxTrials, runs[i].n_trials);
        }
        var span = h - BASE_Y - 6;
        var logMax = Math.log1p(maxTrials);

        var inner = w - 2 * PAD_X;
        var slot = inner / runs.length;
        // Barre lisible sans devenir un pavé : bornée des deux côtés.
        var barW = Math.max(3, Math.min(10, slot - 3));

        // Le plus ANCIEN à gauche, le plus récent à droite : `list_runs` rend
        // les plus récents d'abord, on inverse.
        for (i = 0; i < runs.length; i++) {
            var run = runs[runs.length - 1 - i];
            var hh = FLOOR_H;
            if (typeof run.n_trials === "number" && run.n_trials > 0 && logMax > 0) {
                hh = FLOOR_H + (Math.log1p(run.n_trials) / logMax) * (span - FLOOR_H);
            }
            marks.push({
                x: PAD_X + slot * (i + 0.5),
                slot: slot,
                barW: barW,
                h: hh,
                color: colorFor(run.status),
                run: run,
                t: parseTime(run.started_at),
            });
        }
        return {
            tMin: times.length ? Math.min.apply(null, times) : null,
            tMax: times.length ? Math.max.apply(null, times) : null,
            maxTrials: maxTrials,
            hidden: hidden,
            total: all.length,
        };
    }

    var scale = null;

    function draw(hoverIdx) {
        var g = layout();
        var ctx = g.ctx, w = g.w, h = g.h;
        ctx.clearRect(0, 0, w, h);

        var baseY = h - BASE_Y;
        var muted = token("--ink-text-2");

        // Ligne de base : le papier de l'enregistreur. Seul repère qui reste —
        // la grille datée est partie avec l'axe de temps.
        ctx.strokeStyle = muted;
        ctx.globalAlpha = 0.3;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(PAD_X, baseY + 0.5);
        ctx.lineTo(w - PAD_X, baseY + 0.5);
        ctx.stroke();
        ctx.globalAlpha = 1;

        if (!marks.length) return;

        // Révélation gauche->droite : le mouvement natif d'un enregistreur.
        var cutoff = PAD_X + reveal * (w - 2 * PAD_X);
        for (var i = 0; i < marks.length; i++) {
            var m = marks[i];
            if (m.x > cutoff) continue;
            var active = (i === hoverIdx);

            // Colonne de sélection : la cible vaut toute la largeur du créneau,
            // pas les quelques pixels de la barre.
            if (active) {
                ctx.fillStyle = token("--accent-ink");
                ctx.globalAlpha = 0.14;
                ctx.fillRect(m.x - m.slot / 2, 4, m.slot, baseY - 4);
                ctx.globalAlpha = 1;
            }

            ctx.fillStyle = m.color;
            ctx.globalAlpha = active ? 1 : 0.9;
            var bw = active ? m.barW + 2 : m.barW;
            ctx.fillRect(Math.round(m.x - bw / 2), Math.round(baseY - m.h), Math.round(bw), Math.round(m.h));
        }
        ctx.globalAlpha = 1;
    }

    function writeCaption() {
        if (!caption) return;
        if (!state.available) {
            caption.textContent = tr("record_unavailable",
                "Bande illisible : la base de suivi n'a pas pu être ouverte.");
            return;
        }
        if (!state.runs.length) {
            caption.textContent = tr("record_empty",
                "Aucun run enregistré — la bande se remplira au premier run lancé.");
            return;
        }
        var counts = { done: 0, running: 0, failed: 0, other: 0, unknown_trials: 0 };
        for (var i = 0; i < state.runs.length; i++) {
            var s = state.runs[i].status;
            if (s === "done") counts.done++;
            else if (s === "running" || s === "queued") counts.running++;
            else if (s === "failed" || s === "error") counts.failed++;
            else counts.other++;
            if (typeof state.runs[i].n_trials !== "number") counts.unknown_trials++;
        }
        // Une hauteur sans son plafond n'est pas une mesure : l'échelle est
        // écrite, et les runs sans compte d'essais sont dits, pas fondus.
        var parts = [
            "<b>" + (scale ? scale.total : marks.length) + "</b> " + tr("record_runs", "runs")
                + (scale && scale.hidden
                    ? " " + fmtStr(tr("record_hidden", "({n} hors champ)"), { n: scale.hidden })
                    : ""),
            // L'étendue a quitté le tracé : c'est ici qu'elle vit désormais.
            // « du 28 juil. au 28 juil. » se lit comme un bug : quand tout
            // tient dans une journée, la journée suffit.
            scale && scale.tMin !== null
                ? (fmtDate(scale.tMin) === fmtDate(scale.tMax)
                    ? fmtStr(tr("record_span_day", "le {d}"), { d: fmtDate(scale.tMin) })
                    : fmtStr(tr("record_span_range", "du {from} au {to}"),
                        { from: fmtDate(scale.tMin), to: fmtDate(scale.tMax) }))
                : "",
            fmtStr(tr("record_scale", "hauteur = essais (log, max {max})"),
                { max: scale ? scale.maxTrials : 0 }),
            fmtStr(tr("record_counts", "{done} terminés · {running} en cours · {failed} échoués"),
                counts),
        ];
        if (counts.unknown_trials) {
            parts.push(fmtStr(tr("record_unknown", "{n} sans compte d'essais (hauteur plancher)"),
                { n: counts.unknown_trials }));
        }
        caption.innerHTML = parts.join(" · ");
    }

    function rebuild() {
        var g = layout();
        scale = computeMarks(g.w, g.h);
        canvas.dataset.state = marks.length ? "drawn" : "empty";
        if (marks.length) canvas.setAttribute("tabindex", "0");
        else canvas.removeAttribute("tabindex");
        draw(-1);
        writeCaption();
    }

    function animateIn() {
        if (reduceMotion) { reveal = 1; draw(-1); return; }
        var start = null;
        var DUR = 620;
        function step(ts) {
            if (start === null) start = ts;
            var p = Math.min(1, (ts - start) / DUR);
            reveal = 1 - Math.pow(1 - p, 3);   // sortie exponentielle
            draw(-1);
            if (p < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    }

    // Un doigt ne vise pas au pixel : la tolérance de sélection s'ouvre quand
    // le pointeur est grossier. Mesuré sur la bande réelle, les marques
    // peuvent être distantes de 2px — sans cette ouverture, viser au doigt
    // revient à ne jamais rien sélectionner.
    var coarse = window.matchMedia("(pointer: coarse)").matches;

    /* La sélection se fait au CRÉNEAU, plus à la tolérance en pixels : avec une
       colonne par run, la cible vaut toute la largeur du créneau. La tolérance
       de 9px (18 au doigt) qui rendait la bande quasi impointable n'a plus de
       raison d'être. */
    function nearest(mx) {
        if (!marks.length) return -1;
        var i = Math.floor((mx - PAD_X) / marks[0].slot);
        return (i >= 0 && i < marks.length) ? i : -1;
    }

    // Détail d'une marque, factorisé : le survol et la tape doivent afficher
    // exactement la même chose, sinon l'un des deux chemins ment.
    function showTooltip(idx) {
        if (!tooltip || idx < 0) return;
        var m = marks[idx];
        var trials = typeof m.run.n_trials === "number"
            ? m.run.n_trials + " " + tr("record_trials", "essais")
            : tr("record_no_trials", "essais inconnus");
        var line2 = fmtDateTime(m.t) + " · " + trials + " · " + m.run.status;
        // Au doigt, la tape sélectionne : il faut dire ce que fait la suivante,
        // sinon on ouvre un run qu'on n'a jamais pu lire.
        if (coarse) line2 += " — " + tr("record_tap_again", "touche à nouveau pour ouvrir");
        tooltip.innerHTML = "<b></b><br><span></span>";
        tooltip.firstChild.textContent = m.run.name + " — " + m.run.target;
        tooltip.lastChild.textContent = line2;
        tooltip.classList.remove("hidden");
        var box = canvas.getBoundingClientRect();
        var host = canvas.parentElement.getBoundingClientRect();
        tooltip.style.left = Math.max(4, Math.min(m.x + (box.left - host.left) + 10,
            host.width - tooltip.offsetWidth - 4)) + "px";
        // L'infobulle flotte SUR la plaque, jamais sous elle : posée en dessous
        // elle recouvrait la légende chiffrée -- on masquait l'échelle de la
        // bande au moment précis où l'on interroge une de ses marques.
        tooltip.style.top = (box.top - host.top + 4) + "px";
    }

    canvas.addEventListener("mousemove", function (ev) {
        if (!marks.length || coarse) return;
        var rect = canvas.getBoundingClientRect();
        var idx = nearest(ev.clientX - rect.left);
        draw(idx);
        if (idx < 0) { if (tooltip) tooltip.classList.add("hidden"); return; }
        showTooltip(idx);
    });
    canvas.addEventListener("mouseleave", function () {
        if (coarse) return;
        if (tooltip) tooltip.classList.add("hidden");
        draw(-1);
    });

    /* La bande était pilotée au SURVOL pour lire, au CLIC pour ouvrir. Au
       doigt, le survol n'existe pas : une tape ouvrait donc un run qu'on
       n'avait jamais pu identifier. Sur pointeur grossier, la première tape
       révèle la marque, la seconde ouvre — et l'infobulle le dit. */
    var tapped = -1;
    canvas.addEventListener("click", function (ev) {
        if (!marks.length) return;
        var rect = canvas.getBoundingClientRect();
        var idx = nearest(ev.clientX - rect.left);
        if (idx < 0) {
            tapped = -1;
            if (tooltip) tooltip.classList.add("hidden");
            draw(-1);
            return;
        }
        if (coarse && tapped !== idx) {
            tapped = idx;
            draw(idx);
            showTooltip(idx);
            return;
        }
        window.location.href = "/runs/" + encodeURIComponent(marks[idx].run.run_id);
    });

    /* La bande était un `role="img"` inerte : 18 runs valaient un mot pour un
       lecteur d'écran, et aucune marque n'était atteignable au clavier. Elle
       devient un contrôle — flèches pour parcourir, Entrée pour ouvrir — et
       l'infobulle est annoncée. C'est la contrepartie de la coupe : puisque
       chaque run a maintenant sa colonne, il peut avoir son arrêt. */
    var kbIndex = -1;

    function selectMark(i, announce) {
        if (!marks.length) return;
        kbIndex = Math.max(0, Math.min(marks.length - 1, i));
        draw(kbIndex);
        showTooltip(kbIndex);
        if (announce && tooltip) tooltip.setAttribute("aria-live", "polite");
    }

    canvas.addEventListener("focus", function () {
        if (marks.length && kbIndex < 0) selectMark(marks.length - 1, true);
    });
    canvas.addEventListener("blur", function () {
        kbIndex = -1;
        if (tooltip) tooltip.classList.add("hidden");
        draw(-1);
    });
    canvas.addEventListener("keydown", function (ev) {
        if (!marks.length) return;
        var handled = true;
        if (ev.key === "ArrowRight") selectMark(kbIndex < 0 ? 0 : kbIndex + 1, true);
        else if (ev.key === "ArrowLeft") selectMark(kbIndex < 0 ? marks.length - 1 : kbIndex - 1, true);
        else if (ev.key === "Home") selectMark(0, true);
        else if (ev.key === "End") selectMark(marks.length - 1, true);
        else if ((ev.key === "Enter" || ev.key === " ") && kbIndex >= 0) {
            window.location.href = "/runs/" + encodeURIComponent(marks[kbIndex].run.run_id);
        } else if (ev.key === "Escape") {
            kbIndex = -1;
            if (tooltip) tooltip.classList.add("hidden");
            draw(-1);
        } else handled = false;
        if (handled) ev.preventDefault();
    });

    window.addEventListener("resize", function () { if (state.loaded) rebuild(); });
    window.addEventListener("patrick:theme", function () { if (state.loaded) rebuild(); });

    fetch("/api/activity")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            state.runs = data.runs || [];
            state.available = data.available !== false;
            state.loaded = true;
            rebuild();
            if (marks.length) animateIn();
        })
        .catch(function () {
            state.available = false;
            state.loaded = true;
            rebuild();
        });
})();
