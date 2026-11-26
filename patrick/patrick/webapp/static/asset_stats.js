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

    /* VI1 (26/11) : cône de prévision : fourchette probable du cours sur les CONE_DAYS prochaines séances, à 68 % (±1 écart) et 95 %
       (±1,96), d'après la volatilité journalière prévue (HAR, sinon 60 séances). Une fourchette, jamais une direction. */
    var CONE_DAYS = 20;
    function coneSeries(xs, closes, cone) {
        var n = closes.length, last = closes[n - 1], x0 = xs[n - 1];
        var future = [], d = new Date(x0);
        while (future.length < CONE_DAYS) {
            d = new Date(d.getTime() + 86400000);
            if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) future.push(d.getTime());
        }
        var band = function (z) {
            return future.map(function (_, k) { return last * Math.exp(z * cone.sigma * Math.sqrt(k + 1)); });
        };
        var line = function (z) {
            var out = closes.map(function () { return null; }).concat(band(z));
            out[n - 1] = last;                         // la fourchette part du dernier cours
            return out;
        };
        return {
            xs: xs.concat(future),
            closes: closes.concat(future.map(function () { return null; })),
            series: [
                { name: tr("cone_95", "95 % range"), values: line(1.96), color: "--text-3", width: 1, dash: [2, 3] },
                { name: tr("cone_68", "68 % range"), values: line(1), color: "--brand", width: 1, dash: [4, 3] },
                { name: "", values: line(-1), color: "--brand", width: 1, dash: [4, 3] },
                { name: "", values: line(-1.96), color: "--text-3", width: 1, dash: [2, 3] },
            ],
        };
    }

    function drawChart(host, symbol, data) {
        var P = window.PatrickPlot, dates = data.dates || [], closes = data.closes || [];
        var xs = dates.map(P.parseDate), timed = xs.length === closes.length && xs.every(function (x) { return isFinite(x); });
        if (!timed) xs = closes.map(function (_, i) { return i; });
        var ohlc = timed && data.opens && data.opens.length === closes.length ? { open: data.opens, high: data.highs, low: data.lows } : null;
        var cone = timed && data.cone && data.cone.sigma > 0 && closes.length > 1 ? coneSeries(xs, closes, data.cone) : null;
        var mainSeries = closes.length < 2 ? [] : [{ values: cone ? cone.closes : closes, color: "--brand", width: 1.8 }];
        P.create(host, {
            type: "line", xKind: timed ? "time" : "index", xs: cone ? cone.xs : xs, xLabel: function (i) { return dates[i] || String(i); },
            series: cone ? mainSeries.concat(cone.series) : mainSeries,
            title: (window.PatrickNames ? window.PatrickNames.label(symbol) : symbol), quoteTitle: false, initialDays: 365,
            quote: timed, trend: true, ranges: timed, height: 220, empty: tr("preview_no_data", "No data for this period."),
            ohlc: cone ? null : ohlc, volume: !cone && ohlc && data.volumes && data.volumes.some(function (v) { return v > 0; }) ? data.volumes : null,
            // D3 : changements de champion (« C1 » = horizon 1 jour) et publications de résultats (« R »), repères verticaux datés ;
            // A17 : calendrier économique (« IPC », « Emploi », « Fed », « BCE »...) en pointillé plus discret
            vlines: timed ? (data.events || []).map(function (e) {
                if (e.kind === "macro") return { x: P.parseDate(e.date), label: e.label, color: "--info", dash: [1, 4], minor: true };
                if (e.kind === "note") return { x: P.parseDate(e.date), label: e.label, color: "--text-2", dash: [1, 2] };   // VI24
                return { x: P.parseDate(e.date), label: e.label, color: e.kind === "earnings" ? "--warn" : "--brand", dash: [2, 3] };
            }).filter(function (l) { return isFinite(l.x); }) : [],
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
        if (host && panel.getAttribute("data-events")) renderNotes(panel, symbol, data);
    }

    /* VI24 (26/11) : notes libres datées sous la courbe d'un actif (ajout, liste, suppression) ; repères « ✎ » sur le graphique. */
    function noteButton(label) {
        var b = document.createElement("button");
        b.type = "button"; b.className = "btn-ghost"; b.textContent = label;
        return b;
    }
    function renderNotes(panel, symbol, data) {
        var body = panel.querySelector(".asset-panel-body");
        if (!body || body.querySelector(".chart-notes")) return;
        var notes = (data.events || []).filter(function (e) { return e.kind === "note"; });
        var box = document.createElement("details");
        box.className = "chart-notes";
        var summary = document.createElement("summary");
        summary.textContent = tr("notes_title", "Notes on the chart") + " (" + notes.length + ")";
        box.appendChild(summary);
        var form = document.createElement("form");
        form.className = "chart-notes-form inline-form";
        var day = document.createElement("input");
        day.type = "date"; day.name = "day"; day.setAttribute("aria-label", tr("notes_day", "Date"));
        day.value = (data.dates || []).length ? String(data.dates[data.dates.length - 1]).slice(0, 10) : "";
        var text = document.createElement("input");
        text.type = "text"; text.name = "text"; text.maxLength = 120;
        text.setAttribute("aria-label", tr("notes_text", "Note")); text.placeholder = tr("notes_placeholder", "e.g. ECB announcement");
        var add = document.createElement("button");
        add.type = "submit"; add.className = "btn-secondary"; add.textContent = tr("notes_add", "Add");
        form.appendChild(day); form.appendChild(text); form.appendChild(add);
        box.appendChild(form);
        var list = document.createElement("ul");
        list.className = "ch-list";
        notes.forEach(function (n) {
            var li = document.createElement("li");
            li.textContent = n.date + " · " + n.text + " ";
            var del = noteButton(tr("notes_delete", "Delete"));
            del.addEventListener("click", function () {
                fetch("/api/chart-notes/" + encodeURIComponent(symbol) + "/" + n.note_id, { method: "DELETE", credentials: "same-origin" })
                    .then(function () { reloadPanel(panel); });
            });
            li.appendChild(del);
            list.appendChild(li);
        });
        box.appendChild(list);
        form.addEventListener("submit", function (ev) {
            ev.preventDefault();
            fetch("/api/chart-notes/" + encodeURIComponent(symbol), {
                method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ day: day.value, text: text.value }),
            }).then(function (r) { if (r.ok) reloadPanel(panel, true); });
        });
        body.appendChild(box);
    }
    function reloadPanel(panel, open) {
        var wasOpen = open || !!(panel.querySelector(".chart-notes") || {}).open;
        loadPanel(panel, wasOpen);
    }

    function loadPanel(panel, notesOpen) {
        var symbol = panel.getAttribute("data-symbol");
        if (!symbol) return;
        fetch("/api/asset-stats/" + encodeURIComponent(symbol) + (panel.getAttribute("data-events") ? "?events=1" : ""))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                renderPanel(panel, data);
                var box = panel.querySelector(".chart-notes");
                if (box && notesOpen) box.open = true;
            })
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
