"""Enveloppes d'épargne : ce qui change entre un PEE, une assurance vie, un PER, un PEA, un compte-titres ou un livret, à supports identiques.

Un jeu de paramètres unique décrit toutes les enveloppes (préréglages ci-dessous, tous modifiables) :
- frais d'entrée (% de chaque versement) et frais de gestion annuels de l'enveloppe (% de l'encours, prélevés chaque mois) — les VL des
  supports sont déjà nettes de leurs propres frais ;
- abondement de l'employeur (PEE, PERCO) : taux appliqué aux versements du salarié, plafond annuel, CSG-CRDS prélevée à l'entrée ;
- prélèvements sociaux annuels sur les intérêts du fonds en euros (assurance vie) ;
- fiscalité à la sortie sur les gains : prélèvements sociaux + impôt (taux différent avant et après une durée de détention, abattement
  annuel après cette durée — assurance vie : 8 ans, 4 600 € pour une personne seule, 9 200 € pour un couple) ;
- PER : versements déductibles (économie d'impôt au taux marginal d'entrée), capital imposé à la sortie au taux marginal de sortie.

Valeurs par défaut 2026 (à vérifier et à adapter à chaque contrat) : prélèvements sociaux 18,6 % (hausse de la CSG de 1,4 point par la
LFSS 2026, flat tax 31,4 %), 17,2 % pour l'assurance vie, exclue de la hausse ; plafond d'abondement PEE 8 % du PASS 2026 (48 060 €) =
3 844,80 €, abondement au plus égal à 300 % du versement. Les sources consultées divergeaient sur l'épargne salariale et le PEA : le taux
est un paramètre, pas une certitude.
"""
from __future__ import annotations

import copy

PASS_2026 = 48_060.0
PS_2026 = 18.6
PS_LIFE = 17.2
IR_FLAT = 12.8

ENVELOPES: dict[str, dict] = {
    "pee": {"entry_fee": 0.0, "mgmt_fee": 0.0, "abond_rate": 100.0, "abond_cap": round(0.08 * PASS_2026, 2), "abond_csg": 9.7, "euro_ps": 0.0,
            "ps_exit": PS_2026, "ir_before": 0.0, "ir_after": 0.0, "years_threshold": 5, "allowance": 0.0, "deductible": False, "tmi_in": 0.0,
            "tmi_out": 0.0, "lock_years": 5},
    "perco": {"entry_fee": 0.0, "mgmt_fee": 0.0, "abond_rate": 100.0, "abond_cap": round(0.16 * PASS_2026, 2), "abond_csg": 9.7, "euro_ps": 0.0,
              "ps_exit": PS_2026, "ir_before": 0.0, "ir_after": 0.0, "years_threshold": 0, "allowance": 0.0, "deductible": False, "tmi_in": 0.0,
              "tmi_out": 0.0, "lock_years": 0},
    "av": {"entry_fee": 0.0, "mgmt_fee": 0.6, "abond_rate": 0.0, "abond_cap": 0.0, "abond_csg": 0.0, "euro_ps": PS_LIFE, "ps_exit": PS_LIFE,
           "ir_before": IR_FLAT, "ir_after": 7.5, "years_threshold": 8, "allowance": 4600.0, "deductible": False, "tmi_in": 0.0, "tmi_out": 0.0, "lock_years": 0},
    "per": {"entry_fee": 0.0, "mgmt_fee": 0.6, "abond_rate": 0.0, "abond_cap": 0.0, "abond_csg": 0.0, "euro_ps": 0.0, "ps_exit": PS_2026,
            "ir_before": IR_FLAT, "ir_after": IR_FLAT, "years_threshold": 0, "allowance": 0.0, "deductible": True, "tmi_in": 30.0, "tmi_out": 30.0,
            "lock_years": 0},
    "pea": {"entry_fee": 0.0, "mgmt_fee": 0.0, "abond_rate": 0.0, "abond_cap": 0.0, "abond_csg": 0.0, "euro_ps": 0.0, "ps_exit": PS_2026,
            "ir_before": IR_FLAT, "ir_after": 0.0, "years_threshold": 5, "allowance": 0.0, "deductible": False, "tmi_in": 0.0, "tmi_out": 0.0, "lock_years": 0},
    "cto": {"entry_fee": 0.0, "mgmt_fee": 0.0, "abond_rate": 0.0, "abond_cap": 0.0, "abond_csg": 0.0, "euro_ps": 0.0, "ps_exit": PS_2026,
            "ir_before": IR_FLAT, "ir_after": IR_FLAT, "years_threshold": 0, "allowance": 0.0, "deductible": False, "tmi_in": 0.0, "tmi_out": 0.0, "lock_years": 0},
    "none": {"entry_fee": 0.0, "mgmt_fee": 0.0, "abond_rate": 0.0, "abond_cap": 0.0, "abond_csg": 0.0, "euro_ps": 0.0, "ps_exit": 0.0,
             "ir_before": 0.0, "ir_after": 0.0, "years_threshold": 0, "allowance": 0.0, "deductible": False, "tmi_in": 0.0, "tmi_out": 0.0, "lock_years": 0},
}
BOUNDS = {"entry_fee": (0, 10), "mgmt_fee": (0, 5), "abond_rate": (0, 300), "abond_cap": (0, 100_000), "abond_csg": (0, 20), "euro_ps": (0, 40),
          "ps_exit": (0, 40), "ir_before": (0, 60), "ir_after": (0, 60), "years_threshold": (0, 40), "allowance": (0, 100_000), "tmi_in": (0, 60),
          "tmi_out": (0, 60), "lock_years": (0, 50)}
