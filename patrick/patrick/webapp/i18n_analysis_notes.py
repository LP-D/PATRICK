"""Chaînes FR/EN du carnet de recherche (`/carnet`, `static/carnet.js`). Fusionnées dans `ANALYSIS_STRINGS`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


NOTES_STRINGS: dict[str, dict[str, str]] = {
    "nav_carnet": _s("Carnet", "Notebook"),
    "ra_s_notes": _s("Carnet de recherche", "Research notebook"),
    "ra_h_notes": _s("Notes et hypothèses liées à ce run et à sa cible. Une hypothèse écrite avant le run, puis confirmée ou réfutée, laisse une trace de ce qui était attendu.", "Notes and hypotheses linked to this run and its target. A hypothesis written before the run, then confirmed or refuted, leaves a trace of what was expected."),
    "ra_s_rl_notes": _s("Carnet de recherche", "Research notebook"),
    "ra_h_rl_notes": _s("Notes et hypothèses liées à ce run et à sa cible.", "Notes and hypotheses linked to this run and its target."),
    "cn_title": _s("Carnet de recherche", "Research notebook"),
    "cn_subtitle": _s("Hypothèses, notes, résultats et décisions, liés à une cible, un horizon ou un run. Écrire l'hypothèse AVANT de lancer le run est la meilleure défense contre le p-hacking.", "Hypotheses, notes, results and decisions, linked to a target, a horizon or a run. Writing the hypothesis BEFORE launching the run is the best defence against p-hacking."),
    "cn_s_new": _s("Nouvelle entrée", "New entry"),
    "cn_h_new": _s("Une hypothèse précise (quoi, sur quelle cible, ce qu'on s'attend à voir) se juge ensuite : confirmée ou réfutée. Rien ne se supprime : une entrée inutile s'archive.", "A precise hypothesis (what, on which target, what you expect to see) is judged afterwards: confirmed or refuted. Nothing is deleted: a useless entry is archived."),
    "cn_s_list": _s("Entrées", "Entries"),
    "cn_k_hypothesis": _s("Hypothèse", "Hypothesis"), "cn_k_note": _s("Note", "Note"), "cn_k_result": _s("Résultat", "Result"), "cn_k_decision": _s("Décision", "Decision"),
    "cn_s_open": _s("Ouverte", "Open"), "cn_s_confirmed": _s("Confirmée", "Confirmed"), "cn_s_refuted": _s("Réfutée", "Refuted"), "cn_s_archived": _s("Archivée", "Archived"),
    "cn_f_kind": _s("Type", "Kind"),
    "cn_f_title": _s("Titre (obligatoire)", "Title (required)"),
    "cn_f_body": _s("Détail : ce qu'on attend, comment on le jugera, ce qu'on a vu…", "Detail: what is expected, how it will be judged, what was seen…"),
    "cn_f_tags": _s("Étiquettes séparées par des virgules", "Tags separated by commas"),
    "cn_f_run": _s("Identifiant de run (facultatif)", "Run id (optional)"),
    "cn_save": _s("Enregistrer", "Save"),
    "cn_confirm": _s("Confirmée", "Confirmed"), "cn_refute": _s("Réfutée", "Refuted"), "cn_archive": _s("Archiver", "Archive"),
    "cn_before_run": _s("posée avant le run", "written before the run"), "cn_after_run": _s("écrite après le début du run", "written after the run started"),
    "cn_created": _s("créée le {d}", "created on {d}"), "cn_revised": _s("modifiée {n} fois, dernière le {d}", "edited {n} times, last on {d}"),
    "cn_none": _s("Aucune entrée pour ces filtres.", "No entry for these filters."),
    "cn_none_run": _s("Aucune note liée à ce run.", "No note linked to this run."),
    "cn_related": _s("{n} entrée(s) sur la même cible et le même horizon", "{n} entry(ies) on the same target and horizon"),
    "cn_filter_q": _s("Rechercher dans les titres et textes", "Search titles and texts"),
    "cn_show_archived": _s("Afficher les archivées", "Show archived"),
    "cn_k_total": _s("Entrées actives", "Active entries"), "cn_k_total_sub": _s("hors archivées", "excluding archived"),
    "cn_k_hyp": _s("Hypothèses", "Hypotheses"), "cn_k_hyp_sub": _s("{o} ouvertes · {c} confirmées · {r} réfutées", "{o} open · {c} confirmed · {r} refuted"),
    "cn_k_rate": _s("Taux de confirmation", "Confirmation rate"), "cn_k_rate_sub": _s("sur {n} hypothèses jugées ; un taux très haut peut signaler des hypothèses trop faciles", "over {n} judged hypotheses; a very high rate may signal hypotheses that are too easy"),
    "cn_err_bad_kind": _s("Type inconnu.", "Unknown kind."), "cn_err_bad_status": _s("Statut inconnu.", "Unknown status."), "cn_err_title_required": _s("Le titre est obligatoire.", "The title is required."),
    "cn_err_not_found": _s("Entrée introuvable.", "Entry not found."), "cn_err_bad_horizon": _s("Horizon invalide.", "Invalid horizon."), "cn_err_unknown": _s("L'enregistrement a échoué.", "Saving failed."),
}
