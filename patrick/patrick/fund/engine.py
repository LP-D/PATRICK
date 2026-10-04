"""Moteur de valorisation d'une stratégie (spec §7, §9, §10).

Fonctions pures : (stratégie, ordres, données de marché) -> série quotidienne
de cash / NAV / marge + état de chaque position. Rien n'est stocké : on
rejoue les ordres jour par jour.

Séquence d'une journée de bourse :
  a. dividendes des actions/ETF détenus en début de journée ;
  b. déclenchement des stop/objectif (futures et CFD) des positions dont le
     dernier ordre est antérieur au jour ;
  c. ordres du jour (par ordre d'identifiant) ;
  d. règlement de fin de journée : variation des futures, financement des CFD,
     échéance des futures ;
  e. photographie (cash, valeur, marge, exposition).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from patrick.clock import utc_today
from patrick.fund import fees as fees_mod

EPS = 1e-9
FINANCING_SPREAD = 0.025          # marge du fournisseur sur le taux de référence (CFD)
DEFAULT_REF_RATES = {"EUR": 0.02, "USD": 0.04, "GBP": 0.04, "JPY": 0.005, "CHF": 0.005}
EQUITY_KINDS = ("equity", "etf")
DERIV_KINDS = ("future", "cfd")
DAILY_COLUMNS = ["cash", "equity_value", "cfd_unrealized", "nav", "margin_used", "buying_power",
                 "gross_exposure", "net_exposure", "fees_cum", "dividends_cum", "financing_cum"]


@dataclass
class MarketData:
    """Cotations en unités de la devise ISO (les pence sont déjà convertis)."""
    bars: dict[str, pd.DataFrame] = field(default_factory=dict)   # open high low close volume dividend
    fx: dict[str, pd.Series] = field(default_factory=dict)        # devise -> unités de base par unité de devise
    ref_rates: dict[str, float] = field(default_factory=dict)
    ref_rate_history: dict[str, pd.Series] = field(default_factory=dict)   # devise -> taux court quotidien (décimal)
    base_currency: str = "EUR"
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    def _arrays(self, kind: str, key: str, owner, extract):
        """(dates, valeurs) triées de la série, mises en cache : une recherche dichotomique par jour
        au lieu d'un filtre de tout l'historique (qui rendait le rejeu quadratique)."""
        cached = self._cache.get((kind, key))
        if cached is None or cached[0] is not owner:
            series = extract(owner).dropna() if owner is not None else None
            arrays = None
            if series is not None and len(series):
                arrays = (series.index.values.astype("datetime64[ns]"), series.to_numpy(dtype=float))
            cached = (owner, arrays)
            self._cache[(kind, key)] = cached
        return cached[1]

    @staticmethod
    def _last_at(arrays, day) -> float | None:
        if arrays is None:
            return None
        i = int(np.searchsorted(arrays[0], pd.Timestamp(day).to_datetime64(), side="right")) - 1
        return float(arrays[1][i]) if i >= 0 else None

    def close_at(self, symbol: str, day: pd.Timestamp) -> float | None:
        df = self.bars.get(symbol)
        return self._last_at(self._arrays("close", symbol, df, lambda d: d["close"]), day)

    def split_factor_after(self, symbol: str, day: pd.Timestamp) -> float:
        """Produit des ratios de fractionnement dont l'ex-date suit `day` (1.0 si aucun)."""
        df = self.bars.get(symbol)
        if df is None or "split" not in df.columns:
            return 1.0
        splits = df["split"]
        after = splits[(splits.index > pd.Timestamp(day)) & (splits > 0)]
        return float(np.prod(after.to_numpy(dtype=float))) if len(after) else 1.0

    def bar_on(self, symbol: str, day: pd.Timestamp) -> pd.Series | None:
        df = self.bars.get(symbol)
        if df is None or day not in df.index:
            return None
        return df.loc[day]

    def last_bar_day(self, symbol: str) -> pd.Timestamp | None:
        df = self.bars.get(symbol)
        return None if df is None or df.empty else df.index[-1]

    def dividend_on(self, symbol: str, day: pd.Timestamp) -> float:
        bar = self.bar_on(symbol, day)
        if bar is None or "dividend" not in bar or pd.isna(bar["dividend"]):
            return 0.0
        return float(bar["dividend"])

    def fx_at(self, currency: str, day: pd.Timestamp, default: float = 1.0) -> float:
        if currency == self.base_currency:
            return 1.0
        value = self._last_at(self._arrays("fx", currency, self.fx.get(currency), lambda s: s), day)
        return default if value is None else value

    def ref_rate(self, currency: str, day: pd.Timestamp | None = None) -> float:
        """Taux de référence de `currency` : celui en vigueur à `day` si l'historique est connu (avant sa première
        observation : la première), sinon le taux courant, sinon la constante par défaut."""
        if day is not None:
            arrays = self._arrays("rate", currency, self.ref_rate_history.get(currency), lambda s: s)
            if arrays is not None:
                value = self._last_at(arrays, day)
                return float(arrays[1][0]) if value is None else value
        return self.ref_rates.get(currency, DEFAULT_REF_RATES.get(currency, 0.03))


