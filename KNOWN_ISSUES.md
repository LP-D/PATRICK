# KNOWN_ISSUES.md — Problèmes connus, hors scope des sessions en cours

Suivi des échecs pré-existants identifiés mais volontairement **non corrigés**
dans les sessions de traduction (D1-D6) et d'infrastructure (CI, commit
fréquent, nettoyage de branches) — hors mandat de ces sessions
(« aucune modification de logique fonctionnelle »). À traiter dans une
session de correction dédiée.

---

## 1. `test_data_quality.py::test_ingest_excludes_series_with_explicit_reason_and_persists`

**Symptôme** :
```
RuntimeError: [QUALITY] Insufficient history: data must go back at least 20
years (earliest observation 2018-01-01 < 2006-08-08).
```

**Cause identifiée** : la fixture utilise une date de début **absolue**
codée en dur (`2018-01-01`). Le contrôle qualité (`data/ingest.py:182`)
exige un historique remontant à au moins 20 ans avant la date système
courante. `2018-01-01` était valide tant que "aujourd'hui" restait avant
~2038, mais la logique de test elle-même compare à `pd.Timestamp.today()`
— une date absolue dans une fixture censée représenter "assez ancien"
est structurellement fragile face à l'écoulement du temps réel, pas
seulement face à ce seuil de 20 ans précis.

**Piste de correction déjà identifiée** : remplacer la date absolue par
une date **relative** à l'exécution du test (ex.
`pd.Timestamp.today() - pd.Timedelta(days=21*365)` ou équivalent), pour
que la fixture reste valide indéfiniment plutôt que de se dégrader avec
le temps qui passe.

---

## 2. `test_data_quality.py::test_data_quality_disabled_restores_pre_p6_5_behavior`

Même cause, même piste de correction que le point 1 ci-dessus — fixture
partageant la même date absolue `2018-01-01`.

---

## 3. `test_history_webapp_smoke.py::test_universe_page_renders`

**Symptôme** :
```
assert 'VIX' in resp.text
```
échoue — la page `/universe` rendue ne contient pas la chaîne `"VIX"`
attendue par le test.

**Cause** : **non identifiée** dans les sessions courantes — nécessite une
investigation dédiée (le test seed une base de données de test via
`_seed_db(tmp_path, monkeypatch)` puis vérifie le rendu HTML de la page
`/universe` ; la piste la plus probable est un décalage entre les données
seedées par le test et ce que `tracking/history.py::universe_overview`
attend réellement, mais ceci reste à vérifier, pas supposé ici).

---

## Contexte de découverte

Ces trois échecs sont apparus de façon répétée et cohérente tout au long
des sessions D1-D6 (traduction) et de mise en place de la CI — toujours
les mêmes trois, jamais de régression supplémentaire causée par les
changements de ces sessions (vérifié systématiquement via exécution
isolée et comparaison `git stash`/HEAD non modifié). Confirmés une
dernière fois par la CI elle-même (`.github/workflows/tests.yml`,
premier run réel sur PR #41) : `3 failed, 221 passed, 42 deselected`.

Tant qu'ils ne sont pas corrigés, **la CI de ce dépôt affichera rouge sur
chaque push/PR** — attendu, documenté, pas un signal à ignorer pour
autant : toute NOUVELLE régression doit apparaître comme un 4e échec (ou
un changement dans les 3 existants), pas se cacher dans le bruit.
