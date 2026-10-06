"""Profileur passif : temps mural/CPU par phase, temps exclusif par composant,
compteurs, pic mémoire (échantillonnage RSS, aucun `tracemalloc`).

Il n'altère aucun calcul : chaque wrapper appelle la fonction d'origine avec
les mêmes arguments et renvoie exactement son résultat. Les patchs sont
posés/retirés par `install()` (gestionnaire de contexte).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass

import psutil

OUTSIDE = "(hors phase)"


@dataclass
class _Frame:
    name: str
    kind: str
    phase: str
    t0: float
    cpu0: float
    child: float = 0.0


@dataclass
class Agg:
    count: int = 0
    inclusive_s: float = 0.0
    self_s: float = 0.0

    def as_dict(self) -> dict:
        return {"count": self.count, "inclusive_s": round(self.inclusive_s, 4), "self_s": round(self.self_s, 4)}


class _RssSampler(threading.Thread):
    """Échantillonne le RSS du processus (+ enfants) ; `reset()` au début de
    chaque phase, `peak` = max observé depuis. 20 Hz : coût négligeable."""

    def __init__(self, interval: float = 0.05):
        super().__init__(daemon=True)
        self._proc = psutil.Process()
        self._interval = interval
        self._halt = threading.Event()
        self.peak = 0
        self.global_peak = 0

    def _rss(self) -> int:
        total = 0
        try:
            total = self._proc.memory_info().rss
            for child in self._proc.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
        return total

    def reset(self) -> int:
        now = self._rss()
        self.peak = now
        self.global_peak = max(self.global_peak, now)
        return now

    def sample_now(self) -> int:
        now = self._rss()
        self.peak = max(self.peak, now)
        self.global_peak = max(self.global_peak, now)
        return now

    def run(self) -> None:
        while not self._halt.wait(self._interval):
            self.sample_now()

    def stop(self) -> None:
        self._halt.set()


class Profiler:
    def __init__(self, clock=time.perf_counter, cpu_clock=time.process_time, sample_memory: bool = True):
        self._clock = clock
        self._cpu = cpu_clock
        self._stack: list[_Frame] = []
        self.phases: dict[str, dict] = {}
        self.phase_order: list[str] = []
        self.components: dict[tuple[str, str], Agg] = defaultdict(Agg)
        self.counters: Counter = Counter()                      # (phase, name) -> n
        self.keys: dict[str, Counter] = defaultdict(Counter)    # name -> Counter of hashable keys
        self.values: dict[str, float] = defaultdict(float)      # sommes libres (ex. nb de colonnes)
        self._sampler = _RssSampler() if sample_memory else None
        self._t_start = self._t_end = self._cpu_start = self._cpu_end = None

    # -- cycle de vie ---------------------------------------------------
    def start(self) -> None:
        self._t_start, self._cpu_start = self._clock(), self._cpu()
        if self._sampler is not None:
            self._sampler.sample_now()
            self._sampler.start()

    def stop(self) -> None:
        self._t_end, self._cpu_end = self._clock(), self._cpu()
        if self._sampler is not None:
            self._sampler.sample_now()
            self._sampler.stop()

    @property
    def total_wall_s(self) -> float:
        return (self._t_end if self._t_end is not None else self._clock()) - self._t_start

    @property
    def total_cpu_s(self) -> float:
        return (self._cpu_end if self._cpu_end is not None else self._cpu()) - self._cpu_start

    # -- comptage --------------------------------------------------------
    @property
    def current_phase(self) -> str:
        for f in reversed(self._stack):
            if f.kind == "phase":
                return f.name
        return OUTSIDE

    def count(self, name: str, n: int = 1) -> None:
        self.counters[(self.current_phase, name)] += n

    def add_value(self, name: str, v: float) -> None:
        self.values[name] += v

    def set_value(self, name: str, v: float) -> None:
        self.values[name] = v

    def note_key(self, name: str, key) -> None:
        self.keys[name][key] += 1

    # -- spans -------------------------------------------------------------
    @contextmanager
    def span(self, name: str, kind: str = "comp"):
        phase = name if kind == "phase" else self.current_phase
        frame = _Frame(name, kind, phase, self._clock(), self._cpu())
        rss0 = 0
        if kind == "phase" and self._sampler is not None:
            rss0 = self._sampler.reset()
        self._stack.append(frame)
        try:
            yield
        finally:
            self._stack.pop()
            wall = self._clock() - frame.t0
            cpu = self._cpu() - frame.cpu0
            if self._stack:
                self._stack[-1].child += wall
            if kind == "phase":
                rec = self.phases.get(name)
                if rec is None:
                    rec = self.phases[name] = {"count": 0, "wall_s": 0.0, "cpu_s": 0.0,
                                               "peak_rss_bytes": 0, "rss_start_bytes": rss0}
                    self.phase_order.append(name)
                rec["count"] += 1
                rec["wall_s"] += wall
                rec["cpu_s"] += cpu
                if self._sampler is not None:
                    self._sampler.sample_now()
                    rec["peak_rss_bytes"] = max(rec["peak_rss_bytes"], self._sampler.peak)
            agg = self.components[(frame.phase, name)]
            agg.count += 1
            agg.inclusive_s += wall
            agg.self_s += wall - frame.child

    def wrap(self, fn, name: str, kind: str = "comp", on_call=None, on_return=None):
        prof = self

        def wrapper(*args, **kwargs):
            if on_call is not None:
                on_call(prof, args, kwargs)
            with prof.span(name, kind):
                out = fn(*args, **kwargs)
            if on_return is not None:
                on_return(prof, out, args, kwargs)
            return out

        wrapper.__wrapped__ = fn
        wrapper.__name__ = getattr(fn, "__name__", name)
        return wrapper

    # -- export ------------------------------------------------------------
    def summary(self) -> dict:
        phases = {}
        for name in self.phase_order:
            p = self.phases[name]
            comps = {c: a.as_dict() for (ph, c), a in sorted(self.components.items()) if ph == name and c != name}
            counters = {c: n for (ph, c), n in sorted(self.counters.items()) if ph == name}
            phases[name] = {"count": p["count"], "wall_s": round(p["wall_s"], 4), "cpu_s": round(p["cpu_s"], 4),
                            "peak_rss_mb": round(p["peak_rss_bytes"] / 2**20, 1),
                            "rss_start_mb": round(p["rss_start_bytes"] / 2**20, 1),
                            "components": comps, "counters": counters}
        comp_totals: dict[str, Agg] = defaultdict(Agg)
        for (_ph, c), a in self.components.items():
            if c in self.phases:
                continue
            t = comp_totals[c]
            t.count += a.count
            t.inclusive_s += a.inclusive_s
            t.self_s += a.self_s
        counter_totals: Counter = Counter()
        for (_ph, c), n in self.counters.items():
            counter_totals[c] += n
        phase_sum = sum(p["wall_s"] for p in self.phases.values())
        return {
            "total_wall_s": round(self.total_wall_s, 4),
            "total_cpu_s": round(self.total_cpu_s, 4),
            "sum_of_phases_wall_s": round(phase_sum, 4),
            "unaccounted_wall_s": round(self.total_wall_s - phase_sum, 4),
            "peak_rss_mb": round((self._sampler.global_peak if self._sampler else 0) / 2**20, 1),
            "phases": phases,
            "component_totals": {c: a.as_dict() for c, a in sorted(comp_totals.items())},
            "counter_totals": dict(sorted(counter_totals.items())),
            "distinct_keys": {n: {"calls": sum(c.values()), "distinct": len(c)}
                              for n, c in sorted(self.keys.items())},
            "values": {k: round(v, 4) for k, v in sorted(self.values.items())},
        }

    def deterministic_view(self) -> dict:
        """Ce qui doit être IDENTIQUE d'un run à l'autre (compteurs, pas de temps)."""
        s = self.summary()
        return {"counter_totals": s["counter_totals"], "distinct_keys": s["distinct_keys"], "values": s["values"],
                "phase_order": list(self.phase_order),
                "phase_counters": {n: p["counters"] for n, p in s["phases"].items()}}


# ---------------------------------------------------------------------------
# Compteurs SQLite : sous-classe de Connection, délégation stricte à `super()`.
# ---------------------------------------------------------------------------

class _CountingConnection(sqlite3.Connection):
    _profiler: Profiler | None = None

    def execute(self, *a, **k):
        p = type(self)._profiler
        p.count("sqlite.execute")
        with p.span("sqlite.execute"):
            return super().execute(*a, **k)

    def executemany(self, *a, **k):
        p = type(self)._profiler
        p.count("sqlite.executemany")
        with p.span("sqlite.executemany"):
            return super().executemany(*a, **k)

    def commit(self):
        p = type(self)._profiler
        p.count("sqlite.commit")
        with p.span("sqlite.commit"):
            return super().commit()

    def __exit__(self, exc_type, exc, tb):
        p = type(self)._profiler
        if exc_type is None:       # `with conn:` -> commit
            p.count("sqlite.commit")
            with p.span("sqlite.commit"):
                return super().__exit__(exc_type, exc, tb)
        return super().__exit__(exc_type, exc, tb)


class _SqliteShim:
    """Remplace le module `sqlite3` DANS `patrick.tracking.db` uniquement."""

    def __init__(self, profiler: Profiler):
        class Conn(_CountingConnection):
            pass

        Conn._profiler = profiler
        self._conn_cls = Conn

    def connect(self, *a, **k):
        k.setdefault("factory", self._conn_cls)
        return sqlite3.connect(*a, **k)

    def __getattr__(self, name):
        return getattr(sqlite3, name)


@contextmanager
def install(profiler: Profiler):
    """Pose les wrappers, `yield`, puis restaure CHAQUE attribut d'origine
    (même en cas d'exception)."""
    import optuna
    import sklearn.preprocessing as skpre

    from patrick.features import pool_cache
    from patrick.pipeline import champion_duel, parallel
    from patrick.pipeline import engine as E
    from patrick.tracking import db as trackdb
    from patrick.tracking import holdout_diagnostic as trackholdout
    from patrick.tracking import stats as trackstats
    from patrick.tuning import optuna_runner as OR

    P = profiler
    patches: list[tuple[object, str, object]] = []

    def patch(obj, attr, new):
        patches.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, new)

    def phase(obj, attr, name, **kw):
        patch(obj, attr, P.wrap(getattr(obj, attr), name, "phase", **kw))

    def comp(obj, attr, name, **kw):
        patch(obj, attr, P.wrap(getattr(obj, attr), name, "comp", **kw))

    try:
        # -- phases (fonctions module-level appelées par nom global) ------
        phase(E, "ingest", "ingestion")
        phase(E, "load_snapshot", "ingestion")
        phase(E, "_register_runs", "register_runs")
        phase(E, "build_base_feature_pool", "base_feature_pool",
              on_return=lambda p, out, a, k: p.set_value("base_pool.columns", out.shape[1]))
        phase(E, "_prepare_walkforward", "walkforward_prepare")
        phase(E, "_scan_walkforward", "scan_walkforward")
        phase(E, "_scan_cpcv", "scan_cpcv")
        phase(E, "_track_stability", "stability")
        phase(E, "_holdout_diagnostic", "holdout_diagnostic")
        phase(E, "_tune", "tuning")
        phase(E, "_export_tables", "export_tables")
        phase(E, "_select_finals", "select_finals")
        phase(E, "_export_models", "export_models")
        phase(E, "_final_holdout", "final_holdout")
        phase(E, "_final_diebold_mariano", "final_diebold_mariano")
        phase(E, "_finish_runs", "finish_runs")
        phase(champion_duel, "duel_and_promote", "champion_duel")
        # PBO / essais cumulés : code inline de run_pipeline, appelé via `trackstats.*`
        phase(trackstats, "count_cumulative_trials", "final_stats")
        phase(trackstats, "pbo_for_target", "final_stats")
        phase(trackstats, "pbo_for_target_cpcv", "final_stats")
        phase(trackholdout, "spearman_test_vs_holdout", "final_stats")

        # -- composants (temps exclusif / inclusif + compteurs) ---------------
        comp(E._FoldContext, "prepare", "fold_context.prepare",
             on_call=lambda p, a, k: (p.count("fold_context.prepare"),
                                      p.note_key("fold_context.prepare", (a[1], a[2], a[3]))))
        comp(E, "_select", "select (cache lookup + compute)",
             on_call=lambda p, a, k: p.count("select.calls"))
        comp(E, "select_features", "select_features.compute",
             on_call=lambda p, a, k: p.count("select_features.computed"))
        comp(E, "_fit_eval_full", "fit_eval_full",
             on_call=lambda p, a, k: p.count("fit_eval_full.calls"))
        comp(E, "get_classifier", "get_classifier.engine",
             on_call=lambda p, a, k: p.count("models.constructed"))
        comp(OR, "get_classifier", "get_classifier.optuna",
             on_call=lambda p, a, k: p.count("optuna.cv_fits"))
        comp(parallel, "run_ordered", "parallel.run_ordered",
             on_call=lambda p, a, k: (p.count("parallel.batches"), p.count("parallel.tasks", len(a[0]))))
        comp(E, "tune_config", "optuna.tune_config", on_call=lambda p, a, k: p.count("optuna.studies"))
        comp(E, "run_target", "build_target")   # le moteur appelle run_target (cible brute = build_target) ; nom de mesure inchangé
        comp(E, "compute_baselines", "compute_baselines")
        comp(E, "build_indicator_matrix", "uniqueness.indicator_matrix")
        comp(E, "average_uniqueness", "uniqueness.average")
        comp(E, "_xy_data_hash", "select.xy_data_hash")
        comp(E, "build_parametric_pool", "parametric_pool.build",
             on_call=lambda p, a, k: p.count("parametric_pool.builds"),
             on_return=lambda p, out, a, k: p.add_value("parametric_pool.columns_built", out.shape[1]))
        comp(E, "_discover_interaction_formulas", "interactions.discover")
        comp(E, "_apply_interaction_formulas", "interactions.apply",
             on_call=lambda p, a, k: p.count("interactions.apply"))
        comp(E._FoldPoolBuilder, "get", "fold_pool_builder.get",
             on_call=lambda p, a, k: p.count("fold_pool_builder.get"),
             on_return=lambda p, out, a, k: p.set_value("fold_pool.columns_last", out.shape[1]))
        comp(E, "download_ohlc", "download_ohlc", on_call=lambda p, a, k: p.count("download_ohlc.calls"))
        comp(skpre.RobustScaler, "fit_transform", "scaler.fit_transform",
             on_call=lambda p, a, k: p.count("scaler.fit_transform"))
        comp(skpre.RobustScaler, "transform", "scaler.transform",
             on_call=lambda p, a, k: p.count("scaler.transform"))

        # -- caches EXISTANTS : hits / misses --------------------------------
        orig_sel = trackdb.get_cached_selection

        def get_cached_selection(*a, **k):
            P.note_key("selection_cache.lookup", (a[4], a[5]))     # (data_hash, selector_hash)
            with P.span("selection_cache.lookup"):
                out = orig_sel(*a, **k)
            P.count("selection_cache.hit" if out is not None else "selection_cache.miss")
            return out
        patch(trackdb, "get_cached_selection", get_cached_selection)

        orig_vol = trackdb.get_cached_vol_model

        def get_cached_vol_model(*a, **k):
            with P.span("vol_model_cache.lookup"):
                out = orig_vol(*a, **k)
            P.count("vol_model_cache.hit" if out is not None else "vol_model_cache.miss")
            return out
        patch(trackdb, "get_cached_vol_model", get_cached_vol_model)

        orig_cached = pool_cache.cached

        def cached(stage, raw, payload, compute):
            state = {"hit": True}

            def timed_compute():
                state["hit"] = False
                with P.span(f"feature_pool.compute[{stage}]"):
                    out = compute()
                P.add_value(f"feature_pool.{stage}.columns_computed", out.shape[1])
                return out
            out = orig_cached(stage, raw, payload, timed_compute)
            P.count(f"feature_pool_cache.{stage}." + ("hit" if state["hit"] else "miss"))
            return out
        patch(pool_cache, "cached", cached)

        # -- essais Optuna par état (callback passif ajouté, aucun effet sur l'étude)
        orig_optimize = optuna.study.Study.optimize

        def optimize(self, func, n_trials=None, *a, callbacks=None, **k):
            def count_trial(_study, frozen):
                P.count(f"optuna.trials.{frozen.state.name.lower()}")
            return orig_optimize(self, func, n_trials, *a, callbacks=[*(callbacks or []), count_trial], **k)
        patch(optuna.study.Study, "optimize", optimize)

        # -- SQLite ------------------------------------------------------------
        patch(trackdb, "sqlite3", _SqliteShim(P))

        P.start()
        try:
            yield P
        finally:
            P.stop()
    finally:
        for obj, attr, orig in reversed(patches):
            setattr(obj, attr, orig)
