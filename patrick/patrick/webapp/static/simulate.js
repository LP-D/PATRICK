(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; });
    }
    function escapeHtml(s) {
        var div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
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

    var runSelect = document.getElementById("sim-run-select");
    var trialSelect = document.getElementById("sim-trial-select");
    var form = document.getElementById("sim-form");
    var runBtn = document.getElementById("sim-run-btn");
    var statusEl = document.getElementById("sim-status");
    var guardEl = document.getElementById("sim-overfitting-guard");
    var modeSelect = document.getElementById("sim-mode");
    var assetClassSelect = document.getElementById("sim-asset-class");
    var spreadInput = document.getElementById("sim-spread-bps");
    var commissionInput = document.getElementById("sim-commission-bps");

    var ASSET_CLASS_BPS = { futures_liquid: 1.0, us_large_cap: 3.0, eu_mid_cap: 15.0, crypto_non_major: 30.0 };

    assetClassSelect.addEventListener("change", function () {
        var v = ASSET_CLASS_BPS[assetClassSelect.value];
        if (v !== undefined) {
            spreadInput.value = (v / 2).toFixed(2);
            commissionInput.value = (v / 2).toFixed(2);
        }
    });

    async function loadTrials(runId) {
        trialSelect.innerHTML = '<option value="">—</option>';
        if (!runId) return;
        try {
            var res = await fetch("/api/runs/" + runId + "/trials");
            var data = await res.json();
            (data.trials || []).forEach(function (t) {
                var opt = document.createElement("option");
                opt.value = t.trial_id;
                opt.textContent = (t.is_best ? "★ " : "") + t.algo + " / " + t.sampler + " / N=" + t.n_features + " / " + t.regime;
                if (t.is_best) opt.selected = true;
                trialSelect.appendChild(opt);
            });
        } catch (e) { /* laisse le sélecteur vide */ }
    }

    runSelect.addEventListener("change", function () { loadTrials(runSelect.value); });
    if (window.SIM_INITIAL_RUN_ID) loadTrials(window.SIM_INITIAL_RUN_ID);

    function collectParams() {
        return {
            position_mode: modeSelect.value,
            threshold: parseFloat(document.getElementById("sim-threshold").value) || 0.55,
            kelly_fraction: parseFloat(document.getElementById("sim-kelly-fraction").value) || 0.5,
            max_leverage: parseFloat(document.getElementById("sim-max-leverage").value) || 1.0,
            max_position: parseFloat(document.getElementById("sim-max-position").value) || 1.0,
            short_allowed: document.getElementById("sim-short-allowed").checked,
            overlap_mode: document.getElementById("sim-overlap-mode").value,
            asset_class: assetClassSelect.value || null,
            spread_bps: parseFloat(spreadInput.value) || 0,
            commission_bps: parseFloat(commissionInput.value) || 0,
            carry_bps_per_year: parseFloat(document.getElementById("sim-carry-bps").value) || 0,
        };
    }

    var lastTradeReturns = [];

    form.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        var trialId = trialSelect.value;
        if (!trialId) {
            statusEl.textContent = tr("sim_no_run_selected", "Choose a run then a model.");
            return;
        }
        runBtn.disabled = true;
        statusEl.textContent = tr("sim_loading", "Simulating…");
        guardEl.classList.add("hidden");
        try {
            var res = await fetch("/api/simulate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ trial_id: parseInt(trialId, 10), params: collectParams() }),
            });
            var data = await res.json();
            if (!res.ok || data.ok === false) {
                statusEl.textContent = fmtStr(tr("sim_error", "Error: {error}"), { error: data.message || data.detail || "?" });
                clearPanels();
                return;
            }
            statusEl.textContent = "";
            renderResult(data);
        } catch (e) {
            statusEl.textContent = fmtStr(tr("sim_error", "Error: {error}"), { error: String(e) });
        } finally {
            runBtn.disabled = false;
        }
    });

    function clearPanels() {
        drawLine(document.getElementById("sim-equity-canvas"), [], []);
        drawLine(document.getElementById("sim-drawdown-canvas"), [], [], true);
        drawHistogram(document.getElementById("sim-dist-canvas"), []);
        document.querySelector("#sim-metrics-table tbody").innerHTML = "";
        document.querySelector("#sim-trades-table tbody").innerHTML = "";
    }

    function renderResult(data) {
        if (data.n_simulation_configs_on_target) {
            var dsr = data.strategy && data.strategy.deflated_sharpe;
            guardEl.textContent = fmtStr(tr("sim_overfitting_guard",
                "⚠ {n} simulation configuration(s) tested on this target — deflated Sharpe = {dsr}"),
                { n: data.n_simulation_configs_on_target, dsr: dsr === null || dsr === undefined ? "—" : fmtNum(dsr, 3) });
            guardEl.classList.remove("hidden");
        }
        if (data.message) {
            statusEl.textContent = data.message;
        }

        var eqPoints = (data.equity_curve || []).map(function (p) { return p.v; });
        var bhPoints = (data.buy_and_hold_curve || []).map(function (p) { return p.v; });
        drawLine(document.getElementById("sim-equity-canvas"), eqPoints, bhPoints);
        var ddPoints = (data.drawdown_curve || []).map(function (p) { return p.v; });
        drawLine(document.getElementById("sim-drawdown-canvas"), ddPoints, [], true);

        lastTradeReturns = data.trade_returns || [];
        drawHistogram(document.getElementById("sim-dist-canvas"), lastTradeReturns);

        renderMetricsTable(data.strategy || {}, data.buy_and_hold || {});
        renderTradesTable(lastTradeReturns);
    }

    function renderMetricsTable(strat, bh) {
        var rows = [
            ["sim_metric_cagr", fmtPct(strat.cagr, 2), fmtPct(bh.cagr, 2)],
            ["sim_metric_vol", fmtPct(strat.annualized_vol, 2), fmtPct(bh.annualized_vol, 2)],
            ["sim_metric_sharpe", fmtNum(strat.sharpe, 2) + " (" + fmtNum(strat.deflated_sharpe, 2) + ")", fmtNum(bh.sharpe, 2)],
            ["sim_metric_sortino", fmtNum(strat.sortino, 2), fmtNum(bh.sortino, 2)],
            ["sim_metric_max_dd", fmtPct(strat.max_drawdown, 1) + " (" + (strat.max_drawdown_days || 0) + "j)",
                fmtPct(bh.max_drawdown, 1) + " (" + (bh.max_drawdown_days || 0) + "j)"],
            ["sim_metric_turnover", fmtNum(strat.turnover_annualized, 2), "—"],
            ["sim_metric_hit_rate", fmtPct(strat.hit_rate, 1), "—"],
            ["sim_metric_profit_factor", fmtNum(strat.profit_factor, 2), "—"],
            ["sim_metric_avg_exposure", fmtPct(strat.avg_exposure, 1), fmtPct(bh.avg_exposure, 1)],
            ["sim_metric_break_even", (strat.break_even_cost_bps === null || strat.break_even_cost_bps === undefined ||
                Number.isNaN(strat.break_even_cost_bps)) ? "—" : fmtNum(strat.break_even_cost_bps, 1) + " bps", "—"],
        ];
        var tbody = document.querySelector("#sim-metrics-table tbody");
        tbody.innerHTML = rows.map(function (r) {
            return "<tr><td>" + tr(r[0], r[0]) + "</td><td>" + r[1] + "</td><td>" + r[2] + "</td></tr>";
        }).join("");
    }

    function renderTradesTable(tradeReturns) {
        var tbody = document.querySelector("#sim-trades-table tbody");
        var downloadLink = document.getElementById("sim-trades-download");
        if (!tradeReturns.length) {
            tbody.innerHTML = '<tr><td colspan="2" class="hint">' + tr("sim_trades_none", "No trades.") + "</td></tr>";
            downloadLink.classList.add("hidden");
            return;
        }
        tbody.innerHTML = tradeReturns.map(function (r, i) {
            return "<tr><td>" + (i + 1) + "</td><td>" + fmtPct(r, 2) + "</td></tr>";
        }).join("");
        var csv = "trade,return\n" + tradeReturns.map(function (r, i) { return (i + 1) + "," + r; }).join("\n");
        var blob = new Blob([csv], { type: "text/csv" });
        downloadLink.href = URL.createObjectURL(blob);
        downloadLink.download = "trades.csv";
        downloadLink.classList.remove("hidden");
    }

    // --- graphiques canvas, sans dépendance externe (même technique que market.js) ---

    function drawLine(canvas, series1, series2, isDrawdown) {
        if (!canvas) return;
        var ctx = canvas.getContext("2d");
        var w = canvas.width, h = canvas.height, pad = 30;
        ctx.clearRect(0, 0, w, h);
        var all = series1.concat(series2 || []).filter(function (v) { return v !== null && v !== undefined && !Number.isNaN(v); });
        if (all.length < 2) return;

        var min = isDrawdown ? Math.min.apply(null, all) : Math.min.apply(null, all);
        var max = isDrawdown ? 0 : Math.max.apply(null, all);
        if (min === max) { min -= 0.01; max += 0.01; }
        var muted = getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#9aa1ac";
        var gold = getComputedStyle(document.documentElement).getPropertyValue("--gold-1").trim() || "#E8C97A";
        var accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#4f8cff";

        function plot(series, color) {
            if (!series.length) return;
            var xStep = (w - 2 * pad) / (series.length - 1);
            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            var started = false;
            for (var i = 0; i < series.length; i++) {
                var v = series[i];
                if (v === null || v === undefined || Number.isNaN(v)) continue;
                var x = pad + i * xStep;
                var y = h - pad + ((v - min) / (max - min)) * -(h - 2 * pad);
                if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
            }
            ctx.stroke();
        }

        ctx.fillStyle = muted;
        ctx.font = "10px sans-serif";
        ctx.fillText(fmtNum(max, 2), 2, pad);
        ctx.fillText(fmtNum(min, 2), 2, h - pad + 4);

        if (series2 && series2.length) plot(series2, muted);
        plot(series1, isDrawdown ? "#C1544C" : gold);
    }

    function drawHistogram(canvas, values) {
        if (!canvas) return;
        var ctx = canvas.getContext("2d");
        var w = canvas.width, h = canvas.height, pad = 24;
        ctx.clearRect(0, 0, w, h);
        if (!values.length) return;
        var nBins = Math.min(20, Math.max(5, Math.floor(Math.sqrt(values.length))));
        var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
        if (min === max) { min -= 0.01; max += 0.01; }
        var binW = (max - min) / nBins;
        var bins = new Array(nBins).fill(0);
        values.forEach(function (v) {
            var idx = Math.min(nBins - 1, Math.max(0, Math.floor((v - min) / binW)));
            bins[idx]++;
        });
        var maxCount = Math.max.apply(null, bins);
        var barW = (w - 2 * pad) / nBins;
        var gold = getComputedStyle(document.documentElement).getPropertyValue("--gold-1").trim() || "#E8C97A";
        var zeroBin = (0 - min) / binW;
        for (var i = 0; i < nBins; i++) {
            var barH = (bins[i] / maxCount) * (h - 2 * pad);
            ctx.fillStyle = (i + 0.5) >= zeroBin ? "#3FA985" : "#C1544C";
            ctx.fillRect(pad + i * barW, h - pad - barH, barW - 1, barH);
        }
    }
})();
