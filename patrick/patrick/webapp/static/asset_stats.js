(function () {
    "use strict";

    // feature/ticker-stats-panel: fills the per-asset skeleton cards on
    // /commodities and /macro (`_components.html::asset_panel`). Same
    // client-fetch-then-render split as `market.js`'s preview panel, same
    // canvas technique (native 2D context, CSS custom properties read via
    // getComputedStyle -- no charting library, see that file's own comment)
    // -- deliberately NOT reusing `market.js::drawChart` directly since it
    // is wired to a single global `#preview-canvas`/tooltip pair, while
    // this page draws one chart per asset (potentially dozens); the
    // drawing logic below is the same shape, trimmed of the single-canvas
    // globals and the hover tooltip.

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }
    var MONO = token("--mono") || "monospace";
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

    function drawChart(canvas, closes) {
        if (!canvas) return;
        var ctx = canvas.getContext("2d");
        var w = canvas.width, h = canvas.height, pad = 30;
        ctx.clearRect(0, 0, w, h);
        closes = closes || [];
        if (closes.length < 2) {
            ctx.fillStyle = token("--ink-text-2");
            ctx.font = "12px " + MONO;
            ctx.fillText(tr("preview_no_data", "No data for this period."), pad, h / 2);
            return;
        }
        var min = Math.min.apply(null, closes);
        var max = Math.max.apply(null, closes);
        if (min === max) { min -= 1; max += 1; }
        var xStep = (w - 2 * pad) / (closes.length - 1);
        var accent = token("--accent-ink");
        var muted = token("--ink-text-2");
        var rule = token("--ink-2");

        function xAt(i) { return pad + i * xStep; }
        function yAt(v) { return h - pad + ((v - min) / (max - min)) * -(h - 2 * pad); }

        ctx.strokeStyle = rule;
        ctx.lineWidth = 1;
        for (var gi = 0; gi <= 3; gi++) {
            var gy = Math.round(pad + (gi / 3) * (h - 2 * pad)) + 0.5;
            ctx.beginPath();
            ctx.moveTo(pad, gy);
            ctx.lineTo(w - pad, gy);
            ctx.stroke();
        }

        ctx.fillStyle = muted;
        ctx.font = "10px " + MONO;
        ctx.fillText(fmtNum(max, 2), 2, yAt(max) + 4);
        ctx.fillText(fmtNum(min, 2), 2, yAt(min) + 4);

        ctx.beginPath();
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        for (var i = 0; i < closes.length; i++) {
            var x = xAt(i), y = yAt(closes[i]);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
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
        horizonKeys.forEach(function (h) { head += '<th class="num pk-mono">' + h + 'j</th>'; });
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
            '<div class="chart-wrap"><canvas class="asset-chart" width="560" height="150" role="img"></canvas></div>' +
            renderReturnsTable(data) +
            renderMetricsGrid(data);

        var canvas = body.querySelector(".asset-chart");
        drawChart(canvas, data.closes);
        if (canvas && data.closes && data.closes.length) {
            var closes = data.closes;
            canvas.setAttribute("aria-label", fmtStr(
                tr("preview_aria", "{symbol} price over {period}: {n} points, low {min} to high {max}, last {last}."),
                { symbol: symbol, period: "5y", n: closes.length,
                  min: fmtNum(Math.min.apply(null, closes), 2), max: fmtNum(Math.max.apply(null, closes), 2),
                  last: fmtNum(closes[closes.length - 1], 2) }));
        }
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

    var panels = document.querySelectorAll(".asset-panel[data-symbol]");
    panels.forEach(function (panel) { loadPanel(panel); });
})();
