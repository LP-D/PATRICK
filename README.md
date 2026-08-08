# PATRICK — Plateforme

PATRICK est une plateforme de recherche et d'exécution pour pipelines de données et modèles ML.
Elle regroupe :

- notebooks reproductibles (Colab / local) pour exploration et validation ;
- un package Python autonome (patrick/) pour exécuter pipelines, trainer des modèles et déployer ;
- une interface web légère pour visualiser résultats et rapports.

Ressources principales

- Documentation et notes : ./docs/
- Code et CLI : ./patrick/
- Notebooks reproductibles : ./notebooks/

Démarrage rapide

1. Lire patrick/README.md pour installer les dépendances et la CLI.
2. Ouvrir les notebooks depuis ./notebooks/ (ou via les liens dans docs/).

Politique de résultats

Les sorties expérimentales lourdes (CSV/XLSX, artefacts) doivent être poussées sur des branches
`results/<nom>` et ne sont pas destinées à être mergées dans `main`.

Contribuer

Fork, branchez-vous, puis ouvrez une PR. Pour des résultats expérimentaux, préférez des branches
`results/*` dédiées. Voir docs/ pour guides et méthodologie.

Licence & contact

Voir patrick/README.md et patrick/PRODUCT.md pour détails produits, licences et contact.

---

(Ce README a été mis à jour pour présenter PATRICK comme une plateforme unifiée.)
