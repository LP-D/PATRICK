# Événements de résultats — mode d'emploi

Page `/resultats` (Pilotage → Recherche → Résultats), paquet `patrick/earnings/`, commande `patrick earnings`. Décisions et limites : [ADR 0016](../adr/0016-evenements-de-resultats.md).

## Le flux d'une semaine

1. **Coller** la newsletter dans la zone de texte. Le lundi de la semaine est pré-rempli (lundi de la semaine **en cours**, modifiable). Format reconnu : un jour (lundi à samedi, ou en anglais) suivi de noms séparés par des virgules, sur la même ligne ou les suivantes ; une parenthèse après un nom est un indice (`Novo Nordisk (Copenhague)`, `Ryanair (ADR)`, `Apple (AAPL)`, `SAP (avant ouverture)`).
2. **Analyser** : chaque nom devient une ligne de cotation (alias mémorisés, alias semés, recherche Yahoo). **Rien n'est calculé.**
3. **Confirmer** dans le tableau éditable : symbole local, ADR ou ligne liée, timing (automatique, BMO, AMC, pendant la séance, inconnu). Les badges disent ce qu'il faut vérifier (`nom différent`, `ambigu`, `introuvable`, `Yahoo : <nom retenu>`). Un alias confirmé n'est plus redemandé.
4. **Calculer** : ingestion des prix et du calendrier de chaque titre, instantané du jour, rapprochement des dates de la newsletter avec celles de Yahoo (écart signalé), mesures de tout l'historique d'annonces.
5. **Vue semaine** : les titres classés par amplitude attendue (|CAR| moyen historique rétréci vers le secteur), fourchette 10-90 %, P(hausse), quatre dernières réactions, mouvement implicite si un instantané d'options existe, fiabilité et drapeaux.
6. **Bibliothèque** : 54 cartes, chacune activable et paramétrable, calculée au clic puis lue du cache. Périmètre : tout l'univers, la semaine collée, un secteur, un titre. Le **verdict FDR** (bas de page) corrige l'ensemble des tests essayés.

## Fiche titre et détail d'un événement

`/resultats/titre/<symbole>` : distribution, fiabilité, CAAR moyen cumulé (événements empilés), historique des réactions (CAR, brut, overnight/intraday, surprise, run-up, volume), consensus du dernier instantané, saisie manuelle des dates passées. `/resultats/evenement?symbol=…&day=…` : trajectoire autour de J0 (CAR, rendement anormal, volume, overnight/intraday).

## Quand Yahoo n'a pas d'historique

Constaté sur Diageo (`DGE.L`), LVMH (`MC.PA`), Interparfums (`ITP.PA`) : une seule date à venir, aucune passée. Sur la fiche du titre, saisir les dates passées (une par ligne, `AAAA-MM-JJ [HH:MM] [BMO|AMC]`, heure **locale** à la place) ; les mesures se recalculent aussitôt.

## Réglages

Modèle de rendement attendu (marché, ajusté du marché, facteurs, secteur), fenêtre d'estimation, exclusion autour des autres annonces, fenêtre de réaction (automatique : `[0]` si le timing est certain, sinon `[0, +1]`), run-up, continuation, dérive, test de référence, winsorisation, N minimal, seuil de gros mouvement. Changer le modèle ou la fenêtre d'estimation change les mesures : le bouton **Recalculer tous les titres** apparaît ; le reste se relit des trajectoires déjà stockées.

## Instantanés quotidiens (le seul historique daté en gratuit)

`Prendre l'instantané` (page) ou `patrick earnings snapshot` : consensus, révisions, recommandations, cibles de cours, vendeurs à découvert, straddle de la prochaine annonce, pour les titres dont l'annonce tombe dans les 30 jours. Un instantané d'un jour donné n'est jamais réécrit. La tâche de nuit (`scripts/nightly_run.ps1`, étape « resultats instantanes ») le prend avant les prédictions. Les cartes d'options et d'analystes se remplissent à mesure ; il faut quelques trimestres.

## Ligne de commande

```bash
patrick earnings parse newsletter.txt          # analyse et résout ; crée un lot
patrick earnings run --batch 3                 # confirme les lignes proposées, calcule, affiche la vue semaine
patrick earnings studies                       # liste des cartes
patrick earnings study core_event_study --scope sector:Technology
patrick earnings study m_placebo --param win_lo=2,win_hi=5
patrick earnings ledger                        # verdict FDR de ce qui est calculé
patrick earnings snapshot                      # instantané du jour (étape de nuit)
patrick earnings manual DGE.L dates.txt        # dates passées d'un titre sans historique Yahoo
```

## Piège à connaître

Les dates de newsletter sont des suppositions : si Yahoo donne une annonce à moins de 7 jours, c'est la date Yahoo qui est retenue (écart signalé en badge). Une date inventée par la newsletter et absente de Yahoo reste un événement « à venir » marqué incertain ; elle n'entre dans l'historique que si Yahoo ne la contredit pas.
