"""Detection de regime de volatilite par HMM causal (CHANTIER A,
feature/regime-detection-hmm) : nombre d'etats selectionnable par BIC/AIC
(defaut : le plus bas score parmi 2/3/4), reduit a exactement 3 labels de
sortie (calme/normal/stress) via un seuillage configurable (quantile ou
valeur fixe) applique a la probabilite filtree de l'etat de plus haute
variance.

Reuse vs duplication (verifie avant d'ecrire ce module, cf. grep sur
`features/vol_models.py` demande par le chantier) : `vol_models.py` a deja
`hmm_filtered_stress_prob`, un HMM causal a n_states fixe (defaut 2) qui
expose uniquement P(etat de plus haute variance), pense comme UNE feature
parmi d'autres du pool de volatilite (walk-forward, `fit_end_idx`). Ce
module a un objet different (un LABEL de regime discret, avec selection du
nombre d'etats et seuillage configurable, utilise ensuite par les chantiers
B/D comme partition de l'univers pour l'entrainement par-regime) : le
recyclage direct de la fonction existante aurait force soit a la denaturer
(ajouter selection BIC/AIC et seuillage a une fonction pensee comme une
feature simple), soit a dupliquer sa recursion forward en la generalisant.
Decision : dupliquer UNIQUEMENT la recursion forward bas niveau (30 lignes,
`_causal_forward_filtered_probs` ci-dessous) plutot que le module entier --
signale explicitement ici plutot que laisse silencieux. `vol_models.py`
n'est pas touche par ce chantier (aucun risque de regression sur son usage
existant, deja teste par ailleurs).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from patrick.config.defaults import DEFAULT_MIN_TRAIN_FRAC, DEFAULT_N_WF_FOLDS
from patrick.features._utils import safe_pct_change
from patrick.validation.feasibility import (
    FeasibilityResult,
    is_feasible,
    min_obs_required,
)

if TYPE_CHECKING:
    from hmmlearn.hmm import GaussianHMM

ThresholdMode = Literal["quantile", "fixed"]
REGIME_LABELS = ("calme", "normal", "stress")


class RegimeFragmentationError(ValueError):
    """Leve quand un regime n'a pas assez d'observations pour un walk-forward
    statistiquement valide a l'horizon demande -- meme esprit que
    `validation/feasibility.py` (blocage dur, jamais juste un warning)."""


def _fit_cutoff_index(n: int, fit_end_idx: int | None) -> int:
    if fit_end_idx is None:
        return n
    return max(1, min(fit_end_idx, n))


def _causal_forward_filtered_probs(x: np.ndarray, n_states: int, seed: int,
                                    fit_end_idx: int | None) -> tuple[np.ndarray, GaussianHMM]:
    """Probabilites filtrees (causales) de chaque etat, par l'algorithme
    forward en log-space calcule a la main -- PAS `model.predict_proba`/
    `.decode`, qui lissent avec le futur (forward-backward/Viterbi). Meme
    principe que `vol_models.py::hmm_filtered_stress_prob`, generalise a
    toutes les probabilites d'etat (pas seulement l'etat de plus haute
    variance) et a n_states quelconque. Parametres estimes sur
    `x[:fit_end_idx]` uniquement (train du fold), geles, puis appliques en
    avant sur toute la serie -- aucune re-estimation."""
    from hmmlearn.hmm import GaussianHMM
    from scipy.special import logsumexp
    from scipy.stats import norm

    n = len(x)
    cutoff = _fit_cutoff_index(n, fit_end_idx)
    x_fit = x[:cutoff] if cutoff >= 100 else x

    model = GaussianHMM(n_components=n_states, covariance_type="diag",
                         random_state=seed, n_iter=100)
    model.fit(x_fit)

    means = model.means_.ravel()
    vars_ = np.clip(model.covars_.reshape(n_states, -1)[:, 0], 1e-12, None)
    log_start = np.log(model.startprob_ + 1e-300)
    log_trans = np.log(model.transmat_ + 1e-300)

    log_alpha = np.zeros((n, n_states))
    log_alpha[0] = log_start + norm.logpdf(x[0, 0], means, np.sqrt(vars_))
    for t in range(1, n):
        for k in range(n_states):
            log_alpha[t, k] = (logsumexp(log_alpha[t - 1] + log_trans[:, k])
                                + norm.logpdf(x[t, 0], means[k], np.sqrt(vars_[k])))
    log_norm = logsumexp(log_alpha, axis=1, keepdims=True)
    filtered = np.exp(log_alpha - log_norm)
    return filtered, model


def _hmm_free_params(n_states: int, n_features: int = 1) -> int:
    """Nombre de parametres libres d'un GaussianHMM a covariance diagonale :
    transitions (n_states-1 par ligne), etat initial (n_states-1), moyennes
    et variances (n_states x n_features chacune)."""
    k_trans = n_states * (n_states - 1)
    k_start = n_states - 1
    k_means = n_states * n_features
    k_vars = n_states * n_features
    return k_trans + k_start + k_means + k_vars


def select_n_states_bic(x: np.ndarray, candidates: tuple[int, ...] = (2, 3, 4),
                         seed: int = 42, criterion: Literal["bic", "aic"] = "bic",
                         n_init: int = 5) -> dict:
    """Ajuste un GaussianHMM pour chaque nombre d'etats candidat sur `x`
    (deja restreint au train par l'appelant) et retourne, pour chacun,
    log-vraisemblance/n_params/bic/aic. `model.score(x)` (hmmlearn) est deja
    la log-vraisemblance totale (pas moyenne) sous le modele -- utilisable
    directement dans BIC = -2*LL + k*log(n) / AIC = -2*LL + 2*k.

    `n_init` redemarrages aleatoires par candidat (on garde la
    log-vraisemblance la plus haute) : l'EM de hmmlearn est sensible a
    l'initialisation et peut ne pas converger en 100 iterations (observe
    empiriquement -- `ConvergenceMonitor` averti "Model is not converging"
    sur ce jeu de donnees) ; comparer des BIC issus d'optima locaux de
    qualite inegale entre candidats biaise la selection vers un nombre
    d'etats qui n'a fait que "mieux tomber" a l'init, pas mieux modeliser."""
    from hmmlearn.hmm import GaussianHMM

    n = len(x)
    n_features = x.shape[1] if x.ndim > 1 else 1
    out: dict[int, dict] = {}
    for k in candidates:
        best_ll = -np.inf
        for init in range(n_init):
            model = GaussianHMM(n_components=k, covariance_type="diag",
                                 random_state=seed + init, n_iter=200)
            model.fit(x)
            ll = float(model.score(x))
            best_ll = max(best_ll, ll)
        n_params = _hmm_free_params(k, n_features)
        bic = -2 * best_ll + n_params * np.log(n)
        aic = -2 * best_ll + 2 * n_params
        out[k] = {
            "log_likelihood": best_ll,
            "n_params": n_params,
            "bic": bic,
            "aic": aic,
        }
    return out


