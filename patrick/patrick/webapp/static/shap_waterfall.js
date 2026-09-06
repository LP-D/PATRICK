(function () {
    "use strict";

    // feature/shap-waterfall (Phase 7): on-demand SHAP explanation for the
    // most recent recorded prediction of a (ticker, horizon), on
    // `/targets/{ticker}` (`#shap-waterfall-widget[data-target]`). Same
    // client-fetch-then-render split as `asset_stats.js` -- the SVG itself
    // is fully built server-side (`webapp/shap_chart.py`), this script only
    // fetches it and swaps it into the page; no charting library, no
    // client-side geometry.

    var I18N = window.I18N || {};
    function tr(key, fallback) { return I18N[key] || fallback || key; }
    function fmtStr(str, params) {
        return str.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; });
    }

    function emptyStateHtml(message) {
        return '<div class="empty-state"><p class="empty-state-message">' + message + '</p></div>';
    }

    function render(widget, data) {
        var output = widget.querySelector(".shap-waterfall-output");
        if (!output) return;
        if (!data.ok) {
            output.innerHTML = emptyStateHtml(data.message || tr("shap_unavailable", "No explanation available."));
            return;
        }
        var caption = fmtStr(
            tr("shap_caption", "{date} · predicted: {label} (confidence {proba}) · {n} features · split {split}"),
            {
                date: data.ts,
                label: tr("shap_class_" + data.y_pred, data.y_pred_label),
                proba: data.y_proba === null ? "—" : Math.round(data.y_proba * 100) + "%",
                n: data.n_features_total,
                split: data.split,
            }
        );
        output.innerHTML =
            '<p class="hint shap-caption">' + caption + '</p>' +
            '<div class="shap-waterfall-svg">' + data.svg + '</div>' +
            '<p class="hint shap-units-hint">' + tr("shap_units_hint",
                "Bars are the model's raw per-class score (not a probability): SHAP's additive guarantee holds in that space for a multiclass tree ensemble, not after the softmax.") + '</p>';
    }

    function loadWidget(widget) {
        var target = widget.getAttribute("data-target");
        var select = widget.querySelector(".shap-horizon-select");
        var button = widget.querySelector(".shap-generate-btn");
        var output = widget.querySelector(".shap-waterfall-output");
        if (!target || !select || !button || !output) return;

        button.addEventListener("click", function () {
            var horizon = select.value;
            if (!horizon) return;
            button.disabled = true;
            output.innerHTML = '<p class="hint">' + tr("shap_loading", "Computing…") + '</p>';
            fetch("/api/targets/" + encodeURIComponent(target) + "/shap-waterfall?horizon=" + encodeURIComponent(horizon))
                .then(function (r) { return r.json(); })
                .then(function (data) { render(widget, data); })
                .catch(function () {
                    output.innerHTML = emptyStateHtml(tr("shap_load_error", "Loading error."));
                })
                .finally(function () { button.disabled = false; });
        });
    }

    var widgets = document.querySelectorAll("#shap-waterfall-widget[data-target]");
    widgets.forEach(function (widget) { loadWidget(widget); });
})();