@dataclass
class _Pos:
    position_id: str
    symbol: str
    kind: str
    side: str
    currency: str
    spec: dict
    opened_on: str
    qty: float = 0.0
    cost_local: float = 0.0       # somme quantité x prix de la quantité ouverte (devise de l'instrument)
    cost_base: float = 0.0        # idem en devise de base, au change de chaque ordre
    fx_ref: float = 1.0           # change moyen d'entrée = cost_base / cost_local
    mark: float = 0.0             # futures : prix de règlement moyen de la quantité ouverte
    realized: float = 0.0         # action/CFD : plus-value réalisée (devise de base, hors frais)
    var_cum: float = 0.0          # futures : variation cumulée réglée en cash (devise de base)
    pnl_local_cum: float = 0.0    # futures : variation cumulée en devise du contrat
    fees: float = 0.0
    dividends: float = 0.0
    financing_cost: float = 0.0
    engaged_peak: float = 0.0     # base du %, action : coût ; future/CFD : marge maximale
    status: str = "open"          # open | closed | stop | target | expired
    closed_on: str | None = None
    last_order_day: str = ""
    last_price: float | None = None
    last_fx: float = 1.0

    @property
    def sgn(self) -> float:
        return 1.0 if self.side == "long" else -1.0

    @property
    def multiplier(self) -> float:
        return float(self.spec.get("multiplier", 1.0)) if self.kind == "future" else 1.0

    @property
    def avg_local(self) -> float:
        return self.cost_local / self.qty if self.qty > EPS else 0.0


@dataclass
class SimResult:
    daily: pd.DataFrame
    positions: list[dict]
    violations: list[dict]
    alert_days: list[str]


