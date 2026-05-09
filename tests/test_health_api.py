def test_healthz_returns_ok_json():
    from app import app

    client = app.test_client()
    resp = client.get("/healthz")

    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("status") == "ok"
    for key in ("platform", "region", "env", "queue", "time"):
        assert key in data


def test_readyz_returns_readiness_payload():
    from app import app

    client = app.test_client()
    resp = client.get("/readyz")

    assert resp.status_code in (200, 503)
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("status") in ("ready", "degraded")
    assert isinstance(data.get("checks"), dict)

    for key in ("db", "tables", "migrations", "redis", "queue"):
        assert key in data["checks"]
