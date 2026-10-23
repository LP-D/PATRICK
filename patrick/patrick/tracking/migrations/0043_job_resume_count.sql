-- Reprise automatique des jobs interrompus (2026-10-23) : un job laissé « en cours » par un worker disparu (PC éteint, plantage) est remis
-- en file au lieu d'être marqué en erreur. `resume_count` = nombre de reprises déjà faites ; au-delà de `tracking/jobs.MAX_AUTO_RESUMES` le job
-- passe en erreur (un job qui fait planter le worker à chaque fois ne doit pas boucler indéfiniment).
ALTER TABLE job ADD COLUMN resume_count INTEGER NOT NULL DEFAULT 0;
