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

    function computeMarks(w, h) {
        marks = [];
        var runs = state.runs;
        if (!runs.length) return null;

        var times = [];
        for (var i = 0; i < runs.length; i++) {
            var t = parseTime(runs[i].started_at);
            if (t !== null) times.push(t);
        }
        if (!times.length) return null;

        var now = Date.now();
        var tMin = Math.min.apply(null, times);
        var tMax = Math.max(now, Math.max.apply(null, times));
        // Une bande d'une seule journée n'a pas d'étendue : on lui en donne
        // une (12h) plutôt que de diviser par zéro.
        if (tMax - tMin < 432e5) tMin = tMax - 432e5;

        var maxTrials = 0;
        for (i = 0; i < runs.length; i++) {
            if (typeof runs[i].n_trials === "number") maxTrials = Math.max(maxTrials, runs[i].n_trials);
        }
        var span = h - BASE_Y - 6;
        var logMax = Math.log1p(maxTrials);

        for (i = 0; i < runs.length; i++) {
            var run = runs[i];
            var ts = parseTime(run.started_at);
            if (ts === null) continue;
            var x = PAD_X + ((ts - tMin) / (tMax - tMin)) * (w - 2 * PAD_X);
            var hh = FLOOR_H;
            if (typeof run.n_trials === "number" && run.n_trials > 0 && logMax > 0) {
                hh = FLOOR_H + (Math.log1p(run.n_trials) / logMax) * (span - FLOOR_H);
            }
            marks.push({ x: x, h: hh, color: colorFor(run.status), run: run, t: ts });
        }
        return { tMin: tMin, tMax: tMax, maxTrials: maxTrials };
    }

    var scale = null;

    function draw(hoverIdx) {
        var g = layout();
        var ctx = g.ctx, w = g.w, h = g.h;
        ctx.clearRect(0, 0, w, h);

        var baseY = h - BASE_Y;
        var inner = w - 2 * PAD_X;
        var muted = token("--ink-text-2");

        // Repères et ÉTIQUETTES de temps. Sans elles, une bande où les runs
        // sont groupés d'un côté se lit comme un défaut d'affichage ; avec
        // elles, elle se lit pour ce qu'elle est -- une station qui n'a rien
        // enregistré depuis. Quatre étiquettes, jamais plus : au-delà elles se
        // chevauchent avant 700px de large.
        if (scale) {
            ctx.strokeStyle = token("--ink");
            ctx.lineWidth = 1;
            for (var k = 1; k < 8; k++) {
                var gx = Math.round(PAD_X + (k / 8) * inner) + 0.5;
                ctx.beginPath();
                ctx.moveTo(gx, 6);
                ctx.lineTo(gx, baseY);
                ctx.stroke();
            }

            ctx.fillStyle = muted;
            ctx.globalAlpha = 0.85;
            ctx.font = "10px " + (token("--mono") || "monospace");
            var labels = 4;
            for (k = 0; k < labels; k++) {
                var f = k / (labels - 1);
                var lx = PAD_X + f * inner;
                var txt = fmtDate(scale.tMin + f * (scale.tMax - scale.tMin));
                ctx.textAlign = k === 0 ? "left" : (k === labels - 1 ? "right" : "center");
                ctx.fillText(txt, lx, h - 6);
            }
            ctx.textAlign = "left";
            ctx.globalAlpha = 1;
        }

        // Ligne de base : le papier défile même quand rien ne se produit.
        ctx.strokeStyle = muted;
        ctx.globalAlpha = 0.35;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(PAD_X, baseY + 0.5);
        ctx.lineTo(w - PAD_X, baseY + 0.5);
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Repère « maintenant » : le bord droit EST l'instant présent, et
        // c'est ce qui donne son sens à l'espace vide qui le précède.
        if (scale) {
            var nx = w - PAD_X + 0.5;
            ctx.strokeStyle = token("--accent-ink");
            ctx.globalAlpha = 0.55;
            ctx.setLineDash([2, 3]);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(nx, 6);
            ctx.lineTo(nx, baseY);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.globalAlpha = 1;
        }

        if (!marks.length) return;

        // Révélation gauche->droite : le mouvement natif d'un enregistreur.
        var cutoff = PAD_X + reveal * (w - 2 * PAD_X);
        for (var i = 0; i < marks.length; i++) {
            var m = marks[i];
            if (m.x > cutoff) continue;
            var isHover = (i === hoverIdx);
            ctx.strokeStyle = m.color;
            ctx.globalAlpha = isHover ? 1 : 0.92;
            ctx.lineWidth = isHover ? 4 : 3;
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.moveTo(m.x, baseY);
            ctx.lineTo(m.x, baseY - m.h);
            ctx.stroke();
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
            "<b>" + marks.length + "</b> " + tr("record_runs", "runs"),
            fmtStr(tr("record_span", "du {from} à maintenant"),
                { from: scale ? fmtDate(scale.tMin) : "?" }),
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

    function nearest(mx) {
        var best = -1, bestD = 9;
        for (var i = 0; i < marks.length; i++) {
            var d = Math.abs(marks[i].x - mx);
            if (d < bestD) { bestD = d; best = i; }
        }
        return best;
    }

    canvas.addEventListener("mousemove", function (ev) {
        if (!marks.length) return;
        var rect = canvas.getBoundingClientRect();
        var idx = nearest(ev.clientX - rect.left);
        draw(idx);
        if (idx < 0) { if (tooltip) tooltip.classList.add("hidden"); return; }
        if (!tooltip) return;
        var m = marks[idx];
        var trials = typeof m.run.n_trials === "number"
            ? m.run.n_trials + " " + tr("record_trials", "essais")
            : tr("record_no_trials", "essais inconnus");
        tooltip.innerHTML = "<b></b><br><span></span>";
        tooltip.firstChild.textContent = m.run.name + " — " + m.run.target;
        tooltip.lastChild.textContent = fmtDateTime(m.t) + " · " + trials + " · " + m.run.status;
        tooltip.classList.remove("hidden");
        var box = canvas.getBoundingClientRect();
        var host = canvas.parentElement.getBoundingClientRect();
        tooltip.style.left = Math.max(4, Math.min(m.x + (box.left - host.left) + 10,
            host.width - tooltip.offsetWidth - 4)) + "px";
        // L'infobulle flotte SUR la plaque, jamais sous elle : posée en dessous
        // elle recouvrait la légende chiffrée -- on masquait l'échelle de la
        // bande au moment précis où l'on interroge une de ses marques.
        tooltip.style.top = (box.top - host.top + 4) + "px";
    });
    canvas.addEventListener("mouseleave", function () {
        if (tooltip) tooltip.classList.add("hidden");
        draw(-1);
    });
    canvas.addEventListener("click", function (ev) {
        if (!marks.length) return;
        var rect = canvas.getBoundingClientRect();
        var idx = nearest(ev.clientX - rect.left);
        if (idx >= 0) window.location.href = "/runs/" + encodeURIComponent(marks[idx].run.run_id);
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
