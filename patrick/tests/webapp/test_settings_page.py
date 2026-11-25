

def test_healthz_reports_schema_worker_and_a_server_older_than_its_database():
    """AM27 (25/11) : /healthz dit en quelques millisecondes si le serveur est plus ancien que la base (cause des blocs en 404)."""
    from fastapi.testclient import TestClient

    from patrick.tracking import db as trackdb
    from patrick.webapp.app import app

    client = TestClient(app)
    trackdb.connect().close()
    body = client.get("/healthz").json()
    assert body["ok"] is True and body["db_schema"] == body["code_schema"]
    assert body["server_too_old"] is False and body["migrations_pending"] is False and body["worker"]["alive"] is False
    conn = trackdb.connect()
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (body["code_schema"] + 1,))
    conn.commit()
    conn.close()
    assert client.get("/healthz").json()["server_too_old"] is True
