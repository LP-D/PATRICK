"""Réseaux de neurones (deep learning) comme algorithmes du pipeline : MLP, GRU, LSTM, CNN1D, Transformer.

Un réseau est un ALGO DE PLUS (`models/registry.py::get_classifier`) : même interface scikit-learn (`fit`, `predict`, `predict_proba`,
`classes_`, `sample_weight`), donc mêmes folds walk-forward, purge, embargo, sélection de variables, tuning Optuna, calibration, duel de
champions et classement que le ML. Rien d'autre à brancher.

Points qui diffèrent d'un arbre de décision, et choix faits :

- **Dépendance optionnelle** : PyTorch n'est importé qu'à l'usage (`pip install -e .[deep]`). Sans lui, la page DL s'affiche et le lancement
  est refusé avec un message clair ; aucun autre module n'est touché.
- **Entrées** : les variables arrivent déjà mises à l'échelle (RobustScaler par fold) ; le réseau les standardise encore sur ses lignes
  d'entraînement et les borne à ±8 écarts-types (une valeur extrême ne fait pas exploser les gradients).
- **Fenêtres** (GRU, LSTM, CNN1D, Transformer) : le modèle lit `lookback` lignes consécutives. Les lignes sont supposées triées par date
  (vrai pour le walk-forward et le tuning à découpe temporelle ; `config/schema.py` refuse SMOTE et CPCV avec ces modèles). Les premières
  lignes d'entraînement répètent la première ligne ; à la prédiction, les `lookback − 1` dernières lignes d'entraînement servent de
  contexte (`context="train"`), ou la fenêtre est fournie en entier (`context="none"`, prédiction du jour).
- **Validation interne** : la fin TEMPORELLE de l'entraînement (jamais un tirage aléatoire) sert à l'arrêt anticipé ; les meilleurs poids sont restaurés.
- **Déterminisme** : graine `seed + i` par réseau, moyenne des probabilités sur `n_seeds` réseaux.
- **Sérialisation** : les poids sont gardés en tableaux NumPy et le réseau est reconstruit à la demande (un modèle exporté se relit sans GPU).
"""
from __future__ import annotations

import importlib.util
import math

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin

from patrick.config import defaults as D

DL_ALGOS = tuple(D.ALL_DL_ALGOS)
SEQUENCE_ALGOS = tuple(D.SEQUENCE_DL_ALGOS)
CLIP = 8.0
MIN_VAL_ROWS = 20
MIN_FIT_ROWS = 50


class DeepUnavailableError(RuntimeError):
    """PyTorch n'est pas installé : message affichable tel quel."""


def torch_available() -> bool:
    """Vrai si PyTorch est installable-importable, sans l'importer (la détection reste instantanée)."""
    return importlib.util.find_spec("torch") is not None


def require_torch():
    if not torch_available():
        raise DeepUnavailableError(
            "PyTorch n'est pas installé : les réseaux de neurones sont indisponibles. "
            "Installe-le avec : pip install -e \".[deep]\" (ou pip install torch).")
    import torch
    return torch


_NETS: dict = {}


