/* Page Placements (/placements) : import de VL, simulation en tâche de fond, résultats.
   Deux parties : des fonctions PURES (choix de la meilleure allocation, CSV, couleurs) testées sous Node (tests/js/placements.test.js),
   puis l'interface, lancée seulement si la page est là. Tout texte vient du bloc JSON `#pl-i18n` (clés `pl_*`). Le serveur ne fait aucun
   calcul à l'affichage : les jeux de données, le dernier résultat et l'avancement arrivent par /api/placements/*. */
(function (root) {
    "use strict";

    // ------------------------------------------------------------------ fonctions pures
    var CRITERIA = ["wf_sharpe", "sharpe", "cagr", "vol", "sortino", "mdd", "div_ratio"];

    function finiteOr(v, fallback) { return v === null || v === undefined || !isFinite(v) ? fallback : v; }

    function criterionValue(pf, crit) {
        var wf = pf.walk_forward && pf.walk_forward.sharpe;
        var m = pf.metrics || {};
        if (crit === "wf_sharpe") return (wf === null || wf === undefined) ? -Infinity : wf;
        if (crit === "sharpe") return m.sharpe;
        if (crit === "cagr") return m.cagr;
        if (crit === "vol") return -m.vol;
        if (crit === "sortino") return finiteOr(m.sortino, -Infinity);
        if (crit === "mdd") return finiteOr(m.max_dd_daily, finiteOr(m.max_dd_monthly, -Infinity));      // la baisse la moins profonde
        if (crit === "div_ratio") return finiteOr(m.div_ratio, -Infinity);
        return -Infinity;
    }

    // Toutes les allocations d'une fenêtre et d'un plafond, triées de la meilleure à la moins bonne selon un critère (tri stable).
    function rankBy(portfolios, windowId, cap, crit) {
        var capKey = function (c) { return c === null || c === undefined || c >= 1 ? 1 : c; };
        return portfolios.filter(function (pf) { return pf.window === windowId && capKey(pf.cap) === capKey(cap); })
            .map(function (pf, i) { return { pf: pf, i: i, v: criterionValue(pf, crit), weak: crit === "wf_sharpe" && !!(pf.walk_forward && pf.walk_forward.peu_fiable) }; })
            .sort(function (a, b) { return (a.weak - b.weak) || (b.v - a.v) || (a.i - b.i); })
            .map(function (x) { return x.pf; });
    }

    // ---- statistiques des rendements mensuels (distribution, loi normale, quantiles)
    function returnsFromGrowth(values) {
        var out = [];
        for (var i = 1; i < (values || []).length; i++) {
            if (isFinite(values[i]) && isFinite(values[i - 1]) && values[i - 1] !== 0) out.push(values[i] / values[i - 1] - 1);
        }
        return out;
    }

    // Quantile à interpolation linéaire (méthode par défaut de numpy) d'un tableau TRIÉ.
    function quantile(sorted, q) {
        if (!sorted.length) return NaN;
        var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
        return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
    }

    // Moments et test de normalité de Jarque-Bera (khi-deux à 2 degrés de liberté : p = exp(-JB/2)). `kurt` = aplatissement en excès.
    function moments(xs) {
        var n = xs.length;
        if (n < 3) return { n: n, mean: NaN, sd: NaN, skew: NaN, kurt: NaN, jb: NaN, jb_p: NaN };
        var mean = xs.reduce(function (a, b) { return a + b; }, 0) / n;
        var m2 = 0, m3 = 0, m4 = 0;
        xs.forEach(function (x) { var d = x - mean; m2 += d * d; m3 += d * d * d; m4 += d * d * d * d; });
        m2 /= n; m3 /= n; m4 /= n;
        var skew = m2 > 0 ? m3 / Math.pow(m2, 1.5) : 0, kurt = m2 > 0 ? m4 / (m2 * m2) - 3 : 0;
        var jb = n / 6 * (skew * skew + kurt * kurt / 4);
        return { n: n, mean: mean, sd: Math.sqrt(m2 * n / (n - 1)), skew: skew, kurt: kurt, jb: jb, jb_p: Math.exp(-jb / 2) };
    }

    function normPdf(x, mean, sd) {
        if (!(sd > 0)) return 0;
        var z = (x - mean) / sd;
        return Math.exp(-0.5 * z * z) / (sd * Math.sqrt(2 * Math.PI));
    }

    // Inverse de la loi normale centrée réduite (approximation rationnelle d'Acklam, erreur relative < 1,2e-9).
    function normInv(p) {
        if (p <= 0) return -Infinity;
        if (p >= 1) return Infinity;
        var a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.3577518672690, -30.66479806614716, 2.506628277459239];
        var b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
        var c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
        var d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
        var q, r;
        if (p < 0.02425) {
            q = Math.sqrt(-2 * Math.log(p));
            return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
        }
        if (p > 1 - 0.02425) return -normInv(1 - p);
        q = p - 0.5; r = q * q;
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
    }

    function histogram(xs, bins) {
        var lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs);
        if (!xs.length || !isFinite(lo)) return { edges: [], counts: [] };
        if (hi <= lo) { lo -= 0.005; hi += 0.005; }
        var k = bins || Math.max(8, Math.min(40, Math.round(Math.sqrt(xs.length) * 1.6)));
        var w = (hi - lo) / k, edges = [], counts = [];
        for (var i = 0; i <= k; i++) edges.push(lo + w * i);
        for (i = 0; i < k; i++) counts.push(0);
        xs.forEach(function (x) { counts[Math.min(k - 1, Math.max(0, Math.floor((x - lo) / w)))] += 1; });
        return { edges: edges, counts: counts };
    }

    // Rendements mensuels rangés année × mois (`dates` = fins de mois ISO, une de plus que de rendements : la base 100 du départ).
    function monthlyTable(dates, rets) {
        var years = {}, order = [];
        rets.forEach(function (r, i) {
            var d = String(dates[i + 1] || ""), y = parseInt(d.slice(0, 4), 10), m = parseInt(d.slice(5, 7), 10) - 1;
            if (!isFinite(y) || m < 0 || m > 11) return;
            if (!years[y]) { years[y] = { year: y, months: [null, null, null, null, null, null, null, null, null, null, null, null] }; order.push(y); }
            years[y].months[m] = r;
        });
        return order.sort().map(function (y) {
            var row = years[y], prod = 1, n = 0;
            row.months.forEach(function (r) { if (r !== null) { prod *= 1 + r; n += 1; } });
            row.total = prod - 1;
            row.partial = n < 12;
            return row;
        });
    }

    // Rendement et volatilité annualisée glissants sur `win` mois.
    function rolling(rets, win) {
        var ret = [], vol = [];
        for (var i = 0; i < rets.length; i++) {
            if (i + 1 < win) { ret.push(null); vol.push(null); continue; }
            var slice = rets.slice(i + 1 - win, i + 1), prod = 1;
            slice.forEach(function (r) { prod *= 1 + r; });
            var m = moments(slice);
            ret.push(Math.pow(prod, 12 / win) - 1);
            vol.push(m.sd * Math.sqrt(12));
        }
        return { ret: ret, vol: vol };
    }

    // Histogramme + loi normale de même moyenne et même écart-type + un trait par quantile (SVG, chaîne échappée).
    // o = {edges, counts, mean, sd, quantiles: [{q, v}], marks: [{v, label, kind}], fmt: fn(v) -> texte, width, height}
    function distSvg(o) {
        var width = o.width || 760, height = o.height || 260;
        if (!o.edges || o.edges.length < 2) return "";
        var L = 44, R = 14, T = 22, B = 30, W = width - L - R, H = height - T - B;
        var x0 = o.edges[0], x1 = o.edges[o.edges.length - 1], total = o.counts.reduce(function (a, b) { return a + b; }, 0) || 1;
        var binW = (x1 - x0) / o.counts.length;
        var dens = o.counts.map(function (c) { return c / total / binW; });
        var curve = [];
        for (var i = 0; i <= 80; i++) { var xv = x0 + (x1 - x0) * i / 80; curve.push([xv, normPdf(xv, o.mean, o.sd)]); }
        var yMax = Math.max(Math.max.apply(null, dens), Math.max.apply(null, curve.map(function (p) { return p[1]; }))) * 1.08 || 1;
        function X(v) { return (L + (v - x0) / ((x1 - x0) || 1) * W).toFixed(1); }
        function Y(v) { return (T + (1 - v / yMax) * H).toFixed(1); }
        var fmtv = o.fmt || function (v) { return (v * 100).toFixed(1) + " %"; };
        var out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + width + " " + height + '" class="pl-dist" role="img">'];
        out.push('<line class="pl-sc-grid" x1="' + L + '" x2="' + (L + W) + '" y1="' + Y(0) + '" y2="' + Y(0) + '"/>');
        dens.forEach(function (dv, j) {
            var a = o.edges[j], b = o.edges[j + 1];
            out.push('<rect class="pl-dist-bar" x="' + X(a) + '" y="' + Y(dv) + '" width="' + Math.max(0.5, parseFloat(X(b)) - parseFloat(X(a)) - 1).toFixed(1) +
                     '" height="' + (parseFloat(Y(0)) - parseFloat(Y(dv))).toFixed(1) + '"><title>' + esc(fmtv(a) + " → " + fmtv(b) + " : " + o.counts[j]) + "</title></rect>");
        });
        if (o.sd > 0) out.push('<polyline class="pl-dist-normal" points="' + curve.map(function (p) { return X(p[0]) + "," + Y(p[1]); }).join(" ") + '"/>');
        (o.quantiles || []).forEach(function (q, k) {
            if (!isFinite(q.v) || q.v < x0 || q.v > x1) return;
            var cx = X(q.v), main = q.q === 0.5;
            out.push('<line class="pl-dist-q' + (main ? " is-median" : "") + '" x1="' + cx + '" x2="' + cx + '" y1="' + T + '" y2="' + Y(0) + '"/>');
            out.push('<text class="pl-dist-qlabel" x="' + cx + '" y="' + (T - 6 + (k % 2) * 0) + '" text-anchor="middle">P' + Math.round(q.q * 100) + "</text>");
        });
        (o.marks || []).forEach(function (mk) {
            if (!isFinite(mk.v) || mk.v < x0 || mk.v > x1) return;
            var cx = X(mk.v);
            out.push('<line class="pl-dist-mark pl-dist-' + esc(mk.kind || "mark") + '" x1="' + cx + '" x2="' + cx + '" y1="' + T + '" y2="' + Y(0) + '"><title>' + esc(mk.label) + "</title></line>");
        });
        for (i = 0; i <= 4; i++) {
            var tv = x0 + (x1 - x0) * i / 4;
            out.push('<text class="pl-sc-tick" x="' + X(tv) + '" y="' + (T + H + 18) + '" text-anchor="middle">' + esc(fmtv(tv)) + "</text>");
        }
        out.push("</svg>");
        return out.join("");
    }

    // Diagramme quantile-quantile : quantiles observés (y) contre ceux de la loi normale ajustée (x) ; la droite y = x est la normalité.
    function qqSvg(xs, width, height) {
        width = width || 360; height = height || 260;
        if (xs.length < 5) return "";
        var s = xs.slice().sort(function (a, b) { return a - b; }), m = moments(xs);
        var pts = s.map(function (v, i) { return [m.mean + m.sd * normInv((i + 0.5) / s.length), v]; });
        var all = pts.reduce(function (acc, p) { return acc.concat(p); }, []);
        var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), pad = (hi - lo) * 0.05 || 0.01;
        lo -= pad; hi += pad;
        var L = 44, R = 10, T = 10, B = 30, W = width - L - R, H = height - T - B;
        function X(v) { return (L + (v - lo) / (hi - lo) * W).toFixed(1); }
        function Y(v) { return (T + (1 - (v - lo) / (hi - lo)) * H).toFixed(1); }
        var out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + width + " " + height + '" class="pl-qq" role="img">'];
        for (var i = 0; i <= 4; i++) {
            var v = lo + (hi - lo) * i / 4;
            out.push('<line class="pl-sc-grid" x1="' + L + '" x2="' + (L + W) + '" y1="' + Y(v) + '" y2="' + Y(v) + '"/>');
            out.push('<text class="pl-sc-tick" x="' + (L - 5) + '" y="' + Y(v) + '" text-anchor="end" dominant-baseline="middle">' + (v * 100).toFixed(1) + "</text>");
            out.push('<text class="pl-sc-tick" x="' + X(v) + '" y="' + (T + H + 18) + '" text-anchor="middle">' + (v * 100).toFixed(1) + "</text>");
        }
        out.push('<line class="pl-qq-ref" x1="' + X(lo) + '" y1="' + Y(lo) + '" x2="' + X(hi) + '" y2="' + Y(hi) + '"/>');
        pts.forEach(function (p) { out.push('<circle class="pl-qq-pt" cx="' + X(p[0]) + '" cy="' + Y(p[1]) + '" r="2.6"/>'); });
        out.push("</svg>");
        return out.join("");
    }

    // Barres verticales (rendements annuels du portefeuille et du 1/N, moyenne en trait) : rows = [{label, a, b}] en fractions.
    function barsSvg(rows, width, height, meanA) {
        width = width || 760; height = height || 220;
        if (!rows.length) return "";
        var vals = rows.reduce(function (acc, r) { return acc.concat([r.a, r.b].filter(function (v) { return isFinite(v); })); }, [0]);
        var lo = Math.min(0, Math.min.apply(null, vals)) * 1.12, hi = Math.max(0, Math.max.apply(null, vals)) * 1.12 || 0.01;
        var L = 44, R = 10, T = 10, B = 26, W = width - L - R, H = height - T - B, slot = W / rows.length, bw = Math.max(2, slot * 0.36);
        function Y(v) { return (T + (1 - (v - lo) / ((hi - lo) || 1)) * H).toFixed(1); }
        var out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + width + " " + height + '" class="pl-bars" role="img">'];
        for (var i = 0; i <= 4; i++) {
            var v = lo + (hi - lo) * i / 4;
            out.push('<line class="pl-sc-grid" x1="' + L + '" x2="' + (L + W) + '" y1="' + Y(v) + '" y2="' + Y(v) + '"/>');
            out.push('<text class="pl-sc-tick" x="' + (L - 5) + '" y="' + Y(v) + '" text-anchor="end" dominant-baseline="middle">' + (v * 100).toFixed(0) + " %</text>");
        }
        rows.forEach(function (r, k) {
            var x = L + slot * k + slot / 2;
            [["a", r.a, x - bw], ["b", r.b, x]].forEach(function (spec) {
                if (!isFinite(spec[1])) return;
                var y = parseFloat(Y(Math.max(spec[1], 0))), y0 = parseFloat(Y(Math.min(spec[1], 0)));
                out.push('<rect class="pl-bar-' + spec[0] + (spec[1] < 0 ? " is-neg" : "") + '" x="' + spec[2].toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
                         '" height="' + Math.max(0.5, y0 - y).toFixed(1) + '"><title>' + esc(r.label) + " : " + (spec[1] * 100).toFixed(1) + " %</title></rect>");
            });
            if (rows.length <= 24 || k % Math.ceil(rows.length / 24) === 0) out.push('<text class="pl-sc-tick" x="' + x.toFixed(1) + '" y="' + (T + H + 16) + '" text-anchor="middle">' + esc(r.label) + "</text>");
        });
        out.push('<line class="pl-sc-grid pl-zero" x1="' + L + '" x2="' + (L + W) + '" y1="' + Y(0) + '" y2="' + Y(0) + '"/>');
        if (isFinite(meanA)) out.push('<line class="pl-bars-mean" x1="' + L + '" x2="' + (L + W) + '" y1="' + Y(meanA) + '" y2="' + Y(meanA) + '"/>');
        out.push("</svg>");
        return out.join("");
    }

    // La meilleure allocation d'une fenêtre selon un critère, parmi celles dont la volatilité ne dépasse pas `maxVol` (null = sans limite).
    // `null` si aucune ne respecte la limite. Les égalités sont départagées par l'ordre du résultat (stable).
    function pickBest(portfolios, windowId, crit, maxVol) {
        var pool = portfolios.filter(function (pf) {
            return pf.window === windowId && !(maxVol !== null && maxVol !== undefined && pf.metrics.vol > maxVol + 1e-12);
        });
        // Un walk-forward sur moins de 36 mois hors échantillon est du bruit (un fonds quasi monétaire y obtient un Sharpe énorme) : sur ce
        // critère, les portefeuilles au test fiable passent d'abord ; s'il n'y en a aucun dans la fenêtre, on garde les autres.
        if (crit === "wf_sharpe") {
            var reliable = pool.filter(function (pf) { return !(pf.walk_forward && pf.walk_forward.peu_fiable); });
            if (reliable.length) pool = reliable;
        }
        var best = null, bestValue = -Infinity;
        pool.forEach(function (pf) {
            var v = criterionValue(pf, crit);
            if (best === null || v > bestValue) { best = pf; bestValue = v; }
        });
        return best;
    }

    function csvCell(v) {
        var s = v === null || v === undefined ? "" : String(v);
        return /[";\n\r]/.test(s) ? "\"" + s.replace(/"/g, "\"\"") + "\"" : s;
    }
    // CSV (séparateur « ; », ouvrable tel quel dans un Excel français) : lignes = tableaux de valeurs.
    function toCsv(rows) {
        return rows.map(function (r) { return r.map(csvCell).join(";"); }).join("\r\n");
    }

    // Couleur d'une corrélation : intensité = |valeur|, teinte = signe. Retourne une valeur de 0 à 1 pour la variable CSS --v.
    function corrIntensity(v) {
        if (v === null || v === undefined || !isFinite(v)) return 0;
        return Math.min(1, Math.abs(v));
    }

    function maxVolOf(portfolios, windowId) {
        var m = 0;
        portfolios.forEach(function (pf) { if (pf.window === windowId && pf.metrics.vol > m) m = pf.metrics.vol; });
        return m;
    }

    function esc(text) {
        return String(text === null || text === undefined ? "" : text).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c]; });
    }

    // Nuage risque / rendement en SVG (chaîne, données échappées) : supports en points, frontière efficiente en ligne, allocations marquées.
    // data = {funds: [{label, vol, ret}], line: [{vol, ret}], marks: [{label, vol, ret, kind}]} ; vol et ret en fractions annuelles.
    function scatterSvg(data, width, height) {
        var all = data.funds.concat(data.line, data.marks).filter(function (q) { return isFinite(q.vol) && isFinite(q.ret); });
        if (!all.length) return "";
        var xs = all.map(function (q) { return q.vol; }), ys = all.map(function (q) { return q.ret; });
        var x0 = 0, x1 = Math.max.apply(null, xs) * 1.08 || 0.01;
        var y0 = Math.min(0, Math.min.apply(null, ys) * 1.1), y1 = Math.max.apply(null, ys) * 1.12 || 0.01;
        var L = 48, R = 14, T = 12, B = 34, W = width - L - R, H = height - T - B;
        function X(v) { return (L + (v - x0) / (x1 - x0) * W).toFixed(1); }
        function Y(v) { return (T + (1 - (v - y0) / ((y1 - y0) || 1)) * H).toFixed(1); }
        var out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + width + " " + height + '" class="pl-scatter" role="img">'];
        for (var i = 0; i <= 4; i++) {
            var yv = y0 + (y1 - y0) * i / 4, xv = x0 + (x1 - x0) * i / 4;
            out.push('<line class="pl-sc-grid" x1="' + L + '" x2="' + (L + W) + '" y1="' + Y(yv) + '" y2="' + Y(yv) + '"/>');
            out.push('<text class="pl-sc-tick" x="' + (L - 6) + '" y="' + Y(yv) + '" text-anchor="end" dominant-baseline="middle">' + (yv * 100).toFixed(1) + " %</text>");
            out.push('<text class="pl-sc-tick" x="' + X(xv) + '" y="' + (T + H + 16) + '" text-anchor="middle">' + (xv * 100).toFixed(1) + " %</text>");
        }
        if (data.line.length > 1) out.push('<polyline class="pl-sc-line" points="' + data.line.map(function (q) { return X(q.vol) + "," + Y(q.ret); }).join(" ") + '"/>');
        data.funds.forEach(function (q) {
            out.push('<circle class="pl-sc-fund" cx="' + X(q.vol) + '" cy="' + Y(q.ret) + '" r="4"><title>' + esc(q.label) + " · " + (q.vol * 100).toFixed(1) + " % / " + (q.ret * 100).toFixed(1) + " %</title></circle>");
        });
        data.marks.forEach(function (q) {
            var cx = X(q.vol), cy = Y(q.ret), small = q.kind === "pf";
            out.push('<g class="pl-sc-mark pl-sc-' + esc(q.kind) + '"><circle cx="' + cx + '" cy="' + cy + '" r="' + (small ? 4.5 : 7) + '"><title>' + esc(q.label) + " · " +
                     (q.vol * 100).toFixed(1) + " % / " + (q.ret * 100).toFixed(1) + ' %</title></circle><text x="' + (parseFloat(cx) + (small ? 7 : 10)) + '" y="' + cy +
                     '" dominant-baseline="middle">' + esc(q.label) + "</text></g>");
        });
        out.push("</svg>");
        return out.join("");
    }

    // « 2014 1,8\n2015 2,1 » : nombre de lignes « année taux » lisibles (aide à la saisie d'un fonds en euros).
    function countRateLines(text) {
        return String(text || "").split(/\r?\n/).filter(function (line) { return /^\s*\d{4}\s*[;:,=\t ]\s*[-+]?\d+(?:[.,]\d+)?\s*%?\s*$/.test(line); }).length;
    }

    var api = { CRITERIA: CRITERIA, criterionValue: criterionValue, pickBest: pickBest, rankBy: rankBy, toCsv: toCsv, corrIntensity: corrIntensity,
                maxVolOf: maxVolOf, scatterSvg: scatterSvg, esc: esc, countRateLines: countRateLines, returnsFromGrowth: returnsFromGrowth,
                quantile: quantile, moments: moments, normPdf: normPdf, normInv: normInv, histogram: histogram, monthlyTable: monthlyTable,
                rolling: rolling, distSvg: distSvg, qqSvg: qqSvg, barsSvg: barsSvg };
    if (typeof module === "object" && module.exports) module.exports = api;
    root.PatrickPlacements = api;

    // ------------------------------------------------------------------ interface
    var doc = root.document;
    if (!doc || !doc.getElementById("pl-app")) return;

    var T = {};
    try { T = JSON.parse(doc.getElementById("pl-i18n").textContent || "{}"); } catch (e) { T = {}; }
    var lang = doc.documentElement.lang || "fr";
    function t(key, params) {
        var s = T[key] || key;
        if (params) Object.keys(params).forEach(function (k) { s = s.split("{" + k + "}").join(params[k]); });
        return s;
    }
    function fmt(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : x.toLocaleString(lang, { minimumFractionDigits: d, maximumFractionDigits: d }); }
    function pct(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : fmt(x * 100, d === undefined ? 1 : d) + " %"; }
    function eur(x) { return x === null || x === undefined || !isFinite(x) ? "—" : Math.round(x).toLocaleString(lang) + " €"; }
    function num(x, d) { return fmt(x, d === undefined ? 2 : d); }

    function h(tag, attrs, children) {
        var el = doc.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === null || v === undefined || v === false) return;
            if (k === "text") el.textContent = v;
            else if (k === "class") el.className = v;
            else if (k.indexOf("on") === 0) el.addEventListener(k.slice(2), v);
            else if (v === true) el.setAttribute(k, "");
            else el.setAttribute(k, v);
        });
        (children || []).forEach(function (c) { if (c) el.appendChild(typeof c === "string" ? doc.createTextNode(c) : c); });
        return el;
    }
    function hint(text) { return h("p", { class: "hint", "data-keep": "", text: text }); }
    function clear(el) { el.textContent = ""; return el; }

    function call(method, url, body, isForm) {
        var opt = { method: method, credentials: "same-origin", headers: {} };
        if (body && !isForm) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
        else if (body) opt.body = body;
        return root.fetch(url, opt).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) throw new Error(j.detail || j.error || ("HTTP " + r.status));
                return j;
            });
        });
    }

    var STORE_KEY = "patrick.placements.v1";
    var els = { data: doc.getElementById("pl-data-body"), run: doc.getElementById("pl-run"), runBody: doc.getElementById("pl-run-body"),
                result: doc.getElementById("pl-result"), resultBody: doc.getElementById("pl-result-body"),
                profile: doc.getElementById("pl-profile"), profileBody: doc.getElementById("pl-profile-body") };
    var state = { datasets: [], id: null, ds: null, result: null, creating: false, timer: null, busy: false, notice: null, report: null, catalog: null,
                  sel: { window: null, crit: "wf_sharpe", maxVol: null, pid: null, centering: "prudent", unit: "ann", statWindow: null } };
    try { state.id = (JSON.parse(root.localStorage.getItem(STORE_KEY) || "{}") || {}).id || null; } catch (e) { state.id = null; }
    function remember() { try { root.localStorage.setItem(STORE_KEY, JSON.stringify({ id: state.id })); } catch (e) { /* stockage indisponible */ } }

    var OBJ_KEYS = ["mv_prudent", "mv_balanced", "mv_dynamic", "max_sharpe", "min_vol", "max_diversification", "risk_parity", "max_sortino", "max_return", "equal"];
    var ENV_FIELDS = [["entry_fee", "%"], ["mgmt_fee", "%"], ["abond_rate", "%"], ["abond_cap", "€"], ["abond_csg", "%"], ["euro_ps", "%"], ["ps_exit", "%"],
                      ["ir_before", "%"], ["ir_after", "%"], ["years_threshold", "ans"], ["allowance", "€"], ["tmi_in", "%"], ["tmi_out", "%"], ["lock_years", "ans"]];
    var METHOD_KEYS = ["bootstrap blocs 6 mois", "bootstrap i.i.d.", "bootstrap stationnaire", "GARCH résidus", "Monte Carlo μ incertain"];
    var CAPS = [1, 0.5, 0.4, 0.3];
    var PALETTE = ["--ra-c1", "--ra-c2", "--ra-c3", "--ra-c4", "--ra-c5", "--ra-c6", "--ra-c7", "--ra-c8"];

    function objectiveName(o) { return t("pl_obj_" + o); }
    // Axe des éventails mensuels : « an N » aux années pleines, « N mois » entre deux (bulle de survol comprise).
    function monthLabel(i) { return i === 0 ? "0" : i % 12 === 0 ? t("pl_fan_year", { n: i / 12 }) : t("pl_fan_month", { n: i }); }
    function capName(cap) { return cap === null || cap === undefined || cap >= 1 ? t("pl_cap_none") : Math.round(cap * 100) + " %"; }
    function windowName(w) { return t("pl_window_value", { d: w.start, m: w.months }); }

    // ---- 1. données
    function loadAll() {
        return call("GET", "/api/placements/datasets").then(function (list) {
            state.datasets = list;
            if (!state.id || !list.some(function (d) { return d.id === state.id; })) state.id = list.length ? list[0].id : null;
            return state.id ? selectDataset(state.id) : (render(), null);
        }).catch(function (e) { clear(els.data).appendChild(hint(e.message)); });
    }

    function selectDataset(id) {
        state.id = id; state.creating = false; remember();
        return Promise.all([call("GET", "/api/placements/datasets/" + id), call("GET", "/api/placements/datasets/" + id + "/result")]).then(function (r) {
            state.ds = r[0]; state.result = r[1].result;
            state.sel.window = null; state.sel.pid = null;
            render();
        }).catch(function (e) { state.notice = e.message; render(); });
    }

    function importForm(dataset) {
        var name = h("input", { type: "text", class: "pl-input", maxlength: "80", placeholder: t("pl_name_ph"), "aria-label": t("pl_dataset") });
        var files = h("input", { type: "file", multiple: true, accept: ".csv,.txt,.tsv,.xlsx,.xlsm,.xls,.ods", class: "pl-file", "aria-label": t("pl_import_h") });
        var status = h("p", { class: "hint", "data-keep": "", role: "status" });
        var button = h("button", { type: "submit", class: "btn", text: dataset ? t("pl_add_files") : t("pl_import_btn") });
        var form = h("form", { class: "pl-import", onsubmit: function (e) {
            e.preventDefault();
            if (!files.files.length) return;
            var body = new FormData();
            if (!dataset) body.append("name", name.value);
            Array.prototype.forEach.call(files.files, function (f) { body.append("files", f, f.name); });
            button.disabled = true; status.textContent = t("pl_importing");
            call("POST", dataset ? "/api/placements/datasets/" + dataset.id + "/files" : "/api/placements/datasets", body, true).then(function (res) {
                var ok = res.report.filter(function (r) { return r.ok; }), bad = res.report.filter(function (r) { return !r.ok; });
                var nSeries = ok.reduce(function (a, r) { return a + r.series.length; }, 0);
                state.notice = t("pl_import_done2", { n: nSeries, f: ok.length }) + (bad.length ? " · " + t("pl_import_failed", { n: bad.length }) : "");
                state.report = res.report;
                state.id = res.dataset.id; remember(); return loadAll();
            }).catch(function (err) { status.textContent = err.message; button.disabled = false; });
        } }, [dataset ? null : name, files, button, status]);
        return form;
    }

    function saveSettings(patch) {
        return call("POST", "/api/placements/datasets/" + state.id + "/settings", patch).then(function (ds) { state.ds = ds; render(); })
            .catch(function (e) { state.notice = e.message; render(); });
    }

    function updateFund(key, patch) {
        return call("POST", "/api/placements/datasets/" + state.id + "/funds/" + encodeURIComponent(key), patch).then(function (d) { state.ds = d; render(); })
            .catch(function (e) { state.notice = e.message; render(); });
    }

    function selectOf(options, value, label, onchange, prefix) {
        return h("select", { class: "pl-input pl-compact", "aria-label": label, onchange: onchange },
            options.map(function (o) { return h("option", { value: o, selected: o === value, text: t(prefix + o) }); }));
    }

    function fundsTable(ds) {
        var cat = state.catalog || { kinds: [], categories: [], roles: [] };
        var keys = Object.keys(ds.funds);
        var head = h("tr", {}, [t("pl_col_use"), t("pl_col_fund"), t("pl_col_kind"), t("pl_col_category"), t("pl_col_role"), t("pl_col_min"), t("pl_col_max"),
            t("pl_col_period"), t("pl_col_reading"), ""].map(function (c) { return h("th", { text: c }); }));
        var rows = keys.map(function (k) {
            var f = ds.funds[k], isCash = ds.cash === k;
            var check = f.checks && f.checks.length ? f.checks[f.checks.length - 1] : null;
            var checkText = check ? (check.points_communs ? t("pl_check_value", { n: check.points_communs, gap: num(check.ecart_max, 4) }) : t("pl_check_new", { n: check.nouveaux_points })) : "";
            var useBox = h("input", { type: "checkbox", "aria-label": t("pl_col_use") + " " + f.label, checked: !f.excluded || isCash, disabled: isCash, onchange: function (e) {
                updateFund(k, { excluded: !e.target.checked });
            } });
            var label = h("input", { type: "text", class: "pl-input pl-label-input", value: f.label, "aria-label": t("pl_col_fund"), onchange: function (e) { updateFund(k, { label: e.target.value }); } });
            var kind = selectOf(cat.kinds, f.kind || "price", t("pl_col_kind"), function (e) { updateFund(k, { kind: e.target.value }); }, "pl_kind_");
            var category = selectOf(cat.categories, f.category || "other", t("pl_col_category"), function (e) { updateFund(k, { category: e.target.value }); }, "pl_cat_");
            var role = selectOf(cat.roles, f.role || "uc", t("pl_col_role"), function (e) { updateFund(k, { role: e.target.value }); }, "pl_role_");
            function bound(name) {
                return h("input", { type: "number", class: "pl-input pl-tiny", min: "0", max: "100", step: "1", value: f[name] === null || f[name] === undefined ? "" : String(Math.round(f[name] * 100)),
                    placeholder: name === "min" ? "0" : "100", "aria-label": t("pl_col_" + name) + " " + f.label, onchange: function () {
                        var lo = row.querySelector("input[data-b=min]").value, hi = row.querySelector("input[data-b=max]").value;
                        updateFund(k, { set_bounds: true, min: lo === "" ? null : parseFloat(lo) / 100, max: hi === "" ? null : parseFloat(hi) / 100 });
                    }, "data-b": name });
            }
            var conf = f.confidence === undefined ? null : f.confidence;
            var reading = h("span", { class: "pl-reading" }, [
                conf !== null ? h("span", { class: "status-badge status-" + (conf >= 0.85 ? "ok" : conf >= 0.6 ? "warning" : "error"), text: Math.round(conf * 100) + " %" }) : null,
                h("span", { class: "hint", "data-keep": "", text: [t("pl_freq_" + (f.frequency || "daily")), (f.notes || []).join(" · "), checkText].filter(Boolean).join(" · ") })]);
            var del = h("button", { type: "button", class: "btn-secondary pl-small", title: t("pl_remove_fund"), "aria-label": t("pl_remove_fund") + " " + f.label, text: "✕", onclick: function () {
                if (!root.confirm(t("pl_remove_confirm", { name: f.label }))) return;
                call("DELETE", "/api/placements/datasets/" + ds.id + "/funds/" + encodeURIComponent(k)).then(function (d) { state.ds = d; render(); }).catch(function (e) { state.notice = e.message; render(); });
            } });
            var row = h("tr", { class: f.excluded && !isCash ? "pl-off" : "" }, [
                h("td", {}, [useBox]),
                h("td", {}, [label, isCash ? h("span", { class: "status-badge status-neutral pl-badge", text: t("pl_cash_badge") }) : null, f.isin ? h("span", { class: "hint pl-isin", text: f.isin }) : null]),
                h("td", {}, [kind]), h("td", {}, [category]), h("td", {}, [role]), h("td", {}, [bound("min")]), h("td", {}, [bound("max")]),
                h("td", { class: "pl-nowrap", text: f.start + " → " + f.end + " (" + f.points.toLocaleString(lang) + ")" }), h("td", {}, [reading]), h("td", {}, [del])]);
            return row;
        });
        return h("div", { class: "table-scroll" }, [h("table", { class: "data-table pl-table pl-funds" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]);
    }

    function reportBox() {
        var rep = state.report;
        if (!rep) return null;
        state.report = null;
        return h("details", { class: "pl-report", open: true }, [h("summary", { text: t("pl_report_h") })].concat(rep.map(function (r) {
            if (!r.ok) return h("p", { class: "pl-report-bad", text: r.file + " : " + r.error });
            return h("div", { class: "pl-report-file" }, [h("strong", { text: r.file }), " · " + t("pl_report_series", { n: r.series.length }),
                h("ul", {}, r.series.map(function (x) {
                    return h("li", { text: x.label + " — " + t("pl_kind_" + x.kind) + ", " + t("pl_freq_" + x.frequency) + ", " + x.start + " → " + x.end + " (" + x.points + ")" + (x.notes.length ? " · " + x.notes.join(" · ") : "") });
                })), r.remarks && r.remarks.length ? hint(r.remarks.join(" · ")) : null]);
        })));
    }

    function ratesForm(ds) {
        var name = h("input", { type: "text", class: "pl-input", value: t("pl_rates_default"), "aria-label": t("pl_rates_name") });
        var cat = h("select", { class: "pl-input", "aria-label": t("pl_col_category") }, ["euro", "money", "bond"].map(function (c) { return h("option", { value: c, text: t("pl_cat_" + c) }); }));
        var area = h("textarea", { class: "pl-input pl-area", rows: "4", placeholder: "2022 2,0\n2023 2,6\n2024 2,7", "aria-label": t("pl_rates_lines") });
        var count = h("span", { class: "hint", "data-keep": "" });
        area.addEventListener("input", function () { count.textContent = t("pl_rates_count", { n: countRateLines(area.value) }); });
        var button = h("button", { type: "button", class: "btn-secondary", text: t("pl_rates_add"), onclick: function () {
            call("POST", "/api/placements/datasets/" + ds.id + "/rates", { name: name.value, text: area.value, category: cat.value }).then(function (d) { state.ds = d; state.notice = t("pl_rates_done"); render(); })
                .catch(function (e) { count.textContent = e.message; });
        } });
        return h("details", { class: "pl-rates" }, [h("summary", { text: t("pl_rates_h") }), hint(t("pl_rates_hint")),
            h("div", { class: "pl-row" }, [h("label", { class: "pl-label" }, [t("pl_rates_name"), name]), h("label", { class: "pl-label" }, [t("pl_col_category"), cat])]),
            h("label", { class: "pl-label" }, [t("pl_rates_lines"), area]), h("div", { class: "pl-row" }, [button, count])]);
    }

    // ---- 1 bis. votre épargne : enveloppe, versements, avoirs, contraintes
    function profilePanel() {
        var ds = state.creating ? null : state.ds;
        if (!els.profile) return;
        els.profile.hidden = !ds;
        if (!ds || !state.catalog) return;
        var box = clear(els.profileBody);
        var env = ds.envelope || { kind: "none", overrides: {} };
        var base = state.catalog.envelopes[env.kind] || state.catalog.envelopes.none;
        var draft = { kind: env.kind, overrides: Object.assign({}, env.overrides) };
        var contrib = Object.assign({}, ds.contributions || {});
        var holdings = Object.assign({}, ds.holdings || {});
        var groups = (ds.groups || []).map(function (g) { return Object.assign({}, g); });
        var kindSel = h("select", { class: "pl-input", "aria-label": t("pl_env_kind"), onchange: function (e) {
            save({ envelope: { kind: e.target.value, overrides: {} } });
        } }, Object.keys(state.catalog.envelopes).map(function (k) { return h("option", { value: k, selected: k === env.kind, text: t("pl_env_" + k) }); }));
        var couple = h("label", { class: "checkbox" }, [h("input", { type: "checkbox", checked: !!ds.couple, onchange: function (e) { save({ couple: e.target.checked }); } }), " " + t("pl_couple")]);
        var envFields = ENV_FIELDS.map(function (fd) {
            var key = fd[0], v = draft.overrides[key] !== undefined ? draft.overrides[key] : base[key];
            return h("label", { class: "pl-label" }, [t("pl_envf_" + key) + " (" + fd[1] + ")", h("input", { type: "number", class: "pl-input pl-narrow", step: "any", value: String(v),
                onchange: function (e) { draft.overrides[key] = e.target.value === "" ? null : parseFloat(e.target.value); } })]);
        });
        var deductible = h("label", { class: "checkbox" }, [h("input", { type: "checkbox", checked: draft.overrides.deductible !== undefined ? !!draft.overrides.deductible : !!base.deductible,
            onchange: function (e) { draft.overrides.deductible = e.target.checked; } }), " " + t("pl_envf_deductible")]);
        function cField(key, unit, step) {
            return h("label", { class: "pl-label" }, [t("pl_contrib_" + key) + " (" + unit + ")", h("input", { type: "number", class: "pl-input pl-narrow", min: key === "growth" ? "-20" : "0", step: step,
                value: String(contrib[key] === undefined ? "" : contrib[key]), onchange: function (e) { contrib[key] = parseFloat(e.target.value) || 0; } })]);
        }
        var holdRows = Object.keys(ds.funds).filter(function (k) { return !ds.funds[k].excluded || k === ds.cash; }).map(function (k) {
            return h("label", { class: "pl-label pl-hold" }, [ds.funds[k].label, h("input", { type: "number", class: "pl-input pl-narrow", min: "0", step: "100", value: holdings[k] ? String(holdings[k]) : "",
                placeholder: "0", onchange: function (e) { holdings[k] = parseFloat(e.target.value) || 0; } })]);
        });
        var groupBox = h("div", { class: "pl-groups" });
        function drawGroups() {
            clear(groupBox);
            groups.forEach(function (g, i) {
                groupBox.appendChild(h("div", { class: "pl-row pl-group" }, [
                    h("select", { class: "pl-input", "aria-label": t("pl_col_category"), onchange: function (e) { g.category = e.target.value; g.keys = []; } },
                        state.catalog.categories.map(function (c) { return h("option", { value: c, selected: g.category === c, text: t("pl_cat_" + c) }); })),
                    h("label", { class: "pl-label" }, [t("pl_col_min") + " (%)", h("input", { type: "number", class: "pl-input pl-tiny", min: "0", max: "100", value: String(Math.round((g.min || 0) * 100)), onchange: function (e) { g.min = (parseFloat(e.target.value) || 0) / 100; } })]),
                    h("label", { class: "pl-label" }, [t("pl_col_max") + " (%)", h("input", { type: "number", class: "pl-input pl-tiny", min: "0", max: "100", value: String(Math.round((g.max === undefined || g.max === null ? 1 : g.max) * 100)), onchange: function (e) { g.max = (parseFloat(e.target.value) || 0) / 100; } })]),
                    h("button", { type: "button", class: "btn-secondary pl-small", text: "✕", "aria-label": t("pl_group_remove"), onclick: function () { groups.splice(i, 1); drawGroups(); } })]));
            });
            groupBox.appendChild(h("button", { type: "button", class: "btn-secondary pl-small", text: t("pl_group_add"), onclick: function () { groups.push({ category: "euro", min: 0.2, max: 1 }); drawGroups(); } }));
        }
        drawGroups();
        var status = h("span", { class: "hint", "data-keep": "", role: "status" });
        function save(patch) {
            return call("POST", "/api/placements/datasets/" + ds.id + "/profile", patch).then(function (d) { state.ds = d; render(); })
                .catch(function (e) { status.textContent = e.message; });
        }
        var saveBtn = h("button", { type: "button", class: "btn", text: t("pl_profile_save"), onclick: function () {
            save({ envelope: draft, contributions: contrib, holdings: holdings, groups: groups }).then(function () { state.notice = t("pl_profile_saved"); });
        } });
        box.appendChild(h("div", { class: "pl-grid pl-grid-2" }, [
            h("div", {}, [h("h3", { text: t("pl_env_h") }), h("div", { class: "pl-row" }, [h("label", { class: "pl-label" }, [t("pl_env_kind"), kindSel]), couple]),
                hint(t("pl_env_desc_" + env.kind)),
                h("details", { class: "adv" }, [h("summary", { class: "adv-summary", text: t("pl_env_details") }), hint(t("pl_env_fields_hint")), h("div", { class: "pl-row" }, envFields.concat([deductible]))])]),
            h("div", {}, [h("h3", { text: t("pl_contrib_h") }), h("div", { class: "pl-row" }, [cField("initial", "€", "100"), cField("monthly", "€", "10"), cField("yearly", "€", "100"),
                cField("growth", "%/an", "0.5"), cField("goal", "€", "1000")]), hint(t("pl_contrib_hint"))])]));
        box.appendChild(h("div", { class: "pl-grid pl-grid-2" }, [
            h("div", {}, [h("h3", { text: t("pl_hold_h") }), hint(t("pl_hold_hint")), h("div", { class: "pl-holds" }, holdRows)]),
            h("div", {}, [h("h3", { text: t("pl_groups_h") }), hint(t("pl_groups_hint")), groupBox])]));
        box.appendChild(h("div", { class: "pl-row" }, [saveBtn, status]));
    }

    function dataPanel() {
        var box = clear(els.data);
        if (state.notice) { box.appendChild(h("p", { class: "banner banner-info", role: "status", text: state.notice })); state.notice = null; }
        var ds = state.creating ? null : state.ds;
        if (state.datasets.length) {
            var select = h("select", { class: "pl-input", "aria-label": t("pl_dataset"), onchange: function (e) { if (e.target.value === "__new__") { state.creating = true; state.ds = null; render(); } else selectDataset(e.target.value); } },
                state.datasets.map(function (d) { return h("option", { value: d.id, selected: !state.creating && d.id === state.id, text: d.name + " (" + d.n_funds + ")" }); })
                    .concat([h("option", { value: "__new__", selected: state.creating, text: "+ " + t("pl_import_h") })]));
            box.appendChild(h("div", { class: "pl-row" }, [h("label", { class: "pl-label" }, [t("pl_dataset"), select])]));
        } else {
            box.appendChild(hint(t("pl_no_dataset")));
        }
        if (!ds) {
            box.appendChild(h("h3", { text: t("pl_import_h") }));
            box.appendChild(hint(t("pl_import_hint")));
            box.appendChild(importForm(null));
            return;
        }
        var cashSel = h("select", { class: "pl-input", "aria-label": t("pl_cash_label"), onchange: function (e) { saveSettings({ set_cash: true, cash: e.target.value === "" ? null : e.target.value }); } },
            [h("option", { value: "", selected: !ds.cash, text: t("pl_cash_none") })].concat(Object.keys(ds.funds).map(function (k) { return h("option", { value: k, selected: ds.cash === k, text: ds.funds[k].label }); })));
        var rf = h("input", { type: "number", class: "pl-input", step: "0.1", min: "-5", max: "30", value: String(Math.round((ds.rf_annual || 0) * 1000) / 10), disabled: !!ds.cash, "aria-label": t("pl_rf_label"),
                              onchange: function (e) { saveSettings({ rf_annual: parseFloat(e.target.value) / 100 }); } });
        box.appendChild(h("div", { class: "pl-row" }, [
            h("label", { class: "pl-label" }, [t("pl_cash_label"), cashSel]),
            h("label", { class: "pl-label" }, [t("pl_rf_label") + " (%)", rf])]));
        var report = reportBox();
        if (report) box.appendChild(report);
        box.appendChild(fundsTable(ds));
        box.appendChild(ratesForm(ds));
        box.appendChild(h("div", { class: "pl-row pl-row-end" }, [importForm(ds), h("button", { type: "button", class: "btn-secondary", text: t("pl_delete_dataset"), onclick: function () {
            if (!root.confirm(t("pl_delete_confirm", { name: ds.name }))) return;
            call("DELETE", "/api/placements/datasets/" + ds.id).then(function () { state.id = null; state.ds = null; state.result = null; return loadAll(); }).catch(function (e) { state.notice = e.message; render(); });
        } })]));
    }

    // ---- 2. simulation
    function checkboxes(name, items, label, isChecked) {
        return h("fieldset", { class: "pl-fieldset" }, [h("legend", { text: name })].concat(items.map(function (it) {
            return h("label", { class: "checkbox" }, [h("input", { type: "checkbox", name: label, value: String(it.value), checked: isChecked(it.value) }), " " + it.label]);
        })));
    }

    function runPanel() {
        var ds = state.creating ? null : state.ds;
        var risky = ds ? Object.keys(ds.funds).filter(function (k) { return !ds.funds[k].excluded && k !== ds.cash; }).length : 0;
        els.run.hidden = !ds;
        if (!ds) return;
        var box = clear(els.runBody);
        if (risky < 2) { box.appendChild(hint(t("pl_need_funds"))); return; }
        var horizon = h("input", { type: "number", class: "pl-input pl-narrow", name: "horizon", min: "1", max: String((state.catalog && state.catalog.max_horizon) || 40), value: "10", "aria-label": t("pl_horizon") });
        var sims = h("select", { class: "pl-input", name: "sims", "aria-label": t("pl_sims") }, [5000, 20000, 50000].map(function (n) { return h("option", { value: String(n), selected: n === 20000, text: n.toLocaleString(lang) }); }));
        var windows = h("fieldset", { class: "pl-fieldset" }, [h("legend", { text: t("pl_windows") }), hint(t("pl_windows_auto"))].concat((ds.windows || []).map(function (w) {
            return h("label", { class: "checkbox" }, [h("input", { type: "checkbox", name: "window", value: w.start }), " " + t("pl_window_row", { d: w.start, m: w.months, n: w.funds })]);
        })));
        var advanced = h("details", { class: "adv" }, [h("summary", { class: "adv-summary", text: t("pl_advanced") }),
            h("div", { class: "pl-grid" }, [
                checkboxes(t("pl_methods"), METHOD_KEYS.map(function (m) { return { value: m, label: m }; }), "method", function () { return true; }),
                h("label", { class: "pl-label" }, [t("pl_sims"), sims]), windows])]);
        var status = h("p", { class: "hint pl-status", "data-keep": "", role: "status" });
        var bar = h("progress", { class: "pl-progress", max: "100", value: "0", hidden: true });
        var button = h("button", { type: "button", class: "btn", id: "pl-go", text: t("pl_run") });
        function values(name) { return Array.prototype.map.call(box.querySelectorAll("input[name=" + name + "]:checked"), function (i) { return i.value; }); }
        button.addEventListener("click", function () {
            var body = { horizon_years: parseInt(horizon.value, 10) || 5, objectives: values("objective"), caps: values("cap").map(parseFloat),
                         methods: values("method"), n_sims: parseInt(sims.value, 10), windows: values("window") };
            button.disabled = true; bar.hidden = false; bar.value = 0; status.textContent = t("pl_running");
            call("POST", "/api/placements/datasets/" + ds.id + "/analyse", body).then(function (job) { poll(job.id, bar, status, button); })
                .catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("pl_failed", { e: e.message }); });
        });
        box.appendChild(h("div", { class: "pl-grid" }, [
            h("label", { class: "pl-label" }, [t("pl_horizon"), horizon]),
            checkboxes(t("pl_objectives"), OBJ_KEYS.map(function (o) { return { value: o, label: objectiveName(o) }; }), "objective", function (v) { return v !== "equal"; }),
            checkboxes(t("pl_caps"), CAPS.map(function (c) { return { value: c, label: capName(c) }; }), "cap", function (v) { return v === 1 || v === 0.4; })]));
        box.appendChild(advanced);
        box.appendChild(h("div", { class: "pl-row" }, [button, bar, status]));
    }

    function poll(jobId, bar, status, button) {
        root.clearTimeout(state.timer);
        call("GET", "/api/placements/jobs/" + jobId).then(function (job) {
            bar.value = Math.round(job.fraction * 100);
            status.textContent = job.status === "running" ? t("pl_running") + " " + Math.round(job.fraction * 100) + " % · " + job.message : "";
            if (job.status === "running") { state.timer = root.setTimeout(function () { poll(jobId, bar, status, button); }, 1000); return; }
            button.disabled = false; bar.hidden = true;
            if (job.status === "error") { status.textContent = t("pl_failed", { e: job.error }); return; }
            return call("GET", "/api/placements/datasets/" + state.id + "/result").then(function (r) { state.result = r.result; state.sel.window = null; state.sel.pid = null; renderResult(); });
        }).catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("pl_failed", { e: e.message }); });
    }

    // ---- 3. résultats
    function metricsGrid(pf) {
        var m = pf.metrics;
        var rows = [["pl_m_cagr", pct(m.cagr)], ["pl_m_vol", pct(m.vol)], ["pl_m_sharpe", num(m.sharpe)], ["pl_m_sortino", num(m.sortino)],
                    ["pl_m_mdd", pct(m.max_dd_daily)], ["pl_m_worst12", pct(m.worst_12m)], ["pl_m_var5", pct(m.var5)],
                    ["pl_m_div", num(m.div_ratio)], ["pl_m_effn", num(m.eff_n, 1)]];
        return h("dl", { class: "pl-metrics" }, rows.reduce(function (acc, r) { return acc.concat([h("dt", { text: t(r[0]) }), h("dd", { text: r[1] })]); }, []));
    }

    function weightsBlock(pf) {
        return h("table", { class: "data-table pl-weights" }, [h("thead", {}, [h("tr", {}, [h("th", { text: t("pl_col_fund") }), h("th", { text: t("pl_col_weight") }), h("th", { class: "n", text: t("pl_col_amount") })]) ]),
            h("tbody", {}, pf.weights.map(function (w) {
                return h("tr", {}, [h("td", { text: w.label }), h("td", {}, [h("span", { class: "pl-bar", style: "--w:" + (w.weight * 100).toFixed(1) + "%" }), " " + pct(w.weight)]), h("td", { class: "n", text: eur(w.amount) })]);
            }))]);
    }

    function walkForwardBlock(pf) {
        var wf = pf.walk_forward;
        if (!wf || wf.sharpe === null || wf.sharpe === undefined) return h("p", { class: "hint", "data-keep": "", text: t("pl_wf_none") });
        var parts = [t("pl_wf_line", { s: num(wf.sharpe), b: num(wf.sharpe_1n), m: wf.mois_hors_echantillon }), wf.significatif ? t("pl_wf_sig") : t("pl_wf_nosig")];
        if (wf.peu_fiable) parts.push(t("pl_wf_unreliable"));
        return h("p", { class: "pl-wf" + (wf.peu_fiable ? " is-weak" : ""), "data-keep": "", text: parts.join(" ") });
    }

    function scenarioBlock(pf, amount, years) {
        var sel = state.sel;
        function seg(name, options, key) {
            return h("span", { class: "pl-seg", role: "group" }, options.map(function (o) {
                return h("button", { type: "button", class: "pl-seg-btn", "aria-pressed": sel[key] === o[0] ? "true" : "false", text: o[1], onclick: function () { sel[key] = o[0]; renderResult(); } });
            }));
        }
        var qs = ["05", "25", "50", "75", "95"];
        var head = h("tr", {}, [t("pl_col_method")].concat(qs.map(function (q) { return "P" + parseInt(q, 10); })).concat([t("pl_col_loss")]).map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }));
        var rows = Object.keys(pf.scenarios || {}).map(function (name) {
            var s = pf.scenarios[name][sel.centering];
            if (!s) return h("tr", { class: "pl-off" }, [h("td", { text: name }), h("td", { colspan: "6" }, [h("span", { class: "hint", "data-keep": "", text: t("pl_garch_off", { m: pf.garch ? pf.garch.motif : "" }) })])]);
            return h("tr", {}, [h("td", { text: name })].concat(qs.map(function (q) {
                return h("td", { class: "n", text: sel.unit === "ann" ? pct(s["ann_p" + q]) : eur(amount * (1 + s["cum_p" + q])) });
            })).concat([h("td", { class: "n", text: pct(s.proba_perte) })]));
        });
        var hist = pf.history;
        return h("div", { class: "pl-scn" }, [
            h("h4", { text: t("pl_scn_h", { y: years }) }),
            h("div", { class: "pl-row" }, [seg("c", [["historique", t("pl_cen_hist")], ["prudent", t("pl_cen_prudent")]], "centering"), seg("u", [["ann", t("pl_unit_ann")], ["final", t("pl_unit_final")]], "unit")]),
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]),
            hint(t("pl_scn_note")),
            hist ? hint(t("pl_hist_line", { y: years, w: pct(hist.pire), a: pct(hist.moyen), b: pct(hist.meilleur), n: num(hist.blocs_indep, 1) })) : null]);
    }

    function paintChart(host, opts) {
        if (!root.PatrickPlot) { host.textContent = ""; return; }
        root.PatrickPlot.create(host, opts);
    }

    function fanChart(pf, years) {
        var fan = pf.fan && pf.fan[state.sel.centering];
        var host = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_fan_h") });
        if (!fan) return host;
        var monthly = fan.step === "month";
        var xs = [0].concat(monthly ? fan.mois : fan.annees);
        function vals(k) { return [0].concat(fan[k].map(function (v) { return v * 100; })); }
        root.setTimeout(function () {
            paintChart(host, { type: "line", xKind: "index", xs: xs, xLabel: monthly ? monthLabel : function (i) { return i === 0 ? "0" : t("pl_fan_year", { n: i }); }, height: 240, legend: true, markers: false, finance: false, zoomable: false,
                series: [{ name: "P5", color: "--neg", width: 1.6, values: vals("p05") }, { name: "P25", color: "--text-3", width: 1.2, dash: "4 3", values: vals("p25") },
                         { name: "P50", color: "--brand", width: 2.6, values: vals("p50") }, { name: "P75", color: "--text-3", width: 1.2, dash: "4 3", values: vals("p75") },
                         { name: "P95", color: "--pos", width: 1.6, values: vals("p95") }],
                yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        }, 0);
        return host;
    }

    // Couleur stable d'un support (mêmes couleurs dans toutes les barres empilées) : palette des graphiques, puis teintes espacées.
    function fundColor(r, key) {
        var keys = r.funds.map(function (f) { return f.key; }).concat(r.cash ? [r.cash.key] : []);
        var i = keys.indexOf(key);
        if (i < 0) i = keys.length;
        if (r.cash && key === r.cash.key) return "var(--text-3)";
        return i < PALETTE.length ? "var(" + PALETTE[i] + ")" : "hsl(" + Math.round((i * 137.508) % 360) + " 55% 55%)";
    }

    function svgBox(svg, cls, label) {
        var box = h("div", { class: "pl-svg-box " + (cls || ""), role: "img", "aria-label": label || "" });
        box.innerHTML = svg;
        return box;
    }

    // ---- 3 a. toutes les ventilations proposées, comparées d'un coup d'œil (barres empilées à 100 %), triées selon le critère choisi
    function proposalsSection(r) {
        var sel = state.sel;
        var caps = [];
        r.portfolios.forEach(function (pf) { var c = pf.cap === null || pf.cap === undefined ? 1 : pf.cap; if (caps.indexOf(c) < 0) caps.push(c); });
        caps.sort(function (a, b) { return b - a; });
        var winSel = h("select", { class: "pl-input", "aria-label": t("pl_window"), onchange: function (e) { sel.window = e.target.value; sel.pid = null; renderResult(); } },
            r.windows.map(function (w) { return h("option", { value: w.id, selected: w.id === sel.window, text: windowName(w) }); }));
        var capSel = h("select", { class: "pl-input", "aria-label": t("pl_col_cap"), onchange: function (e) { sel.cap = parseFloat(e.target.value); sel.pid = null; renderResult(); } },
            caps.map(function (c) { return h("option", { value: String(c), selected: c === sel.cap, text: capName(c) }); }));
        var critSel = h("select", { class: "pl-input", "aria-label": t("pl_criterion"), onchange: function (e) { sel.crit = e.target.value; sel.pid = null; renderResult(); } },
            CRITERIA.map(function (c) { return h("option", { value: c, selected: c === sel.crit, text: t("pl_crit_" + c) }); }));
        var ranked = rankBy(r.portfolios, sel.window, sel.cap, sel.crit);
        var used = {};
        ranked.forEach(function (pf) { pf.weights.forEach(function (w) { used[w.key] = w.label; }); });
        var head = h("tr", {}, [t("pl_col_obj"), t("pl_col_alloc"), t("pl_m_cagr"), t("pl_m_vol"), t("pl_m_sharpe"), t("pl_col_wf"), t("pl_m_mdd"), t("pl_m_div")]
            .map(function (c, i) { return h("th", { class: i > 1 ? "n" : "", text: c }); }));
        var rows = ranked.map(function (pf, rank) {
            var wf = pf.walk_forward || {}, m = pf.metrics || {};
            var bar = h("div", { class: "pl-stack", role: "img", "aria-label": pf.weights.map(function (w) { return w.label + " " + Math.round(w.weight * 100) + " %"; }).join(", ") },
                pf.weights.map(function (w) {
                    return h("span", { class: "pl-stack-seg", style: "width:" + (w.weight * 100).toFixed(2) + "%;background:" + fundColor(r, w.key),
                                       title: w.label + " · " + pct(w.weight) }, [w.weight >= 0.12 ? Math.round(w.weight * 100) + " %" : ""]);
                }));
            var isOn = pf.id === state.chosenId;
            return h("tr", { class: "pl-pick" + (isOn ? " is-on" : ""), tabindex: "0", "data-pid": pf.id,
                             onclick: function () { state.sel.pid = pf.id; state.sel.window = pf.window; renderResult(); var d = doc.getElementById("pl-best"); if (d) d.scrollIntoView({ behavior: "smooth", block: "start" }); },
                             onkeydown: function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.currentTarget.click(); } } }, [
                h("td", { class: "pl-prop-name" }, [rank === 0 ? h("span", { class: "pl-star", title: t("pl_best_by", { c: t("pl_crit_" + sel.crit) }), text: "★ " }) : null, objectiveName(pf.objective)]),
                h("td", { class: "pl-prop-bar" }, [bar]),
                h("td", { class: "n", text: pct(m.cagr) }), h("td", { class: "n", text: pct(m.vol) }), h("td", { class: "n", text: num(m.sharpe) }),
                h("td", { class: "n" + (wf.peu_fiable ? " pl-weak" : ""), title: wf.peu_fiable ? t("pl_wf_unreliable") : "", text: wf.sharpe === null || wf.sharpe === undefined ? "—" : num(wf.sharpe) }),
                h("td", { class: "n", text: pct(finiteOr(m.max_dd_daily, m.max_dd_monthly)) }), h("td", { class: "n", text: num(m.div_ratio) })]);
        });
        var legend = h("ul", { class: "pl-legend" }, Object.keys(used).map(function (k) {
            return h("li", {}, [h("span", { class: "pl-swatch", style: "background:" + fundColor(r, k) }), used[k]]);
        }));
        return h("div", { class: "card pl-card", id: "pl-proposals" }, [
            h("h3", { text: t("pl_prop_h") }), hint(t("pl_prop_hint")),
            h("div", { class: "pl-row" }, [h("label", { class: "pl-label" }, [t("pl_window"), winSel]), h("label", { class: "pl-label" }, [t("pl_col_cap"), capSel]),
                h("label", { class: "pl-label" }, [t("pl_sort_by"), critSel])]),
            ranked.length ? h("div", { class: "table-scroll" }, [h("table", { class: "data-table pl-table pl-proposals" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]) : hint(t("pl_no_match")),
            legend]);
    }

    // ---- 3 c. les rendements mensuels du portefeuille : distribution et loi normale, quantiles, Q-Q, calendrier, années, glissant
    function returnsBlock(pf, r) {
        var ch = r.charts[pf.window];
        var growth = ch && ch.portfolios[pf.id];
        if (!growth) return null;
        var rets = returnsFromGrowth(growth);
        if (rets.length < 6) return null;
        var sorted = rets.slice().sort(function (a, b) { return a - b; });
        var m = moments(rets);
        var QS = [0.05, 0.25, 0.5, 0.75, 0.95];
        var hist = histogram(rets);
        var dist = distSvg({ edges: hist.edges, counts: hist.counts, mean: m.mean, sd: m.sd, width: 760, height: 250,
                             quantiles: QS.map(function (q) { return { q: q, v: quantile(sorted, q) }; }),
                             marks: [{ v: 0, label: "0 %", kind: "zero" }] });
        var normalQ = QS.map(function (q) { return m.mean + m.sd * normInv(q); });
        var qTable = h("table", { class: "data-table pl-qtable" }, [
            h("thead", {}, [h("tr", {}, [""].concat(QS.map(function (q) { return "P" + Math.round(q * 100); })).map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]),
            h("tbody", {}, [
                h("tr", {}, [h("td", { text: t("pl_q_observed") })].concat(QS.map(function (q) { return h("td", { class: "n", text: pct(quantile(sorted, q), 2) }); }))),
                h("tr", {}, [h("td", { text: t("pl_q_normal") })].concat(normalQ.map(function (v) { return h("td", { class: "n", text: pct(v, 2) }); })))])]);
        var normalVerdict = m.jb_p < 0.05 ? t("pl_jb_reject", { p: num(m.jb_p, 3) }) : t("pl_jb_ok", { p: num(m.jb_p, 3) });
        var facts = h("dl", { class: "pl-metrics" }, [
            ["pl_m_mean_m", pct(m.mean, 2)], ["pl_m_sd_m", pct(m.sd, 2)], ["pl_m_skew", num(m.skew)], ["pl_m_kurt", num(m.kurt)],
            ["pl_m_best_m", pct(sorted[sorted.length - 1], 1)], ["pl_m_worst_m", pct(sorted[0], 1)],
            ["pl_m_pos_m", pct(rets.filter(function (x) { return x > 0; }).length / rets.length, 0)]]
            .reduce(function (acc, x) { return acc.concat([h("dt", { text: t(x[0]) }), h("dd", { text: x[1] })]); }, []));

        // calendrier année × mois
        var table = monthlyTable(ch.dates, rets);
        var MONTHS = t("pl_months_short").split(",");
        var cal = h("table", { class: "pl-cal" }, [
            h("thead", {}, [h("tr", {}, [h("th", { text: "" })].concat(MONTHS.map(function (mo) { return h("th", { text: mo }); })).concat([h("th", { text: t("pl_year_col") })]))]),
            h("tbody", {}, table.map(function (row) {
                return h("tr", {}, [h("th", { text: String(row.year) })].concat(row.months.map(function (v) {
                    return v === null ? h("td", { class: "pl-cal-empty" }) :
                        h("td", { class: "pl-cal-cell " + (v < 0 ? "is-neg" : "is-pos"), style: "--v:" + Math.min(1, Math.abs(v) / 0.06).toFixed(2), text: fmt(v * 100, 1) });
                })).concat([h("td", { class: "pl-cal-total " + (row.total < 0 ? "is-neg" : "is-pos"), title: row.partial ? t("pl_year_partial") : "", text: fmt(row.total * 100, 1) + (row.partial ? "*" : "") })]));
            }))]);

        // années : portefeuille contre 1/N
        var eqRets = returnsFromGrowth(ch.one_over_n || []);
        var eqTable = monthlyTable(ch.dates, eqRets);
        var eqByYear = {};
        eqTable.forEach(function (row) { eqByYear[row.year] = row.total; });
        var full = table.filter(function (row) { return !row.partial; });
        var meanYear = full.length ? full.reduce(function (a, row) { return a + row.total; }, 0) / full.length : NaN;
        var bars = barsSvg(table.map(function (row) { return { label: String(row.year) + (row.partial ? "*" : ""), a: row.total, b: eqByYear[row.year] }; }), 760, 220, meanYear);

        // glissant 12 mois
        var roll = rolling(rets, 12);
        var rollHost = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_roll_h") });
        var xs = ch.dates.slice(1).map(function (d) { return Date.parse(d); });
        root.setTimeout(function () {
            paintChart(rollHost, { type: "line", xKind: "time", xs: xs, height: 210, legend: true, markers: false, finance: false,
                series: [{ name: t("pl_roll_ret"), color: "--brand", width: 2, values: roll.ret.map(function (v) { return v === null ? null : v * 100; }) },
                         { name: t("pl_roll_vol"), color: "--info", width: 1.6, values: roll.vol.map(function (v) { return v === null ? null : v * 100; }) }],
                hlines: [{ y: 0, label: "", color: "--text-3" }],
                yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        }, 0);

        return h("div", { class: "pl-returns" }, [
            h("h4", { text: t("pl_dist_h", { n: rets.length }) }),
            svgBox(dist, "pl-dist-box", t("pl_dist_h", { n: rets.length })),
            h("p", { class: "pl-dist-legend hint", "data-keep": "" }, [h("span", { class: "pl-key pl-key-bar" }), t("pl_dist_key_bars"), h("span", { class: "pl-key pl-key-normal" }), t("pl_dist_key_normal"),
                h("span", { class: "pl-key pl-key-q" }), t("pl_dist_key_q")]),
            h("div", { class: "pl-grid pl-grid-2" }, [
                h("div", {}, [h("div", { class: "table-scroll" }, [qTable]), facts, hint(normalVerdict)]),
                h("div", {}, [h("h5", { text: t("pl_qq_h") }), svgBox(qqSvg(rets, 360, 250), "pl-qq-box", t("pl_qq_h")), hint(t("pl_qq_note"))])]),
            h("h4", { text: t("pl_cal_h") }), h("div", { class: "table-scroll" }, [cal]),
            h("h4", { text: t("pl_years_h") }), svgBox(bars, "pl-bars-box", t("pl_years_h")),
            h("p", { class: "pl-dist-legend hint", "data-keep": "" }, [h("span", { class: "pl-key pl-key-a" }), t("pl_portfolio"), h("span", { class: "pl-key pl-key-b" }), t("pl_one_n"),
                h("span", { class: "pl-key pl-key-mean" }), t("pl_years_mean", { v: pct(meanYear) })]),
            h("h4", { text: t("pl_roll_h") }), rollHost]);
    }

    // ---- 3 d. valeur finale simulée de l'épargne : histogramme, loi normale ajustée, traits des quantiles, objectif
    function finalDistBlock(pf, r) {
        var pr = pf.projection && (pf.projection[state.sel.centering] || pf.projection.prudent);
        var d = pr && pr.dist_net;
        if (!d || !d.edges || d.edges.length < 2) return null;
        var c = r.contributions || {};
        var QS = [["p05", 0.05], ["p25", 0.25], ["p50", 0.5], ["p75", 0.75], ["p95", 0.95]];
        var marks = [{ v: pr.invested, label: t("pl_sav_invested") + " " + eur(pr.invested), kind: "invested" }];
        if (c.goal) marks.push({ v: c.goal, label: t("pl_goal_line") + " " + eur(c.goal), kind: "goal" });
        var svg = distSvg({ edges: d.edges, counts: d.counts, mean: d.mean, sd: d.std, width: 760, height: 240, fmt: function (v) { return eur(v); },
                            quantiles: QS.map(function (q) { return { q: q[1], v: d.q[q[0]] }; }), marks: marks });
        return h("div", {}, [h("h4", { text: t("pl_final_h", { y: r.params.horizon_years, n: d.n }) }), svgBox(svg, "pl-dist-box", t("pl_final_h", { y: r.params.horizon_years, n: d.n })),
            h("p", { class: "pl-dist-legend hint", "data-keep": "" }, [h("span", { class: "pl-key pl-key-bar" }), t("pl_dist_key_paths"), h("span", { class: "pl-key pl-key-normal" }), t("pl_dist_key_normal"),
                h("span", { class: "pl-key pl-key-q" }), t("pl_dist_key_q"), h("span", { class: "pl-key pl-key-invested" }), t("pl_sav_invested"),
                c.goal ? h("span", { class: "pl-key pl-key-goal" }) : null, c.goal ? t("pl_goal_line") : null]),
            hint(t("pl_final_note"))]);
    }

    function portfolioDetail(pf, r) {
        var years = r.params.horizon_years;
        return h("div", { class: "pl-detail" }, [
            h("div", { class: "pl-detail-head" }, [h("h3", { text: objectiveName(pf.objective) + " · " + t("pl_col_cap") + " " + capName(pf.cap) })]),
            h("div", { class: "pl-grid pl-grid-2" }, [h("div", {}, [weightsBlock(pf)]), h("div", {}, [metricsGrid(pf), h("h4", { text: t("pl_wf_h") }), walkForwardBlock(pf)])]),
            pf.projection ? savingsBlock(pf, r) : null,
            pf.projection ? finalDistBlock(pf, r) : null,
            scenarioBlock(pf, r.params.amount, years),
            h("h4", { text: t("pl_fan_h") }), fanChart(pf, years),
            returnsBlock(pf, r),
            pf.replay ? replayBlock(pf, r) : null,
            pf.risk ? riskBlock(pf, r) : null]);
    }

    function labelOf(r, key) { return (r.funds.filter(function (f) { return f.key === key; })[0] || { label: key === (r.cash && r.cash.key) ? r.cash.label : key }).label; }

    function savingsBlock(pf, r) {
        var sel = state.sel;
        var pr = pf.projection[sel.centering] || pf.projection.prudent;
        var c = r.contributions || {};
        var seg = h("span", { class: "pl-seg", role: "group", "aria-label": t("pl_centering") }, [["prudent", t("pl_center_prudent")], ["historique", t("pl_center_hist")]].map(function (o) {
            return h("button", { type: "button", class: "pl-seg-btn", "aria-pressed": sel.centering === o[0] ? "true" : "false", text: o[1], onclick: function () { sel.centering = o[0]; renderResult(); } });
        }));
        var qs = ["p05", "p25", "p50", "p75", "p95"];
        var table = h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, [""].concat(qs.map(function (q) { return "P" + parseInt(q.slice(1), 10); })).map(function (x, i) { return h("th", { class: i ? "n" : "", text: x }); }))]),
            h("tbody", {}, [["pl_sav_gross", pr.gross], ["pl_sav_net", pr.net]].map(function (row) {
                return h("tr", {}, [h("td", { text: t(row[0]) })].concat(qs.map(function (q) { return h("td", { class: "n", text: eur(row[1][q]) }); })));
            }))]);
        var facts = h("dl", { class: "pl-metrics" }, [
            ["pl_sav_invested", eur(pr.invested)], ["pl_sav_abond", eur(pr.abondement)], ["pl_sav_fees", eur(pr.fees_median)], ["pl_sav_fee_drag", eur(pr.fee_drag_median)],
            ["pl_sav_euro_ps", eur(pr.euro_ps_median)], ["pl_sav_taxes", eur(pr.taxes_median)], ["pl_sav_irr", pct(pr.net_irr_median, 2)],
            ["pl_sav_loss", pct(pr.prob_loss, 0)], pr.prob_goal === null || pr.prob_goal === undefined ? null : ["pl_sav_goal", t("pl_sav_goal_v", { p: pct(pr.prob_goal, 0), g: eur(c.goal) })],
            pr.tax_saving_entry ? ["pl_sav_saving", eur(pr.tax_saving_entry)] : null].filter(Boolean).reduce(function (acc, x) { return acc.concat([h("dt", { text: t(x[0]) }), h("dd", { text: x[1] })]); }, []));
        var host = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_sav_fan") });
        var xs = pr.fan.p50.map(function (_v, i) { return i; });
        root.setTimeout(function () {
            if (!root.PatrickPlot) return;
            root.PatrickPlot.create(host, { type: "line", xKind: "index", xs: xs, xLabel: pr.fan_step === "month" ? monthLabel : function (i) { return i === 0 ? "0" : t("pl_fan_year", { n: i }); }, height: 240, legend: true, markers: false, finance: false, zoomable: false,
                series: [{ name: "P5", color: "--neg", width: 1.5, values: pr.fan.p05 }, { name: "P25", color: "--text-3", width: 1.1, dash: "4 3", values: pr.fan.p25 },
                         { name: "P50", color: "--brand", width: 2.6, values: pr.fan.p50 }, { name: "P75", color: "--text-3", width: 1.1, dash: "4 3", values: pr.fan.p75 },
                         { name: "P95", color: "--pos", width: 1.5, values: pr.fan.p95 }],
                hlines: c.goal ? [{ y: c.goal, label: t("pl_goal_line"), color: "--warn" }] : [],
                yFmt: function (v) { return eur(v); }, tipFmt: function (v) { return eur(v); } });
        }, 0);
        return h("div", { class: "pl-savings" }, [h("div", { class: "pl-row pl-row-between" }, [h("h4", { text: t("pl_sav_h", { y: r.params.horizon_years, e: t("pl_env_" + ((r.envelope && r.envelope.kind) || "none")) }) }), seg]),
            hint(t("pl_sav_line", { i: eur(c.initial), m: eur(c.monthly), a: eur(c.yearly), g: fmt(c.growth || 0, 1) })),
            h("div", { class: "pl-grid pl-grid-2" }, [h("div", { class: "table-scroll" }, [table]), facts]), host, hint(t("pl_sav_note"))]);
    }

    function replayBlock(pf, r) {
        var rp = pf.replay;
        var host = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_replay_h") });
        root.setTimeout(function () {
            if (!root.PatrickPlot) return;
            root.PatrickPlot.create(host, { type: "line", xKind: "time", xs: rp.dates.map(function (d) { return Date.parse(d); }), height: 220, legend: true, markers: false, finance: false,
                series: [{ name: t("pl_replay_value"), color: "--brand", width: 2, values: rp.value }, { name: t("pl_replay_invested"), color: "--text-3", width: 1.3, dash: "5 4", values: rp.invested }],
                yFmt: function (v) { return eur(v); }, tipFmt: function (v) { return eur(v); } });
        }, 0);
        return h("div", {}, [h("h4", { text: t("pl_replay_h") }), host,
            hint(t("pl_replay_line", { s: rp.dates[0], f: eur(rp.final), i: eur(rp.total_invested), r: pct(rp.irr, 2), d: pct(rp.max_dd) }))]);
    }

    function riskBlock(pf, r) {
        return h("div", {}, [h("h4", { text: t("pl_risk_h") }), h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [
            h("thead", {}, [h("tr", {}, [t("pl_col_fund"), t("pl_col_weight"), t("pl_col_risk")].map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]),
            h("tbody", {}, pf.risk.map(function (x) {
                return h("tr", {}, [h("td", { text: labelOf(r, x.key) }), h("td", { class: "n", text: pct(x.weight) }),
                    h("td", { class: "n" }, [h("span", { class: "pl-bar", style: "--w:" + Math.max(0, x.risk * 100).toFixed(1) + "%" }), " " + pct(x.risk)])]);
            }))])]), hint(t("pl_risk_note"))]);
    }

    function frontierSection(r, chosen) {
        var ch = r.charts[state.sel.window];
        if (!ch || !ch.frontier || !ch.frontier.points.length) return null;
        var fr = ch.frontier;
        var marks = [];
        rankBy(r.portfolios, state.sel.window, state.sel.cap, state.sel.crit).forEach(function (pf) {
            if (pf.point && (!chosen || pf.id !== chosen.id)) marks.push({ label: t("pl_objs_" + pf.objective), vol: pf.point.vol, ret: pf.point.ret, kind: "pf" });
        });
        if (chosen && chosen.point) marks.push({ label: t("pl_mark_chosen"), vol: chosen.point.vol, ret: chosen.point.ret, kind: "chosen" });
        if (fr.current) marks.push({ label: t("pl_mark_current"), vol: fr.current.vol, ret: fr.current.ret, kind: "current" });
        var svg = scatterSvg({ funds: fr.funds.map(function (f) { return { label: labelOf(r, f.key), vol: f.vol, ret: f.ret }; }), line: fr.points, marks: marks }, 760, 340);
        var host = h("div", { class: "pl-scatter-box" });
        host.innerHTML = svg;
        return h("div", { class: "card pl-card" }, [h("h3", { text: t("pl_frontier_h") }), host, hint(t("pl_frontier_note"))]);
    }

    function currentSection(r, chosen) {
        var cur = (r.current || []).filter(function (c) { return c.window === state.sel.window; })[0];
        if (!cur) return null;
        var pc = cur.projection[state.sel.centering] || cur.projection.prudent, pch = chosen && chosen.projection ? (chosen.projection[state.sel.centering] || chosen.projection.prudent) : null;
        var rows = [["pl_m_cagr", pct(cur.metrics.cagr), chosen ? pct(chosen.metrics.cagr) : "—"], ["pl_m_vol", pct(cur.metrics.vol), chosen ? pct(chosen.metrics.vol) : "—"],
                    ["pl_m_sharpe", num(cur.metrics.sharpe), chosen ? num(chosen.metrics.sharpe) : "—"], ["pl_m_mdd", pct(cur.metrics.max_dd_daily), chosen ? pct(chosen.metrics.max_dd_daily) : "—"],
                    ["pl_sav_net", eur(pc.net.p50), pch ? eur(pch.net.p50) : "—"], ["pl_sav_goal_short", pc.prob_goal === null ? "—" : pct(pc.prob_goal, 0), pch && pch.prob_goal !== null ? pct(pch.prob_goal, 0) : "—"],
                    ["pl_replay_irr", pct(cur.replay.irr, 2), chosen && chosen.replay ? pct(chosen.replay.irr, 2) : "—"]];
        return h("div", { class: "card pl-card" }, [h("h3", { text: t("pl_current_h") }),
            hint(t("pl_current_line", { n: eur(cur.total), w: cur.weights.map(function (w) { return w.label + " " + Math.round(w.weight * 100) + " %"; }).join(" / ") })),
            cur.missing.length ? hint(t("pl_current_missing", { s: cur.missing.join(", ") })) : null,
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, ["", t("pl_current_col"), t("pl_chosen_col")].map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]),
                h("tbody", {}, rows.map(function (x) { return h("tr", {}, [h("td", { text: t(x[0]) }), h("td", { class: "n", text: x[1] }), h("td", { class: "n", text: x[2] })]); }))])]),
            hint(t("pl_current_note"))]);
    }

    function envelopeSection(r) {
        var rows = r.envelope_compare || [];
        if (!rows.length) return null;
        var best = r.portfolios.filter(function (p) { return p.id === r.envelope_best; })[0];
        return h("div", { class: "card pl-card" }, [h("h3", { text: t("pl_envcmp_h") }),
            best ? hint(t("pl_envcmp_line", { p: objectiveName(best.objective) + " · " + capName(best.cap) + " · " + best.window, y: r.params.horizon_years })) : null,
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [
                h("thead", {}, [h("tr", {}, [t("pl_env_kind"), "P5", "P50", "P95", t("pl_sav_taxes"), t("pl_sav_fees"), t("pl_sav_abond"), t("pl_sav_saving"), t("pl_sav_goal_short")].map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]),
                h("tbody", {}, rows.map(function (x) {
                    var mine = r.envelope && r.envelope.kind === x.kind;
                    return h("tr", { class: mine ? "best" : "" }, [h("td", { text: t("pl_env_" + x.kind) + (mine ? " ★" : "") }), h("td", { class: "n", text: eur(x.net.p05) }), h("td", { class: "n", text: eur(x.net.p50) }),
                        h("td", { class: "n", text: eur(x.net.p95) }), h("td", { class: "n", text: eur(x.taxes_median) }), h("td", { class: "n", text: eur(x.fees_median) }),
                        h("td", { class: "n", text: eur(x.abondement) }), h("td", { class: "n", text: x.tax_saving_entry ? eur(x.tax_saving_entry) : "—" }),
                        h("td", { class: "n", text: x.prob_goal === null || x.prob_goal === undefined ? "—" : pct(x.prob_goal, 0) })]);
                }))])]), hint(t("pl_envcmp_note"))]);
    }

    // Le portefeuille par défaut : le meilleur de la fenêtre et du plafond choisis selon le critère, sous la limite de volatilité.
    function defaultPick(r) {
        var sel = state.sel;
        var capKey = function (c) { return c === null || c === undefined || c >= 1 ? 1 : c; };
        var pool = r.portfolios.filter(function (pf) { return capKey(pf.cap) === capKey(sel.cap); });
        return pickBest(pool, sel.window, sel.crit, sel.maxVol) || pickBest(r.portfolios, sel.window, sel.crit, sel.maxVol);
    }

    function chosenPortfolio(r) {
        var picked = defaultPick(r);
        var chosen = state.sel.pid ? r.portfolios.filter(function (p) { return p.id === state.sel.pid; })[0] : null;
        return chosen || picked;
    }

    // ---- 3 b. le détail de l'allocation retenue (clic sur une ligne des ventilations, sinon la meilleure selon le critère)
    function bestSection(r) {
        var sel = state.sel;
        var top = maxVolOf(r.portfolios, sel.window);
        var volValue = sel.maxVol === null ? top : sel.maxVol;
        var volLabel = h("output", { class: "pl-out", text: sel.maxVol === null ? t("pl_maxvol_any") : pct(sel.maxVol) });
        var vol = h("input", { type: "range", class: "pl-range", min: "0", max: String(Math.ceil(top * 1000) / 1000), step: "0.001", value: String(volValue), "aria-label": t("pl_maxvol"),
            oninput: function (e) { var v = parseFloat(e.target.value); sel.maxVol = v >= top - 1e-9 ? null : v; sel.pid = null; volLabel.textContent = sel.maxVol === null ? t("pl_maxvol_any") : pct(sel.maxVol); },
            onchange: function () { renderResult(); } });
        var chosen = chosenPortfolio(r);
        return h("div", { class: "card pl-card", id: "pl-best" }, [
            h("h3", { text: t("pl_best_h") }),
            h("div", { class: "pl-row" }, [h("label", { class: "pl-label" }, [t("pl_maxvol"), h("span", { class: "pl-range-row" }, [vol, volLabel])])]),
            chosen ? portfolioDetail(chosen, r) : hint(t("pl_no_match"))]);
    }

    function allocationsTable(r) {
        var head = h("tr", {}, [t("pl_window"), t("pl_col_obj"), t("pl_col_cap"), t("pl_col_alloc"), t("pl_m_cagr"), t("pl_m_vol"), t("pl_m_sharpe"), t("pl_col_wf"), t("pl_col_1n")].map(function (c, i) { return h("th", { class: i > 3 ? "n" : "", text: c }); }));
        var rows = r.portfolios.map(function (pf) {
            var wf = pf.walk_forward || {};
            return h("tr", { class: "pl-pick" + (pf.id === state.sel.pid ? " is-on" : ""), tabindex: "0", onclick: function () { state.sel.pid = pf.id; state.sel.window = pf.window; renderResult(); root.scrollTo({ top: els.resultBody.offsetTop, behavior: "smooth" }); } }, [
                h("td", { text: pf.window }), h("td", { text: objectiveName(pf.objective) }), h("td", { text: capName(pf.cap) }),
                h("td", { text: pf.weights.slice(0, 3).map(function (w) { return w.label + " " + Math.round(w.weight * 100) + " %"; }).join(" / ") }),
                h("td", { class: "n", text: pct(pf.metrics.cagr) }), h("td", { class: "n", text: pct(pf.metrics.vol) }), h("td", { class: "n", text: num(pf.metrics.sharpe) }),
                h("td", { class: "n", text: wf.sharpe === null || wf.sharpe === undefined ? "—" : num(wf.sharpe) }), h("td", { class: "n", text: wf.sharpe_1n === null || wf.sharpe_1n === undefined ? "—" : num(wf.sharpe_1n) })]);
        });
        var exportBtn = h("button", { type: "button", class: "btn-secondary", text: t("pl_export"), onclick: function () {
            var csv = toCsv([["window", "objective", "cap", "allocation", "cagr", "vol", "sharpe", "wf_sharpe", "sharpe_1n"]].concat(r.portfolios.map(function (pf) {
                var wf = pf.walk_forward || {};
                return [pf.window, pf.objective, pf.cap === null ? "" : pf.cap, pf.weights.map(function (w) { return w.label + " " + (w.weight * 100).toFixed(1) + "%"; }).join(" / "),
                        pf.metrics.cagr, pf.metrics.vol, pf.metrics.sharpe, wf.sharpe, wf.sharpe_1n];
            })));
            var a = h("a", { href: root.URL.createObjectURL(new root.Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" })), download: "placements.csv" });
            doc.body.appendChild(a); a.click(); a.remove();
        } });
        return h("div", { class: "card pl-card" }, [h("div", { class: "pl-row pl-row-between" }, [h("h3", { text: t("pl_all_h") }), exportBtn]),
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table pl-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])])]);
    }

    function growthSection(r, pf) {
        var ch = r.charts[state.sel.window];
        if (!ch) return null;
        var xs = ch.dates.map(function (d) { return Date.parse(d); });
        var inAlloc = pf ? pf.weights.map(function (w) { return w.key; }) : [];
        var series = [];
        if (pf && ch.portfolios[pf.id]) series.push({ name: t("pl_portfolio"), color: "--brand", width: 2.8, values: ch.portfolios[pf.id] });
        series.push({ name: t("pl_one_n"), color: "--text-3", width: 1.6, dash: "4 3", values: ch.one_over_n });
        inAlloc.forEach(function (k, i) { if (ch.funds[k]) series.push({ name: (r.funds.filter(function (f) { return f.key === k; })[0] || { label: k }).label, color: PALETTE[i % PALETTE.length], width: 1.3, values: ch.funds[k] }); });
        var growth = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_growth_h") });
        var drawdown = h("div", { class: "pl-chart", role: "img", "aria-label": t("pl_dd_h") });
        function dd(values) { var peak = -Infinity; return values.map(function (v) { peak = Math.max(peak, v); return (v / peak - 1) * 100; }); }
        root.setTimeout(function () {
            paintChart(growth, { type: "line", xKind: "time", xs: xs, series: series, height: 280, legend: true, markers: false, finance: false, yFmt: function (v, d) { return fmt(v, d); }, tipFmt: function (v) { return fmt(v, 1); } });
            paintChart(drawdown, { type: "line", xKind: "time", xs: xs, height: 200, legend: false, markers: false, finance: false, zoomable: true, sync: "pl-dd",
                series: series.map(function (s) { return { name: s.name, color: s.color, width: s.width, dash: s.dash, values: dd(s.values) }; }),
                yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        }, 0);
        return h("div", {}, [h("h4", { text: t("pl_growth_h") }), growth, h("h4", { text: t("pl_dd_h") }), drawdown]);
    }

    function statsSection(r) {
        var sel = state.sel;
        var windows = r.stat_windows;
        if (!sel.statWindow || windows.indexOf(sel.statWindow) < 0) sel.statWindow = windows[windows.length - 1];
        var pick = h("select", { class: "pl-input", "aria-label": t("pl_stats_window"), onchange: function (e) { sel.statWindow = e.target.value; renderResult(); } },
            windows.map(function (w) { return h("option", { value: w, selected: w === sel.statWindow, text: w }); }));
        var head = h("tr", {}, [t("pl_col_fund"), t("pl_col_start"), t("pl_col_cagr"), t("pl_col_vol"), t("pl_col_sharpe"), t("pl_col_mdd"), t("pl_col_w12")].map(function (c, i) { return h("th", { class: i > 1 ? "n" : "", text: c }); }));
        var rows = r.fund_stats.filter(function (f) { return f.windows[sel.statWindow]; }).sort(function (a, b) { return (b.windows[sel.statWindow].sharpe || -99) - (a.windows[sel.statWindow].sharpe || -99); }).map(function (f) {
            var s = f.windows[sel.statWindow];
            return h("tr", {}, [h("td", { text: f.label }), h("td", { text: s.start }), h("td", { class: "n", text: pct(s.cagr) }), h("td", { class: "n", text: pct(s.vol) }), h("td", { class: "n", text: num(s.sharpe) }), h("td", { class: "n", text: pct(s.max_dd) }), h("td", { class: "n", text: pct(s.worst_12m) })]);
        });
        var corr = r.correlation;
        var labelOf = function (k) { return (r.funds.filter(function (f) { return f.key === k; })[0] || { label: k }).label; };
        var cHead = h("tr", {}, [h("th", {})].concat(corr.keys.map(function (k, i) { return h("th", { class: "pl-corr-h", title: labelOf(k), text: String(i + 1) }); })));
        var cRows = corr.keys.map(function (k, i) {
            return h("tr", {}, [h("th", { class: "pl-corr-row", text: (i + 1) + " · " + labelOf(k) })].concat(corr.matrix[i].map(function (v, j) {
                return h("td", { class: "pl-corr " + (v < 0 ? "is-neg" : "is-pos"), style: "--v:" + corrIntensity(v).toFixed(2), title: labelOf(k) + " × " + labelOf(corr.keys[j]), text: v === null ? "—" : fmt(v, 2) });
            })));
        });
        var fs = r.fund_scenarios.map(function (f) {
            var s = f.scenarios["bootstrap blocs 6 mois"] && f.scenarios["bootstrap blocs 6 mois"][state.sel.centering];
            return s ? h("tr", {}, [h("td", { text: f.label }), h("td", { class: "n", text: pct(f.expected) }), h("td", { class: "n", text: pct(s.ann_p05) }), h("td", { class: "n", text: pct(s.ann_p50) }), h("td", { class: "n", text: pct(s.ann_p95) }), h("td", { class: "n", text: pct(s.proba_perte) })]) : null;
        });
        return h("div", { class: "card pl-card" }, [
            h("h3", { text: t("pl_funds_h") }), h("label", { class: "pl-label" }, [t("pl_stats_window"), pick]),
            h("div", { class: "table-scroll" }, [h("table", { class: "data-table pl-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]),
            h("h4", { text: t("pl_corr_h") }), h("div", { class: "table-scroll" }, [h("table", { class: "pl-corrtable" }, [h("thead", {}, [cHead]), h("tbody", {}, cRows)])]),
            fs.filter(Boolean).length ? h("div", {}, [h("h4", { text: t("pl_fscn_h") }),
                h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, [t("pl_col_fund"), "E", "P5", "P50", "P95", t("pl_col_loss")].map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]), h("tbody", {}, fs.filter(Boolean))])])]) : null]);
    }

    function renderResult() {
        var r = state.result;
        els.result.hidden = !r || state.creating;
        if (!r || state.creating) return;
        var sel = state.sel;
        if (!sel.window || !r.windows.some(function (w) { return w.id === sel.window; })) sel.window = r.windows[r.windows.length - 1].id;
        var caps = r.portfolios.map(function (pf) { return pf.cap === null || pf.cap === undefined ? 1 : pf.cap; });
        if (sel.cap === undefined || sel.cap === null || caps.indexOf(sel.cap) < 0) sel.cap = caps.length ? Math.max.apply(null, caps) : 1;
        var chosen = chosenPortfolio(r);
        state.chosenId = chosen ? chosen.id : null;
        var scrollY = root.scrollY;
        var box = clear(els.resultBody);
        box.appendChild(hint(t("pl_generated", { d: r.generated_at.replace("T", " ").slice(0, 16), c: r.last_common })));
        if (r.warnings && r.warnings.length) box.appendChild(h("ul", { class: "pl-warnings" }, r.warnings.map(function (w) { return h("li", { text: w }); })));
        // D'abord toutes les ventilations proposées (comparées, triées selon le critère), puis le détail de celle qu'on regarde.
        box.appendChild(proposalsSection(r));
        box.appendChild(bestSection(r));
        [frontierSection(r, chosen), currentSection(r, chosen), envelopeSection(r)].forEach(function (sec) { if (sec) box.appendChild(sec); });
        var growth = growthSection(r, chosen);
        if (growth) box.appendChild(h("div", { class: "card pl-card" }, [growth]));
        box.appendChild(allocationsTable(r));
        box.appendChild(statsSection(r));
        root.scrollTo(0, scrollY);           // re-rendu (tri, plafond, fenêtre) : la page ne saute pas
    }

    function render() { dataPanel(); profilePanel(); runPanel(); renderResult(); }
    call("GET", "/api/placements/catalog").then(function (c) { state.catalog = c; }).catch(function () { state.catalog = null; }).then(loadAll);
})(typeof window !== "undefined" ? window : globalThis);
