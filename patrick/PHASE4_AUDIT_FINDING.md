# Phase 4 -- Audit degradation en UI : constat de blocage (mismatch confirme)

Branche : `feature/degradation-badge` (HEAD au moment de l'audit :
`fbd354b32de01f9cad4d424ee96a7330d78b827f`, = HEAD de `main`).

## 1. Ce que fait reellement `patrick audit degradation`

Source : `patrick/patrick/audit.py` (module docstring, lignes 1-22) et
`patrick/patrick/cli.py::audit_degradation_cmd` (lignes 198-213).

- **Nature** : un rapport de correction ponctuel ("Correction report, C7"),
  pas un moniteur continu. Il mesure l'impact reel des correctifs de fuite
  de donnees de la Phase 0 (purge/embargo, alignement as-of par classe
  d'actif, vintages FRED/ALFRED) en comparant **4 configurations empilees
  et cumulatives** (`CONFIGURATIONS = ("baseline_avant", "+purge",
  "+vintages", "complet")`, `audit.py` ligne 45) sur le **meme** univers de
  cibles et le **meme** seed :
  > "The 4 configurations are CUMULATIVE (each adds one fix on top of the
  > previous one), not independent -- this isolates the marginal
  > contribution of each fix" (`audit.py`, lignes 11-13).
- **Univers fixe et restreint** : `DEFAULT_TARGETS` (`audit.py`, lignes
  52-68) contient exactement **5 cibles**, une par classe d'actif
  (`indice_us` = ^GSPC, `action_europe` = MC.PA, `paire_fx` = EURUSD=X,
  `matiere_premiere` = GC=F, `crypto` = BTC-USD) -- commentaire a la ligne
  49-51 : "One asset per class (Phase 0 concerns the whole yfinance/FRED
  surface, not a single market)". Ce n'est pas un echantillon de la
  production (68 tickers), c'est un jeu de test dedie a la validation de la
  correction.
- **Reseau reel obligatoire** : `run_degradation_audit()` appelle
  `run_pipeline(cfg, store=store, force_ingest=True, db_path=db_path)`
  (`audit.py` ligne 205) avec `force_ingest=True` explicitement pour
  eviter tout cache -- chaque config de chaque cible re-ingere en reseau
  (yfinance + FRED). Le docstring de `cli.py` (lignes 211-212) est
  explicite : "Runs the real pipeline (yfinance/FRED network access
  required)".
- **`FRED_API_KEY` obligatoire, echec explicite sinon** : `audit.py` lignes
  176-185 -- `run_degradation_audit` leve un `RuntimeError` immediat si la
  variable d'environnement `FRED_API_KEY_ENV` est absente, car sans elle la
  configuration `+vintages` n'a aucun sens (le fallback de scraping ne peut
  retourner que la revision courante d'une serie FRED, jamais une vraie
  vintage ALFRED point-in-time -- voir `_vintage_date_for_audit()`, lignes
  71-77, et `data/sources/fred_source.py`).
- **Sortie** : un CSV + un markdown (`_export`, lignes 153-170) avec une
  ligne par (cible, configuration) -- 5 cibles x 4 configs = 20 lignes --
  portant les colonnes `BalAcc_4cls`, `MCC_4cls`, `F1_dir` (`METRIC_COLUMNS`,
  ligne 47), plus `fred_source` et `n_evaluations`. Ce n'est PAS un score de
  "degradation" par (ticker, horizon) : c'est une comparaison de 3 metriques
  de performance entre 4 variantes de pipeline, pour les memes 5 cibles,
  a horizon fixe (`horizons=[5]`, `_config_for`, ligne 92).

## 2. Verdict : mismatch confirme entre la premisse de la Phase 4 et le code

Confirmation explicite, apres lecture complete de `audit.py` (211 lignes) et
de la commande CLI associee :

