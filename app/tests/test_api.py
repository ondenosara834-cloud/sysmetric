from fastapi.testclient import TestClient

from app import api

client = TestClient(api.app)


def setup_function():
    # Repartir d'une liste vide avant chaque test
    api.received_metrics.clear()


def valid_payload():
    return {
        "agent": "system-metrics-agent",
        "event_type": "system_metrics",
        "data": {"hostname": "test-host", "cpu": {"percent": 10.0}},
    }


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_latest_metrics_empty_returns_404():
    response = client.get("/metrics/latest")
    assert response.status_code == 404


def test_post_then_get_metrics():
    response = client.post("/metrics", json=valid_payload())
    assert response.status_code == 201
    assert response.json()["total_received"] == 1

    latest = client.get("/metrics/latest").json()
    assert latest["agent"] == "system-metrics-agent"
    assert "received_at" in latest

    all_metrics = client.get("/metrics").json()
    assert all_metrics["total"] == 1


def test_post_invalid_payload_returns_422():
    # agent vide : refusé par la validation Pydantic (min_length=1)
    payload = valid_payload()
    payload["agent"] = ""
    response = client.post("/metrics", json=payload)
    assert response.status_code == 422
