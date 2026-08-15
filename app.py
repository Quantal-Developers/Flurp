"""Flurp V1: an evidence-first pre-IPO executive research prototype.

Run locally with: ``uvicorn app:app --reload``.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import fitz
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATABASE_PATH = Path(os.getenv("FLURP_DATABASE_PATH", "data/flurp.db"))
UPLOAD_DIRECTORY = Path("uploads")
DOCUMENT_TYPES = {"DRHP", "RHP"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
PDF_HEADER = b"%PDF-"
PDF_HEADER_SCAN_WINDOW = 1024

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    return db


def initialise_database() -> None:
    with closing(connection()) as db:
        db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS source_documents (
                id TEXT PRIMARY KEY,
                issuer TEXT NOT NULL,
                document_type TEXT NOT NULL CHECK(document_type IN ('DRHP', 'RHP')),
                filing_date TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                page_count INTEGER NOT NULL,
                extracted_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE RESTRICT,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                disclosed_shares INTEGER,
                price_per_share REAL,
                price_label TEXT,
                evidence_page INTEGER NOT NULL CHECK(evidence_page > 0),
                evidence_quote TEXT NOT NULL,
                match_confidence REAL CHECK(match_confidence >= 0 AND match_confidence <= 1),
                email TEXT,
                linkedin_url TEXT,
                enrichment_evidence TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outreach (
                id TEXT PRIMARY KEY,
                lead_id TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('draft', 'approved', 'sent', 'replied', 'bounced', 'opted_out')),
                state_note TEXT,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialise_database()
    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Flurp V1", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class LeadCreate(BaseModel):
    document_id: str
    name: str = Field(min_length=2, max_length=160)
    role: str = Field(min_length=2, max_length=160)
    disclosed_shares: int | None = Field(default=None, ge=0)
    price_per_share: float | None = Field(default=None, ge=0)
    price_label: str | None = Field(default=None, max_length=80)
    evidence_page: int = Field(ge=1)
    evidence_quote: str = Field(min_length=10, max_length=2000)


class EnrichmentReview(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    linkedin_url: str | None = Field(default=None, max_length=500)
    match_confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=10, max_length=2000)


class OutreachCreate(BaseModel):
    message: str = Field(min_length=20, max_length=5000)


class OutreachStateChange(BaseModel):
    state: Literal["draft", "approved", "sent", "replied", "bounced", "opted_out"]
    note: str | None = Field(default=None, max_length=1000)


OUTREACH_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"approved", "opted_out"},
    "approved": {"sent", "opted_out"},
    "sent": {"replied", "bounced", "opted_out"},
    "replied": {"opted_out"},
    "bounced": set(),
    "opted_out": set(),
}


def _has_word(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def role_points(role: str) -> int:
    lower = role.lower()
    if any(_has_word(lower, word) for word in ("chief", "ceo", "cfo", "coo", "cto", "founder", "managing director")):
        return 25
    if any(_has_word(lower, word) for word in ("vice president", "vp", "director", "head of")):
        return 18
    if any(_has_word(lower, word) for word in ("manager", "lead", "principal")):
        return 10
    return 5


def share_points(disclosed_shares: int | None) -> int:
    if not disclosed_shares:
        return 0
    if disclosed_shares >= 1_000_000:
        return 55
    if disclosed_shares >= 100_000:
        return 40
    if disclosed_shares >= 10_000:
        return 25
    return 10


def freshness_points(filing_date: str) -> tuple[int, bool]:
    """"Fresh" per the V1 data contract is within 72 hours (3 days); older is stale."""
    days_old = (date.today() - date.fromisoformat(filing_date)).days
    if days_old <= 1:
        return 15, False
    if days_old <= 3:
        return 10, False
    return 0, True


def normalized_text(value: str) -> str:
    """Compare PDF text while tolerating its line-wrap and spacing quirks."""
    return " ".join(value.casefold().split())


def lead_view(row: sqlite3.Row) -> dict:
    fresh_points, stale = freshness_points(row["filing_date"])
    breakdown = {
        "share": share_points(row["disclosed_shares"]),
        "role": role_points(row["role"]),
        "freshness": fresh_points,
        "rhp": 5 if row["document_type"] == "RHP" else 0,
    }
    return {
        **dict(row),
        "score": sum(breakdown.values()),
        "score_breakdown": breakdown,
        "stale": stale,
        "automatic_outreach_eligible": False,
    }


def get_lead_or_404(db: sqlite3.Connection, lead_id: str) -> sqlite3.Row:
    row = db.execute(
        """SELECT leads.*, source_documents.issuer, source_documents.document_type,
                  source_documents.filing_date, source_documents.original_filename
           FROM leads JOIN source_documents ON source_documents.id = leads.document_id
           WHERE leads.id = ?""",
        (lead_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return row


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "human-approved-prototype"}


@app.get("/api/documents")
def list_documents() -> list[dict]:
    with closing(connection()) as db:
        rows = db.execute(
            """SELECT id, issuer, document_type, filing_date, original_filename, sha256, page_count, created_at
               FROM source_documents ORDER BY filing_date DESC"""
        ).fetchall()
        return [dict(row) for row in rows]


def _read_upload_within_limit(upload: UploadFile, limit: int) -> bytes:
    """Read the underlying file synchronously, aborting as soon as the running
    total exceeds the limit instead of buffering an unbounded body first."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=422,
                detail=f"The PDF exceeds the {limit // (1024 * 1024)}MB upload limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/documents/upload", status_code=status.HTTP_201_CREATED)
