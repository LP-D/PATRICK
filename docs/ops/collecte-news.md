# Collecte des nouvelles — exploitation

Date : 2026-10-18. Module `patrick/text/`, page `/news`, commande `patrick news`.

## Commandes

```bash
patrick news refresh                 # flux RSS par défaut + réglage news_extra_feeds, puis notes et rattachement
patrick news refresh --gdelt         # ajoute GDELT (une requête / 5 s, ~35 s)
patrick news refresh --yahoo AAPL,^GSPC   # titres Yahoo de ces symboles
patrick news summary                 # chiffres du magasin
```

Le bouton « Actualiser » de `/news` lance la même collecte (flux par défaut seulement) dans un fil d'arrière-plan.

## Tâche planifiée (optionnelle)

`scripts/schtasks_news.ps1` affiche la tâche Windows `Patrick-NewsRefresh` (toutes les 4 h, journal `runs/news_refresh.log`) sans rien
installer ; `-Install` la crée, `-Remove` la supprime. Les flux ne gardent que quelques dizaines d'articles : sans collecte régulière,
l'historique point-in-time ne se constitue pas.

## Réglages (`~/.patrick/settings.json`)

| Clé | Rôle |
|---|---|
| `news_extra_feeds` | Liste `{name, url, kind, language}` de flux supplémentaires (https uniquement ; `kind` = `news`, `central_bank` ou `commodity_report`). |
| `news_lm_dictionary` | Chemin du « Master Dictionary » Loughran-McDonald (CSV) : remplace le lexique réduit intégré. Non redistribué par PATRICK. |

## Flux par défaut (vérifiés le 2026-10-18)

Fed (communiqués monétaires, discours), Banque d'Angleterre, EIA (deux flux), FT Markets, BBC Business, CNBC Markets, MarketWatch.
Ne répondaient pas : BCE (certificat refusé par Python sur ce poste), USDA et OPEP (403), AIE (404), GDELT (429 persistant). Les ajouter
par `news_extra_feeds` quand une URL valide est connue.

## Règles à retenir

- Une nouvelle est utilisable à partir de `max(publication annoncée, première observation)` ; après la clôture, elle compte pour la
  séance suivante ; une date sans heure est lue en fin de journée.
- Une nouvelle vue plus de 72 h après sa publication est stockée mais écartée des agrégats (un flux relu des mois plus tard n'est pas
  de l'actualité).
- La collecte n'écrit que dans les tables `news_*` de la base de suivi : ni cache de séries, ni data lake. Ne pas la lancer pendant une
  maintenance de la base (voir la règle « pas de maintenance DB pendant un run »).
