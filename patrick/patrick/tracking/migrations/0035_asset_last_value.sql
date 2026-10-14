-- Dernière valeur connue de chaque actif suivi (page /predictions) : le dernier cours vu par une actualisation live,
-- la date de la séance à laquelle il appartient, s'il s'agit de la clôture ou d'un cours en séance, et l'heure de la
-- mise à jour. Une ligne par cible, réécrite à chaque actualisation (jamais vers une séance plus ancienne).
CREATE TABLE IF NOT EXISTS asset_last_value (
    target       TEXT PRIMARY KEY,
    session_date TEXT NOT NULL,
    value        REAL NOT NULL,
    bar_final    INTEGER NOT NULL,
    updated_at   TEXT NOT NULL
);