def _net_classes(torch):
    """Les classes de réseaux, créées une fois PyTorch importé."""
    if _NETS:
        return _NETS
    nn = torch.nn

    class MLPNet(nn.Module):
        def __init__(self, d, k, hidden, layers, dropout, **_):
            super().__init__()
            blocks, width = [], d
            for _i in range(layers):
                blocks += [nn.Linear(width, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(dropout)]
                width = hidden
            blocks.append(nn.Linear(width, k))
            self.net = nn.Sequential(*blocks)

        def forward(self, x):
            return self.net(x)

    class RNNNet(nn.Module):
        def __init__(self, d, k, hidden, layers, dropout, kind="GRU", **_):
            super().__init__()
            cell = nn.GRU if kind == "GRU" else nn.LSTM
            self.rnn = cell(d, hidden, num_layers=layers, batch_first=True, dropout=dropout if layers > 1 else 0.0)
            self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Dropout(dropout), nn.Linear(hidden, k))

        def forward(self, x):
            out, _state = self.rnn(x)
            return self.head(out[:, -1])

    class CausalBlock(nn.Module):
        def __init__(self, c_in, c_out, kernel, dilation, dropout):
            super().__init__()
            self.pad = (kernel - 1) * dilation
            self.conv = nn.Conv1d(c_in, c_out, kernel, dilation=dilation, padding=self.pad)
            self.act, self.drop = nn.GELU(), nn.Dropout(dropout)
            self.skip = nn.Conv1d(c_in, c_out, 1) if c_in != c_out else nn.Identity()

        def forward(self, x):
            y = self.conv(x)
            if self.pad:
                y = y[:, :, :-self.pad]                    # convolution causale : jamais de regard vers la droite (l'avenir)
            return self.drop(self.act(y)) + self.skip(x)

    class CNNNet(nn.Module):
        def __init__(self, d, k, hidden, layers, dropout, kernel_size=3, **_):
            super().__init__()
            blocks, width = [], d
            for i in range(layers):
                blocks.append(CausalBlock(width, hidden, kernel_size, 2 ** i, dropout))
                width = hidden
            self.blocks = nn.Sequential(*blocks)
            self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, k))

        def forward(self, x):                              # x : (lot, fenêtre, variables)
            y = self.blocks(x.transpose(1, 2))             # -> (lot, canaux, fenêtre)
            return self.head(y[:, :, -1])

    class TransformerNet(nn.Module):
        def __init__(self, d, k, hidden, layers, dropout, lookback=20, n_heads=4, **_):
            super().__init__()
            heads = max(1, min(n_heads, hidden))
            width = max(heads, (hidden // heads) * heads)   # la largeur doit être un multiple du nombre de têtes
            self.proj = nn.Linear(d, width)
            self.pos = nn.Parameter(torch.zeros(1, lookback, width))
            layer = nn.TransformerEncoderLayer(width, heads, dim_feedforward=2 * width, dropout=dropout, batch_first=True,
                                               norm_first=True, activation="gelu")
            self.enc = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
            self.head = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, k))

        def forward(self, x):
            y = self.enc(self.proj(x) + self.pos[:, :x.shape[1]])
            return self.head(y[:, -1])

    _NETS.update(MLP=MLPNet, GRU=RNNNet, LSTM=RNNNet, CNN1D=CNNNet, Transformer=TransformerNet)
    return _NETS


