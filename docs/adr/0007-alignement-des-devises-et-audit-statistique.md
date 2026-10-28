# ADR 0007 — Alignement des cibles de change et audit statistique des fuites de date

Date : 2026-10-28 · Statut : acceptée · Code : `data/session_calendar.py` (`CURRENT_SESSION_RULE`, `session_lag_days(rule=)`, `target_close_hour`), `data/ingest.py` (`_apply_session_lag`, version de cache), `data/alignment.py` (`audit_threshold`, `fred_columns`, règle FRED, `ALIGNMENT_VERSION = 2`), `config/schema.py` (`ObjectiveConfig.session_rule`), `pipeline/engine.py` (`run_pipeline`, `_config_hash`), `validation/suspicion.py` (`alignment_reason`), `tracking/db.py` (`alignment_reasons`), `fund/selection.py` · Tests : `tests/test_fx_alignment.py`, `tests/test_alignment.py`

## Contexte

Un placebo (variables retardées d'un jour de plus) sur le run EURUSD à 1 jour a montré que son exactitude directionnelle sur le holdout
(70,8 %, AUC 0,69) disparaît dès qu'on retarde les variables (45,8 %, AUC 0,51) ; USDJPY donne 81,6 % puis 45,4 %. Les variables retenues
sont les rendements **du jour** de l'or, de l'argent, du cuivre et du S&P 500.

Cause : une barre journalière Yahoo `=X` datée d porte le cours du **début** de la journée d. Brexit (chute de la livre le vendredi
24/06/2016) : -1,56 % à la date 24/06 et -7,60 % à la date du lundi 27/06 ; choc du franc suisse (jeudi 15/01/2015) : EURCHF -17,2 %
à la date du vendredi 16/01 ; yen du Brexit : -2,64 % à la date 27/06. Le S&P 500 (témoin) est à la bonne date. Le label d'une ligne
(prix d+1 / prix d) est donc le mouvement réel du jour d, que les clôtures du jour d expliquent par simple corrélation : un « nowcast »
sans gain négociable. La règle des séances supposait que le change clôture à 22 h UTC le même jour ; la garde empirique (`alignment.py`)
n'agissait qu'au-delà d'une corrélation de rang de 0,30, sur les seules séries Yahoo.

Un audit de tous les snapshots du data lake (506, corrélation de rang entre le rendement du jour de chaque variable telle que le modèle la
reçoit et le rendement futur de la cible) a montré que le défaut dépasse les devises :

| Classe | Corrélation maximale médiane, avant | Après |
|---|---|---|
| Devises (20) | 0,41 | 0,05 |
| Actions Asie-Pacifique (25) | 0,18 | 0,05 |
| Actions Europe (149) | 0,08 | 0,04 |
| États-Unis, futures, crypto, indices de volatilité | 0,05 à 0,07 | inchangé (bruit) |

Pour l'Asie et l'Europe la fuite vient de séries FRED quotidiennes (VIX, VXN, RVX, écarts de crédit, anticipations d'inflation) : en mode
ALFRED leur première publication tombe le soir même, donc la valeur du jour d est « connue » à la ligne d alors que la cible a déjà clôturé.

## Décision

1. **Règle des séances 2** (`ObjectiveConfig.session_rule`, défaut 1 = règle d'origine). Sous la règle 2, une cible `=X` retarde d'une barre
   toute série Yahoo qui n'est pas une paire `=X` (DXY compris). Un run neuf reçoit la règle courante dans `run_pipeline` ; un run
   enregistré avant le champ garde la règle 1 (le live, l'explication et la reprise lui rejouent donc ses entrées d'origine). Le champ n'entre
   dans le hachage de configuration que pour une cible de change (aucune autre cible n'est construite autrement).
2. **Version de cache** : le snapshot brut d'une cible de change sous la règle 2 porte le suffixe `:fx-start-of-day` ; les anciens snapshots de
   change ne sont plus servis.
3. **Audit statistique** (`ALIGNMENT_VERSION = 2`) : le seuil fixe de 0,30 devient `max(0,10 ; 5 / racine(n))` (cinq écarts-types du bruit de
   corrélation de rang), et l'audit couvre aussi les séries FRED d'une cible cotée.
4. **Règle FRED** : pour une cible cotée qui clôture avant 20 h UTC (Asie, Europe, changes), toute série FRED quotidienne (mode ALFRED) est
   retardée d'une barre. Les écarts de crédit n'ont que trois ans d'historique : l'audit n'a pas la puissance pour les voir seul.
5. **Anciens runs de change** : lisibles, jamais supprimés, mais marqués suspects (`alignement des devises`) dans les listes de runs, exclus des
   modèles négociables du fonds (motif `alignment`) et refusés comme règle. Un nouveau run de change défie le champion en titre sur ses données
   corrigées (le duel rejoue la configuration du champion sur l'objectif du challenger).

## Conséquences

- Les 46 champions de change (sur 1 886) ne sont plus crédibles tant qu'un run sous la règle 2 ne les remplace pas. Les 13 runs de change au DM
  de holdout significatif à 5 % sont à relire comme des artefacts.
- Les actions Asie-Pacifique et, plus légèrement, Europe auront des métriques plus basses sous la garde v2 : c'est attendu. Les runs déjà faits ne
  sont pas réécrits (leur spécification d'alignement reste la leur).
- L'audit de non-régression sur les 506 snapshots est dans `docs/modelisation/triage-critique-2026-10-28.md`.
- Limite : la règle 2 vaut pour les paires Yahoo `=X`. Les contrats à terme de change (`6E=F`) et le DXY ont un cours de clôture réel et ne sont
  pas concernés. Les classes États-Unis, futures, crypto et volatilité sont au niveau du bruit : aucune règle n'y a été ajoutée.