def _threshold_cutoffs(stress_prob: pd.Series, mode: ThresholdMode,
                        threshold_values: tuple[float, float],
                        fit_end_idx: int | None) -> tuple[float, float]:
    lo, hi = threshold_values
    if not (0.0 <= lo < hi <= 1.0):
        raise ValueError(f"threshold_values doit verifier 0 <= lo < hi <= 1, recu {threshold_values}")

    if mode == "fixed":
        return lo, hi
    if mode == "quantile":
        cutoff = _fit_cutoff_index(len(stress_prob), fit_end_idx)
        train_slice = stress_prob.iloc[:cutoff] if cutoff >= 20 else stress_prob
        return float(train_slice.quantile(lo)), float(train_slice.quantile(hi))
    raise ValueError(f"threshold_mode inconnu : {mode!r} (attendu 'quantile' ou 'fixed')")


def _label_from_cutoffs(stress_prob: pd.Series, cutoffs: tuple[float, float]) -> pd.Series:
    lo, hi = cutoffs
    labels = np.full(len(stress_prob), "normal", dtype=object)
    labels[stress_prob.values <= lo] = "calme"
    labels[stress_prob.values > hi] = "stress"
    return pd.Series(labels, index=stress_prob.index, name="regime")


@dataclass(frozen=True)
class RegimeDetectionResult:
    regime: pd.Series            # labels calme/normal/stress, index = series causal (returns)
    stress_prob: pd.Series       # P(etat de plus haute variance), filtree, causale
    n_states_selected: int
    selection_scores: dict | None  # None si n_states passe explicitement (pas de selection)
    threshold_mode: ThresholdMode
    threshold_cutoffs: tuple[float, float]


