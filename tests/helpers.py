from datetime import date

import fitz


def make_pdf(text: str = "Jane Doe, Chief Financial Officer, holds 50000 shares.") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    content = doc.tobytes()
    doc.close()
    return content


def make_encrypted_pdf(user_pw: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Jane Doe, Chief Financial Officer, holds 50000 shares.")
    content = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw=user_pw)
    doc.close()
    return content


def make_blank_pdf() -> bytes:
    """A structurally valid PDF with a page but no text on it."""
    doc = fitz.open()
    doc.new_page()
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
    files = {"file": ("filing.pdf", content if content is not None else make_pdf(), "application/pdf")}
    return client.post("/api/documents/upload", data=data, files=files)


def add_lead(client, document_id, **overrides):
    payload = {
        "document_id": document_id,
        "name": "Jane Doe",
        "role": "Chief Financial Officer",
        "evidence_page": 1,
        "evidence_quote": "Jane Doe, Chief Financial Officer, holds 50000 shares.",
    }
    payload.update(overrides)
    return client.post("/api/leads", json=payload)