def simulate(strategy: dict, orders: list[dict], market: MarketData, end=None) -> SimResult:
    base = market.base_currency
    opened = pd.Timestamp(strategy["opened_on"])
    end_ts = pd.Timestamp(end if end is not None else utc_today())
    # Un ordre « du jour » est exécuté à la dernière clôture connue : un week-end ou le matin, c'est la séance
    # qui précède l'ouverture de la stratégie. Il reste valide, et la grille démarre alors à cette séance.
    early = [pd.Timestamp(o["ts"]) for o in orders if opened - pd.offsets.BDay(1) <= pd.Timestamp(o["ts"]) < opened]
    start = min(early) if early else opened
    days = _session_days(start, end_ts, market, orders)
    violations: list[dict] = []
    by_day: dict[pd.Timestamp, list[dict]] = {}

    def sort_key(o: dict):
        # un candidat (sans identifiant) se rejoue APRÈS les ordres déjà enregistrés du même jour
        return (o["ts"], o["order_id"] if o.get("order_id") is not None else float("inf"))
    for o in sorted(orders, key=sort_key):
        o = _split_adjusted(o, market)
        d = pd.Timestamp(o["ts"])
        if d < start:
            violations.append({"day": o["ts"], "message": f"ordre du {o['ts']} antérieur à l'ouverture de la stratégie"})
            continue
        i = days.searchsorted(d)
        if i >= len(days):
            violations.append({"day": o["ts"], "message": f"ordre du {o['ts']} postérieur à la fin de la période"})
            continue
        by_day.setdefault(days[i], []).append(o)

    cash = float(strategy["initial_capital"])
    positions: dict[str, _Pos] = {}
    totals = {"fees": 0.0, "dividends": 0.0, "financing": 0.0}
    rows: list[dict] = []
    alert_days: list[str] = []

    def violate(day: str, message: str) -> None:
        violations.append({"day": day, "message": message})

    def apply_open_or_increase(pos: _Pos, o: dict, fx: float) -> None:
        nonlocal cash
        q, p = float(o["quantity"]), float(o["price"])
        if pos.kind == "future":
            pos.mark = (pos.qty * pos.mark + q * p) / (pos.qty + q)
        if pos.kind in EQUITY_KINDS:
            cash -= q * p * fx
        pos.cost_local += q * p
        pos.cost_base += q * p * fx
        pos.fx_ref = pos.cost_base / pos.cost_local if pos.cost_local > EPS else fx
        pos.qty += q
        if pos.kind in EQUITY_KINDS:
            pos.engaged_peak = max(pos.engaged_peak, pos.cost_base)

    def apply_reduce(pos: _Pos, o: dict, fx: float, day: str, whole: bool) -> None:
        nonlocal cash
        q = pos.qty if whole else float(o["quantity"])
        if q > pos.qty + 1e-6:
            violate(day, f"{pos.symbol} : vente de {q:g} pour {pos.qty:g} détenus")
        q = min(q, pos.qty)
        if q <= EPS:
            return
        p = float(o["price"])
        frac_left = (pos.qty - q) / pos.qty
        if pos.kind in EQUITY_KINDS:
            proceeds = q * p * fx
            pos.realized += proceeds - pos.cost_base / pos.qty * q
            cash += proceeds
        elif pos.kind == "cfd":
            gain = pos.sgn * q * (p - pos.avg_local) * fx
            pos.realized += gain
            cash += gain
        else:  # future : règle la variation de la quantité sortante jusqu'au prix de l'ordre
            local = pos.sgn * q * pos.multiplier * (p - pos.mark)
            gain = local * fx
            pos.realized += pos.sgn * q * pos.multiplier * (p - pos.avg_local) * fx   # lots sortis, au prix d'entrée moyen
            pos.pnl_local_cum += local
            pos.var_cum += gain
            cash += gain
        pos.cost_local *= frac_left
        pos.cost_base *= frac_left
        pos.qty -= q
        if pos.qty <= EPS:
            pos.qty = 0.0
            pos.cost_local = pos.cost_base = 0.0
            pos.status, pos.closed_on = "closed", day

    def charge_fees(pos: _Pos, amount: float) -> None:
        nonlocal cash
        cash -= amount
        pos.fees += amount
        totals["fees"] += amount

    def auto_close(pos: _Pos, price: float, day: pd.Timestamp, reason: str) -> None:
        iso = day.date().isoformat()
        fx = market.fx_at(pos.currency, day, pos.fx_ref)
        fc = pos.spec.get("fee_ctx", {})
        notional = pos.qty * pos.multiplier * price * fx
        ctx = fees_mod.FeeContext(kind=pos.kind, notional_base=notional, quantity=pos.qty,
                                  currency=pos.currency, base_currency=base, **fc)
        amount = fees_mod.estimate_fees(ctx, fees_mod.make_seed(pos.position_id, reason)).total
        apply_reduce(pos, {"price": price}, fx, iso, whole=True)
        charge_fees(pos, amount)
        pos.status, pos.closed_on = reason, iso

    for i, day in enumerate(days):
        iso = day.date().isoformat()
        # nuits à financer après cette clôture : jusqu'au prochain jour ouvré (3 le vendredi)
        cal_days = (days[i + 1] - day).days if i + 1 < len(days) else 1

        # a. dividendes (quantité détenue en début de journée)
        for pos in positions.values():
            if pos.status == "open" and pos.kind in EQUITY_KINDS and pos.qty > EPS:
                div = market.dividend_on(pos.symbol, day)
                if div:
                    amount = pos.qty * div * market.fx_at(pos.currency, day, pos.fx_ref)
                    cash += amount
                    pos.dividends += amount
                    totals["dividends"] += amount

        # b. stop / objectif
        for pos in positions.values():
            if pos.status != "open" or pos.kind not in DERIV_KINDS or pos.last_order_day >= iso:
                continue
            bar = market.bar_on(pos.symbol, day)
            if bar is None or bar[["open", "high", "low"]].isna().any():
                continue
            hit = _trigger(pos, float(bar["open"]), float(bar["high"]), float(bar["low"]))
            if hit:
                auto_close(pos, hit[1], day, hit[0])

        # c. ordres du jour
        risk_up = False
        for o in by_day.get(day, []):
            pid, act = o["position_id"], o["action"]
            pos = positions.get(pid)
            fx = float(o["fx_rate"])
            if act == "open":
                if pos is not None:
                    violate(iso, f"{o['symbol']} : position {pid} déjà ouverte")
                    continue
                pos = positions[pid] = _Pos(pid, o["symbol"], o["instrument_kind"], o["side"], o["currency"],
                                            dict(o.get("spec") or {}), iso)
            elif pos is None:
                violate(iso, f"{o['symbol']} : ordre {act} sans position ouverte")
                continue
            elif pos.status != "open":
                violate(iso, f"{pos.symbol} : position déjà clôturée ({pos.status}) le {pos.closed_on}")
                continue
            if act in ("open", "increase"):
                apply_open_or_increase(pos, o, fx)
                risk_up = True
            elif act in ("reduce", "close"):
                apply_reduce(pos, o, fx, iso, whole=(act == "close"))
            elif act == "modify":
                pos.spec.update({k: v for k, v in (o.get("spec") or {}).items() if k in ("stop", "target", "leverage")})
            else:
                violate(iso, f"action inconnue : {act!r}")
                continue
            charge_fees(pos, float(o.get("fees") or 0.0))
            pos.last_order_day = iso

        # d. règlement de fin de journée
        for pos in positions.values():
            if pos.status != "open" or pos.qty <= EPS:
                continue
            close = market.close_at(pos.symbol, day)
            if close is None:
                continue
            fx = market.fx_at(pos.currency, day, pos.fx_ref)
            pos.last_price, pos.last_fx = close, fx
            if pos.kind == "future":
                local = pos.sgn * pos.qty * pos.multiplier * (close - pos.mark)
                cash += local * fx
                pos.var_cum += local * fx
                pos.pnl_local_cum += local
                pos.mark = close
                last = market.last_bar_day(pos.symbol)
                expiry = pd.Timestamp(pos.spec["expiry"]) if pos.spec.get("expiry") else None
                if (expiry is not None and last is not None and expiry <= end_ts
                        and last < end_ts - pd.Timedelta(days=7)):
                    expiry = min(expiry, last)
                if expiry is not None and day >= expiry:
                    auto_close(pos, close, day, "expired")
            elif pos.kind == "cfd":
                notional = pos.qty * close * fx
                rate = market.ref_rate(pos.currency, day)
                fin = (-notional * (rate + FINANCING_SPREAD) if pos.side == "long"
                       else notional * (rate - FINANCING_SPREAD)) * cal_days / 365.0
                cash += fin
                pos.financing_cost -= fin
                totals["financing"] -= fin

        # e. photographie
        equity_value = cfd_unreal = margin = gross = net = 0.0
        for pos in positions.values():
            if pos.status != "open" or pos.qty <= EPS or pos.last_price is None:
                continue
            c, fx = pos.last_price, pos.last_fx
            if pos.kind in EQUITY_KINDS:
                mv = pos.qty * c * fx
                equity_value += mv
                gross += abs(mv)
                net += mv
            elif pos.kind == "cfd":
                cfd_unreal += pos.sgn * pos.qty * (c - pos.avg_local) * fx
                notional = pos.qty * c * fx
                m = notional / float(pos.spec.get("leverage") or 1.0)
                margin += m
                gross += notional
                net += pos.sgn * notional
                pos.engaged_peak = max(pos.engaged_peak, m)
            else:
                notional = pos.qty * pos.multiplier * c * fx
                m = pos.qty * float(pos.spec.get("margin_per_unit", 0.0)) * fx
                margin += m
                gross += notional
                net += pos.sgn * notional
                pos.engaged_peak = max(pos.engaged_peak, m)
        nav = cash + equity_value + cfd_unreal
        buying_power = cash + cfd_unreal - margin
        if risk_up and buying_power < -1e-6:        # alléger ou fermer ne doit jamais être bloqué
            violate(iso, f"liquidités ou marge insuffisantes le {iso} (disponible {buying_power:,.2f} {base})")
        if margin > EPS and nav < 0.5 * margin:
            alert_days.append(iso)
        rows.append({"date": day, "cash": cash, "equity_value": equity_value, "cfd_unrealized": cfd_unreal,
                     "nav": nav, "margin_used": margin, "buying_power": buying_power,
                     "gross_exposure": gross, "net_exposure": net, "fees_cum": totals["fees"],
                     "dividends_cum": totals["dividends"], "financing_cum": totals["financing"]})

    daily = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=DAILY_COLUMNS)
    return SimResult(daily, [_view(p, market, end_ts) for p in positions.values()], violations, alert_days)


