(function () {
    "use strict";

    // P9 -- /targets/{ticker} "Dérive des sous-phases" trend chart: durée de
    // chaque sous-phase de `run_phase_timing` (migrations 0016/0017) au fil
    // des runs successifs d'une cible, une ligne par phase. Même technique
    // canvas que market.js/simulate.js (lecture des jetons CSS sans repli
    // codé en dur, pas de librairie externe) -- voir la note identique dans
    // ces deux fichiers pour la raison. Page-specific (comme simulate.js,
    // pas comme market.js) : chargé uniquement par target.html, où
    // window.DRIFT_POINTS/DRIFT_PHASE_LABELS sont toujours définis (à [] /
    // {} près) par le gabarit -- pas de garde `if (!window.DRIFT_POINTS)`
    // nécessaire, mais `#drift-canvas` peut être absent (aucune donnée de
    // chronométrage pour cette cible) : chaque fonction le vérifie.

    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }
    var MONO = token("--mono") || "monospace";

    function fmtNum(v) {
        return v.toLocaleString(document.documentElement.lang || "fr", { maximumFractionDigits: 0 });
    }
    function fmtDuration(s) {
        if (s === null || s === undefined) return "—";
        if (s >= 3600) return (s / 3600).toFixed(1) + " h";
        if (s >= 60) return (s / 60).toFixed(1) + " min";
        return fmtNum(s) + " s";
    }

    var canvas = document.getElementById("drift-canvas");
    var legendEl = document.getElementById("drift-legend");
    var tooltip = document.getElementById("drift-tooltip");
    var points = window.DRIFT_POINTS || [];
    var phaseLabels = window.DRIFT_PHASE_LABELS || {};

    if (!canvas || !points.length) return;

    // Palette fixe cyclée par ordre de première apparition de la phase --
    // 7 jetons distincts couvrent les 7 phases connues (migration 0017)
    // sans qu'aucune couleur ne soit codée en dur (mêmes jetons que
    // market.js/simulate.js, plus les 3 propres à cette palette : jaune
    // d'alerte, bordure, texte principal).
    var PALETTE_TOKENS = ["--accent-ink", "--error-ink", "--color-warning",
                           "--ink-2", "--ink-text-2", "--color-border", "--color-foreground"];

    // --- Regroupement : un point par (run, phase) en entrée -> une série
    // temporelle par phase, alignée sur la liste chronologique des runs. ---
    var runs = []; // [{run_id, started_at}], ordre déjà chronologique (server-side ORDER BY)
    var runIndexById = {};
    var phases = []; // ordre de première apparition
    var seenPhase = {};
    points.forEach(function (p) {
        if (runIndexById[p.run_id] === undefined) {
            runIndexById[p.run_id] = runs.length;
            runs.push({ run_id: p.run_id, started_at: p.started_at });
        }
        if (!seenPhase[p.phase]) { seenPhase[p.phase] = true; phases.push(p.phase); }
    });
    // series[phase] = array (length = runs.length) de duration_s ou null
    var series = {};
    phases.forEach(function (phase) { series[phase] = runs.map(function () { return null; }); });
    points.forEach(function (p) {
        series[p.phase][runIndexById[p.run_id]] = p.duration_s;
    });
    var colorByPhase = {};
    phases.forEach(function (phase, i) {
        colorByPhase[phase] = token(PALETTE_TOKENS[i % PALETTE_TOKENS.length]);
    });

    function phaseLabel(phase) { return phaseLabels[phase] || phase; }

    // --- Légende ---
    if (legendEl) {
        legendEl.innerHTML = "";
        phases.forEach(function (phase) {
            var item = document.createElement("span");
            item.className = "drift-legend-item";
            var swatch = document.createElement("span");
            swatch.className = "drift-legend-swatch";
            swatch.style.background = colorByPhase[phase];
            var label = document.createElement("span");
            label.textContent = phaseLabel(phase);
            item.appendChild(swatch);
            item.appendChild(label);
            legendEl.appendChild(item);
        });
    }

    // --- Tracé ---
    var ctx = canvas.getContext("2d");
    var w = canvas.width, h = canvas.height;
    var padL = 48, padR = 12, padT = 12, padB = 28;
    var plotW = w - padL - padR, plotH = h - padT - padB;

    var allDurations = [];
    phases.forEach(function (phase) {
        series[phase].forEach(function (v) { if (v !== null) allDurations.push(v); });
    });
    var maxDuration = allDurations.length ? Math.max.apply(null, allDurations) : 1;
    if (maxDuration <= 0) maxDuration = 1;
    var nRuns = runs.length;
    var xStep = nRuns > 1 ? plotW / (nRuns - 1) : 0;

    function xAt(i) { return padL + i * xStep; }
    function yAt(v) { return padT + plotH - (v / maxDuration) * plotH; }

    function draw() {
        ctx.clearRect(0, 0, w, h);

        // Grille horizontale (4 lignes, même geste que market.js : assez
        // pour lire une mesure, pas assez pour concurrencer les courbes).
        var rule = token("--ink-2");
        var muted = token("--ink-text-2");
        ctx.strokeStyle = rule;
        ctx.lineWidth = 1;
        for (var gi = 0; gi <= 3; gi++) {
            var gy = Math.round(padT + (gi / 3) * plotH) + 0.5;
            ctx.beginPath();
            ctx.moveTo(padL, gy);
            ctx.lineTo(w - padR, gy);
            ctx.stroke();
        }

        // Axe Y (durée)
        ctx.fillStyle = muted;
        ctx.font = "10px " + MONO;
        ctx.textAlign = "right";
        ctx.fillText(fmtDuration(maxDuration), padL - 6, padT + 8);
        ctx.fillText(fmtDuration(0), padL - 6, padT + plotH + 4);

        // Axe X (dates de démarrage) : premier, milieu, dernier run --
        // au-delà, les libellés se chevaucheraient sur un historique long.
        ctx.textAlign = "center";
        var tickIdxs = nRuns > 2 ? [0, Math.floor((nRuns - 1) / 2), nRuns - 1] : runs.map(function (_, i) { return i; });
        tickIdxs.forEach(function (idx) {
            var label = (runs[idx].started_at || "").slice(0, 10) || "?";
            ctx.fillText(label, xAt(idx), h - 6);
        });

        // Une ligne par phase, AVEC coupure de trait sur les points
        // manquants (un run peut ne pas avoir chronométré une phase donnée,
        // p.ex. la stabilité de sélection désactivée) -- contrairement au
        // `plot()` de simulate.js qui saute silencieusement une valeur
        // nulle sans rompre le trait : ici relier deux runs non consécutifs
        // par une ligne continue serait une valeur fabriquée, pas un trou
        // honnête.
        phases.forEach(function (phase) {
            var vals = series[phase];
            ctx.strokeStyle = colorByPhase[phase];
            ctx.lineWidth = 2;
            ctx.beginPath();
            var started = false;
            for (var i = 0; i < vals.length; i++) {
                var v = vals[i];
                if (v === null || v === undefined) { started = false; continue; }
                var x = xAt(i), y = yAt(v);
                if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
            }
            ctx.stroke();
            // Points marqués : un historique court (2-4 runs) se lit mal en
            // ligne seule, le marqueur ancre chaque mesure réelle.
            ctx.fillStyle = colorByPhase[phase];
            for (var j = 0; j < vals.length; j++) {
                if (vals[j] === null || vals[j] === undefined) continue;
                ctx.beginPath();
                ctx.arc(xAt(j), yAt(vals[j]), 2.5, 0, Math.PI * 2);
                ctx.fill();
            }
        });

        canvas._baseImage = ctx.getImageData(0, 0, w, h);
    }

    draw();

    // Équivalent textuel : sans lui, la toile ne dit rien à un lecteur
    // d'écran (même principe que market.js/simulate.js).
    var totalsByPhase = phases.map(function (phase) {
        var vals = series[phase].filter(function (v) { return v !== null; });
        var last = vals.length ? vals[vals.length - 1] : null;
        return phaseLabel(phase) + " " + fmtDuration(last);
    });
    canvas.setAttribute("aria-label",
        "Dérive des durées de sous-phase sur " + nRuns + " run(s) pour cette cible. " +
        "Dernière mesure par phase : " + totalsByPhase.join(", ") + ".");

    // --- Infobulle au survol : durée de chaque phase pour le run le plus proche ---
    canvas.onmousemove = function (ev) {
        if (nRuns < 1) return;
        var rect = canvas.getBoundingClientRect();
        var mx = (ev.clientX - rect.left) * (canvas.width / rect.width);
        var idx = nRuns > 1 ? Math.round((mx - padL) / xStep) : 0;
        if (idx < 0 || idx >= nRuns) { if (tooltip) tooltip.classList.add("hidden"); return; }

        ctx.putImageData(canvas._baseImage, 0, 0);
        var x = xAt(idx);
        ctx.beginPath();
        ctx.strokeStyle = token("--ink-2");
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.moveTo(x, padT);
        ctx.lineTo(x, padT + plotH);
        ctx.stroke();
        ctx.setLineDash([]);

        if (tooltip) {
            var lines = [runs[idx].started_at || "?"];
            phases.forEach(function (phase) {
                var v = series[phase][idx];
                if (v !== null) lines.push(phaseLabel(phase) + " : " + fmtDuration(v));
            });
            tooltip.innerHTML = lines.map(function (l, i) {
                return i === 0 ? "<strong>" + l + "</strong>" : l;
            }).join("<br>");
            var my = (ev.clientY - rect.top) * (canvas.height / rect.height);
            tooltip.style.left = Math.min(x + 8, w - 180) + "px";
            tooltip.style.top = Math.max(my - 20, 0) + "px";
            tooltip.classList.remove("hidden");
        }
    };
    canvas.onmouseleave = function () {
        if (tooltip) tooltip.classList.add("hidden");
        ctx.putImageData(canvas._baseImage, 0, 0);
    };
})();
