# Feuille de route du 2026-10-20 : état au 2026-10-20

Spécification : [analyse-des-entrainements](../superpowers/specs/2026-10-20-analyse-des-entrainements-design.md). Trois statuts :
**fait** (livré dans ce chantier), **déjà présent** (existait, vérifié, lien donné), **reporté** (avec la raison). Rien ne touche le
pipeline d'entraînement : hachage de configuration, golden master et worker sont inchangés.

## Où voir quoi

| Page | Adresse | Contenu |
|---|---|---|
| Analyses | `/analyses` | tous les entraînements ML, DL, RL ; carte cible × horizon ; comparateur `/analyses/comparer` |
| Analyse d'un run | `/runs/{id}/analyse` | protocole, prédit contre réel, confusion, calibration, plis, stratégie, erreurs, régimes, variables, essais, robustesse, holdout et live, lecture guidée ; export HTML autonome |
| Garde-fous | `/garde-fous` | essais cumulés, Sharpe déflaté, lectures du holdout |
| Variables | `/variables` | usage des variables par run, par famille, par cible |
| Dérive | `/derive` | PSI par variable et Page-Hinkley sur les appels live |
| Journal | `/journal` | journal de prédictions chaîné (SHA-256), vérification, export |
| Registre de modèles | `/modeles` | versions par (cible, horizon), fiche modèle, promotion |
| Carnet | `/carnet` | hypothèses écrites avant un run, notes, décisions |
| Données | `/donnees` | data lake, vue point dans le temps, révisions, calendrier, listes de suivi, import |
| Risque | `/risque` | VaR/ES, contributions, crises, simulation marche avant, écarts à une cible |
| Diagnostics | `/diagnostics` | CPU, mémoire, disques, processus, base, dossiers, journaux |

## Bloc 1 : garde-fous transversaux

| Point | Statut | Où / pourquoi |
|---|---|---|
| Registre global d'exploration et budget | fait (vue) | table `trial_registry` déjà présente ; `/garde-fous` agrège essais cumulés, p-valeur déflatée (Šidák, n effectif = n / h) et verdict |
| Registre d'accès au holdout | fait (vue) | table `holdout_access` (migration 0038) déjà présente mais **vide** sur la base réelle : la page infère les lectures depuis les runs et duels et le dit |

## Bloc 2 : lancer sans coder

| Point | Statut | Où / pourquoi |
|---|---|---|
| Préréglages Rapide / Standard / Exhaustif | déjà présent | 16 profils dans `config/training_profiles.py` |
| File d'attente, pause, reprise, ordre, retrait | déjà présent | `/api/jobs/*`, `/api/queue/*` |
| Estimation de durée, anti-veille | déjà présent | `run_manager._estimated_remaining_s`, `keep_awake.py` |
| Divulgation progressive | déjà présent | mode simple / expert du poste de lancement |
| Notification de fin de run | fait | cloche de la barre supérieure (`run_notify.js`) ; opt-in ; notification du système si le navigateur l'autorise, bandeau dans la page sinon |
| Modèles de configuration versionnés et différences | fait en partie | les profils du poste de lancement gardent leurs 8 dernières versions et affichent les réglages modifiés à l'enregistrement et au chargement. Pas de menu de versions ni de restauration ; stockage dans le navigateur, donc non partagé entre PC |
| Point de reprise après arrêt brutal | reporté | demande une refonte du moteur du worker ; hors du périmètre « aucun changement du pipeline » |

## Bloc 3 : données

| Point | Statut | Où / pourquoi |
|---|---|---|
| Santé des données | déjà présent | `/data-quality`, `/data-freshness` |
| Import CSV et Excel | fait | `/donnees` → Importer ; aperçu, contrôles de qualité du dépôt, enregistrement sous `user_<nom>` (jamais une clé du pipeline). **Non branché** à un entraînement |
| Recherche de symbole Yahoo | fait | vérification en direct (cotation récente, historique suffisant), seul appel réseau de la page |
| Recherche de série FRED | reporté | demande une clé d'API et un appel réseau ; non testable hors ligne |
| Vue point dans le temps | fait | `/donnees` → Point dans le temps : colonne par colonne, ce qui était visible à une date |
| Révisions entre instantanés | fait | cellules réécrites, dont celles qui concernent des dates anciennes (fuite possible) |
| Listes de suivi et étiquettes | fait | migration 0042, `tracking/watchlists.py` |
| Calendrier des publications macro | fait (estimé) | règle de décalage du pipeline, pas un calendrier officiel |

## Bloc 4 : explorer et comprendre