class DeepClassifier(BaseEstimator, ClassifierMixin):
    """Classifieur neuronal multiclasse compatible scikit-learn (voir le module). `arch` ∈ `DL_ALGOS`."""

    is_deep = True

    def __init__(self, arch="MLP", seed=42, hidden_size=64, n_layers=2, dropout=0.2, lookback=20, epochs=30, batch_size=128,
                 learning_rate=1e-3, weight_decay=1e-4, patience=5, val_fraction=0.15, grad_clip=1.0, class_weight="balanced",
                 n_seeds=1, device="auto", n_heads=4, kernel_size=3, threads=1):
        self.arch = arch
        self.seed = seed
        self.hidden_size = hidden_size
        self.n_layers = n_layers
        self.dropout = dropout
        self.lookback = lookback
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.patience = patience
        self.val_fraction = val_fraction
        self.grad_clip = grad_clip
        self.class_weight = class_weight
        self.n_seeds = n_seeds
        self.device = device
        self.n_heads = n_heads
        self.kernel_size = kernel_size
        self.threads = threads

    # ------------------------------------------------------------------ propriétés
    @property
    def needs_history(self) -> bool:
        """Vrai pour un modèle à fenêtre : la prédiction d'une ligne isolée exige les lignes qui la précèdent."""
        return self.arch in SEQUENCE_ALGOS

    @property
    def window(self) -> int:
        return max(2, int(self.lookback)) if self.needs_history else 1

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_nets", None)                      # reconstruits à la demande à partir de `state_`
        return state

    # ------------------------------------------------------------------ utilitaires
    def _device(self, torch):
        if self.device == "cuda" and torch.cuda.is_available():
            return torch.device("cuda")
        if self.device == "auto" and torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    def _standardize(self, X):
        X = np.asarray(X, dtype=np.float64)
        X = np.nan_to_num(X, nan=0.0, posinf=CLIP, neginf=-CLIP)
        return np.clip((X - self.mu_) / self.sd_, -CLIP, CLIP).astype(np.float32)

    def _make_net(self, torch, d, k):
        cls = _net_classes(torch)[self.arch]
        return cls(d, k, hidden=int(self.hidden_size), layers=int(self.n_layers), dropout=float(self.dropout),
                   kind=self.arch, kernel_size=int(self.kernel_size), lookback=self.window, n_heads=int(self.n_heads))

    @staticmethod
    def _windows(padded: np.ndarray, length: int) -> np.ndarray:
        """(n + length − 1, d) -> (n, length, d), sans copie."""
        return np.lib.stride_tricks.sliding_window_view(padded, (length, padded.shape[1]))[:, 0]

    def _input(self, Xs: np.ndarray, context: str) -> np.ndarray:
        """Entrée du réseau pour des lignes standardisées : lignes seules (MLP) ou fenêtres (n, lookback, d)."""
        if not self.needs_history:
            return Xs
        length = self.window
        if context == "train" and len(self.context_):
            head = self.context_[-(length - 1):]
            if len(head) < length - 1:
                head = np.vstack([np.repeat(head[:1], length - 1 - len(head), axis=0), head])
        else:
            head = np.repeat(Xs[:1], length - 1, axis=0)
        return self._windows(np.vstack([head, Xs]), length)

    # ------------------------------------------------------------------ apprentissage
    def fit(self, X, y, sample_weight=None):
        torch = require_torch()
        nn = torch.nn
        if int(self.threads) != torch.get_num_threads():
            torch.set_num_threads(int(self.threads))
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y).astype(int).ravel()
        if len(X) != len(y):
            raise ValueError("X et y n'ont pas le même nombre de lignes")
        n, d = X.shape
        self.classes_ = np.unique(y)
        k = len(self.classes_)
        yi = np.searchsorted(self.classes_, y)
        X = np.nan_to_num(X, nan=0.0, posinf=CLIP, neginf=-CLIP)
        self.mu_ = X.mean(axis=0)
        sd = X.std(axis=0)
        self.sd_ = np.where(sd < 1e-8, 1.0, sd)
        self.n_features_in_ = d
        Xs = self._standardize(X)
        length = self.window
        self.context_ = Xs[-(length - 1):].copy() if length > 1 else np.empty((0, d), dtype=np.float32)
        if self.needs_history:
            padded = np.vstack([np.repeat(Xs[:1], length - 1, axis=0), Xs])
            inputs = self._windows(padded, length)
        else:
            inputs = Xs

        n_val = int(round(n * float(self.val_fraction))) if int(self.patience) > 0 else 0
        if n_val < MIN_VAL_ROWS or n - n_val < MIN_FIT_ROWS:
            n_val = 0
        n_tr = n - n_val
        counts = np.bincount(yi[:n_tr], minlength=k).astype(float)
        if self.class_weight == "balanced":
            cw = np.where(counts > 0, n_tr / (k * np.maximum(counts, 1.0)), 0.0)
        else:
            cw = np.ones(k)
        sw = np.ones(n) if sample_weight is None else np.asarray(sample_weight, dtype=float).ravel()
        sw = np.where(np.isfinite(sw) & (sw > 0), sw, 0.0)
        sw = sw / max(float(sw[:n_tr].mean()), 1e-12)
        device = self._device(torch)

        self.state_, self.epochs_run_ = [], []
        for s in range(int(self.n_seeds)):
            torch.manual_seed(int(self.seed) + s)
            rng = np.random.default_rng(int(self.seed) + s)
            net = self._make_net(torch, d, k).to(device)
            opt = torch.optim.AdamW(net.parameters(), lr=float(self.learning_rate), weight_decay=float(self.weight_decay))
            loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(cw, dtype=torch.float32, device=device), reduction="none")
            tr_idx = np.arange(n_tr)
            best, best_state, bad, ran = math.inf, None, 0, 0
            for _epoch in range(int(self.epochs)):
                net.train()
                order = rng.permutation(tr_idx)
                for start in range(0, n_tr, int(self.batch_size)):
                    b = order[start:start + int(self.batch_size)]
                    if len(b) < 2:
                        continue
                    xb = torch.from_numpy(np.ascontiguousarray(inputs[b])).to(device)
                    yb = torch.from_numpy(yi[b]).to(device)
                    wb = torch.from_numpy(sw[b].astype(np.float32)).to(device)
                    opt.zero_grad(set_to_none=True)
                    loss = (loss_fn(net(xb), yb) * wb).mean()
                    loss.backward()
                    if float(self.grad_clip) > 0:
                        nn.utils.clip_grad_norm_(net.parameters(), float(self.grad_clip))
                    opt.step()
                ran += 1
                if n_val:
                    net.eval()
                    with torch.no_grad():
                        xv = torch.from_numpy(np.ascontiguousarray(inputs[n_tr:])).to(device)
                        yv = torch.from_numpy(yi[n_tr:]).to(device)
                        wv = torch.from_numpy(sw[n_tr:].astype(np.float32)).to(device)
                        val = float((loss_fn(net(xv), yv) * wv).mean())
                    if val < best - 1e-5:
                        best, bad = val, 0
                        best_state = {kk: v.detach().cpu().clone() for kk, v in net.state_dict().items()}
                    else:
                        bad += 1
                        if bad >= int(self.patience):
                            break
            if best_state is not None:
                net.load_state_dict(best_state)
            self.state_.append({kk: v.detach().cpu().numpy().copy() for kk, v in net.state_dict().items()})
            self.epochs_run_.append(ran)
        self._nets = None
        return self

    # ------------------------------------------------------------------ prédiction
    def _networks(self, torch, device):
        nets = getattr(self, "_nets", None)
        if nets is None or getattr(self, "_nets_device", None) != str(device):
            nets = []
            for state in self.state_:
                net = self._make_net(torch, self.n_features_in_, len(self.classes_)).to(device)
                net.load_state_dict({kk: torch.from_numpy(v) for kk, v in state.items()})
                net.eval()
                nets.append(net)
            self._nets, self._nets_device = nets, str(device)
        return nets

    def predict_proba(self, X, context: str = "train"):
        """Probabilités (n, len(classes_)). `context="train"` : les `lookback − 1` dernières lignes d'entraînement précèdent `X`
        (walk-forward). `context="none"` : `X` porte sa propre fenêtre (prédiction du jour : passer les `lookback` dernières lignes
        et lire la dernière ligne du résultat)."""
        torch = require_torch()
        if int(self.threads) != torch.get_num_threads():
            torch.set_num_threads(int(self.threads))
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or X.shape[1] != self.n_features_in_:
            raise ValueError(f"X doit avoir {self.n_features_in_} colonnes")
        inputs = self._input(self._standardize(X), context)
        device = self._device(torch)
        nets = self._networks(torch, device)
        out = np.zeros((len(X), len(self.classes_)), dtype=np.float64)
        with torch.no_grad():
            for start in range(0, len(X), 2048):
                xb = torch.from_numpy(np.ascontiguousarray(inputs[start:start + 2048])).to(device)
                p = sum(torch.softmax(net(xb), dim=1) for net in nets) / len(nets)
                out[start:start + 2048] = p.cpu().numpy()
        return out

    def predict(self, X, context: str = "train"):
        return self.classes_[np.argmax(self.predict_proba(X, context=context), axis=1)]

    # ------------------------------------------------------------------ explication
    def proba_function(self, history: np.ndarray, class_index: int):
        """Fonction `f(X_dernière_ligne) -> P(classe)` pour l'explication : `history` (≤ lookback lignes, la dernière est celle
        à expliquer) fournit les lignes précédentes ; seules les valeurs de la dernière ligne varient (`shap.PermutationExplainer`)."""
        prior = np.asarray(history, dtype=np.float64)[:-1]

        def fn(rows: np.ndarray) -> np.ndarray:
            rows = np.atleast_2d(rows)
            if not self.needs_history:
                return self.predict_proba(rows)[:, class_index]
            window = np.vstack([prior, rows[:1]])
            out = []
            for r in rows:
                window[-1] = r
                out.append(self.predict_proba(window, context="none")[-1, class_index])
            return np.asarray(out)

        return fn


def build_deep_classifier(arch: str, seed: int = 42, **params) -> DeepClassifier:
    """Construit le classifieur ; `params` (clés de `config.defaults.DEFAULT_DEEP` + `seed`) inconnus -> `ValueError`."""
    if arch not in DL_ALGOS:
        raise ValueError(f"Algorithme neuronal inconnu : '{arch}' (attendu : {DL_ALGOS})")
    unknown = set(params) - set(D.DEFAULT_DEEP)
    if unknown:
        raise ValueError(f"Réglage(s) neuronal(aux) inconnu(s) : {sorted(unknown)}")
    merged = {**D.DEFAULT_DEEP, **params}
    for key in ("hidden_size", "n_layers", "lookback", "epochs", "batch_size", "patience", "n_seeds", "n_heads", "kernel_size", "threads"):
        merged[key] = int(merged[key])
    return DeepClassifier(arch=arch, seed=seed, **merged)