def detect_regime(series: pd.Series, n_states: int | Literal["auto"] = "auto",
                   state_candidates: tuple[int, ...] = (2, 3, 4),
                   criterion: Literal["bic", "aic"] = "bic",
                   threshold_mode: ThresholdMode = "quantile",
                   threshold_values: tuple[float, float] = (1 / 3, 2 / 3),
                   seed: int = 42,
                   fit_end_idx: int | None = None) -> RegimeDetectionResult:
    """Detecte le regime de volatilite courant, causalement, sur toute la
    serie `series` (prix ou niveau ; les rendements sont derives en
    interne). `n_states="auto"` selectionne le nombre d'etats HMM par
    `criterion` (BIC par defaut) parmi `state_candidates`, sur le train
    (`x[:fit_end_idx]`) uniquement. `threshold_mode`/`threshold_values`
    controlent independamment comment la probabilite filtree de l'etat de
    plus haute variance est reduite a 3 labels (voir docstring module)."""
    if threshold_mode not in ("quantile", "fixed"):
        raise ValueError(f"threshold_mode inconnu : {threshold_mode!r} (attendu 'quantile' ou 'fixed')")

    ret = safe_pct_change(series).dropna()
    x = ret.values.reshape(-1, 1)
    n = len(x)
    if n < 100:
        empty = pd.Series(pd.NA, index=ret.index, dtype="object", name="regime")
        empty_prob = pd.Series(np.nan, index=ret.index, name="stress_prob")
        return RegimeDetectionResult(
            regime=empty, stress_prob=empty_prob, n_states_selected=0,
            selection_scores=None, threshold_mode=threshold_mode,
            threshold_cutoffs=(np.nan, np.nan),
        )

    selection_scores = None
    if n_states == "auto":
        cutoff = _fit_cutoff_index(n, fit_end_idx)
        x_fit = x[:cutoff] if cutoff >= 100 else x
        selection_scores = select_n_states_bic(x_fit, candidates=state_candidates, seed=seed)
        n_states_selected = min(selection_scores, key=lambda k: selection_scores[k][criterion])
    else:
        n_states_selected = int(n_states)

    filtered, model = _causal_forward_filtered_probs(x, n_states_selected, seed, fit_end_idx)
    vars_ = np.clip(model.covars_.reshape(n_states_selected, -1)[:, 0], 1e-12, None)
    stress_state = int(np.argmax(vars_))
    stress_prob = pd.Series(filtered[:, stress_state], index=ret.index, name="stress_prob")

    cutoffs = _threshold_cutoffs(stress_prob, threshold_mode, threshold_values, fit_end_idx)
    regime = _label_from_cutoffs(stress_prob, cutoffs)

    return RegimeDetectionResult(
        regime=regime, stress_prob=stress_prob, n_states_selected=n_states_selected,
        selection_scores=selection_scores, threshold_mode=threshold_mode,
        threshold_cutoffs=cutoffs,
    )


def check_regime_fragmentation(regime: pd.Series, horizon: int,
                                n_wf_folds: int = DEFAULT_N_WF_FOLDS,
                                min_train_frac: float = DEFAULT_MIN_TRAIN_FRAC,
                                ) -> dict[str, FeasibilityResult]:
    """Garde-fou de fragmentation (CHANTIER A) : pour CHAQUE label de regime
    present, traite son nombre d'observations comme un `n_obs` a part
    entiere et reutilise directement `validation/feasibility.is_feasible`
    (meme formule ~8.33x horizon, deja auditee) -- pas un nouveau seuil
    invente pour l'occasion. Leve `RegimeFragmentationError` (blocage dur)
    si au moins un regime present est infaisable a cet horizon ; ne
    retourne jamais silencieusement un warning."""
    results: dict[str, FeasibilityResult] = {}
    infeasible: list[str] = []
    for label, n_obs in regime.value_counts().items():
        required = min_obs_required(horizon, n_wf_folds, min_train_frac)
        feasible = is_feasible(int(n_obs), horizon, n_wf_folds, min_train_frac)
        results[label] = FeasibilityResult(
            symbol=str(label), horizon=horizon, feasible=feasible, n_obs=int(n_obs),
            n_obs_required=required, source="regime",
            reason=(f"Regime '{label}' : {n_obs}j, {required}j requis pour horizon {horizon}j."),
        )
        if not feasible:
            infeasible.append(str(label))

    if infeasible:
        details = ", ".join(f"{lbl} ({results[lbl].n_obs}j < {results[lbl].n_obs_required}j requis)"
                             for lbl in infeasible)
        raise RegimeFragmentationError(
            f"Regime(s) trop fragmente(s) pour un walk-forward valide a horizon={horizon}j : {details}"
        )
    return results
