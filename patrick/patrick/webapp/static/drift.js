(function () {
    "use strict";

    // P9 -- /targets/{ticker} "Dérive des sous-phases" trend chart: durée de
    // chaque sous-phase de `run_phase_timing` (migrations 0016/0017) au fil
    // des runs successifs d'une cible, une ligne par phase. Tracé par le moteur
    // commun (chart_kit.js : zoom, légende cliquable, infobulle, thème) ; page-
    // specific : chargé uniquement par target.html, où window.DRIFT_POINTS /
    // DRIFT_PHASE_LABELS sont toujours définis (à [] / {} près) par le gabarit.
    // `#drift-chart` peut être absent (aucune donnée de chronométrage pour
    // cette cible) : on sort alors sans rien faire.

    var LANG = document.documentElement.lang || "fr";
    function fmtNum(v, d) {
        return v.toLocaleString(LANG, { minimumFractionDigits: d || 0, maximumFractionDigits: d === undefined ? 0 : d });
    }
    function fmtDuration(s) {
        if (s === null || s === undefined) return "—";
        if (s >= 3600) return fmtNum(s / 3600, 1) + " h";
        if (s >= 60) return fmtNum(s / 60, 1) + " min";
        return fmtNum(s) + " s";
    }

    var host = document.getElementById("drift-chart");
    var points = window.DRIFT_POINTS || [];
    var phaseLabels = window.DRIFT_PHASE_LABELS || {};

    if (!host || !points.length) return;

    // Palette cyclée par ordre de première apparition de la phase : 7 jetons
    // distincts couvrent les 7 phases connues (migration 0017), aucune couleur
    // n'est codée en dur.
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

    function phaseLabel(phase) { return phaseLabels[phase] || phase; }

    // Axe Y dans l'unité la plus lisible (s, min ou h) : des graduations rondes (0, 5, 10 min…) au lieu de secondes converties une à une.
    var allValues = [];
    phases.forEach(function (phase) { series[phase].forEach(function (v) { if (v !== null && v !== undefined) allValues.push(v); }); });
    var top = allValues.length ? Math.max.apply(null, allValues) : 0;
    var unit = top >= 3600 ? 3600 : (top >= 60 ? 60 : 1), unitLabel = unit === 3600 ? "h" : (unit === 60 ? "min" : "s");

    // Étiquettes de l'axe X : la date de démarrage du run, complétée de l'heure quand plusieurs runs partent le même jour.
    var perDay = {};
    runs.forEach(function (r) { var d = (r.started_at || "").slice(0, 10); perDay[d] = (perDay[d] || 0) + 1; });
    function runLabel(i) {
        var at = runs[i].started_at || "", day = at.slice(0, 10) || "?";
        return perDay[day] > 1 && at.length >= 16 ? day + " " + at.slice(11, 16) : day;
    }

    // Axe : un run = une position (les runs ne sont pas espacés régulièrement dans le temps, le rang est la lecture honnête) ; les
    // trous (phase non chronométrée pour un run) coupent le trait au lieu d'être reliés par une valeur fabriquée.
    window.PatrickPlot.create(host, {
        type: "line", xKind: "index", xs: runs.map(function (_, i) { return i; }), xLabel: runLabel,
        series: phases.map(function (phase, i) {
            return { name: phaseLabel(phase), color: PALETTE_TOKENS[i % PALETTE_TOKENS.length], width: 2,
                     values: series[phase].map(function (v) { return v === null || v === undefined ? null : v / unit; }) };
        }),
        yMin: 0, yFmt: function (v, d) { return fmtNum(v, d) + " " + unitLabel; }, tipFmt: function (v) { return fmtDuration(v * unit); },
        markers: true, legend: true, title: host.getAttribute("aria-label") || "", height: 260,
        // Un repère par run devenu champion de la cible : on voit si un changement de durée précède ou suit une promotion.
        vlines: (window.DRIFT_CHAMPIONS || []).filter(function (id) { return runIndexById[id] !== undefined; })
            .map(function (id) { return { x: runIndexById[id], label: window.DRIFT_CHAMPION_LABEL || "", color: "--accent-ink", dash: "4 3" }; }),
    });
})();
