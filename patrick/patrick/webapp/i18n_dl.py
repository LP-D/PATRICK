"""Chaînes FR/EN de la page Deep learning (`/dl`) : titres, champs du réseau, profils d'entraînement. Fusionnées par `i18n_models`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


DL_STRINGS: dict[str, dict[str, str]] = {
    "dl_title": _s("Deep learning", "Deep learning"),
    "dl_subtitle": _s(
        "Réseaux de neurones (MLP, GRU, LSTM, CNN1D, Transformer) entraînés comme des algorithmes de plus du même pipeline : mêmes cibles, "
        "mêmes horizons, même validation walk-forward avec purge et embargo, même sélection de variables, même tuning Optuna, même "
        "classement. Vue simplifiée : choisis les réseaux et un profil. Vue experte : architecture, entraînement et calcul champ par champ.",
        "Neural networks (MLP, GRU, LSTM, CNN1D, Transformer) trained as extra algorithms of the same pipeline: same targets, same "
        "horizons, same walk-forward validation with purge and embargo, same feature selection, same Optuna tuning, same leaderboard. "
        "Simple view: pick the networks and a profile. Expert view: architecture, training and compute, field by field."),
    "dl_no_torch": _s(
        "PyTorch n'est pas installé : les réseaux sont indisponibles et le lancement est désactivé. Installe-le avec « pip install -e \".[deep]\" ».",
        "PyTorch is not installed: networks are unavailable and launching is disabled. Install it with \"pip install -e \".[deep]\"\"."),
    "dl_sec_networks": _s("Réseaux", "Networks"),
    "dl_window_hint": _s(
        "MLP lit une ligne à la fois. GRU, LSTM, CNN1D et Transformer lisent une fenêtre de lignes consécutives (« lookback ») : ils exigent "
        "le sampler « none » (un sur-échantillonneur comme SMOTE réordonne et synthétise des lignes) et ne tournent pas en CPCV (groupes "
        "non contigus). Le formulaire refuse ces combinaisons au lancement.",
        "MLP reads one row at a time. GRU, LSTM, CNN1D and Transformer read a window of consecutive rows (\"lookback\"): they require the "
        "\"none\" sampler (an oversampler such as SMOTE reorders and synthesizes rows) and do not run under CPCV (non-contiguous groups). "
        "The form refuses these combinations at launch."),
    "dl_sec_arch": _s("Architecture", "Architecture"),
    "dl_sec_train": _s("Entraînement", "Training"),
    "dl_sec_compute": _s("Calcul", "Compute"),
    "dl_sec_extra": _s("Calibration et empilement", "Calibration and stacking"),

    "dl_f_hidden_size": _s("Taille cachée", "Hidden size"),
    "dl_f_n_layers": _s("Couches", "Layers"),
    "dl_f_dropout": _s("Dropout", "Dropout"),
    "dl_f_lookback": _s("Fenêtre (lookback)", "Window (lookback)"),
    "dl_f_n_heads": _s("Têtes d'attention", "Attention heads"),
    "dl_f_kernel_size": _s("Noyau (CNN1D)", "Kernel (CNN1D)"),
    "dl_f_epochs": _s("Époques maximum", "Max epochs"),
    "dl_f_batch_size": _s("Taille de lot", "Batch size"),
    "dl_f_learning_rate": _s("Taux d'apprentissage", "Learning rate"),
    "dl_f_weight_decay": _s("Décroissance des poids", "Weight decay"),
    "dl_f_patience": _s("Patience (arrêt anticipé)", "Patience (early stopping)"),
    "dl_f_val_fraction": _s("Fraction de validation", "Validation fraction"),
    "dl_f_grad_clip": _s("Coupure du gradient", "Gradient clipping"),
    "dl_f_class_weight": _s("Pondération des classes", "Class weighting"),
    "dl_f_n_seeds": _s("Réseaux moyennés", "Averaged networks"),
    "dl_f_device": _s("Appareil", "Device"),
    "dl_f_threads": _s("Fils de calcul", "Compute threads"),
    "dl_o_class_weight_balanced": _s("Équilibrée", "Balanced"),
    "dl_o_class_weight_none": _s("Aucune", "None"),
    "dl_o_device_auto": _s("Automatique", "Automatic"),
    "dl_o_device_cpu": _s("Processeur", "CPU"),
    "dl_o_device_cuda": _s("Carte graphique (CUDA)", "Graphics card (CUDA)"),

    # --- profils (clés `prof_<profil>_name|desc` lues par `_profile_gallery.html`)
    "prof_dl_quick_name": _s("Réseau rapide", "Quick network"),
    "prof_dl_quick_desc": _s("Un MLP léger, sans réglage Optuna, 3 folds et une grille de variables étroite : pour vérifier qu'un réseau trouve quelque chose avant d'investir.",
                             "A light MLP, no Optuna tuning, 3 folds and a narrow feature grid: check that a network finds something before investing."),
    "prof_dl_standard_name": _s("Standard", "Standard"),
    "prof_dl_standard_desc": _s("Les réglages par défaut du deep learning : MLP et GRU, 15 essais Optuna, arrêt anticipé.",
                                "The deep-learning defaults: MLP and GRU, 15 Optuna trials, early stopping."),
    "prof_dl_sequence_name": _s("Séquences", "Sequences"),
    "prof_dl_sequence_desc": _s("GRU, LSTM et CNN1D sur une fenêtre de 30 barres : pour tester si l'ordre des jours porte un signal que la ligne seule n'a pas.",
                                "GRU, LSTM and CNN1D on a 30-bar window: test whether the order of days carries a signal a single row lacks."),
    "prof_dl_attention_name": _s("Attention (Transformer)", "Attention (Transformer)"),
    "prof_dl_attention_desc": _s("Un Transformer sur 40 barres, 2 couches : le plus coûteux des réseaux, à réserver aux cibles avec beaucoup d'historique.",
                                 "A Transformer over 40 bars, 2 layers: the costliest network, for targets with a lot of history."),
    "prof_dl_sober_name": _s("Sobre (peu de données)", "Sober (little data)"),
    "prof_dl_sober_desc": _s("Petits réseaux, dropout élevé, forte régularisation, sans Optuna : quand l'historique est court et que le surapprentissage menace.",
                             "Small networks, high dropout, strong regularization, no Optuna: when history is short and overfitting looms."),
    "prof_dl_ensemble_name": _s("Ensemble de réseaux", "Network ensemble"),
    "prof_dl_ensemble_desc": _s("Les cinq architectures, 3 graines chacune moyennées, probabilités calibrées : lisse le hasard d'initialisation, coût multiplié.",
                                "All five architectures, 3 averaged seeds each, calibrated probabilities: smooths initialization luck, cost multiplied."),
    "prof_dl_wide_search_name": _s("Recherche large", "Wide search"),
    "prof_dl_wide_search_desc": _s("MLP, GRU et LSTM, 60 essais Optuna et 2 configurations affinées par horizon, grille de variables étendue : la recherche la plus exhaustive.",
                                   "MLP, GRU and LSTM, 60 Optuna trials and 2 tuned configurations per horizon, wider feature grid: the most exhaustive search."),
    "prof_dl_long_memory_name": _s("Mémoire longue", "Long memory"),
    "prof_dl_long_memory_desc": _s("GRU et LSTM sur 60 barres, 96 unités : pour les signaux lents (tendances, cycles) qu'une fenêtre courte ne voit pas.",
                                   "GRU and LSTM over 60 bars, 96 units: for slow signals (trends, cycles) a short window cannot see."),
}