`patrick audit degradation` est un **outil de validation ponctuelle d'une
correction de fuite de donnees** (Phase 0), execute a la demande par un
humain qui dispose d'un acces reseau complet (yfinance + FRED) et d'une cle
`FRED_API_KEY`, sur un univers FIXE de 5 cibles choisies pour couvrir les
classes d'actifs -- **pas** un moniteur de derive de performance par
(ticker, horizon) exploitable en continu sur les 68 tickers de production.
Consequences concretes qui rendent un badge "degradation" par
ticker/horizon denue de sens produit ici :

1. **Pas de couverture de l'univers** : seulement 5 cibles sur 68 ont un
   resultat -- un badge sur les 63 autres ticker/horizon n'aurait aucune
   donnee source.
2. **Cout reseau a la demande** : `force_ingest=True` force une
   re-ingestion complete (yfinance + FRED) a chaque invocation, pour
   chacune des 4 configurations -- executer ceci pour alimenter une page
   web a chaque chargement (ou meme en tache de fond reguliere) serait
   couteux et lent, et echouerait purement et simplement sans
   `FRED_API_KEY`.
3. **Semantique differente** : le signal produit compare des variantes de
   pipeline (avec/sans purge, avec/sans vintages) sur les MEMES donnees et
   le MEME horizon, pas une evolution de la performance d'un modele de
   production dans le temps. Il n'y a pas de notion de "seuil ok/warning"
   par ticker/horizon a en tirer -- juste un delta baseline vs corrige,
   pour un usage de validation technique, pas de suivi produit continu.

**En consequence, conformement a la consigne, je m'arrete ici : pas de
badge "degradation" par ticker/horizon ajoute, pas de route web modifiee,
pas de nouveau composant `status_badge` pour cette notion.**

## 3. Piste alternative (signalee, non implementee)

Si un signal de "sante"/derive par (ticker, horizon) doit exister, les
candidats reels deja presents dans le code (lecture seule, deja peu
couteux, pas de reseau) sont, par ordre de pertinence :

- `patrick/patrick/tracking/holdout_diagnostic.py::spearman_test_vs_holdout`
  (lignes 44 et suivantes) : correlation de rang entre le classement des
  trials sur `test` et sur `holdout` pour un run donne -- un diagnostic de
  generalisation deja calcule et affiche en lecture seule sur
  `/runs/{run_id}` (via `tracking/history.py::run_detail`, ligne 261).
  Explicitement documente comme jamais utilise pour la selection de
  modele (isolation garantie par
  `tests/test_holdout_diagnostic_isolation.py`), donc un candidat "propre"
  pour un badge de risque de surapprentissage par run/cible.
- `patrick/patrick/tracking/history.py::target_detail` (lignes 295-337) :
  calcule deja `pbo_by_horizon` (probability of backtest overfitting, par
  horizon, walkforward ET cpcv) pour une cible donnee, a partir de l'
  historique de runs deja en base -- aucun appel reseau, deja utilise par
  `/targets/{ticker}`. Un vrai candidat "par (ticker, horizon)" a cout nul.
- `patrick/patrick/tracking/history.py::direction_metrics_by_target` /
  `latest_predictions_by_target` (lignes 450-637) : F1/precision/recall par
  direction pour le dernier run termine de chaque cible -- deja agrege pour
  `/` (synthesis) sans requete N+1, purement lecture de base.

Ces trois sources meriteraient une comparaison EXPLICITE dans le temps
(ex. `pbo_by_horizon` ou le F1 test/holdout du run le plus recent vs celui
d'il y a N runs pour la meme cible/horizon) pour constituer un vrai signal
de "derive" -- ce calcul n'existe pas encore tel quel dans le code. Piste
seulement, non implementee dans cette branche.

## 4. Statut final

- Etape 1 (audit) : **effectuee**, mismatch confirme, documente ci-dessus.
- Etape 2 (badge par ticker/horizon) : **non realisee**, bloquee par le
  constat de l'etape 1 (conformement a la consigne de la tache).
- Etape 3 (TDD + verification navigateur) : **non applicable**, aucune
  route/fonction d'exposition nouvelle n'a ete creee.
- Aucun fichier de code modifie. Seul ce document est ajoute.
- Branche : `feature/degradation-badge`, prete a review (commit de
  documentation du blocage uniquement).