| Point | Statut | Où / pourquoi |
|---|---|---|
| Explorateur de variables | fait | `/variables` |
| Comparateur de runs, matrice Diebold-Mariano | fait | `/analyses/comparer` (4 runs au plus) |
| Analyse d'erreurs | fait | section « Erreurs » (régime, calendrier, confiance) |
| Tests de robustesse | fait | section « Robustesse » (permutation, bootstrap par blocs, décalage) |
| Frise des régimes (HMM causal) | fait | section « Régimes » ; le HMM est ajusté avant le premier jour de test |
| Avance-retard entre séries | déjà présent, approfondi le 2026-10-24 | `/exploration` (corrélation croisée préblanchie, Granger robuste, matrice « qui mène qui », dépendance non linéaire) |
| « Explique ce résultat » | fait | « Lecture guidée » : texte déterministe produit à partir des métriques, sans modèle de langage, jamais de conseil |
| SHAP global, ablation par famille | reporté | exigent de ré-entraîner (2 entrées seulement en cache SHAP) : à lancer comme jobs |

## Bloc 5 : prédiction, suivi, modèles

| Point | Statut | Où / pourquoi |
|---|---|---|
| Journal de prédictions immuable | fait | migration 0040 ; déclencheurs SQL interdisant modification et suppression ; chaîne de hachage vérifiable |
| Moniteur de dérive | fait | `/derive` : PSI, Page-Hinkley (δ 0,05, λ 12, 30 appels indépendants au moins) |
| Registre de modèles et fiche modèle | fait | `/modeles` |
| Rapport exportable d'un run | fait | HTML autonome et CSV |

## Bloc 6 : portefeuille et patrimoine

| Point | Statut | Où / pourquoi |
|---|---|---|
| HRP, Black-Litterman | déjà présent | `tracking/hrp.py`, `tracking/black_litterman.py` |
| Multi-comptes | déjà présent | `/patrimoine` (réels et fictifs) |
| Tableau de risque, stress, contributions | fait | `/risque` |
| Simulation marche avant avec coûts et attribution | fait | quatre règles (poids égaux, inverse de la volatilité, HRP, poids actuels) |
| Écarts à une cible | fait | arithmétique, jamais une recommandation d'opération |
| Fiscalité | évitée | choix assumé : trop dépendante de la situation de chacun |

## Bloc 7 : cibles et modèles étendus

| Point | Statut | Où / pourquoi |
|---|---|---|
| Conformal, calibration en pli, méta-étiquetage | déjà présent | `validation/meta_labeling.py`, profil `calibration` |
| Barrière triple, différenciation fractionnaire | fait (désactivés) | `features/triple_barrier.py`, `features/fracdiff.py` ; testés ; **non branchés** à l'entraînement |
| Deep learning de diffusion, autres architectures | reporté | chantier de recherche, hors de la feuille de route exécutable |

## Bloc 8 : confort et plateforme

| Point | Statut | Où / pourquoi |
|---|---|---|
| Carnet de recherche | fait | `/carnet`, migration 0041 |
| Palette Ctrl + K, exports PNG / CSV / HTML | déjà présent / fait | palette existante ; exports dans les pages d'analyse |
| Diagnostics système | fait | `/diagnostics` |
| Sauvegarde | déjà présent | Réglages ; la restauration reste manuelle, par prudence |
| Vues enregistrées | reporté | faible valeur tant que les filtres tiennent dans l'adresse de la page |
| Constructeur déclaratif de variables | reporté | modifie le hachage de configuration et le golden master |
| Planificateur visuel | reporté | les tâches planifiées passent par Windows et les agents (`taches-planifiees-agents.md`) |

## Limites connues

- Le journal de prédictions et les listes de suivi ne sont **pas synchronisés** entre deux PC (la fusion de `partage-entre-pc.md` ne les connaît pas).
- Les migrations 0040, 0041 et 0042 s'appliquent au prochain démarrage de `patrick serve` : relancer le serveur après la fusion.
- Les rendements d'une analyse viennent du snapshot du run ; un run sans snapshot n'a pas les sections « rendements ».
- Les courbes d'apprentissage des réseaux de neurones ne sont pas conservées : seules les métriques finales le sont.
- `/risque` suppose des poids constants (rééquilibrage quotidien) pour le risque historique ; les cours ne sont pas ajustés des dividendes.
- Le calendrier des publications est estimé ; une série dont la valeur ne change pas (taux directeur) peut apparaître « figée » dans la vue point dans le temps.
- Un fichier importé n'est lu par aucun entraînement : l'enregistrer ne change aucun résultat.
