/* Boîtes de dialogue de la page, partagées : aucune boîte native du navigateur (confirm, prompt).
   - window.patrickDialog.ask(dialog, prepare, result) : ouvre `dialog` en modal ; rend result() si son formulaire
     est soumis, null sur Annuler (bouton [data-close-dialog]) ou Échap. Le résultat vient des boutons et de la
     soumission, pas de l'événement « close », qui n'est pas déclenché partout.
   - window.patrickDialog.confirm(message, label, danger) : Promise<boolean> sur la boîte #confirm-dialog de
     base_v2.html ; `label` = texte du bouton de validation, `danger` = bouton rouge (action sans retour).
   - <form data-confirm="message" [data-confirm-label="…"] [data-confirm-danger]> : l'envoi attend la réponse.
   Les pages appellent ces aides à l'usage : ce script est chargé après les leurs. Texte toujours par textContent. */
(function () {
    "use strict";

    function ask(dialog, prepare, result) {
        return new Promise(function (resolve) {
            var form = dialog ? dialog.querySelector("form") : null;
            if (!form || !dialog.showModal) { resolve(null); return; }
            function finish(value) {
                form.removeEventListener("submit", onSubmit);
                dialog.removeEventListener("click", onClick);
                dialog.removeEventListener("cancel", onDismiss);
                dialog.removeEventListener("close", onDismiss);
                if (dialog.open) dialog.close();
                resolve(value);
            }
            function onSubmit(e) { e.preventDefault(); finish(result()); }
            function onClick(e) { if (e.target.closest("[data-close-dialog]")) finish(null); }
            function onDismiss() { finish(null); }
            form.addEventListener("submit", onSubmit);
            dialog.addEventListener("click", onClick);
            dialog.addEventListener("cancel", onDismiss);
            dialog.addEventListener("close", onDismiss);
            prepare();
            dialog.showModal();
        });
    }

    async function confirmAction(message, label, danger) {
        var dialog = document.getElementById("confirm-dialog");
        var ok = document.getElementById("confirm-ok");
        var answer = await ask(dialog, function () {
            document.getElementById("confirm-message").textContent = message;
            ok.textContent = label || ok.getAttribute("data-default-label") || "OK";
            ok.classList.toggle("btn-danger", !!danger);
        }, function () { return true; });
        return answer === true;
    }

    window.patrickDialog = { ask: ask, confirm: confirmAction };

    /* Formulaires à confirmer : on suspend l'envoi, on demande, puis on envoie (sans repasser par cet écouteur). */
    document.addEventListener("submit", async function (e) {
        var form = e.target;
        if (!form.matches || !form.matches("form[data-confirm]")) return;
        e.preventDefault();
        if (form.dataset.asking === "1") return;          // double clic : une seule question à la fois
        form.dataset.asking = "1";
        var yes = await confirmAction(form.getAttribute("data-confirm"), form.getAttribute("data-confirm-label"),
                                      form.hasAttribute("data-confirm-danger"));
        delete form.dataset.asking;
        if (yes) HTMLFormElement.prototype.submit.call(form);
    }, true);
})();