def upload_document(
    issuer: Annotated[str, Form(min_length=2, max_length=160)],
    document_type: Annotated[str, Form()],
    filing_date: Annotated[date, Form()],
    file: Annotated[UploadFile, File()],
) -> dict:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=422, detail="document_type must be DRHP or RHP")
    if filing_date > date.today():
        raise HTTPException(status_code=422, detail="filing_date cannot be in the future")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="A PDF filing is required")

    content = _read_upload_within_limit(file, MAX_UPLOAD_BYTES)
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded PDF is empty")
    if PDF_HEADER not in content[:PDF_HEADER_SCAN_WINDOW]:
        raise HTTPException(status_code=422, detail="The file is not a readable PDF")
    digest = hashlib.sha256(content).hexdigest()
    try:
        pdf = fitz.open(stream=content, filetype="pdf")
    except (fitz.FileDataError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail="The file is not a readable PDF") from error
    try:
        if pdf.is_encrypted:
            raise HTTPException(
                status_code=422,
                detail="Password-protected or encrypted PDFs are not supported in V1",
            )
        try:
            extracted_text = "\n".join(page.get_text() for page in pdf)
        except Exception as error:
            raise HTTPException(status_code=422, detail="The file is not a readable PDF") from error
        page_count = pdf.page_count
    finally:
        pdf.close()
    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="The PDF has no extractable text; OCR is not in V1")

    identifier = str(uuid4())
    stored_path = UPLOAD_DIRECTORY / f"{identifier}.pdf"
    with closing(connection()) as db:
        existing = db.execute("SELECT id FROM source_documents WHERE sha256 = ?", (digest,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"This document is already recorded as {existing['id']}")
        stored_path.write_bytes(content)
        try:
            db.execute(
                "INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier, issuer.strip(), document_type, filing_date.isoformat(), file.filename, str(stored_path), digest, page_count, extracted_text, utc_now()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            stored_path.unlink(missing_ok=True)
            existing = db.execute("SELECT id FROM source_documents WHERE sha256 = ?", (digest,)).fetchone()
            raise HTTPException(
                status_code=409,
                detail=f"This document is already recorded as {existing['id'] if existing else 'an existing record'}",
            ) from None
    return {"id": identifier, "issuer": issuer.strip(), "page_count": page_count, "sha256": digest}


@app.get("/api/leads")
def list_leads() -> list[dict]:
    with closing(connection()) as db:
        rows = db.execute(
            """SELECT leads.*, source_documents.issuer, source_documents.document_type,
                      source_documents.filing_date, source_documents.original_filename
               FROM leads JOIN source_documents ON source_documents.id = leads.document_id"""
        ).fetchall()
    return sorted((lead_view(row) for row in rows), key=lambda item: item["score"], reverse=True)


@app.post("/api/leads", status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadCreate) -> dict:
    identifier = str(uuid4())
    with closing(connection()) as db:
        document = db.execute(
            "SELECT page_count, extracted_text FROM source_documents WHERE id = ?",
            (payload.document_id,),
        ).fetchone()
        if document is None:
            raise HTTPException(status_code=404, detail="Source document not found")
        if payload.evidence_page > document["page_count"]:
            raise HTTPException(status_code=422, detail="Evidence page is outside the source document")
        if normalized_text(payload.evidence_quote) not in normalized_text(document["extracted_text"]):
            raise HTTPException(
                status_code=422,
                detail="Evidence quote was not found in the extracted source text",
            )
        db.execute(
            """INSERT INTO leads (id, document_id, name, role, disclosed_shares, price_per_share, price_label, evidence_page, evidence_quote, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (identifier, payload.document_id, payload.name.strip(), payload.role.strip(), payload.disclosed_shares, payload.price_per_share, payload.price_label, payload.evidence_page, payload.evidence_quote.strip(), utc_now()),
        )
        db.commit()
        return lead_view(get_lead_or_404(db, identifier))


@app.patch("/api/leads/{lead_id}/enrichment")
def review_enrichment(lead_id: str, payload: EnrichmentReview) -> dict:
    with closing(connection()) as db:
        get_lead_or_404(db, lead_id)
        db.execute(
            "UPDATE leads SET email = ?, linkedin_url = ?, match_confidence = ?, enrichment_evidence = ? WHERE id = ?",
            (payload.email, payload.linkedin_url, payload.match_confidence, payload.evidence.strip(), lead_id),
        )
        db.commit()
        return lead_view(get_lead_or_404(db, lead_id))


@app.post("/api/leads/{lead_id}/outreach", status_code=status.HTTP_201_CREATED)
def create_outreach(lead_id: str, payload: OutreachCreate) -> dict:
    identifier = str(uuid4())
    now = utc_now()
    with closing(connection()) as db:
        get_lead_or_404(db, lead_id)
        db.execute(
            "INSERT INTO outreach VALUES (?, ?, ?, 'draft', NULL, ?, ?)",
            (identifier, lead_id, payload.message.strip(), now, now),
        )
        db.commit()
    return {"id": identifier, "lead_id": lead_id, "state": "draft"}


@app.patch("/api/outreach/{outreach_id}/state")
def change_outreach_state(outreach_id: str, payload: OutreachStateChange) -> dict:
    with closing(connection()) as db:
        item = db.execute("SELECT * FROM outreach WHERE id = ?", (outreach_id,)).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="Outreach record not found")
        current_state = item["state"]
        if payload.state not in OUTREACH_TRANSITIONS.get(current_state, set()):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot move outreach from {current_state} to {payload.state}",
            )
        db.execute(
            "UPDATE outreach SET state = ?, state_note = ?, updated_at = ? WHERE id = ?",
            (payload.state, payload.note, utc_now(), outreach_id),
        )
        db.commit()
        return dict(db.execute("SELECT * FROM outreach WHERE id = ?", (outreach_id,)).fetchone())


@app.get("/", response_class=HTMLResponse)
def dashboard(_: Request) -> HTMLResponse:
    return HTMLResponse((Path(__file__).parent / "static" / "index.html").read_text())
