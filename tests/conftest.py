import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATABASE_PATH", tmp_path / "flurp.db")
    monkeypatch.setattr(app_module, "UPLOAD_DIRECTORY", tmp_path / "uploads")
    with TestClient(app) as test_client:
        yield test_client
