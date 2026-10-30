# ADR 0012 — Les actions dans leur vrai groupe, features de contexte de marché

Date : 2026-10-30 · Statut : acceptée · Code : `config/equity_universe.py`, `config/equity_context.py`, `features/equity_context.py`, `pipeline/engine.py` (`_build_base_feature_pool`, `_config_hash`), `webapp/forms.py` (`universe_excluding`), `config/defaults.py` (`MACRO_ONLY_FRED_SERIES`) · Tests : `tests/test_equity_context.py`, `tests/test_equity_asset_class.py`, `tests/test_extended_fred_series.py`

## Contexte

Quatre titres (TotalEnergies, Thales, Amazon, D.A.T.E) vivaient dans un groupe à part, « Actions individuelles », avec une page, un
bloc de fondamentaux affichés et une classe de fonds à eux seuls, alors que les 280 autres actions étaient rangées par pays et par taille.
Cette séparation datait du chantier des fondamentaux : elle n'avait plus de raison d'être (les fondamentaux ne sont pas des features, faute
de source point-in-time) et elle privait ces quatre titres de la comparaison avec leurs pairs.

Côté features, une action recevait le pipeline standard : le même traitement par série (technique, pics, volatilité, macro) que le VIX ou
l'or. Rien ne la comparait à SON marché, et l'univers de features par défaut (S&P 500, VIX, matières premières, bitcoin) est américain :
une action européenne n'avait ni l'indice de sa place, ni la zone euro, ni aucune série macro européenne autre que le Bund à 10 ans.

## Décision

1. **Plus de groupe à part.** TotalEnergies et Thales rejoignent « Actions France (CAC 40) », Amazon « Actions US (méga-capitalisations) »,
   D.A.T.E « Actions France (autres valeurs) ». `config/equity_universe.py` ne garde que les historiques courts déclarés (D.A.T.E et son indice de
   substitution) et la reconnaissance d'un symbole d'action ; la page Equity perd le bloc réservé à quatre titres (disponibilité, fondamentaux
   affichés) au profit d'un bloc « Features des actions ». La classe de fonds « Actions individuelles » disparaît.
2. **Features de contexte** (`features/equity_context.py`, `config/equity_context.py`) pour toute cible qui est une action : rendement relatif,
   bêta, corrélation, volatilité propre et force relative face à l'indice de sa place de cotation, à un indice composite de la zone euro (moyenne
   des rendements du CAC 40, DAX, AEX, IBEX et FTSE MIB, tous en euros et servis depuis 1997 au plus tard) et au S&P 500 ; pour la zone euro,
   écarts Italie / France contre Allemagne et taux de la BCE contre celui de la Fed. Les indices nécessaires sont ajoutés à l'univers du run
   (`universe_excluding`). L'Euro Stoxx 50 n'est pas utilisé : Yahoo le sert depuis 2007, le filtre de couverture à 85 % depuis 2000 le retirerait.
3. **Six séries FRED de la zone euro**, d'entraînement seulement, pour tous les runs : rendements français et italien à 10 ans, HICP, PIB réel,
   chômage allemand, taux de refinancement de la BCE. Écartées : les séries OECD interrompues entre 2023 et début 2026, l'écart de crédit euro
   (trois ans d'historique), l'indice d'incertitude européen (révisé après coup).

## Conséquences

- L'interrupteur `FeaturesConfig.enable_equity_context_features` vaut `False` dans le schéma : un run enregistré se rejoue (prédiction, explication,
  reprise) avec ses colonnes d'origine. Tout run neuf (formulaire, lots) le met à `True`. Il n'entre dans le hachage de configuration que pour une
  action qui l'active : le hachage d'un run sur un autre actif ne bouge pas à cause de lui.
- Contrôle sur données réelles (2026-10-30) : pour MC.PA et SAP.DE, les sept séries passent le filtre de couverture, 36 colonnes sont produites,
  aucune valeur manquante après 300 séances.
- Non fait, et pourquoi : pas de momentum transversal (il exigerait les cours de tous les titres du groupe dans chaque run, jusqu'à 134) ; pas de
  fondamentaux comme features (aucune source point-in-time). Le gain prédictif des nouvelles features n'est pas mesuré : c'est à la sélection
  (SHAP, FDR) de dire lesquelles servent, et une ablation sur un panel d'actions européennes reste à faire.
- Une stratégie de fonds nommée « Systematic Actions individuelles » qui existerait dans une base n'est plus proposée par le pilote automatique ;
  les actions sont couvertes par « Actions US », « Actions France », « Actions Europe » et « Actions Asie ».