CONTRIB_DEFAULTS = {"initial": 10_000.0, "monthly": 0.0, "yearly": 0.0, "growth": 0.0, "goal": 0.0}
ROLES = ("uc", "euro", "money")
CATEGORIES = ("equity", "bond", "money", "euro", "mixed", "real_estate", "commodity", "other")
CATEGORY_HINTS = (
    ("euro", ("fonds euro", "fonds en euro", "fonds en euros", "fonds euros", "actif general", "actif général", "general fund", "eurocroissance",
              "fonds general", "fonds général", "support euro", "support en euros")),
    ("money", ("monetaire", "monétaire", "money market", "tresorerie", "trésorerie", "court terme", "cash", "liquidite")),
    ("real_estate", ("immobilier", "scpi", "opci", "sci ", "real estate", "reit", "pierre")),
    ("bond", ("oblig", "bond", "credit", "crédit", "taux", "fixed income", "rendement", "high yield", "souverain", "aggregate")),
    ("mixed", ("diversifi", "equilibre", "équilibre", "patrimoine", "allocation", "flexible", "prudent", "dynamique", "balanced", "multi", "profil", "mixte")),
    ("commodity", ("or ", "gold", "matieres", "matières", "commodit", "energie", "énergie")),
    ("equity", ("action", "equity", "equities", "stock", "pme", "eti", "small", "large cap", "indice", "msci", "s&p", "cac", "euro stoxx", "nasdaq",
                "world", "emerging", "emergent", "technolog", "sante", "santé", "water", "clean")),
)


class EnvelopeError(ValueError):
    """Paramètre d'enveloppe invalide : message en français."""


def normalise(kind: str, overrides: dict | None = None) -> dict:
    if kind not in ENVELOPES:
        raise EnvelopeError(f"Enveloppe inconnue : {kind}.")
    env = copy.deepcopy(ENVELOPES[kind])
    for k, v in (overrides or {}).items():
        if k not in env:
            continue
        if k == "deductible":
            env[k] = bool(v)
            continue
        try:
            v = float(v)
        except (TypeError, ValueError) as exc:
            raise EnvelopeError(f"Enveloppe : {k} invalide.") from exc
        lo, hi = BOUNDS[k]
        if not lo <= v <= hi:
            raise EnvelopeError(f"Enveloppe : {k} doit être compris entre {lo} et {hi}.")
        env[k] = v
    env["kind"] = kind
    return env


def contributions(raw: dict | None) -> dict:
    out = dict(CONTRIB_DEFAULTS)
    for k, v in (raw or {}).items():
        if k in out:
            try:
                out[k] = float(v or 0)
            except (TypeError, ValueError) as exc:
                raise EnvelopeError(f"Versements : {k} invalide.") from exc
    if out["initial"] < 0 or out["monthly"] < 0 or out["yearly"] < 0 or out["goal"] < 0:
        raise EnvelopeError("Les versements et l'objectif doivent être positifs.")
    if out["initial"] + out["monthly"] + out["yearly"] <= 0:
        raise EnvelopeError("Indiquez au moins un versement (initial, mensuel ou annuel).")
    if not -20 <= out["growth"] <= 20:
        raise EnvelopeError("La progression annuelle des versements doit être comprise entre -20 % et 20 %.")
    return out


def guess_category(label: str, vol: float | None = None) -> str:
    """Catégorie probable d'un support d'après son nom (mots entiers ou débuts de mots), sinon d'après sa volatilité."""
    import re
    text = " " + re.sub(r"[^a-z0-9éèêàâîôûç&]+", " ", label.lower()) + " "
    for cat, hints in CATEGORY_HINTS:
        if any(re.search(r"(?<![a-z0-9])" + re.escape(h.strip()) + (r"(?![a-z0-9])" if h.endswith(" ") or cat == "euro" else ""), text) for h in hints):
            return cat
    if vol is not None:
        if vol < 0.01:
            return "money"
        if vol < 0.06:
            return "bond"
        if vol > 0.12:
            return "equity"
        return "mixed"
    return "other"


def role_of(category: str) -> str:
    return "euro" if category == "euro" else ("money" if category == "money" else "uc")


def exit_tax(gains: float, contributions_total: float, years: float, env: dict, already_taxed: float = 0.0, couple: bool = False) -> dict:
    """Impôts et prélèvements à la sortie (rachat total) : `{ps, ir, total}`.

    Prélèvements sociaux sur les gains pas déjà taxés (intérêts du fonds en euros taxés chaque année en assurance vie) ; impôt au taux
    « avant » ou « après » le seuil de durée, après abattement (une fois le seuil passé). PER : le capital versé est imposé au taux marginal de
    sortie (les versements avaient été déduits), les gains au taux forfaitaire."""
    g = max(gains, 0.0)
    ps = max(g - already_taxed, 0.0) * env["ps_exit"] / 100
    after = years >= env["years_threshold"] and env["years_threshold"] > 0
    rate = env["ir_after"] if after else env["ir_before"]
    allowance = env["allowance"] * (2 if couple else 1) if after else 0.0
    ir = max(g - allowance, 0.0) * rate / 100
    if env.get("deductible"):
        ir += contributions_total * env["tmi_out"] / 100
    return {"ps": ps, "ir": ir, "total": ps + ir}
