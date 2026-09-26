(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }

    // Une toile ne peut pas heriter d'une couleur CSS : elle doit la LIRE.
    // Les jetons sont donc la seule source, sans valeur de repli codee en
    // dur -- un repli survit aux remplacements d'identite et repeint
    // silencieusement l'ancien monde (c'est exactement ce qui s'est produit
    // avec `--gold-1`). Si le jeton disparait, on veut le voir tout de suite.
    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }
    var MONO = token("--mono") || "monospace";
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
    var segmentSelect = document.getElementById("sim-segment");
    var segmentInfo = document.getElementById("sim-segment-info");
    var assetClassSelect = document.getElementById("sim-asset-class");
    var spreadInput = document.getElementById("sim-spread-bps");
    var commissionInput = document.getElementById("sim-commission-bps");

    // Phase 10 -- doit rester synchronisé avec simulate.engine.ASSET_CLASS_FRICTION_BPS
    // (justification des ordres de grandeur documentée là-bas, en commentaire).
    var ASSET_CLASS_BPS = { futures_liquid: 1.0, us_large_cap: 3.0, eu_mid_cap: 15.0, crypto_non_major: 30.0 };

    function applyAssetClassPreset() {
        var v = ASSET_CLASS_BPS[assetClassSelect.value];
        if (v !== undefined) {
            spreadInput.value = (v / 2).toFixed(2);
            commissionInput.value = (v / 2).toFixed(2);
        }
    }

    assetClassSelect.addEventListener("change", applyAssetClassPreset);
    // Défaut pré-rempli dès le chargement (pas seulement au changement) : le
    // <select> porte déjà un `selected` documenté dans le template (futures_liquid,
    // 1bp) -- cet appel garde le JS comme source de vérité unique du calcul
    // spread/commission, y compris pour la valeur initiale.
    applyAssetClassPreset();

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

    var METRIC_ANNOTATIONS = {
        "sim_metric_cagr": "Compound Annual Growth Rate (CAGR) — taux de croissance annuel composé du portefeuille.",
        "sim_metric_vol": "Volatilité annualisée — écart-type des rendements annualisé. Plus bas = plus stable.",
        "sim_metric_sharpe": "Ratio de Sharpe — rendement excédentaire par unité de risque (volatilité). Plus haut = mieux. Les valeurs entre parenthèses incluent la correction de Sharpe déflaté pour tenir compte du surapprentissage.",
        "sim_metric_sortino": "Ratio de Sortino — comme Sharpe, mais ne compte que la volatilité à la baisse (rend de négatifs). Plus haut = mieux.",
        "sim_metric_max_dd": "Drawdown maximal — pire baisse cumulative depuis un pic. La valeur entre parenthèses est la durée en jours. Un DD plus petit est préférable.",
        "sim_metric_turnover": "Turnover annualisé — nombre de fois où le portefeuille est rebalancé par an. Indique l'activité de trading.",
        "sim_metric_hit_rate": "Hit Rate ou Win Rate — pourcentage de trades rentables. Plus haut = meilleur edge, mais doit être combiné avec Profit Factor.",
        "sim_metric_profit_factor": "Profit Factor — ratio des gains totaux sur les pertes totales. Un PF > 1 est rentable; > 1.5 est solide.",
        "sim_metric_avg_exposure": "Exposition moyenne au marché — proportion moyenne du capital investi. 1 = toujours 100% investi, 0.5 = 50% en moyenne.",
        "sim_metric_break_even": "Break Even Cost — coûts maximums tolérés (en basis points) pour que la stratégie reste rentable au seuil."
    };

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
        if (segmentInfo) segmentInfo.classList.add("hidden");
        try {
            var res = await fetch("/api/simulate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ trial_id: parseInt(trialId, 10), params: collectParams(),
                                       segment: (segmentSelect && segmentSelect.value) || null }),
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
        // Une plaque de tracé vide est un trou noir de 400px : au repos, les
        // trois panneaux de résultat portent leur état vide, et c'est ce
        // drapeau qui le retire au premier rendu. Marqué sur `<body>` pour que
        // le CSS le lise sans que chaque panneau ait à connaître les autres.
        document.body.dataset.simLoaded = "";
        lastRender = data;
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
        renderSegment(data);

        lastDates = (data.equity_curve || []).map(function (p) { return p.t; });
        var eqPoints = (data.equity_curve || []).map(function (p) { return p.v; });
        var bhPoints = (data.buy_and_hold_curve || []).map(function (p) { return p.v; });
        drawLine(document.getElementById("sim-equity-canvas"), eqPoints, bhPoints);
        var ddPoints = (data.drawdown_curve || []).map(function (p) { return p.v; });
        drawLine(document.getElementById("sim-drawdown-canvas"), ddPoints, [], true);

        lastTradeReturns = data.trade_returns || [];
        drawHistogram(document.getElementById("sim-dist-canvas"), lastTradeReturns);

        renderMetricsTable(data.strategy || {}, data.buy_and_hold || {});
        renderTradesTable(lastTradeReturns);
        describeCanvases(eqPoints, bhPoints, ddPoints, lastTradeReturns);
    }

    /* F06 : le segment reellement simule (le defaut de l'API peut differer du
       choix "Auto") et son avertissement -- un Sharpe sur le segment test est
       biaise par la selection, il ne doit jamais s'afficher sans le dire. */
    function renderSegment(data) {
        if (!segmentInfo || !data.segment) return;
        var avail = data.available_segments || {};
        var list = Object.keys(avail).map(function (k) { return k + " (" + avail[k] + ")"; }).join(", ") || "—";
        var text = fmtStr(tr("sim_segment_used", "Simulated segment: {segment} ({n} signals). Available: {available}."),
            { segment: data.segment, n: data.n_signals, available: list });
        segmentInfo.textContent = "";
        var line = document.createElement("div");
        line.textContent = text;
        segmentInfo.appendChild(line);
        if (data.segment_warning) {
            var warn = document.createElement("div");
            warn.textContent = data.segment_warning;
            segmentInfo.appendChild(warn);
        }
        segmentInfo.className = "banner " + (data.segment_warning ? "banner-warning" : "banner-info");
    }

    var lastRender = null;
    window.addEventListener("patrick:themechange", function () { if (lastRender) renderResult(lastRender); });
    var resizeTimer = null;
    window.addEventListener("resize", function () {
        if (!lastRender) return;
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(function () { renderResult(lastRender); }, 150);
    });

    /* Équivalents textuels des trois toiles. Un graphique sans texte de
       remplacement n'existe pas pour un lecteur d'écran, et ces trois-là
       portent l'intégralité du résultat d'une simulation. Écrit à partir des
       vraies séries, jamais d'un libellé générique. */
    function describeCanvases(eq, bh, dd, trades) {
        function setLabel(id, text) {
            var el = document.getElementById(id);
            if (el) el.setAttribute("aria-label", text);
        }
        if (eq.length) {
            setLabel("sim-equity-canvas", fmtStr(tr("sim_aria_equity",
                "Equity curve over {n} points: {first} to {last}, against buy-and-hold ending at {bh}."),
                { n: eq.length, first: fmtNum(eq[0], 3), last: fmtNum(eq[eq.length - 1], 3),
                  bh: bh.length ? fmtNum(bh[bh.length - 1], 3) : "—" }));
        }
        if (dd.length) {
            setLabel("sim-drawdown-canvas", fmtStr(tr("sim_aria_drawdown",
                "Drawdown over {n} points, deepest {max}."),
                { n: dd.length, max: fmtNum(Math.min.apply(null, dd), 3) }));
        }
        if (trades.length) {
            var pos = 0, neg = 0;
            for (var i = 0; i < trades.length; i++) { if (trades[i] > 0) pos++; else if (trades[i] < 0) neg++; }
            setLabel("sim-dist-canvas", fmtStr(tr("sim_aria_dist",
                "Distribution of {n} trades: {pos} winning, {neg} losing, worst {min}, best {max}."),
                { n: trades.length, pos: pos, neg: neg,
                  min: fmtNum(Math.min.apply(null, trades), 4),
                  max: fmtNum(Math.max.apply(null, trades), 4) }));
        }
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
            var label = tr(r[0], r[0]);
            var annotation = METRIC_ANNOTATIONS[r[0]] || "";
            var help = annotation ? '<span class="metric-help" title="' + escapeHtml(annotation) + '">?</span>' : "";
            return '<tr class="metric-row"><td class="metric-label">' + label + ' ' + help + '</td><td class="metric-value num">' + r[1] + '</td><td class="metric-value num">' + r[2] + "</td></tr>";
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
            return '<tr><td class="num">' + (i + 1) + '</td><td class="num">' + fmtPct(r, 2) + "</td></tr>";
        }).join("");
        var csv = "trade,return\n" + tradeReturns.map(function (r, i) { return (i + 1) + "," + r; }).join("\n");
        var blob = new Blob([csv], { type: "text/csv" });
        downloadLink.href = URL.createObjectURL(blob);
        downloadLink.download = "trades.csv";
        downloadLink.classList.remove("hidden");
    }

    // --- graphiques canvas, sans dépendance externe (même technique que market.js) ---

    // HiDPI canvas: the backing store follows the CSS box x devicePixelRatio,
    // drawing happens in CSS pixels -- text stays crisp and is never
    // stretched by `width: 100%` (the fixed 520px backing store was).
    function setupCanvas(canvas, cssHeight) {
        var ratio = window.devicePixelRatio || 1;
        var cssW = Math.max(240, Math.round(canvas.getBoundingClientRect().width || canvas.parentNode.clientWidth || 520));
        canvas.style.height = cssHeight + "px";
        canvas.width = Math.round(cssW * ratio);
        canvas.height = Math.round(cssHeight * ratio);
        var ctx = canvas.getContext("2d");
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, cssW, cssHeight);
        return { ctx: ctx, w: cssW, h: cssHeight };
    }
    function niceTicks(min, max, count) {
        var span = max - min;
        if (!(span > 0)) return [min];
        var step = Math.pow(10, Math.floor(Math.log10(span / count)));
        var err = (span / count) / step;
        if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
        var ticks = [];
        for (var v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(v);
        return ticks;
    }
    var lastDates = [];

    function drawLine(canvas, series1, series2, isDrawdown) {
        if (!canvas) return;
        var box = setupCanvas(canvas, isDrawdown ? 130 : 240);
        var ctx = box.ctx, w = box.w, h = box.h;
        var padL = 56, padR = 14, padT = 12, padB = 26;
        var all = series1.concat(series2 || []).filter(function (v) { return v !== null && v !== undefined && !Number.isNaN(v); });
        if (all.length < 2) return;

        var min = Math.min.apply(null, all);
        var max = isDrawdown ? 0 : Math.max.apply(null, all);
        if (min === max) { min -= 0.01; max += 0.01; }
        var n = Math.max(series1.length, (series2 || []).length);
        function xAt(i) { return padL + (n > 1 ? i / (n - 1) : 0) * (w - padL - padR); }
        function yAt(v) { return padT + (1 - (v - min) / (max - min)) * (h - padT - padB); }

        var muted = token("--ink-text-2");
        ctx.font = "11px " + MONO;
        ctx.textBaseline = "middle";
        ctx.textAlign = "right";
        var ticks = niceTicks(min, max, isDrawdown ? 2 : 4);
        ticks.forEach(function (tv) {
            var y = Math.round(yAt(tv)) + 0.5;
            ctx.strokeStyle = token("--chart-grid");
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
            ctx.fillStyle = muted;
            ctx.fillText(isDrawdown ? fmtPct(tv, 0) : fmtNum(tv, 2), padL - 8, y);
        });
        if (!isDrawdown && min < 1 && max > 1) {
            var y1 = Math.round(yAt(1)) + 0.5;
            ctx.strokeStyle = token("--color-border");
            ctx.setLineDash([3, 3]);
            ctx.beginPath(); ctx.moveTo(padL, y1); ctx.lineTo(w - padR, y1); ctx.stroke();
            ctx.setLineDash([]);
        }

        ctx.textBaseline = "alphabetic";
        ctx.fillStyle = muted;
        var labels = [0, Math.floor((n - 1) / 2), n - 1];
        labels.forEach(function (idx, k) {
            var text = lastDates[idx] || String(idx);
            ctx.textAlign = k === 0 ? "left" : (k === 2 ? "right" : "center");
            ctx.fillText(text, xAt(idx), h - 7);
        });

        function plot(series, color, width) {
            if (!series || !series.length) return;
            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = width;
            ctx.lineJoin = "round";
            var started = false;
            for (var i = 0; i < series.length; i++) {
                var v = series[i];
                if (v === null || v === undefined || Number.isNaN(v)) continue;
                if (!started) { ctx.moveTo(xAt(i), yAt(v)); started = true; } else { ctx.lineTo(xAt(i), yAt(v)); }
            }
            ctx.stroke();
        }
        if (isDrawdown) {
            ctx.beginPath();
            ctx.moveTo(xAt(0), yAt(0));
            for (var i = 0; i < series1.length; i++) {
                var v = series1[i];
                if (v === null || v === undefined || Number.isNaN(v)) continue;
                ctx.lineTo(xAt(i), yAt(v));
            }
            ctx.lineTo(xAt(series1.length - 1), yAt(0));
            ctx.closePath();
            ctx.globalAlpha = 0.18;
            ctx.fillStyle = token("--error-ink");
            ctx.fill();
            ctx.globalAlpha = 1;
            plot(series1, token("--error-ink"), 1.25);
        } else {
            plot(series2, token("--ink-text-2"), 1.25);
            plot(series1, token("--accent-ink"), 1.75);
        }
    }

    function drawHistogram(canvas, values) {
        if (!canvas) return;
        var box = setupCanvas(canvas, 200);
        var ctx = box.ctx, w = box.w, h = box.h;
        var padL = 40, padR = 14, padT = 12, padB = 26;
        if (!values.length) return;
        var nBins = Math.min(30, Math.max(5, Math.floor(Math.sqrt(values.length))));
        var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
        if (min === max) { min -= 0.01; max += 0.01; }
        var binW = (max - min) / nBins;
        var bins = new Array(nBins).fill(0);
        values.forEach(function (v) {
            var idx = Math.min(nBins - 1, Math.max(0, Math.floor((v - min) / binW)));
            bins[idx]++;
        });
        var maxCount = Math.max.apply(null, bins);
        var plotW = w - padL - padR, plotH = h - padT - padB;
        var barW = plotW / nBins;
        var gain = token("--ok-ink"), loss = token("--error-ink");
        var muted = token("--ink-text-2");

        ctx.font = "11px " + MONO;
        ctx.textBaseline = "middle";
        ctx.textAlign = "right";
        niceTicks(0, maxCount, 3).forEach(function (tv) {
            var y = Math.round(padT + plotH - (tv / maxCount) * plotH) + 0.5;
            ctx.strokeStyle = token("--chart-grid");
            ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
            ctx.fillStyle = muted;
            ctx.fillText(String(Math.round(tv)), padL - 8, y);
        });
        var zeroBin = (0 - min) / binW;
        for (var i = 0; i < nBins; i++) {
            var barH = (bins[i] / maxCount) * plotH;
            ctx.fillStyle = (i + 0.5) >= zeroBin ? gain : loss;
            ctx.fillRect(padL + i * barW + 1, padT + plotH - barH, Math.max(1, barW - 2), barH);
        }
        ctx.textBaseline = "alphabetic";
        ctx.fillStyle = muted;
        ctx.textAlign = "left";
        ctx.fillText(fmtPct(min, 1), padL, h - 7);
        ctx.textAlign = "center";
        ctx.fillText(fmtPct(min + (max - min) / 2, 1), padL + plotW / 2, h - 7);
        ctx.textAlign = "right";
        ctx.fillText(fmtPct(max, 1), w - padR, h - 7);
    }
})();