def _session_days(start: pd.Timestamp, end_ts: pd.Timestamp, market: MarketData,
                  orders: list[dict]) -> pd.DatetimeIndex:
    """Jours rejoués : les jours ouvrés, plus les samedis et dimanches où un symbole de la stratégie a coté
    (cryptoactifs : sans eux un ordre du week-end serait rejoué le lundi, ou refusé s'il tombe après le dernier
    vendredi). Une stratégie d'actions garde un calendrier de jours ouvrés."""
    days = pd.bdate_range(start, end_ts)
    weekend: set[pd.Timestamp] = set()
    for symbol in {o["symbol"] for o in orders}:
        df = market.bars.get(symbol)
        if df is None or df.empty:
            continue
        idx = df.index
        weekend.update(idx[(idx >= start) & (idx <= end_ts) & (idx.dayofweek >= 5)])
    return days.union(pd.DatetimeIndex(sorted(weekend))) if weekend else days


def _split_adjusted(o: dict, market: MarketData) -> dict:
    """Ordre action/ETF exprimé en titres d'aujourd'hui : un fractionnement postérieur à l'ordre multiplie la
    quantité et divise le prix (l'historique stocké est déjà ajusté), valeur et P&L sont inchangés."""
    if o["instrument_kind"] not in EQUITY_KINDS:
        return o
    factor = market.split_factor_after(o["symbol"], pd.Timestamp(o["ts"]))
    if factor == 1.0:
        return o
    adjusted = dict(o)
    adjusted["quantity"] = float(o["quantity"]) * factor
    if o.get("price"):
        adjusted["price"] = float(o["price"]) / factor
    return adjusted


