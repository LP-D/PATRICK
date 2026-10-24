(function () {
    "use strict";

    // feature/ticker-stats-panel: fills the per-asset skeleton cards on
    // /commodities and /macro (`_components.html::asset_panel`). Même découpage
    // « récupérer côté client puis tracer » que l'aperçu de `market.js` ; le
    // tracé passe par le moteur commun (chart_kit.js : zoom, infobulle, thème).

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; });
    }
    function fmtNum(v, digits) {
        if (v === null || v === undefined || Number.isNaN(v)) return "—";
        return Number(v).toLocaleString(document.documentElement.lang || "fr",
            { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }
    function fmtPct(v, digits) {
        if (v === null || v === undefined || Number.isNaN(v)) return "—";
        return fmtNum(v * 100, digits) + "%";
    }
    function fmtSigned(v, digits) {
        if (v === null || v === undefined || Number.isNaN(v)) return "—";
        return (v > 0 ? "+" : "") + fmtNum(v, digits);
    }

    function drawChart(host, symbol, data) {
        var P = window.PatrickPlot, dates = data.dates || [], closes = data.closes || [];
        var xs = dates.map(P.parseDate), timed = xs.length === closes.length && xs.every(function (x) { return isFinite(x); });
        if (!timed) xs = closes.map(function (_, i) { return i; });
        var ohlc = timed && data.opens && data.opens.length === closes.length ? { open: data.opens, high: data.highs, low: data.lows } : null;
        P.create(host, {
            type: "line", xKind: timed ? "time" : "index", xs: xs, xLabel: function (i) { return dates[i] || String(i); },
            series: closes.length < 2 ? [] : [{ values: closes, color: "--brand", width: 1.8 }],
            title: (window.PatrickNames ? window.PatrickNames.label(symbol) : symbol), quoteTitle: false, initialDays: 365,
            quote: timed, trend: true, ranges: timed, height: 220, empty: tr("preview_no_data", "No data for this period."),
            ohlc: ohlc, volume: ohlc && data.volumes && data.volumes.some(function (v) { return v > 0; }) ? data.volumes : null,
        });
    }

    function emptyStateHtml(message, hint) {
        return '<div class="empty-state"><p class="empty-state-message">' + message + '</p>' +
            (hint ? '<p class="hint">' + hint + '</p>' : '') + '</div>';
    }

    function renderReturnsTable(data) {
        var horizonKeys = Object.keys(data.returns || {});
        var longKeys = Object.keys(data.long_window_returns || {});
        if (!horizonKeys.length && !longKeys.length) return '';
        var head = '<tr>';
        horizonKeys.forEach(function (h) { head += '<th class="num pk-mono">' + h + tr("day_suffix", "d") + '</th>'; });
        longKeys.forEach(function (w) { head += '<th class="num pk-mono">' + w + 'b</th>'; });
        head += '</tr>';
        var row = '<tr>';
        horizonKeys.forEach(function (h) { row += '<td class="num pk-mono">' + fmtSigned(data.returns[h] * 100, 2) + '%</td>'; });
        longKeys.forEach(function (w) {
            var v = data.long_window_returns[w];
            row += '<td class="num pk-mono">' + (v === null ? '—' : fmtSigned(v * 100, 2) + '%') + '</td>';
        });
        row += '</tr>';
        return '<p class="hint">' + tr("assetpanel_returns", "Returns (pipeline horizons)") + ' / ' +
            tr("assetpanel_long_window", "Longer-window view") + '</p>' +
            '<div class="table-scroll"><table class="data-table"><thead>' + head + '</thead><tbody>' + row + '</tbody></table></div>';
    }

    function renderMetricsGrid(data) {
        var metrics = [];
        metrics.push([tr("assetpanel_zscore", "Z-score (60 bars)"),
            data.zscore_60d === null || data.zscore_60d === undefined ? '—' : fmtSigned(data.zscore_60d, 2)]);
        Object.keys(data.moving_averages || {}).forEach(function (w) {
            var v = data.moving_averages[w];
            metrics.push([fmtStr(tr("assetpanel_ma", "Price vs moving average"), {}) + ' MA' + w,
                v === null ? '—' : fmtSigned(v * 100, 2) + '%']);
        });
        if (data.volatility) {
            metrics.push([tr("assetpanel_vol_current", "current (20 bars)"), fmtPct(data.volatility.annualized_current, 1)]);
            metrics.push([tr("assetpanel_vol_long_run", "long-run (~252 bars)"), fmtPct(data.volatility.annualized_long_run, 1)]);
        }
        return '<div class="metric-grid asset-metric-grid">' + metrics.map(function (m) {
            return '<div class="metric"><div class="metric-label">' + m[0] + '</div>' +
                '<div class="metric-value pk-mono">' + m[1] + '</div></div>';
        }).join('') + '</div>';
    }

    function renderPanel(panel, data) {
        var body = panel.querySelector(".asset-panel-body");
        if (!body) return;
        var symbol = panel.getAttribute("data-symbol") || "?";

        if (data.error) {
            body.dataset.state = "error";
            body.innerHTML = emptyStateHtml(
                fmtStr(tr("assetpanel_error", "Unavailable: {error}"), { error: data.error }));
            return;
        }
        if (data.insufficient_history) {
            body.dataset.state = "empty";
            body.innerHTML = emptyStateHtml(
                tr("assetpanel_insufficient", "Not enough history to compute these stats yet."),
                fmtStr("{n} obs.", { n: data.n_obs }));
            return;
        }

        body.dataset.state = "ready";
        body.innerHTML =
            '<div class="chart-wrap asset-chart"></div>' +
            renderReturnsTable(data) +
            renderMetricsGrid(data);

        var host = body.querySelector(".asset-chart");
        if (host) drawChart(host, symbol, data);
    }

    function loadPanel(panel) {
        var symbol = panel.getAttribute("data-symbol");
        if (!symbol) return;
        fetch("/api/asset-stats/" + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) { renderPanel(panel, data); })
            .catch(function () {
                var body = panel.querySelector(".asset-panel-body");
                if (body) {
                    body.dataset.state = "error";
                    body.innerHTML = emptyStateHtml(tr("assetpanel_load_error", "Loading error."));
                }
            });
    }

    // /macro lists ~100 series: fetch each panel only when it is about to
    // scroll into view (one request per panel, not 100 at page load).
    var panels = document.querySelectorAll(".asset-panel[data-symbol]");
    if ("IntersectionObserver" in window) {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                observer.unobserve(entry.target);
                loadPanel(entry.target);
            });
        }, { rootMargin: "400px 0px" });
        panels.forEach(function (panel) { observer.observe(panel); });
    } else {
        panels.forEach(function (panel) { loadPanel(panel); });
    }
})();
