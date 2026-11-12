import base64

import pytest

from app import create_app


def _auth(password):
    return {"Authorization": "Basic " + base64.b64encode(f"jay:{password}".encode()).decode()}


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "main.js").write_text("console.log(1)")
    return tmp_path


def test_serves_frontend_and_client_routes(dist, monkeypatch):
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    client = create_app().test_client()

    assert client.get("/").data == b"<html>app</html>"
    assert client.get("/god/sim_x").data == b"<html>app</html>"
    assert client.get("/assets/main.js").data == b"console.log(1)"
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/health").json["status"] == "ok"


def test_password_gate_protects_site_and_api(dist, monkeypatch):
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    client = create_app().test_client()

    assert client.get("/").status_code == 401
    assert "Basic" in client.get("/").headers["WWW-Authenticate"]
    assert client.get("/api/simulation/list").status_code == 401
    assert client.get("/", headers=_auth("wrong")).status_code == 401
    assert client.get("/", headers=_auth("s3cret")).data == b"<html>app</html>"
    assert client.get("/health").status_code == 200  # platform health checks stay open


def test_no_frontend_and_no_password_by_default(monkeypatch):
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    client = create_app().test_client()
    assert client.get("/").status_code == 404
    assert client.get("/health").status_code == 200
