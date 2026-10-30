# Collecte des nouvelles — exploitation

Date : 2026-10-18, mis à jour le 2026-10-27. Module `patrick/text/`, page `/news`, commande `patrick news`.

## Commandes

```bash
patrick news refresh                 # flux RSS par défaut + réglage news_extra_feeds, pages des banques centrales, notes, rattachement
patrick news refresh --gdelt         # ajoute GDELT (une requête / 5 s, ~35 s)
patrick news refresh --yahoo AAPL,^GSPC   # titres Yahoo de ces symboles
patrick news summary                 # chiffres du magasin
patrick news readiness [--symbol X]  # historique disponible pour l'entraînement et date à laquelle il suffira
patrick news lexicon [fichier.csv]   # lexique de sentiment actif et couverture ; avec un fichier : le valide, le branche, renote
patrick news lexicon --clear         # revient au lexique réduit intégré
```

Le bouton « Actualiser » de `/news` lance la même collecte (flux par défaut seulement) dans un fil d'arrière-plan.

## Quand la collecte tourne

- **Passage de nuit** (`Patrick-Nightly`, 23 h) : l'étape « actualités » passe **avant** les prédictions. Elle était placée après et
  n'avait jamais tourné : les prédictions durent des heures et la tâche était coupée à 6 h, en pleines prédictions (limite supprimée le 27/10)
  (journal du 26 au 27/10, code de résultat 267014). La sauvegarde de la base et la synchronisation, placées après les prédictions,
  sont coupées de la même façon.
- **Tâche dédiée** (optionnelle) : `scripts/schtasks_news.ps1` affiche la tâche Windows `Patrick-NewsRefresh` (toutes les 4 h,
  journal `runs/news_refresh.log`) sans rien installer ; `-Install` la crée, `-Remove` la supprime. Les flux ne gardent que quelques
  dizaines d'articles (une journée au plus pour CNBC et MarketWatch) : une collecte par nuit laisse passer une bonne part de la
  journée. La collecte étant idempotente, les deux ensemble ne gênent pas.

## Pages complètes des banques centrales

Le flux RSS d'une banque centrale ne donne qu'un titre et une phrase (80 à 160 caractères en moyenne) : le ton « faucon / colombe »
n'y trouvait aucune expression. Pour les seules nouvelles de type `central_bank`, la collecte lit la page liée (`text/fulltext.py`),
la garde dans la table `news_body` (migration 0045) et calcule le ton dessus (version 3).

- Seules les pages **https** dont l'hôte est celui d'un flux `central_bank` sont lues. 60 pages au plus par collecte, 4 minutes au plus ;
  l'arriéré se résorbe sur quelques passages. Un échec est retenté 3 fois, puis le ton se calcule sur le titre et le résumé.
- Fed : `<div id="article">` ; BoE, BCE, BRI, Banque du Canada : `<main>`. Pour un communiqué qui annonce les procès-verbaux du FOMC,
  la page `fomcminutesAAAAMMJJ.htm` est lue à sa place.
- Le ton n'existe que pour un texte qui parle de politique monétaire (au moins 3 mentions d'inflation, de taux, de « monetary policy »…
  dans un texte long) et qui contient au moins 2 expressions. Un discours sur la supervision bancaire n'a pas de ton : c'est voulu.
  Mesure du 2026-10-27 : 17 documents sur 152 ont un ton (le procès-verbal du FOMC de septembre : +0,86 ; la décision de septembre de la
  BoE : +0,40), contre 0 sur 79 avant.

## Réglages (`~/.patrick/settings.json`)

| Clé | Rôle |
|---|---|
| `news_extra_feeds` | Liste `{name, url, kind, language}` de flux supplémentaires (https uniquement ; `kind` = `news`, `central_bank` ou `commodity_report`). |
| `news_lm_dictionary` | Chemin du « Master Dictionary » Loughran-McDonald (CSV) : remplace le lexique réduit intégré. Non redistribué par PATRICK. |

### Brancher le dictionnaire Loughran-McDonald complet

Le fichier est distribué par ses auteurs (page « Loughran-McDonald Master Dictionary » du site SRAF de l'Université de Notre Dame) ;
il faut le télécharger soi-même et en respecter les conditions d'usage. Puis :

```bash
patrick news lexicon C:\chemin\vers\Loughran-McDonald_MasterDictionary.csv
```

La commande valide les colonnes (`Word`, `Negative`, `Positive`, `Uncertainty`, `Litigious`), enregistre le réglage, renote toutes les
nouvelles (la version du lexique change, donc les anciennes notes restent en base) et compare la couverture avec le lexique intégré.

## Flux par défaut

Fed (communiqués monétaires, discours), Banque d'Angleterre, BCE (communiqués, discours), Banque du Canada (communiqués), BRI (discours
de banquiers centraux), EIA (deux flux), FT Markets, BBC Business, CNBC Markets, MarketWatch.

Vérifiés le 2026-10-27 et **non disponibles** : OPEP (403 aux requêtes automatiques), AIE (aucun flux RSS officiel, 404 sur les URL
usuelles), USDA (`usda.gov` 403 ; `ams.usda.gov` répond mais ne publie que des formations et des événements), Banque du Japon (liens en
http, refusés par la règle https ; surtout des séries statistiques), GDELT (HTTP 429 persistant, y compris pour une requête isolée).
Les ajouter par `news_extra_feeds` quand une URL valide est connue.

**Certificat de la BCE (et de la SNB)** : Python s'appuie sur le magasin de certificats de Windows, qui n'y ajoute un certificat
intermédiaire qu'après qu'un programme Windows (navigateur, `curl.exe`) a validé la chaîne. Le 27/10, un `curl.exe` sur l'adresse de la BCE a
suffi : Python la lit depuis. Si une erreur « certificate verify failed » réapparaît sur un site légitime, ouvrir l'adresse du flux une fois
dans un navigateur. La vérification n'est jamais désactivée.

## Règles à retenir

- Une nouvelle est utilisable à partir de `max(publication annoncée, première observation)` ; après la clôture, elle compte pour la
  séance suivante ; une date sans heure est lue en fin de journée.
- Une nouvelle vue plus de 72 h après sa publication est stockée mais écartée des agrégats (un flux relu des mois plus tard n'est pas
  de l'actualité).
- La collecte n'écrit que dans les tables `news_*` de la base de suivi : ni cache de séries, ni data lake. Ne pas la lancer pendant une
  maintenance de la base (voir la règle « pas de maintenance DB pendant un run »).
- Les notes sont incrémentales et versionnées : lexique `builtin-fr-en-reduced-2`, ton `3`, rattachement `2`. Changer une version renote
  tout au passage suivant, les anciennes lignes restent.

## Historique requis avant l'entraînement

Aucune variable textuelle n'entre dans un entraînement tant que l'historique est trop court (`text/readiness.py`) : 250 séances ouvrées
entre la première et la dernière nouvelle utilisable, dont au moins 60 jours avec nouvelles. La page `/news` affiche l'avancement et
`patrick news readiness` donne la date au mieux (collecte quotidienne sans trou). Le seul point d'entrée prévu pour le pipeline est
`aggregate.training_features_for_symbol`, qui refuse (`NewsHistoryTooShort`) tant que la porte est fermée.

Le branchement dans `RunConfig` n'est pas fait, volontairement : ajouter un champ à `FeaturesConfig` change la clé du cache de variables
(plusieurs Go) et l'identité des runs existants. À faire avec un drapeau explicite, une fois la porte franchie, et à évaluer en walk-forward
avant d'activer par défaut.
