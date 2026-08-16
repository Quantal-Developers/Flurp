from datetime import date

from helpers import make_blank_pdf, make_pdf, upload


def test_health_endpoint(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "human-approved-prototype"}


def test_dashboard_serves_html(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_unknown_document_type_is_rejected(client) -> None:
    response = upload(client, document_type="10-K")
    assert response.status_code == 422
    assert "DRHP or RHP" in response.json()["detail"]


def test_non_pdf_filename_is_rejected(client) -> None:
    response = client.post(
        "/api/documents/upload",
        data={"issuer": "Acme Ltd", "document_type": "DRHP", "filing_date": date.today().isoformat()},
        files={"file": ("filing.txt", make_pdf(), "text/plain")},
    )
    assert response.status_code == 422
    assert "PDF filing is required" in response.json()["detail"]


def test_empty_file_is_rejected(client) -> None:
    response = upload(client, content=b"")
    assert response.status_code == 422
    assert "empty" in response.json()["detail"].lower()


def test_non_pdf_content_is_rejected(client) -> None:
    response = upload(client, content=b"this is definitely not a pdf")
    assert response.status_code == 422
    assert "not a readable PDF" in response.json()["detail"]


def test_corrupt_pdf_header_only_is_rejected(client) -> None:
    """Passes the cheap %PDF- header sniff but is not a structurally valid
    PDF, so PyMuPDF must reject it when actually parsing the stream."""
    response = upload(client, content=b"%PDF-1.4\ngarbage that is not a real xref table")
    assert response.status_code == 422
    assert "not a readable PDF" in response.json()["detail"]


def test_pdf_with_no_extractable_text_is_rejected(client) -> None:
    response = upload(client, content=make_blank_pdf())
    assert response.status_code == 422
    assert "no extractable text" in response.json()["detail"]


def test_issuer_below_minimum_length_is_rejected(client) -> None:
    response = upload(client, issuer="A")
    assert response.status_code == 422


def test_successful_upload_reports_page_count_and_hash(client) -> None:
    response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["page_count"] == 1
    assert len(body["sha256"]) == 64
    assert body["issuer"] == "Acme Ltd"
