import pytest

from app.config import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("METRICS_ENDPOINT", raising=False)
    monkeypatch.delenv("COLLECTION_INTERVAL", raising=False)
    monkeypatch.delenv("REQUEST_TIMEOUT", raising=False)

    settings = Settings.from_env()

    assert settings.metrics_endpoint == "http://127.0.0.1:8000/metrics"
    assert settings.collection_interval == 5
    assert settings.request_timeout == 5


def test_settings_non_numeric(monkeypatch):
    monkeypatch.setenv("COLLECTION_INTERVAL", "abc")
    with pytest.raises(ValueError, match="numériques"):
        Settings.from_env()


def test_settings_negative(monkeypatch):
    monkeypatch.setenv("COLLECTION_INTERVAL", "-1")
    monkeypatch.setenv("REQUEST_TIMEOUT", "5")
    with pytest.raises(ValueError, match="> 0"):
        Settings.from_env()
