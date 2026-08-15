from datetime import date, timedelta

import fitz
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


def make_pdf(text: str = "Jane Doe, Chief Financial Officer, holds 50000 shares.") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    content = doc.tobytes()
    doc.close()
    return content


def upload(client, content: bytes | None = None, **overrides):
    data = {
        "issuer": "Acme Ltd",
        "document_type": "DRHP",
        "filing_date": date.today().isoformat(),
    }
    data.update(overrides)
    files = {"file": ("filing.pdf", content or make_pdf(), "application/pdf")}
    return client.post("/api/documents/upload", data=data, files=files)


def add_lead(client, document_id):
    return client.post(
        "/api/leads",
        json={
            "document_id": document_id,
            "name": "Jane Doe",
            "role": "Chief Financial Officer",
            "evidence_page": 1,
            "evidence_quote": "Jane Doe, Chief Financial Officer, holds 50000 shares.",
        },
    ).json()


def test_document_list_excludes_internal_fields(client) -> None:
    upload(client)
    doc = client.get("/api/documents").json()[0]
    assert "stored_path" not in doc
    assert "extracted_text" not in doc


def test_duplicate_upload_is_rejected(client) -> None:
    content = make_pdf()
    assert upload(client, content=content).status_code == 201
    assert upload(client, content=content).status_code == 409


def test_future_filing_date_is_rejected(client) -> None:
    future = (date.today() + timedelta(days=1)).isoformat()
    assert upload(client, filing_date=future).status_code == 422


def test_oversized_upload_is_rejected(client, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 10)
    response = upload(client)
    assert response.status_code == 422
    assert "MB upload limit" in response.json()["detail"]


def test_outreach_cannot_leave_a_terminal_state(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"])
    outreach = client.post(
        f"/api/leads/{lead['id']}/outreach",
        json={"message": "Hello, congratulations on the upcoming listing!"},
    ).json()

    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "opted_out"}).status_code == 200
    reapprove = client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "approved"})
    assert reapprove.status_code == 409
    resend = client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "sent"})
    assert resend.status_code == 409


def test_outreach_requires_approval_before_send(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"])
    outreach = client.post(
        f"/api/leads/{lead['id']}/outreach",
        json={"message": "Hello, congratulations on the upcoming listing!"},
    ).json()

    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "sent"}).status_code == 409
    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "approved"}).status_code == 200
    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "sent"}).status_code == 200
