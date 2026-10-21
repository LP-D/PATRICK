/* HMM market state on the synthesis page: reads /api/market-state (cache
   filled by a background thread, a few seconds per market) and polls while the first
   computation is still running. No-op without #market-state. */
(function () {
    "use strict";
    var root = document.getElementById("market-state");
    if (!root) return;
    var I18N = window.I18N || {};
    var LANG = document.documentElement.lang || "fr";
    function T(key, fallback, params) {
        var text = I18N[key] || fallback || key;
        return params ? text.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; }) : text;
    }
    var STATE = { calme: "ok", stress: "error" };
    var LABEL = { calme: T("js_ms_calm", "calm"), stress: T("js_ms_stressed", "stress") };

    function pct(x) { return (x * 100).toLocaleString(LANG, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + (LANG === "fr" ? " %" : "%"); }

    function note(text) {
        root.innerHTML = "";
        var p = document.createElement("p");
        p.className = "hint";
        p.textContent = text;
        root.appendChild(p);
    }

    function cell(tr, text, cls) {
        var td = document.createElement("td");
        if (cls) td.className = cls;
        if (text instanceof Node) td.appendChild(text); else td.textContent = text;
        tr.appendChild(td);
        return td;
    }

    function render(data) {
        root.innerHTML = "";
        var wrap = document.createElement("div");
        wrap.className = "table-scroll";
        var table = document.createElement("table");
        table.className = "data-table";
        table.innerHTML = "<thead><tr><th>" + T("js_ms_market", "Market") + "</th><th>" + T("js_ms_regime", "Regime") + "</th><th class='num'>" + T("js_ms_pstress", "P(stress)") + "</th>" +
            "<th>" + T("js_ms_since", "Since") + "</th><th class='num'>" + T("js_ms_stress", "Stress (63 sess.)") + "</th><th class='num'>" + T("js_ms_vol21", "Vol. 21 sess.") + "</th>" +
            "<th class='num'>" + T("js_ms_vol_long", "Long-term vol.") + "</th><th class='num'>" + T("js_ms_vol_states", "Vol. calm / stress state") + "</th></tr></thead>";
        var tbody = document.createElement("tbody");
        data.rows.forEach(function (r) {
            var tr = document.createElement("tr");
            cell(tr, r.label);
            if (r.status !== "ok") {
                var msg = r.status === "insufficient" ? T("js_ms_insufficient", "insufficient history") : T("js_ms_row_unavailable", "unavailable: {error}", { error: r.error || "" });
                var td = cell(tr, msg, "na");
                td.colSpan = 7;
                tbody.appendChild(tr);
                return;
            }
            var badge = document.createElement("span");
            badge.className = "status-badge status-" + (STATE[r.regime] || "neutral");
            badge.textContent = LABEL[r.regime] || r.regime;
            cell(tr, badge);
            cell(tr, pct(r.stress_prob), "num pk-mono");
            cell(tr, r.since + " (" + r.sessions_in_regime + " " + T("js_ms_sess", "sess.") + ")", "pk-mono");
            cell(tr, pct(r.share_stress_63), "num pk-mono");
            cell(tr, pct(r.vol_21d), "num pk-mono");
            cell(tr, pct(r.vol_long), "num pk-mono");
            cell(tr, pct(r.vol_calm) + " / " + pct(r.vol_stress), "num pk-mono");
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        root.appendChild(wrap);
        var foot = document.createElement("p");
        foot.className = "table-footer";
        foot.textContent = T("js_ms_updated", "Updated: {at} · last session per market: {sessions}", { at: data.updated_at,
            sessions: data.rows.filter(function (r) { return r.as_of; }).map(function (r) { return r.label + " " + r.as_of; }).join(", ") });
        root.appendChild(foot);
    }

    async function load(attempt) {
        try {
            var res = await fetch("/api/market-state");
            var data = await res.json();
            if (data.rows && data.rows.length) { render(data); return; }
            if (data.error) { note(data.error); return; }
            note(T("js_ms_computing", "Computing the market state (HMM)…"));
            if (attempt < 40) setTimeout(function () { load(attempt + 1); }, 5000);
        } catch (e) {
            note(T("js_ms_unavailable", "Market state unavailable: {error}", { error: e }));
        }
    }
    load(0);
})();
