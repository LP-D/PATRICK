(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }

    // Lecture des jetons sans repli code en dur : voir la note identique
    // dans simulate.js -- un repli survit au remplacement d'identite et
    // repeint l'ancien monde sans que rien ne le signale.
    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }
    var MONO = token("--mono") || "monospace";
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; });
    }

    var targetSelect = document.getElementById("target_symbol");
    var canvas = document.getElementById("preview-canvas");
    var tooltip = document.getElementById("preview-tooltip");
    var statusEl = document.getElementById("preview-status");
    var rangesEl = document.getElementById("preview-ranges");
    var newsList = document.getElementById("news-list");

    var currentPeriod = "1y";
    var currentSymbol = null;
    var currentSeries = null; // {dates, closes}

    function fmtNum(v) {
        return v.toLocaleString(document.documentElement.lang || "fr", { maximumFractionDigits: 2 });
    }

    function drawChart(series) {
        if (!canvas) return;
        var ctx = canvas.getContext("2d");
        var w = canvas.width, h = canvas.height;
        var pad = 28;
        ctx.clearRect(0, 0, w, h);

        var closes = series.closes || [];
        if (closes.length < 2) {
            ctx.fillStyle = token("--ink-text-2");
            ctx.font = "13px " + MONO;
            ctx.fillText(tr("preview_no_data", "No data for this period."), pad, h / 2);
            canvas.setAttribute("aria-label", tr("preview_aria_empty",
                "Target price history — nothing plotted yet."));
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

        // Grille de la plaque : sans elle, la toile est un aplat d'encre avec
        // une courbe posee dessus. Une plaque d'instrument porte ses
        // graduations -- c'est ce qui la fait lire comme une mesure et non
        // comme une decoration. Quatre lignes, jamais plus : au-dela elles
        // concurrencent la courbe.
        ctx.strokeStyle = rule;
        ctx.lineWidth = 1;
        for (var gi = 0; gi <= 3; gi++) {
            var gy = Math.round(pad + (gi / 3) * (h - 2 * pad)) + 0.5;
            ctx.beginPath();
            ctx.moveTo(pad, gy);
            ctx.lineTo(w - pad, gy);
            ctx.stroke();
        }

        // axis labels (min/max)
        ctx.fillStyle = muted;
        ctx.font = "11px " + MONO;
        ctx.fillText(fmtNum(max), 2, yAt(max) + 4);
        ctx.fillText(fmtNum(min), 2, yAt(min) + 4);

        ctx.beginPath();
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        for (var i = 0; i < closes.length; i++) {
            var x = xAt(i), y = yAt(closes[i]);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        canvas._baseImage = ctx.getImageData(0, 0, w, h);

        // Équivalent textuel : sans lui, la toile ne dit rien du tout à un
        // lecteur d'écran. Réécrit à chaque tracé, avec les vraies bornes.
        canvas.setAttribute("aria-label", fmtStr(
            tr("preview_aria", "{symbol} price over {period}: {n} points, low {min} to high {max}, last {last}."),
            { symbol: currentSymbol || "?", period: currentPeriod, n: closes.length,
              min: fmtNum(min), max: fmtNum(max), last: fmtNum(closes[closes.length - 1]) }));

        canvas.onmousemove = function (ev) {
            var rect = canvas.getBoundingClientRect();
            var mx = (ev.clientX - rect.left) * (canvas.width / rect.width);
            var idx = Math.round((mx - pad) / xStep);
            if (idx < 0 || idx >= closes.length) { if (tooltip) tooltip.classList.add("hidden"); return; }
            var x = xAt(idx), y = yAt(closes[idx]);

            ctx.putImageData(canvas._baseImage, 0, 0);
            ctx.beginPath();
            ctx.strokeStyle = rule;
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.moveTo(x, pad);
            ctx.lineTo(x, h - pad);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.beginPath();
            ctx.fillStyle = accent;
            ctx.arc(x, y, 3, 0, Math.PI * 2);
            ctx.fill();

            if (tooltip) {
                tooltip.textContent = (series.dates[idx] || "") + " — " + fmtNum(closes[idx]);
                tooltip.style.left = Math.min(x + 8, w - 140) + "px";
                tooltip.style.top = Math.max(y - 24, 0) + "px";
                tooltip.classList.remove("hidden");
            }
        };
        canvas.onmouseleave = function () {
            if (tooltip) tooltip.classList.add("hidden");
            ctx.putImageData(canvas._baseImage, 0, 0);
        };
    }

    function loadPreview(symbol, period) {
        if (!canvas) return;
        currentSymbol = symbol;
        if (statusEl) statusEl.textContent = tr("preview_loading", "Loading…");
        fetch("/api/preview/" + encodeURIComponent(symbol) + "?period=" + encodeURIComponent(period))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                currentSeries = data;
                drawChart(data);
                if (statusEl) {
                    statusEl.textContent = data.error ? fmtStr(tr("preview_unavailable", "Unavailable: {error}"), { error: data.error })
                        : (data.closes && data.closes.length ? "" : tr("preview_no_data", "No data for this period."));
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
        var symbol = targetSelect.value;
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
            if (targetSelect && targetSelect.value) loadPreview(targetSelect.value, currentPeriod);
        });
    }

    // Liste d'alertes (movers) : rafraîchie côté serveur toutes les 30 min ; on
    // repolle ici juste pour refléter une page restée ouverte longtemps, sans
    // recharger toute la page.
    var moversGainers = document.getElementById("movers-gainers");
    var moversLosers = document.getElementById("movers-losers");
    var moversUpdated = document.getElementById("movers-updated");

    function renderMoversList(el, rows, sign) {
        if (!el) return;
        if (!rows || !rows.length) {
            el.innerHTML = "<li class=\"hint\"></li>";
            el.firstChild.textContent = tr("movers_no_data", "No data yet.");
            return;
        }
        el.innerHTML = "";
        rows.forEach(function (row) {
            var li = document.createElement("li");
            var symSpan = document.createElement("span");
            symSpan.className = "movers-symbol";
            symSpan.textContent = row.symbol;
            var labelSpan = document.createElement("span");
            labelSpan.className = "movers-label";
            labelSpan.textContent = row.label;
            var pctSpan = document.createElement("span");
            pctSpan.className = "movers-pct " + (sign > 0 ? "movers-up" : "movers-down");
            pctSpan.textContent = (sign > 0 ? "+" : "") + row.pct + "%";
            li.appendChild(symSpan);
            li.appendChild(labelSpan);
            li.appendChild(pctSpan);
            el.appendChild(li);
        });
    }

    function pollMovers() {
        fetch("/api/movers").then(function (r) { return r.json(); }).then(function (data) {
            renderMoversList(moversGainers, data.gainers, 1);
            renderMoversList(moversLosers, data.losers, -1);
            if (moversUpdated) {
                moversUpdated.textContent = data.updated_at
                    ? fmtStr(tr("movers_updated_at", "Updated at {time}"), { time: data.updated_at })
                    : tr("movers_computing", "Computing (every 30 min)…");
            }
        }).catch(function () {});
    }

    if (moversGainers || moversLosers) {
        setInterval(pollMovers, 5 * 60 * 1000);
    }
})();
