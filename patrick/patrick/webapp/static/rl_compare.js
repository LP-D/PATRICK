/* Page /compare-runs pour des runs RL : courbes de capital hors échantillon (base 1), une par run, sur la grille de dates commune
   préparée par `webapp/rl_compare.py` (valeur vide avant le début et après la fin d'un run). Réutilise `PatrickCharts.lineChart`. */
(function () {
    "use strict";
    var C = window.PatrickCharts, node = document.getElementById("cmp-rl-chart"), data = document.getElementById("cmp-rl-data");
    if (!C || !node || !data) return;
    var chart = JSON.parse(data.textContent);
    node.appendChild(C.lineChart({
        dates: chart.dates, title: C.tr("rlp_c_equity"),
        series: chart.series.map(function (s) { return { values: s.values, color: s.color }; }),
        hlines: [{ y: 1, dash: "1 3" }],
    }));
})();
