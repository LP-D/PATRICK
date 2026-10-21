"""Chaînes FR/EN du journal de prédictions (`/journal`, `static/journal.js`). Fusionnées dans `ANALYSIS_STRINGS`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


JOURNAL_STRINGS: dict[str, dict[str, str]] = {
    "nav_journal": _s("Journal", "Journal"),
    "aj_title": _s("Journal de prédictions", "Prediction journal"),
    "aj_subtitle": _s("Chaque signal est scellé, horodaté et relié à l'empreinte du modèle qui l'a produit, avant que son issue ne soit connue. La chaîne de hachage rend toute modification visible.", "Every signal is sealed, timestamped and linked to the fingerprint of the model that produced it, before its outcome is known. The hash chain makes any change visible."),
    "aj_s_chain": _s("Intégrité de la chaîne", "Chain integrity"),
    "aj_h_chain": _s("Chaque ligne contient l'empreinte de la précédente : modifier, insérer ou supprimer une ligne casse la chaîne à cet endroit. La vérification rejoue tout le journal.", "Each row holds the fingerprint of the previous one: changing, inserting or deleting a row breaks the chain at that point. Verification replays the whole journal."),
    "aj_s_pairs": _s("Réussite et calibration live par couple", "Live hit rate and calibration by pair"),
    "aj_h_pairs": _s("Calculées sur le journal seul (le premier signal écrit fait foi), jamais sur la table des prédictions qui peut se réécrire.", "Computed from the journal alone (the first signal written stands), never from the predictions table which can be rewritten."),
    "aj_s_entries": _s("Lignes du journal", "Journal rows"),
    "aj_h_entries": _s("Les plus récentes d'abord. « Scellement » = prédiction déjà stockée, ajoutée après coup : son horodatage est celui du scellement, pas de l'émission.", "Most recent first. \"Sealing\" = a prediction already stored, added afterwards: its timestamp is the sealing time, not the issuing time."),
    "aj_k_entries": _s("Lignes", "Rows"), "aj_k_entries_sub": _s("{s} signaux · {o} issues", "{s} signals · {o} outcomes"),
    "aj_k_span": _s("Depuis", "Since"), "aj_k_span_sub": _s("dernière ligne : {d}", "last row: {d}"), "aj_k_empty": _s("journal vide", "empty journal"),
    "aj_k_models": _s("Modèles distincts", "Distinct models"), "aj_k_models_sub": _s("empreintes de fichiers de modèle", "model file fingerprints"),
    "aj_k_backfill": _s("Signaux scellés après coup", "Signals sealed afterwards"), "aj_k_backfill_sub": _s("horodatage = scellement", "timestamp = sealing"),
    "aj_k_div": _s("Écarts avec la table", "Gaps with the table"), "aj_k_div_sub": _s("sur {n} signaux comparés", "out of {n} signals compared"),
    "aj_verify": _s("Vérifier la chaîne", "Verify the chain"),
    "aj_verifying": _s("Vérification en cours…", "Verifying…"),
    "aj_ok": _s("Chaîne intacte : {n} lignes rejouées, dernière empreinte {h}…", "Chain intact: {n} rows replayed, last fingerprint {h}…"),
    "aj_broken": _s("Chaîne cassée à la ligne {id} ({r}). Les lignes à partir de là ne sont plus fiables.", "Chain broken at row {id} ({r}). Rows from there on are no longer reliable."),
    "aj_reason_prev_mismatch": _s("la ligne ne relie pas la précédente : insertion ou suppression", "the row does not link the previous one: insertion or deletion"),
    "aj_reason_hash_mismatch": _s("le contenu ne correspond plus à son empreinte : modification", "the content no longer matches its fingerprint: modification"),
    "aj_seal": _s("Sceller l'existant", "Seal existing"),
    "aj_seal_confirm": _s("Ajouter au journal les prédictions live déjà stockées qui n'y figurent pas ? Elles seront marquées « scellement » : leur horodatage sera celui d'aujourd'hui.", "Add to the journal the already stored live predictions that are not in it? They will be marked \"sealing\": their timestamp will be today's."),
    "aj_sealing": _s("Scellement en cours…", "Sealing…"),
    "aj_sealed": _s("{s} signaux et {o} issues scellés.", "{s} signals and {o} outcomes sealed."),
    "aj_seal_hint": _s("Les nouveaux signaux sont journalisés automatiquement dès leur émission ; ce bouton ne sert qu'à l'existant, une seule fois.", "New signals are journaled automatically as soon as they are issued; this button is only for what already exists, once."),
    "aj_export": _s("Exporter (CSV)", "Export (CSV)"),
    "aj_no_pairs": _s("Aucun signal dans le journal. Les prochains signaux live y seront inscrits automatiquement ; « Sceller l'existant » y ajoute ceux déjà stockés.", "No signal in the journal. The next live signals will be written automatically; \"Seal existing\" adds those already stored."),
    "aj_c_signals": _s("Signaux", "Signals"), "aj_c_judged": _s("Jugés", "Judged"), "aj_c_pending": _s("En attente", "Pending"),
    "aj_c_last": _s("{n} derniers", "Last {n}"), "aj_c_base": _s("sans compétence", "no skill"),
    "aj_c_span": _s("Période", "Period"), "aj_c_models": _s("Modèles", "Models"), "aj_c_backfill": _s("Scellés", "Sealed"),
    "aj_pairs_hint": _s("Réussite sur les {m} derniers signaux jugés ; calibration (ECE, Brier) dès 30 signaux jugés avec P(hausse).", "Hit rate over the last {m} judged signals; calibration (ECE, Brier) from 30 judged signals with P(up)."),
    "aj_div_h": _s("Écarts entre le journal et la table des prédictions", "Gaps between the journal and the predictions table"),
    "aj_div_journal": _s("Journal (fait foi)", "Journal (stands)"), "aj_div_table": _s("Table des prédictions", "Predictions table"),
    "aj_div_hint": _s("Un signal de la table diffère du premier signal journalisé : la table a été réécrite après l'émission. Le journal fait foi.", "A table signal differs from the first journaled signal: the table was rewritten after issuing. The journal stands."),
    "aj_c_date": _s("Date du signal", "Signal date"), "aj_c_recorded": _s("Inscrit le", "Recorded"), "aj_c_kind": _s("Type", "Kind"), "aj_c_origin": _s("Origine", "Origin"),
    "aj_c_pred": _s("Prédit", "Predicted"), "aj_c_outcome": _s("Issue", "Outcome"), "aj_c_model": _s("Modèle (SHA)", "Model (SHA)"), "aj_c_hash": _s("Empreinte", "Fingerprint"),
    "aj_kind_signal": _s("signal", "signal"), "aj_kind_outcome": _s("issue", "outcome"), "aj_backfill": _s("scellement", "sealing"),
    "aj_entries_n": _s("Lignes {a} à {b} sur {n}.", "Rows {a} to {b} of {n}."),
}
