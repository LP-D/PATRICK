-- Journal de prédictions fusionné entre PC (2026-11-02, ADR 0015). Chaque PC a SA chaîne d'empreintes (`prev_hash` / `entry_hash`) : l'union de deux chaînes ne se
-- vérifie plus comme une seule. Les lignes venues d'un autre PC sont donc recopiées TELLES QUELLES (empreintes et `trial_id` compris : ils sont dans la charge utile
-- hachée) et marquées ici ; `NULL` = produite sur ce PC. Les lignes locales gardent leur chaîne, que les écritures suivantes prolongent ; les lignes importées se
-- vérifient chacune contre l'empreinte précédente qu'elles annoncent. Un `trial_id` importé désigne un essai de l'AUTRE base : toute lecture par `trial_id` filtre sur `NULL`.
ALTER TABLE prediction_journal ADD COLUMN imported_from TEXT;
