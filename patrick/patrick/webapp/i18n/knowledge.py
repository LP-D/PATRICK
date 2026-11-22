"""Chaînes FR/EN de la section Connaissances (parcours, cours, dictionnaire). Fusionné dans `i18n_models.MODELS_STRINGS`. Les LIBELLÉS des notions, thèmes et niveaux
viennent de `patrick/knowledge/` (déjà dans les deux langues) ; ici, seulement le texte de l'interface."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


KNOWLEDGE_STRINGS: dict[str, dict[str, str]] = {
    "nav_cat_connaissances": _s("CONNAISSANCES", "KNOWLEDGE"),
    "nav_cat_desc_connaissances": _s("Apprendre : un parcours des bases de la finance aux méthodes avancées, des cours détaillés et un dictionnaire du quant.",
                                     "Learn: a path from the basics of finance to advanced methods, detailed courses and a quant dictionary."),
    "nav_knowledge_hub": _s("Parcours", "Learning path"),
    "nav_knowledge_courses": _s("Cours", "Courses"),
    "nav_knowledge_dictionary": _s("Dictionnaire", "Dictionary"),

    # --- parcours (page d'accueil de la section)
    "kb_hub_title": _s("Connaissances du quant", "Quant knowledge"),
    "kb_hub_subtitle": _s("Des bases de la finance aux méthodes les plus avancées : un parcours en trois niveaux, des cours détaillés et un dictionnaire de {n} notions.",
                          "From the basics of finance to the most advanced methods: a three-level path, detailed courses and a dictionary of {n} entries."),
    "kb_search_placeholder": _s("Chercher une notion (Sharpe, GARCH, duration…)", "Search an entry (Sharpe, GARCH, duration…)"),
    "kb_search_go": _s("Chercher", "Search"),
    "kb_levels_title": _s("Trois niveaux", "Three levels"),
    "kb_level_entries": _s("{n} notions", "{n} entries"),
    "kb_level_unit": _s("notions", "entries"),
    "kb_open_dictionary": _s("Ouvrir le dictionnaire", "Open the dictionary"),
    "kb_courses_title": _s("Cours", "Courses"),
    "kb_courses_hub_hint": _s("Des cours rédigés pour aller au fond d'un sujet, avec les formules et des exemples chiffrés. Chaque notion du dictionnaire liée à un cours y renvoie.",
                              "Courses written to go deep on a subject, with formulas and worked numbers. Every dictionary entry tied to a course links to it."),
    "kb_matrix_title": _s("Carte des notions : thème × niveau", "Entry map: theme × level"),
    "kb_matrix_hint": _s("Chaque case est un lien vers les notions correspondantes. Lire de gauche à droite pour monter en difficulté.", "Each cell links to the matching entries. Read left to right to move up in difficulty."),
    "kb_matrix_theme": _s("Thème", "Theme"),
    "kb_path_hint": _s("Conseil : commencer par le niveau 1 des thèmes « Bases » et « Marchés », puis le niveau 2 de « Risque » et « Portefeuille », avant d'aborder les séries temporelles et le backtest.",
                       "Tip: start with level 1 of the 'Basics' and 'Markets' themes, then level 2 of 'Risk' and 'Portfolio', before tackling time series and backtesting."),

    # --- cours
    "kb_courses_page_title": _s("Cours", "Courses"),
    "kb_courses_page_subtitle": _s("Les cours de PATRICK : chaque chapitre explique la méthode, les mathématiques et la lecture d'un résultat.", "PATRICK's courses: each chapter explains the method, the maths and how to read a result."),
    "kb_read_course": _s("Lire le cours", "Read the course"),
    "kb_reading_time": _s("{n} min de lecture", "{n} min read"),
    "kb_course_entries": _s("{n} notions liées", "{n} linked entries"),
    "kb_course_unavailable": _s("Cours indisponible : le dossier docs/cours est absent de cette installation.", "Course unavailable: the docs/cours folder is missing from this installation."),
    "kb_course_french_only": _s("Ce cours est rédigé en français.", "This course is written in French."),
    "kb_course_toc": _s("Plan du cours", "Course outline"),
    "kb_course_back": _s("Tous les cours", "All courses"),
    "kb_course_terms": _s("Notions de ce cours", "Entries in this course"),
    "kb_course_terms_hint": _s("Les définitions courtes du dictionnaire qui renvoient à un chapitre de ce cours.", "The short dictionary definitions that point to a chapter of this course."),
    "kb_course_missing": _s("Cours inconnu.", "Unknown course."),

    # --- dictionnaire
    "kb_dict_title": _s("Dictionnaire du quant", "Quant dictionary"),
    "kb_dict_subtitle": _s("{n} notions, de la finance de base à l'économétrie et au backtest. Chaque définition est autonome ; les renvois et les cours permettent d'aller plus loin.",
                           "{n} entries, from basic finance to econometrics and backtesting. Each definition stands alone; cross-references and courses let you go further."),
    "kb_dict_search": _s("Chercher dans le dictionnaire…", "Search the dictionary…"),
    "kb_dict_count": _s("{n} / {total} notions", "{n} / {total} entries"),
    "kb_dict_none": _s("Aucune notion ne correspond à ces filtres.", "No entry matches these filters."),
    "kb_filter_level": _s("Niveau", "Level"),
    "kb_filter_theme": _s("Thème", "Theme"),
    "kb_filter_all": _s("Tous", "All"),
    "kb_filter_all_themes": _s("Tous les thèmes", "All themes"),
    "kb_filter_reset": _s("Tout réinitialiser", "Reset all"),
    "kb_letters": _s("Index alphabétique", "Alphabetical index"),
    "kb_see_also": _s("Voir aussi", "See also"),
    "kb_in_course": _s("Dans le cours", "In the course"),
    "kb_formula": _s("Formule", "Formula"),
    "kb_permalink": _s("Lien vers cette notion", "Link to this entry"),
    "kb_also_called": _s("Aussi : {names}", "Also: {names}"),
    "kb_from_bubbles": _s("Vient du lexique de l'application", "From the application lexicon"),
    "kb_legacy_page": _s("Le lexique compact de l'application (celui des bulles « ? ») est inclus dans ce dictionnaire.", "The application's compact lexicon (the one behind the '?' bubbles) is included in this dictionary."),
    "kb_open_full_dictionary": _s("Dictionnaire complet", "Full dictionary"),
}
