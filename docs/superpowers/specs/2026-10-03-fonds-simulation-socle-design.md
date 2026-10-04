# Refonte Simulation + page Fonds — chantier 1 : le socle

Date : 2026-10-03
Statut : conception validée oralement le 2026-10-03, **en attente de relecture écrite**

## 1. Objectif

Remplacer la page `/simulate` (rejeu de signaux d'un run) par un **ticket
d'ordres** : ouvrir des positions long/short sur des instruments financiers
classiques, à une date d'exécution choisie, rattachées à une **stratégie** (un
portefeuille avec capital, cash et enveloppe PEA ou CTO). Transformer la page
« Simulateur patrimoine » (`/patrimoine-simulation`) en page **Fonds**
(`/fonds`, EN : *LP Fund*) : toutes les stratégies, KPI de portefeuille,
modification et fermeture des positions.

C'est un bac à sable de papier-trading : aucun ordre réel, les prix sont ceux
du marché (historiques ou derniers connus), les frais sont saisis ou estimés.

## 2. Décisions prises

| Sujet | Décision |
|---|---|
| Découpage | Chantier 1 = socle (ce document). Chantier 2 = options et swaps de taux. Chantier 3 = modes systématiques (modèle ML avec seuils, carry trade). Chantier 4 = fiscalité (à confirmer par l'utilisateur). |
| Capital | Chaque stratégie a un capital de départ et un cash. Marge bloquée pour futures et CFD. Ordre refusé si cash ou marge insuffisants. |
| « Modifier » une position | Événements datés (renforcer, alléger, fermer, changer levier/stop/objectif) + bouton « corriger l'ordre initial ». Le passé ne change pas. |
| Ancien simulateur | Retiré tout de suite (pages et routes). Moteurs et tables conservés dans le code pour le chantier 3. |
| Futures | **Contrats à échéance précise** (ex. `ESZ26.CME`), pas la série continue `ES=F` (voir §6). |
| Frais estimés | Commission déterministe + coût de spread tiré d'une loi log-normale, tirage stocké avec l'ordre. |
| Position short | Interdite sur action/ETF (compte comptant). Possible sur future et CFD. |
| Enveloppes | PEA : long seulement, cotés en euro, ni futures ni CFD, cash ≥ 0, versements ≤ 150 000 €. CTO : tout permis, avec marge. Ordres interdits refusés. |

## 3. Périmètre

Dans le périmètre : stratégies, ordres (ouvrir/renforcer/alléger/fermer/
modifier), instruments action, ETF, future, CFD, prix, change, dividendes,
frais, règles d'enveloppe, valorisation quotidienne, KPI, pages Simulation et
Fonds, retrait de l'ancien simulateur.

Hors périmètre : options et swaps (chantier 2), modes automatiques
(chantier 3), fiscalité dont la taxe sur les transactions financières et la
retenue sur dividendes (chantier 4), versements ou retraits après la création,
roll automatique d'un future, liquidation automatique à 50 % de marge
(alerte seulement), benchmark, import d'ordres.

## 4. Architecture

Nouveau paquet `patrick/fund/`, sans dépendance vers `patrick/wealth/` sauf
pour deux utilitaires réutilisés tels quels : `wealth.symbols.yahoo_search`
(recherche de ticker) et les fonctions pures de `simulate.metrics`
(volatilité, Sharpe, drawdown).

| Fichier | Rôle |
|---|---|
| `fund/instruments.py` | Spécifications par type, catalogue de futures, plafonds de levier CFD, classes d'actifs. |
| `fund/prices.py` | Cotations OHLC, dividendes, change : téléchargement Yahoo + persistance dans `fund_price`. |
| `fund/fees.py` | Profils de frais, estimation log-normale reproductible. |
| `fund/rules.py` | Règles d'enveloppe et de marge : `check(...) -> (blocages, avertissements)`. |
| `fund/engine.py` | Rejeu des événements jour par jour : cash, positions, marge, valeur, P&L. Fonctions pures. |
| `fund/kpis.py` | KPI d'une stratégie à partir de la série de valeur. |
| `fund/service.py` | Agrégats pour les pages et l'API (une fonction par écran). |
| `fund/store.py` | Persistance des stratégies et des ordres ; validation de la création d'une stratégie. |
| `webapp/fund_routes.py` | Routes de pages et API, même motif que `wealth_routes.py`. |
| `templates/simulate.html` (réécrit), `templates/fonds.html` | Pages. |
| `static/simulate.js` (réécrit), `static/fonds.js` | Interactions et graphiques canvas. |
| `tracking/migrations/0029_fund.sql` | Tables. |

Le moteur est **piloté par les événements** : la position, le cash et la valeur
ne sont jamais stockés, toujours recalculés depuis les ordres (même principe
que `wealth/ledger.py`). Chaque type d'instrument implémente la même interface
(`valeur(jour)`, `marge(jour)`, `flux_cash(jour)`) pour que les chantiers 2 et
3 s'ajoutent sans toucher au moteur.

## 5. Modèle de données (migration 0029)

```sql
CREATE TABLE fund_strategy (
    strategy_id TEXT PRIMARY KEY,                 -- str_<hex10>
    name TEXT NOT NULL,
    wrapper TEXT NOT NULL CHECK (wrapper IN ('PEA', 'CTO')),
    base_currency TEXT NOT NULL DEFAULT 'EUR',    -- l'interface n'offre que EUR
    initial_capital REAL NOT NULL CHECK (initial_capital > 0),
    opened_on TEXT NOT NULL,                      -- date ISO
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE fund_order (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL REFERENCES fund_strategy(strategy_id) ON DELETE CASCADE,
    position_id TEXT NOT NULL,                    -- pos_<hex10>, commun à tous les ordres d'une position
    ts TEXT NOT NULL,                             -- date de bourse effective de l'exécution
    action TEXT NOT NULL CHECK (action IN ('open', 'increase', 'reduce', 'close', 'modify')),
    instrument_kind TEXT NOT NULL,                -- equity | etf | future | cfd (validé par le code : les chantiers 2-3 ajoutent des types sans reconstruire la table)
    symbol TEXT NOT NULL,                         -- ticker Yahoo
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    quantity REAL NOT NULL CHECK (quantity >= 0), -- actions, contrats ou unités de CFD de cet ordre ; 0 pour 'modify'
    price REAL,                                   -- dans la devise de l'instrument ; NULL pour 'modify'
    price_source TEXT CHECK (price_source IN ('market', 'manual')),
    currency TEXT NOT NULL,                       -- devise de l'instrument
    fx_rate REAL NOT NULL,                        -- devise de base par unité de devise de l'instrument, à la date
    fees REAL NOT NULL DEFAULT 0,                 -- en devise de base
    fees_source TEXT CHECK (fees_source IN ('manual', 'estimated')),
    fee_seed INTEGER,                             -- graine du tirage des frais estimés
    spec_json TEXT NOT NULL DEFAULT '{}',         -- composantes : multiplicateur, mois du contrat, levier, marge, stop, objectif
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_fund_order_strategy ON fund_order(strategy_id, ts, order_id);
CREATE INDEX idx_fund_order_position ON fund_order(position_id);

CREATE TABLE fund_price (
    symbol TEXT NOT NULL,
    day TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL NOT NULL DEFAULT 0,        -- volume moyen 20 jours : taille des frais estimés
    dividend REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, day)
);

CREATE TABLE fund_price_meta (              -- devise ISO du symbole et dernière actualisation (cache 6 h)
    symbol TEXT PRIMARY KEY,
    currency TEXT,
    refreshed_at TEXT
);
```

`fund_price` conserve **définitivement** les cotations utilisées : Yahoo
retire les contrats expirés, et la valeur d'une stratégie doit rester
calculable après l'échéance.

Un ordre « modify » ne change ni quantité ni prix : il remplace dans
`spec_json` le stop, l'objectif ou le levier à partir de sa date.

## 6. Prix et données de marché

Source unique : Yahoo Finance (`yfinance`), clôtures **non ajustées des
dividendes** (comme `wealth/prices.py`, pour ne pas compter deux fois le
dividende) mais ajustées des fractionnements.

- **Prix d'exécution** : clôture du jour d'exécution ; si ce jour n'est pas
  un jour de bourse, clôture du jour de bourse suivant (c'est ce jour qui est
  stocké dans `ts`). Pour aujourd'hui, dernier cours disponible. Date future
  refusée. L'utilisateur peut saisir le prix à la main (`price_source =
  'manual'`).
- **Rafraîchissement** : à chaque affichage d'une stratégie, les symboles
  détenus sont téléchargés si la dernière donnée stockée a plus de 6 heures,
  puis insérés dans `fund_price` (upsert). Si Yahoo ne répond pas, on valorise
  avec les données stockées et la page l'indique.
- **Change** : `{BASE}{DEVISE}=X` inversé (EURUSD=X donne des USD par EUR ;
  le taux utilisé est EUR par USD = 1 / cours). Les cours en pence (`GBp`)
  sont divisés par 100 et traités en GBP. Le dernier taux connu est reporté
  les jours sans cotation.
- **Futures** : un test sur Yahoo (2026-10-03) montre que les contrats
  *cotés aujourd'hui* ont une série propre (`ESZ26.CME` : 2 ans d'historique,
  prime de portage cohérente avec `ES=F`), alors que les contrats expirés ne
  renvoient plus rien (`ESZ25.CME`). Conséquences : (1) l'utilisateur choisit
  un **mois de contrat** parmi ceux cotés aujourd'hui, la position suit cette
  série et il n'y a **aucun saut de roll** à corriger ; (2) la date
  d'exécution est limitée à l'historique disponible du contrat (message
  explicite sinon) ; (3) à l'échéance la position est clôturée au dernier
  cours stocké.
- **Échéance d'un future** : calculée par règle propre à chaque produit
  (catalogue). Si la série stockée s'arrête avant, la dernière date stockée
  fait foi.
- **CFD** : le sous-jacent est une série Yahoo spot (indice `^GSPC`, paire
  `EURUSD=X`, action, crypto `BTC-EUR`). Un CFD sur un future continu (ex.
  `CL=F`) est accepté avec l'avertissement « série continue, sauts de roll non
  corrigés » (`price_quality` affiché sur la position).
- **Dividendes** : colonne `Dividends` de Yahoo, stockée dans `fund_price`.
  Crédités au cash à la date ex-dividende pour les positions longues sur
  action/ETF, au change du jour, sans retenue (chantier 4).

## 7. Instruments du chantier 1

Notations : `s = +1` long, `−1` short ; `n` quantité ; `p` prix ; `fx` taux de
change du jour ; `B` devise de base. Prix moyen d'entrée = moyenne pondérée
(méthode du PRU : prix de revient unitaire), tenue en devise de l'instrument
(`cout_local`) et en devise de base (`cout_base`) ; fx moyen d'entrée =
`cout_base / cout_local`.

**Action / ETF** (long seulement)
- Achat : `cash −= n·p·fx + frais`. Vente : `cash += n·p·fx − frais`, plus-value
  réalisée = produit − `PRU_base · n`.
- Valeur = `n · close · fx_jour`.
- Décomposition du P&L latent : effet prix = `n·(close − p_moy)·fx_moy` ;
  effet change = `n·close·(fx_jour − fx_moy)`. La somme égale `valeur − coût`.
- Composantes du ticket : quantité **ou** montant (le montant couvre les titres
  **et** les frais : « investir tout mon cash » ne dépasse jamais le cash ;
  quantité = montant arrondi
  à l'entier inférieur au prix du jour, fractions interdites).

**Future**
- Composantes : racine (catalogue), mois de contrat, sens, nombre de contrats,
  stop, objectif. Pas de décimales de contrat.
- Catalogue (`fund/instruments.py`) : par racine, bourse, devise, multiplicateur
  `M`, taille de tick, mois cotés, règle d'échéance, marge initiale indicative
  par contrat (devise du contrat), commission fixe par contrat et par sens.
  Entrées initiales : ES, NQ, YM, RTY (indices US), CL, NG (énergie), GC, SI, HG
  (métaux), ZC, ZW, ZS (grains), ZN (taux), 6E (change) et leurs versions micro
  quand Yahoo les sert. Chaque valeur de marge et de commission est renseignée
  avec sa source et sa date dans le fichier ; chaque entrée est vérifiée par un
  script de contrôle réseau (`scripts/check_fund_catalog.py`) avant livraison.
- À l'ouverture : aucun décaissement hormis les frais ; la marge initiale est
  **bloquée** dans le cash (elle n'en sort pas).
- Chaque jour : `variation = s·n·M·(close_j − close_{j−1})·fx_j` créditée ou
  débitée au cash. À l'ouverture, `close_{j−1}` est le prix d'exécution.
- Valeur de la position dans la NAV = 0 (tout est déjà dans le cash). P&L de la
  position = somme des variations − frais ; effet prix calculé au fx moyen
  d'entrée, effet change = reste.

**CFD**
- Composantes : sous-jacent, sens, taille (unités du sous-jacent), levier,
  stop, objectif.
- Plafond de levier pour un client non professionnel, selon la classe du
  sous-jacent (mesures ESMA sur les CFD, voir §15) : 30:1 paires de devises
  majeures ; 20:1 autres paires, or et indices majeurs ; 10:1 matières
  premières hors or et indices non majeurs ; 5:1 actions et autres ; 2:1
  cryptoactifs. La classe vient d'une table de correspondance (liste explicite
  des paires et indices majeurs) ; sous-jacent inconnu = classe « autres » (5:1).
- Notionnel = `n·p·fx`. Marge requise = `notionnel / levier`, bloquée.
- Valeur dans la NAV = P&L latent = `s·n·(close − p_moy)·fx_jour`. À la
  clôture le P&L réalisé entre dans le cash.
- Financement quotidien appliqué à chaque jour calendaire (week-ends
  inclus) : long, `−notionnel · (taux_ref + marge_fin) / 365` ; short,
  `+notionnel · (taux_ref − marge_fin) / 365` (peut être négatif). `taux_ref`
  = taux court de la devise du sous-jacent (€STR, SOFR, SONIA via FRED quand la
  clé FRED est configurée ; sinon constante documentée par devise, avec un
  avertissement affiché). Avec FRED, `taux_ref` est celui **en vigueur le jour
  financé** (historique quotidien depuis 2015 ; avant sa première observation,
  la première valeur connue), pas le taux actuel. `marge_fin` = 2,5 % par
  défaut (constante modifiable).
- Alerte, sans liquidation : jours où `NAV < 50 % de la marge requise`
  (règle de clôture automatique ESMA, simulée en alerte seulement).

**Stop et objectif** (futures et CFD seulement), évalués chaque jour de bourse
sur le plus bas et le plus haut : position longue, le stop est touché si
`low ≤ stop`, exécuté à `stop` (ou à l'ouverture du jour si elle est déjà
au-delà) ; l'objectif si `high ≥ objectif`, exécuté à `objectif` (ou à
l'ouverture si au-delà). Le short est symétrique. Stop et objectif touchés le
même jour : stop retenu (hypothèse prudente). La clôture déclenchée est
**calculée au rejeu** (pas stockée) ; ses frais sont estimés avec une graine
déduite de `position_id`. Une position clôturée par déclenchement n'accepte
plus d'ordre daté après le déclenchement.

## 8. Frais

Deux modes par ordre : **manuels** (montant en devise de base saisi) ou
**estimés** (`fees_source = 'estimated'`).

Frais estimés = commission + coût de spread + frais de change.
- Commission, déterministe, par profil dans `fund/fees.py` : action/ETF = max(1 €,
  0,05 % du montant) ; future = commission fixe du catalogue × contrats (un
  prix fixe par produit, par exemple le gaz naturel) ; CFD = aucune
  commission, coût porté par le spread.
- Coût de spread, aléatoire : `bps = médiane(classe) · exp(σ·Z) · facteur_taille`,
  `Z ~ N(0,1)`, `σ = 0,5`, appliqué au notionnel. Médianes indicatives en bps :
  grande capitalisation 2, moyenne 8, ETF 3, future 0,5 tick converti en bps,
  CFD indice 1, CFD paire majeure 0,8, CFD matière 4, CFD action 5, CFD
  crypto 30. `facteur_taille = 1 + min(5, 100·participation)` pour action/ETF,
  `participation = quantité / volume moyen 20 jours` ; `1 + min(2, notionnel / 1 M€)`
  pour future et CFD.
- Frais de change : 10 bps du montant converti, **pour les actions et ETF** dont la
  devise diffère de la base. Futures et CFD ne convertissent que leur P&L, pas leur
  notionnel : pas de frais de change (constaté avec de vraies cotations : sinon un
  contrat ES coûtait 341 € de frais).
- La graine (`fee_seed`) est dérivée de `strategy_id|position_id|ts|numéro` ;
  le tirage est fait à l'aperçu du ticket, la graine est renvoyée avec l'aperçu
  et réutilisée à la validation : **le montant affiché est celui qui est
  enregistré**.

Toutes ces valeurs sont des ordres de grandeur indicatifs, pas des mesures
sur un courtier réel ; elles vivent dans des constantes nommées d'un seul
fichier.

## 9. Enveloppes et règles (`fund/rules.py`)

Les règles sont évaluées en **rejouant toute la chronologie de la stratégie
avec l'ordre candidat** : un ordre antidaté est refusé s'il rend invalide un
événement postérieur.

Blocages communs : date antérieure à `opened_on` ou à l'ordre précédent de la
position ; position déjà clôturée (y compris par stop/objectif) ; quantité
supérieure à la position en réduction ; date future ; prix indisponible ;
liquidités disponibles négatives après l'ordre.

`liquidités disponibles = cash + P&L latent des CFD − marge requise`.

PEA, blocages : sens short ; type future ou CFD ; devise de l'instrument ≠ EUR ;
capital initial > 150 000 € (refusé à la création de la stratégie).
Avertissement : ticker sans suffixe de place UE/EEE (même liste que
`wealth/ledger.PEA_LIKELY_ELIGIBLE_SUFFIXES`).

CTO, blocages : short sur action ou ETF ; levier CFD supérieur au plafond de sa
classe ; marge insuffisante.

## 10. Valorisation et KPI

Série quotidienne (jours ouvrés, de `opened_on` à aujourd'hui ; les samedis et
dimanches s'y ajoutent quand un symbole de la stratégie cote ces jours-là,
cryptoactifs : un ordre du week-end est alors rejoué le jour même, et non le
lundi). Volatilité et Sharpe sont mesurés sur les clôtures de jours ouvrés
(annualisation sur 252 jours) :
`NAV = cash + valeur des actions/ETF + P&L latent des CFD`.
Identité comptable vérifiée par test : `NAV − capital initial = Σ P&L des
positions (réalisé + latent) + dividendes − frais − financement`.

KPI d'une stratégie : NAV ; capital ; P&L total en € et en % du capital, dont
réalisé et latent ; frais cumulés ; dividendes ; financement CFD ; rendement
pondéré par le temps (TWR : pas de flux externes au chantier 1, il égale donc
le rendement sur capital) ; volatilité annualisée ; ratio de Sharpe ;
drawdown maximum ; exposition brute et nette (% de la NAV) ; levier brut ;
marge utilisée et liquidités disponibles ; nombre de positions ouvertes.

Par position : devise d'origine, fx d'ouverture et fx actuel, prix moyen
d'entrée, cours actuel, valeur en devise de base, P&L total en € et en %
(sur le coût, ou sur la marge pour future/CFD), effet prix et effet change,
marge, stop, objectif, statut (ouverte, fermée, clôturée par stop/objectif/
échéance), `price_quality`.

Fonds (page Fonds, en-tête) : NAV totale des stratégies non archivées, capital
total, P&L total en € et en %, répartition par stratégie.

## 11. API

| Route | Rôle |
|---|---|
| `GET /simulate`, `GET /fonds` | Pages. |
| `GET /patrimoine-simulation` | Redirection permanente vers `/fonds`. |
| `POST /api/fund/strategies`, `PATCH …/{id}` (renommer, archiver), `DELETE …/{id}` | Cycle de vie des stratégies. |
| `GET /api/fund/instruments/search?q=&kind=` | Recherche de ticker (action, ETF, CFD) ; `GET /api/fund/futures/catalog`, `GET /api/fund/futures/{racine}/contracts` (mois cotés). |
| `POST /api/fund/quote` | Aperçu : prix, change, notionnel, marge, frais estimés (+ graine), règles violées. N'écrit rien. |
| `POST /api/fund/strategies/{id}/orders` | Ouvrir, renforcer, alléger, fermer, modifier. Revalide toute la chronologie. |
| `PATCH /api/fund/orders/{id}` | Corriger l'ordre d'ouverture (revalidation complète). |
| `DELETE /api/fund/positions/{id}` | Supprimer une position entière. |
| `GET /api/fund/strategies/{id}/panel` | Fragment HTML (rendu serveur, échappé) du détail d'une stratégie pour `/fonds`. |
| `GET /api/fund/strategies/{id}/detail` | KPI, série de NAV, positions, ordres. |
| `GET /api/fund/overview` | Portefeuilles par stratégie + total du fonds. |

Les erreurs de règle renvoient 422 avec la liste des blocages en français ; une
saisie mal formée (date illisible, champ du mauvais type, année de contrat
absente…) renvoie 400, jamais 500. Les écritures exigent
`Content-Type: application/json` (415 sinon : un POST « simple » d'un autre site
ne peut rien écrire). L'identifiant d'une nouvelle position, proposé par
l'aperçu, a la forme `pos_` + 10 caractères hexadécimaux et ne peut pas déjà
servir (dans aucune stratégie) : `DELETE /api/fund/positions/{id}` vise donc
une seule position.

## 12. Pages

**Simulation** (`/simulate`).
1. Ticket : stratégie (avec « Nouvelle stratégie » en ligne : nom, enveloppe,
   capital, date d'ouverture) → type d'instrument (Action/ETF, Future, CFD) →
   recherche du ticker (ou racine + mois de contrat pour un future) → sens →
   taille → composantes propres au type (levier plafonné avec sa classe
   affichée, stop, objectif) → date d'exécution → prix (auto, ou saisi) → frais
   (estimés ou manuels). Un panneau d'aperçu se met à jour en direct
   (`/api/fund/quote`) : prix, change, notionnel en devise d'origine et en EUR,
   marge, frais, liquidités restantes, blocages (rouge) et avertissements
   (ambre). Le bouton « Ouvrir la position » est inactif tant qu'un blocage
   subsiste.
2. En dessous : une carte par stratégie (nom, enveloppe, NAV, cash, P&L en € et
   en %, nombre de positions, mini-courbe de NAV, lien vers Fonds).

**Fonds** (`/fonds`).
1. En-tête : total du fonds.
2. Tableau des stratégies (même colonnes que les cartes + exposition et
   levier) ; un clic ouvre le panneau de détail sous le tableau.
3. Panneau : grille de KPI ; graphique NAV contre capital ; tableau des
   positions avec boutons *Ajuster* (formulaire en ligne : renforcer, alléger,
   fermer, modifier levier/stop/objectif, avec date, prix et frais), *Corriger*
   (ordre d'ouverture) et *Supprimer* ; positions fermées avec P&L réalisé ;
   historique des ordres repliable. L'ajout d'une nouvelle position ne se fait
   pas ici : lien vers Simulation.

Interface : charte `design-system/patrick/MASTER.md`, mise en page serveur
(Jinja) et graphiques canvas comme `wealth.js`. Toutes les chaînes passent par
`i18n.STRINGS` en français et en anglais ; clé `nav_fonds` : FR « Fonds », EN
« LP Fund ».

## 13. Retraits

- Page `/simulate` actuelle, `templates/simulate.html`, `static/simulate.js`
  (réécrits pour le ticket), routes `POST /api/simulate` et
  `GET /api/simulate/{id}`.
- `templates/patrimoine_simulation.html`, route `POST
  /api/wealth/accounts/{id}/replay`, bloc « patrimoine replay » de
  `static/wealth.js`.
- Entrée de navigation `patrimoine_simulation` remplacée par `fonds` (`/fonds`)
  dans `nav_registry.py` ; `/simulate` garde son entrée.
- Conservés sans page : `simulate/engine.py`, `simulate/metrics.py`,
  `wealth/signal_replay.py`, table `simulation`, leurs tests unitaires
  (réutilisés au chantier 3). Les tests des pages et routes retirées
  (`test_simulate_webapp.py`, tests de l'API de rejeu dans `test_wealth_webapp.py`,
  entrées de `test_nav_registry.py`) sont remplacés par les nouveaux.

## 14. Tests

- **Moteur**, cas calculés à la main : long action en USD avec variation de
  change (effet prix et effet change séparés) ; renforcement puis allègement
  (PRU et plus-value) ; short future avec variations quotidiennes ; CFD avec
  financement en week-end ; stop touché sur gap à l'ouverture ; échéance de
  future avec série expirée relue depuis `fund_price`.
- **Identité comptable** : `NAV − capital = Σ P&L + dividendes − frais −
  financement` sur des historiques générés aléatoirement (test de propriété).
- **Frais** : même graine, même montant ; le montant de l'aperçu est celui
  enregistré ; mode manuel prioritaire.
- **Règles** : chaque blocage PEA et CTO ; ordre antidaté invalidant un
  événement postérieur ; plafond de levier par classe.
- **Prix** : insertion et relecture de `fund_price`, repli hors ligne, jour
  non ouvré décalé au jour suivant, dividende crédité à l'ex-date, `GBp`.
- **Routes** : création de stratégie, aperçu, ordre refusé en 422, ordre
  accepté, correction, suppression, détail ; redirection
  `/patrimoine-simulation`.
- **Navigation** : `test_nav_registry` à jour (entrée `fonds`, redirection
  déclarée dans `NON_PAGE_ROUTES`).
- Le réseau est simulé dans tous les tests ; `scripts/check_fund_catalog.py`
  est un contrôle manuel, hors CI.

## 15. Risques et points à vérifier

1. **Historique des futures limité** : Yahoo ne sert que les contrats cotés
   et environ 2 ans de recul ; un ordre antidaté sur un contrat sans données
   à cette date est refusé. Atténuation : persistance dans `fund_price`.
2. **Marges, commissions et spreads indicatifs** : les marges CME changent ;
   chaque valeur du catalogue est datée et sourcée, à revoir périodiquement.
3. **Plafonds de levier ESMA** : valeurs confirmées sur la page de l'ESMA
   (mesures d'intervention sur les CFD, 2018) ; la table de correspondance
   classe d'actif ↔ plafond est écrite à la main et à relire par
   l'utilisateur.
4. **CFD sur futures continus** : sauts de roll non corrigés, signalés par un
   avertissement.
5. **Cours du jour** : un cours intraday peut être pris pour « aujourd'hui » ;
   il est signalé comme provisoire.
6. **Qualité des dividendes Yahoo** : irrégulière sur certains titres ; pas
   de retenue à la source avant le chantier 4.
7. **Mise en œuvre isolée** : l'arbre de travail principal contient des
   modifications non commitées d'un autre chantier (contrôles de runs :
   `app.py`, `i18n.py`, `jobs.py`…). Le plan prévoit un worktree git dédié pour
   ne pas les mêler.

## 16. Suite

- Chantier 2 : options (call/put : style, strike, échéance ; prix estimé par
  Black-Scholes, formule standard de prix d'option, avec volatilité
  historique ; grecques) et swaps de taux (nominal, taux fixe, maturité ;
  courbe FRED ; sensibilité DV01).
- Chantier 3 : modes systématiques (modèle ML avec seuils saisis, carry
  trade) qui génèrent des ordres automatiquement ; réutilise
  `simulate.engine` et `wealth.signal_replay`.
- Chantier 4 : fiscalité (flat tax, PEA après 5 ans, taxe sur les transactions
  financières, retenue sur dividendes) si l'utilisateur la confirme.
