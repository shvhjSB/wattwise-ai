from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wattwise.api.main import create_app
from wattwise.api.public import READ_ONLY_DETAIL
from wattwise.core.config import Settings
from wattwise.public_demo import configure, database_url


def client(**settings: object) -> TestClient:
    return TestClient(create_app(Settings(environment="test", **settings)))  # type: ignore[arg-type]


def test_read_only_refuses_every_api_write_and_keeps_reads() -> None:
    with client(read_only=True) as api:
        for path in (
            "/api/v1/alerts/1/feedback",
            "/api/v1/data/upload",
            "/api/v1/inference/analyze",
        ):
            response = api.post(path, json={})
            assert response.status_code == 403
            assert response.json() == {"detail": READ_ONLY_DETAIL}
        assert api.put("/api/v1/alerts/1", json={}).status_code == 403
        health = api.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["read_only"] is True


def test_writes_are_untouched_when_not_read_only() -> None:
    with client() as api:
        assert api.get("/api/v1/health").json()["read_only"] is False
        # no database here: the write reaches its route, which is not a 403
        assert api.post("/api/v1/alerts/1/feedback", json={}).status_code != 403


@pytest.fixture
def site(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("outside", encoding="utf-8")
    return tmp_path


def test_the_frontend_is_served_on_the_same_origin(site: Path) -> None:
    with client(static_dir=site) as api:
        assert api.get("/").text == "<html>app</html>"
        assert api.get("/alerts").text == "<html>app</html>"  # the app's own routes
        assert api.get("/assets/app.js").text == "console.log(1)"
        assert api.get("/favicon.svg").text == "<svg/>"
        assert api.get("/assets/missing.js").status_code == 404
        assert api.get("/api/v1/health").json()["status"] == "ok"
        assert api.get("/api/v1/unknown").status_code == 404
        assert api.get("/api/v1/unknown").headers["content-type"] == "application/json"


def test_uptime_monitors_can_use_head_requests(site: Path) -> None:
    with client(static_dir=site, read_only=True) as api:
        assert api.head("/").status_code == 200
        assert api.head("/api/v1/health").status_code == 200


def test_files_outside_the_site_are_never_served(site: Path) -> None:
    with client(static_dir=site) as api:
        response = api.get("/..%2Fsecret.txt")
        assert "outside" not in response.text


def test_security_headers_are_added_when_serving_the_frontend(site: Path) -> None:
    with client(static_dir=site) as api:
        for path in ("/", "/api/v1/health"):
            headers = api.get(path).headers
            assert headers["x-content-type-options"] == "nosniff"
            assert headers["x-frame-options"] == "DENY"
            assert headers["referrer-policy"] == "no-referrer"


def test_a_site_without_index_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"index\.html"):
        create_app(Settings(environment="test", static_dir=tmp_path))


def test_the_platform_database_url_gets_the_psycopg_driver() -> None:
    assert database_url({"DATABASE_URL": "postgresql://u:p@h:5432/d"}) == (
        "postgresql+psycopg://u:p@h:5432/d"
    )
    assert database_url({"DATABASE_URL": "postgres://u:p@h/d"}) == "postgresql+psycopg://u:p@h/d"
    explicit = "postgresql+psycopg://a:b@c/d"
    assert database_url({"WATTWISE_DATABASE_URL": explicit, "DATABASE_URL": "postgresql://x"}) == (
        explicit
    )
    assert database_url({"DATABASE_URL": "mysql://u@h/d"}) is None


def test_configure_sets_the_public_demo_defaults() -> None:
    environ = {"DATABASE_URL": "postgresql://u:p@h/d"}

    configure(environ)

    assert environ["WATTWISE_DATABASE_URL"] == "postgresql+psycopg://u:p@h/d"
    assert environ["WATTWISE_READ_ONLY"] == "true"
    assert environ["WATTWISE_MODEL_DATA_KIND"] == "synthetic"
    with pytest.raises(ValueError, match="DATABASE_URL"):
        configure({})
