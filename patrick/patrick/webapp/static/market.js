(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }

    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; });
    }

    var targetSelect = document.getElementById("target_symbols");
    var chartHost = document.getElementById("preview-chart");
    var statusEl = document.getElementById("preview-status");
    var rangesEl = document.getElementById("preview-ranges");
    var newsList = document.getElementById("news-list");

    var currentPeriod = "1y";
    var currentSymbol = null;
    var chart = null;

    // Le panneau d'aperçu (un graphique, une liste d'actus) reste
    // mono-cible même si `#target_symbols` accepte désormais plusieurs
    // sélections (lancement en batch) : on affiche toujours la première
    // cible sélectionnée, jamais N aperçus. `.value` sur un `<select
    // multiple>` est peu fiable d'un navigateur à l'autre -- on lit
    // `selectedOptions[0]` explicitement.
    function firstSelectedValue(select) {
        if (!select || !select.selectedOptions || !select.selectedOptions.length) return null;
        return select.selectedOptions[0].value;
    }

    // Tracé : moteur commun (chart_kit.js) en style cotation : en-tête (dernier cours, variation de la période), courbe verte / rouge selon
    // la tendance, bougies et volumes quand le fournisseur les donne. Zoom par sélection, déplacement, infobulle, redessin au changement de thème.
    function drawChart(series) {
        if (!chartHost) return;
        if (chart) chart.destroy();
        var closes = series.closes || [], dates = series.dates || [];
        var xs = dates.map(window.PatrickPlot.parseDate);
        var timed = xs.length === closes.length && xs.every(function (x) { return isFinite(x); });
        if (!timed) xs = closes.map(function (_, i) { return i; });
        var ohlc = timed && series.opens && series.opens.length === closes.length
            ? { open: series.opens, high: series.highs, low: series.lows } : null;
        chart = window.PatrickPlot.create(chartHost, {
            type: "line", xKind: timed ? "time" : "index", xs: xs, xLabel: function (i) { return dates[i] || String(i); },
            series: closes.length < 2 ? [] : [{ values: closes, color: "--brand", width: 2 }],
            title: currentSymbol || "", quote: timed, trend: true, height: 240,
            ohlc: ohlc, volume: ohlc && series.volumes && series.volumes.some(function (v) { return v > 0; }) ? series.volumes : null,
            empty: tr("preview_no_data", "No data for this period."),
        });
    }

    function loadPreview(symbol, period) {
        if (!chartHost) return;
        currentSymbol = symbol;
        if (statusEl) statusEl.textContent = tr("preview_loading", "Loading…");
        fetch("/api/preview/" + encodeURIComponent(symbol) + "?period=" + encodeURIComponent(period))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                drawChart(data);
                if (statusEl) {
                    // La plaque écrit déjà « Pas de données pour cette période »
                    // quand la série est vide : le répéter juste en dessous
                    // disait deux fois la même chose. Cette ligne ne porte donc
                    // plus que ce que la plaque ne peut pas dire — la cause.
                    statusEl.textContent = data.error
                        ? fmtStr(tr("preview_unavailable", "Unavailable: {error}"), { error: data.error })
                        : "";
                }
            })
            .catch(function () {
                if (statusEl) statusEl.textContent = tr("preview_load_error", "Loading error.");
            });
    }

    function loadNews(symbol) {
        if (!newsList) return;
        newsList.innerHTML = "<li class=\"hint\"></li>";
        newsList.firstChild.textContent = tr("news_loading", "Loading…");
        fetch("/api/news/" + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var items = data.items || [];
                if (!items.length) {
                    newsList.innerHTML = "<li class=\"hint\"></li>";
                    newsList.firstChild.textContent = tr("news_none", "No news available for this target.");
                    return;
                }
                newsList.innerHTML = "";
                items.forEach(function (item) {
                    var li = document.createElement("li");
                    var a = document.createElement("a");
                    a.href = item.link || "#";
                    a.target = "_blank";
                    a.rel = "noopener noreferrer";
                    a.textContent = item.title;
                    li.appendChild(a);
                    if (item.publisher) {
                        var span = document.createElement("span");
                        span.className = "hint news-publisher";
                        span.textContent = " — " + item.publisher;
                        li.appendChild(span);
                    }
                    newsList.appendChild(li);
                });
            })
            .catch(function () {
                newsList.innerHTML = "<li class=\"hint\"></li>";
                newsList.firstChild.textContent = tr("news_load_error", "Error loading news.");
            });
    }

    function refreshAll() {
        if (!targetSelect) return;
        var symbol = firstSelectedValue(targetSelect);
        if (!symbol) return;
        loadPreview(symbol, currentPeriod);
        loadNews(symbol);
    }

    if (targetSelect) {
        targetSelect.addEventListener("change", refreshAll);
        refreshAll();
    }

    if (rangesEl) {
        rangesEl.addEventListener("click", function (ev) {
            var btn = ev.target.closest ? ev.target.closest(".range-btn") : null;
            if (!btn) return;
            currentPeriod = btn.getAttribute("data-period");
            Array.prototype.forEach.call(rangesEl.querySelectorAll(".range-btn"), function (b) {
                b.classList.toggle("active", b === btn);
            });
            var rangeSymbol = firstSelectedValue(targetSelect);
            if (rangeSymbol) loadPreview(rangeSymbol, currentPeriod);
        });
    }
})();
