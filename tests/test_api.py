from contextlib import closing
from datetime import date, timedelta

import app as app_module
from helpers import add_lead, make_encrypted_pdf, make_pdf, upload


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


def test_password_required_pdf_is_rejected(client) -> None:
    response = upload(client, content=make_encrypted_pdf(user_pw="secret"))
    assert response.status_code == 422
    assert "encrypted" in response.json()["detail"].lower()


def test_owner_password_only_pdf_is_rejected(client) -> None:
    """PyMuPDF auto-authenticates a PDF with an empty user password (e.g. an
    owner-password-only file) and then reports is_encrypted=False -- the
    check must use a persistent indicator (needs_pass/metadata) instead, or
    this file would be silently accepted."""
    response = upload(client, content=make_encrypted_pdf(user_pw=""))
    assert response.status_code == 422
    assert "encrypted" in response.json()["detail"].lower()


def test_oversized_upload_is_rejected_before_reaching_the_handler(client, monkeypatch) -> None:
    """The Content-Length-declared body size must be rejected by the ASGI
    middleware -- before Starlette's multipart parser spools it to disk --
    not merely by the handler re-reading an already-buffered upload."""
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 10)
    response = upload(client)
    assert response.status_code == 413
    assert "MB limit" in response.json()["detail"]


def test_streamed_upload_without_content_length_is_cut_off(client, monkeypatch) -> None:
    """A request with no Content-Length header (chunked transfer, or a client
    that lies about the header) must still be rejected once the ASGI layer's
    running byte count crosses the limit -- not just the declared-size case."""
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 200)
    boundary = "X"
    preamble = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="issuer"\r\n\r\nAcme\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="document_type"\r\n\r\nDRHP\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="filing_date"\r\n\r\n2026-08-01\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "%PDF-1.4\n"
    ).encode()

    def body_chunks():
        yield preamble
        for _ in range(10):  # far more than the 200-byte cap once combined with the preamble
            yield b"A" * 100

    response = client.post(
        "/api/documents/upload",
        content=body_chunks(),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )
    assert "content-length" not in {k.lower() for k in response.request.headers.keys()}
    assert response.status_code == 413
    assert "MB limit" in response.json()["detail"]


def test_outreach_cannot_leave_a_terminal_state(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()
    outreach = client.post(
        f"/api/leads/{lead['id']}/outreach",
        json={"message": "Hello, congratulations on the upcoming listing!"},
    ).json()

    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "opted_out"}).status_code == 200
    reapprove = client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "approved"})
    assert reapprove.status_code == 409
    resend = client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "sent"})
    assert resend.status_code == 409


def test_outreach_state_change_is_atomic_under_a_race(client, monkeypatch) -> None:
    """A rival write that commits between this request's SELECT and its own
    UPDATE must make the request's own write a no-op (409), not a silent
    overwrite -- the conditional UPDATE's WHERE id = ? AND state = ? must
    reject a stale write instead of blindly applying it."""
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()
    outreach = client.post(
        f"/api/leads/{lead['id']}/outreach",
        json={"message": "Hello, congratulations on the upcoming listing!"},
    ).json()
    outreach_id = outreach["id"]

    real_connection = app_module.connection
    raced = False

    def inject_race() -> None:
        nonlocal raced
        if raced:
            return
        raced = True
        with closing(real_connection()) as rival:
            rival.execute(
                "UPDATE outreach SET state = ?, state_note = ?, updated_at = ? WHERE id = ? AND state = ?",
                ("opted_out", "raced ahead", app_module.utc_now(), outreach_id, "draft"),
            )
            rival.commit()

    class RacingConnection:
        """Wraps a real connection so the first "UPDATE outreach" call races
        a rival write in underneath it, simulating a concurrent request that
        commits between this request's SELECT and its own UPDATE."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args):
            if sql.startswith("UPDATE outreach"):
                inject_race()
            return self._real.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._real, name)

    monkeypatch.setattr(app_module, "connection", lambda: RacingConnection(real_connection()))
    response = client.patch(f"/api/outreach/{outreach_id}/state", json={"state": "approved"})
    assert response.status_code == 409

    with closing(real_connection()) as db:
        final_state = db.execute("SELECT state FROM outreach WHERE id = ?", (outreach_id,)).fetchone()["state"]
    assert final_state == "opted_out"  # the rival's write persisted; ours was correctly rejected, not applied on top


def test_outreach_requires_approval_before_send(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()
    outreach = client.post(
        f"/api/leads/{lead['id']}/outreach",
        json={"message": "Hello, congratulations on the upcoming listing!"},
    ).json()

    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "sent"}).status_code == 409
    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "approved"}).status_code == 200
    assert client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "sent"}).status_code == 200
