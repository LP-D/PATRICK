# Fonds, chantier 3 — mode systématique « modèle ML avec seuils »

Suite de `2026-10-03-fonds-simulation-socle-design.md` (§16). Premier mode du chantier 3; le carry trade viendra
ensuite sur le même squelette.

## 1. Objectif

Une stratégie du fonds génère ses ordres elle-même à partir des signaux d'un modèle déjà entraîné
(`prediction`), avec des seuils d'entrée et de sortie saisis. Les ordres produits passent par
`fund.service.place_order` : mêmes règles d'enveloppe, mêmes frais, même moteur de valorisation que les ordres
manuels. Aucun nouveau moteur.

## 2. Règle

Une règle (`fund_rule`) lie une stratégie à un essai de modèle (`trial_id`) et à un instrument.

| Champ | Sens |
|---|---|
| `trial_id` | essai gagnant dont on rejoue les signaux |
| `segment` | `holdout` (défaut), `live` ou `test` (biaisé à la hausse : averti, comme `simulate.engine.SEGMENT_WARNINGS`) |
| `enter` | `0,5 < enter < 1` : ouvre un long si score ≥ `enter`, un short si score ≤ `1 − enter` |
| `exit` | `0,5 ≤ exit ≤ enter` : ferme un long si score < `exit`, un short si score > `1 − exit` (hystérésis) |
| `allow_short` | `false` par défaut; refusé sur action/ETF (compte comptant), possible en CFD et future |
| `instrument` | `kind` (`equity`, `etf`, `cfd`, `future`), `symbol`, `spec` (racine/échéance d'un future, levier d'un CFD) |
| `sizing` | `amount` (action/ETF, en devise de base) ou `quantity` entière (CFD, future) |

Le score est celui du simulateur de recherche : `y_proba` si la classe prédite est haussière, sinon `1 − y_proba`
(`simulate.engine._directional_score`).

## 3. Du signal à l'ordre

- Machine à états par règle : à plat, long ou short. Une fermeture suivie d'une ouverture de sens opposé le même
  jour donne deux ordres (`close` puis `open`).
- **Retard** : un signal du jour *t* est exécuté à la première séance du *titre négocié* à partir de *t + 1 jour*,
  au cours de clôture. Jamais le jour du signal.
- Tenue : la position est conservée jusqu'au signal de sortie (équivalent du mode `renewed` du simulateur), pas de
  fermeture à l'horizon du modèle.
- Un ordre refusé par les règles (liquidités, enveloppe, cotation absente) n'est pas placé : il est listé avec ses
  motifs. Les ordres suivants de la même position sont sautés. Un ordre dont la date d'exécution est dans le futur
  reste « en attente ».

## 4. Idempotence

Chaque ordre généré porte la note `auto:<rule_id>:<date du signal>:<open|close>`. `apply` recalcule tout le plan,
ignore les ordres déjà présents (même note) et place les autres dans l'ordre chronologique. Relancer ne duplique
jamais. Un ordre automatique existant qui n'est plus dans le plan (règle modifiée) est signalé (`drift`), jamais
supprimé.

## 5. Honnêteté statistique

Chaque création de règle est enregistrée via `simulate.engine.save_simulation` : les seuils saisis sont une
configuration de plus essayée sur la cible et comptent dans tous les DSR suivants (`trial_registry`, F03).

## 6. Données

Migration `0031_fund_rule.sql` : table `fund_rule` (`rule_id`, `strategy_id`, `name`, `config_json`, `created_at`).
Préfixe `fund_` : exclue automatiquement de `patrick sync` vers GitHub.

## 7. Hors périmètre de ce jalon

- Page web de gestion des règles (jalon suivant) : ce jalon livre le module et la CLI
  (`patrick fund rule-create | rule-list | rule-apply`).
- Planification automatique quotidienne de `apply`.
- Dimensionnement proportionnel au score (seul le tout-ou-rien à seuils est fourni).
- Carry trade.

## 8. Point à confirmer

La date `ts` d'une ligne `prediction` correspond-elle à une information disponible à la clôture de *ts* ? Le
simulateur de recherche entre au cours de clôture du jour du signal (retard 1 barre sur la grille de rendements);
ce mode exécute une séance plus tard, donc au moins aussi prudent. À vérifier avant d'aligner les deux.
