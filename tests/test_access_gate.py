import pytest
from werkzeug.security import generate_password_hash
from flask import Flask
from access_gate import COOKIE, install_access_gate
from usage_limits import UsageStore


@pytest.fixture
def gated(tmp_path):
    app = Flask(__name__, template_folder="../templates")
    app.config.update(ACCESS_GATE_ENABLED=True, SITE_PASSWORD_HASH=generate_password_hash("test-pass"), TESTING=True)
    store = UsageStore(tmp_path / "usage.sqlite3")
    install_access_gate(app, store, lambda: "127.0.0.1")
    app.add_url_rule("/", endpoint="home", view_func=lambda: "private home")
    app.add_url_rule("/chat", endpoint="chat", view_func=lambda: "private chat", methods=["POST"])
    return app, app.test_client(), store


def test_blocks_pages_assets_and_api(gated):
    _, client, _ = gated
    for path in ["/", "/index.html", "/crest.png", "/campus-map.html"]:
        response = client.get(path)
        assert response.status_code == 303
        assert response.location == "/login"
        assert "no-store" in response.headers["Cache-Control"]
    assert client.post("/chat").status_code == 401
    assert client.get("/api/upcoming-events").status_code == 401


def test_login_failure_success_logout(gated):
    _, client, _ = gated
    assert client.get("/login").status_code == 200
    assert client.post("/login", data={"password": "wrong"}).status_code == 401
    response = client.post("/login", data={"password": "test-pass"}, base_url="https://localhost")
    assert response.status_code == 303
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie
    assert client.get("/", base_url="https://localhost").data == b"private home"
    assert client.post("/chat", base_url="https://localhost").status_code == 200
    client.post("/logout", base_url="https://localhost")
    assert client.get("/", base_url="https://localhost").status_code == 303


def test_tampering_expiry_and_password_rotation(gated, monkeypatch):
    app, client, store = gated
    client.set_cookie(COOKIE, "forged")
    assert client.get("/").status_code == 303
    client.post("/login", data={"password": "test-pass"})
    import itsdangerous.timed
    with monkeypatch.context() as patch:
        patch.setattr(itsdangerous.timed.time, "time", lambda: 4000000000)
        assert client.get("/").status_code == 303
    app.config["SITE_PASSWORD_HASH"] = generate_password_hash("changed")
    assert client.get("/").status_code == 303


def test_attempt_limit_is_shared_and_missing_config_fails_closed(gated):
    app, client, store = gated
    for _ in range(10):
        assert client.post("/login", data={"password": "wrong"}).status_code == 401
    response = app.test_client().post("/login", data={"password": "test-pass"})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    app.config["SITE_PASSWORD_HASH"] = ""
    assert client.get("/").status_code == 503


def test_cross_origin_login_rejected(gated):
    _, client, _ = gated
    assert client.post("/login", data={"password": "test-pass"}, headers={"Origin": "https://other.example"}).status_code == 403
