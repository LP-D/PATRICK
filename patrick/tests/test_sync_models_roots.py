"""Où chercher les modèles à publier (constat du 2026-10-23 : le partage ne contenait que 34 modèles).

`trial.artifact_path` est RELATIF au dossier de travail du worker pour les modèles entraînés sur ce PC (`runs/<run>/<modèle>.joblib`,
sous le dossier du projet). La publication cherchait donc ces fichiers depuis le dossier de travail de SON processus : trouvés quand le
lanceur la démarre (il se place dans le dossier du projet), jamais quand la tâche planifiée `PATRICK-Sync` la démarre (Windows la place
dans `C:\\Windows\\System32` : aucun modèle relatif trouvé, 618 des 1 978 modèles de ce PC ignorés, `models.zip` réduit aux modèles
restaurés par une synchro)."""
from __future__ import annotations

from pathlib import Path

from patrick import sync


def test_relative_model_paths_resolve_whatever_the_working_directory(tmp_path, monkeypatch):
    project = tmp_path / "projet"
    model = project / "runs" / "GSPC_34" / "GSPC_34_best_model_h1.joblib"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"modele")
    system32 = tmp_path / "System32"                       # le dossier où Windows lance la tâche planifiée
    system32.mkdir()
    monkeypatch.setattr(sync, "_project_dir", lambda: project)
    monkeypatch.chdir(system32)

    found = sync._resolve_model("runs\\GSPC_34\\GSPC_34_best_model_h1.joblib", sync._default_models_roots())

    assert found == model


def test_the_project_folder_is_the_one_that_holds_the_patrick_package():
    project = sync._project_dir()

    assert (project / "patrick" / "sync.py").is_file() and Path(sync.__file__).resolve().parents[1] == project
