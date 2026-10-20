-- Manifeste de lancement d'un run (audit externe du 2026-10-19) : plateforme (système, processeur, BLAS, instructions SIMD),
-- empreinte de l'environnement installé et du fichier de contraintes. Le SHA git, la graine, l'empreinte de configuration, les
-- versions de bibliothèques et l'empreinte des données (snapshot) sont déjà des colonnes ; `tracking/manifest.py` rassemble
-- le tout. NULL pour un run d'avant : le manifeste le dit au lieu de deviner.
ALTER TABLE run ADD COLUMN manifest_json TEXT;
