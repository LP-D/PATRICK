/* Questions en langage naturel sur un run (A27) : envoie la question à /api/runs/{id}/ask, affiche la réponse en texte brut (jamais du
   HTML venu du modèle) et l'avertissement de fuite temporelle quand une partie des dates évaluées précède la limite du modèle. */
(function () {
    "use strict";
    var box = document.querySelector(".run-qa");
    if (!box) return;
    var form = box.querySelector(".run-qa-form"), out = box.querySelector(".run-qa-answer"), btn = form.querySelector("button");
    function show(nodes) {
        out.replaceChildren.apply(out, nodes);
        out.hidden = false;
    }
    function para(text, cls) {
        var p = document.createElement("p");
        if (cls) p.className = cls;
        p.textContent = text;
        return p;
    }
    form.addEventListener("submit", function (e) {
        e.preventDefault();
        var question = form.elements.question.value.trim();
        if (!question) return;
        btn.disabled = true;
        show([para(box.dataset.labelWait || "…", "hint")]);
        fetch("/api/runs/" + encodeURIComponent(box.dataset.runId) + "/ask", {
            method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
            body: JSON.stringify({ question: question }),
        }).then(function (r) {
            return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        }).then(function (res) {
            if (!res.ok) {
                show([para((box.dataset.labelError || "Error") + " : " + (res.data.detail || ""), "banner banner-error")]);
                return;
            }
            var d = res.data, nodes = [];
            (d.answer || box.dataset.labelRefused || "").split(/\n{2,}/).forEach(function (chunk) { nodes.push(para(chunk, "run-qa-text")); });
            var leak = d.leak || {};
            if (leak.clean_share !== null && leak.clean_share !== undefined && leak.clean_share < 1) {
                var share = Math.round(leak.clean_share * 100) + " %";
                nodes.push(para((box.dataset.labelLeak || "").replace("{cutoff}", leak.cutoff).replace("{share}", share), "hint run-qa-leak"));
            }
            show(nodes);
        }).catch(function () {
            show([para(box.dataset.labelError || "Error", "banner banner-error")]);
        }).finally(function () { btn.disabled = false; });
    });
})();