def _trigger(pos: _Pos, o: float, h: float, lo: float) -> tuple[str, float] | None:
    stop, target = pos.spec.get("stop"), pos.spec.get("target")
    if pos.side == "long":
        if stop is not None and lo <= stop:
            return "stop", min(float(stop), o)
        if target is not None and h >= target:
            return "target", max(float(target), o)
    else:
        if stop is not None and h >= stop:
            return "stop", max(float(stop), o)
        if target is not None and lo <= target:
            return "target", min(float(target), o)
    return None


def _view(pos: _Pos, market: MarketData, end_ts: pd.Timestamp) -> dict:
    close = pos.last_price if pos.last_price is not None else market.close_at(pos.symbol, end_ts)
    fx_now = market.fx_at(pos.currency, end_ts, pos.fx_ref)
    is_open = pos.status == "open" and pos.qty > EPS
    value = latent = price_effect = fx_effect = margin = 0.0
    if is_open and close is not None:
        if pos.kind in EQUITY_KINDS:
            value = pos.qty * close * fx_now
            latent = value - pos.cost_base
            price_effect = pos.qty * (close - pos.avg_local) * pos.fx_ref
            fx_effect = pos.qty * close * (fx_now - pos.fx_ref)
        elif pos.kind == "cfd":
            latent = pos.sgn * pos.qty * (close - pos.avg_local) * fx_now
            value = latent
            price_effect = pos.sgn * pos.qty * (close - pos.avg_local) * pos.fx_ref
            fx_effect = latent - price_effect
            margin = pos.qty * close * fx_now / float(pos.spec.get("leverage") or 1.0)
        else:
            # futures : réalisé / latent plus bas, depuis le règlement cumulé
            margin = pos.qty * float(pos.spec.get("margin_per_unit", 0.0)) * fx_now
    if pos.kind == "future":
        # Le règlement quotidien est déjà en cash : tant que la position est ouverte, ce qui n'a pas été
        # réalisé par une sortie est latent ; une fois fermée, tout est réalisé (aucun résidu de change).
        realized = pos.realized if is_open else pos.var_cum
        latent = pos.var_cum - realized if is_open else 0.0
        price_effect = pos.pnl_local_cum * pos.fx_ref
        fx_effect = pos.var_cum - price_effect
        gross = pos.var_cum
    else:
        realized = pos.realized
        if not is_open:
            price_effect, fx_effect = realized, 0.0
        gross = realized + latent
    pnl = gross - pos.fees + pos.dividends - pos.financing_cost
    engaged = pos.engaged_peak
    return {
        "position_id": pos.position_id, "symbol": pos.symbol, "kind": pos.kind, "side": pos.side,
        "currency": pos.currency, "status": pos.status, "opened_on": pos.opened_on, "closed_on": pos.closed_on,
        "quantity": pos.qty, "avg_entry": pos.avg_local if is_open else None, "last_price": close,
        "fx_open": pos.fx_ref, "fx_now": fx_now, "value_base": value, "margin": margin,
        "realized": realized, "latent": latent, "price_effect": price_effect, "fx_effect": fx_effect,
        "fees": pos.fees, "dividends": pos.dividends, "financing": pos.financing_cost,
        "pnl": pnl, "pnl_pct": pnl / engaged if engaged > EPS else None,
        "stop": pos.spec.get("stop"), "target": pos.spec.get("target"),
        "leverage": pos.spec.get("leverage"), "expiry": pos.spec.get("expiry"),
        "price_quality": pos.spec.get("price_quality"),
    }
