from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core import audit
from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes, sha256_hex
from app.core.db import get_db, utcnow
from app.core.deps import AuthContext, get_auth, profile_editor, profile_reader
from app.core.storage import delete_blob, get_blob, put_blob
from app.models import (
    BiomarkerResult,
    Condition,
    Document,
    ExtractedFact,
    LabResult,
    Medication,
    PatientProfile,
    Procedure,
)
from app.models.enums import (
    Assertion,
    DocumentStatus,
    DocumentType,
    FactType,
    MedicationStatus,
    Provenance,
    ReviewStatus,
    Verification,
)
from app.modules.agents.llm import phi_allowed
from app.modules.documents.extraction import document_pages, extract_candidates, merge_llm_candidates
from app.modules.documents.llm_extract import llm_candidates

router = APIRouter(prefix="/api/profiles/{profile_id}", tags=["documents"])

ALLOWED_TYPES = {"application/pdf", "text/plain"}


def fact_out(f: ExtractedFact) -> dict:
    return {"id": str(f.id), "document_id": str(f.document_id), "fact_type": f.fact_type.value, "payload": f.payload,
            "source_page": f.source_page, "source_excerpt": f.source_excerpt, "method": f.method,
            "confidence": f.confidence, "warnings": f.warnings or [], "review_status": f.review_status.value,
            "created_fact_id": str(f.created_fact_id) if f.created_fact_id else None}


def doc_out(d: Document, include_facts: bool = False) -> dict:
    out = {"id": str(d.id), "filename": decrypt_bytes(d.filename_encrypted).decode("utf-8", "replace"),
           "content_type": d.content_type, "size_bytes": d.size_bytes, "doc_type": d.doc_type.value,
           "status": d.status.value, "page_count": d.page_count, "extraction_methods": d.extraction_methods or [],
           "error_code": d.error_code, "uploaded_at": d.created_at.isoformat(),
           "pending_count": sum(1 for f in d.extracted_facts if f.review_status == ReviewStatus.pending),
           "fact_count": len(d.extracted_facts)}
    if include_facts:
        out["facts"] = [fact_out(f) for f in sorted(d.extracted_facts, key=lambda f: (f.source_page or 0, f.fact_type.value))]
    return out


def _consented_ai(auth: AuthContext) -> bool:
    latest = {}
    for c in sorted(auth.user.consents, key=lambda c: c.created_at):
        latest[c.consent_type] = c.granted
    return bool(latest.get("ai_processing"))


@router.post("/documents", status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...), doc_type: DocumentType = Form(DocumentType.other),
                          profile: PatientProfile = Depends(profile_editor), auth: AuthContext = Depends(get_auth),
                          db: Session = Depends(get_db)):
    s = get_settings()
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {s.max_upload_mb} MB.")
    ctype = (file.content_type or "").split(";")[0]
    if data[:5] == b"%PDF-":
        ctype = "application/pdf"
    if ctype not in ALLOWED_TYPES:
        raise HTTPException(415, "Please upload a PDF or plain-text file.")
    if ctype == "application/pdf" and data[:5] != b"%PDF-":
        raise HTTPException(415, "The file does not look like a valid PDF.")
    doc = Document(profile_id=profile.id, uploaded_by_user_id=auth.user.id,
                   filename_encrypted=encrypt_bytes((file.filename or "document").encode()[:255]), content_type=ctype,
                   size_bytes=len(data), sha256=sha256_hex(data), storage_key=put_blob(data), doc_type=doc_type,
                   status=DocumentStatus.processing)
    db.add(doc)
    db.flush()
    methods = ["rules"]
    try:
        pages = document_pages(data, ctype)
        result = extract_candidates(pages)
        candidates = result.candidates
        allowed, _reason = phi_allowed(profile, _consented_ai(auth))
        if allowed and result.status == "extracted":
            extra = llm_candidates(pages)
            if extra:
                methods.append("llm")
            candidates = merge_llm_candidates(candidates, extra)
        doc.page_count = len(pages)
        doc.status = DocumentStatus.extracted if result.status == "extracted" else DocumentStatus.no_text
        for c in candidates:
            db.add(ExtractedFact(document_id=doc.id, profile_id=profile.id, fact_type=FactType(c.fact_type),
                                 payload=c.payload, source_page=c.page, source_excerpt=c.excerpt[:1000],
                                 method=c.method, confidence=c.confidence, warnings=c.warnings + []))
        doc.extraction_methods = methods + ([f"note:{n}" for n in result.notes] if result.notes else [])
    except Exception:  # noqa: BLE001 - malformed PDFs raise many error types
        doc.status = DocumentStatus.failed
        doc.error_code = "extraction_failed"
    audit.record(db, "document.upload", actor_id=auth.user.id, request=request, resource_type="document",
                 resource_id=doc.id, profile_id=profile.id, meta={"doc_type": doc_type.value, "status": doc.status.value})
    db.commit()
    doc = db.scalar(select(Document).where(Document.id == doc.id).options(selectinload(Document.extracted_facts))
                    .execution_options(populate_existing=True))
    return doc_out(doc, include_facts=True)


@router.get("/documents")
def list_documents(profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).where(Document.profile_id == profile.id).order_by(Document.created_at.desc())
                      .options(selectinload(Document.extracted_facts))).all()
    return [doc_out(d) for d in docs]


def _doc(db: Session, profile: PatientProfile, document_id: uuid.UUID) -> Document:
    d = db.scalar(select(Document).where(Document.id == document_id, Document.profile_id == profile.id)
                  .options(selectinload(Document.extracted_facts)).execution_options(populate_existing=True))
    if d is None:
        raise HTTPException(404, "Document not found")
    return d


@router.get("/documents/{document_id}")
def get_document(document_id: uuid.UUID, profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    return doc_out(_doc(db, profile, document_id), include_facts=True)


@router.get("/documents/{document_id}/file")
def download_document(document_id: uuid.UUID, request: Request, profile: PatientProfile = Depends(profile_reader),
                      auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    d = _doc(db, profile, document_id)
    audit.record(db, "document.download", actor_id=auth.user.id, request=request, resource_type="document",
                 resource_id=d.id, profile_id=profile.id)
    db.commit()
    return Response(get_blob(d.storage_key), media_type=d.content_type,
                    headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})


@router.delete("/documents/{document_id}")
def delete_document(document_id: uuid.UUID, request: Request, profile: PatientProfile = Depends(profile_editor),
                    auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Deletes the file and pending candidates. Facts the user already accepted stay in the
    profile (they become patient-confirmed data) but lose their document link."""
    d = _doc(db, profile, document_id)
    delete_blob(d.storage_key)
    audit.record(db, "document.delete", actor_id=auth.user.id, request=request, resource_type="document",
                 resource_id=d.id, profile_id=profile.id)
    db.delete(d)
    db.commit()
    return {"deleted": True}


def _d(v):
    return date.fromisoformat(v) if isinstance(v, str) and v else None


@router.post("/extracted-facts/{fact_id}/accept")
def accept_fact(fact_id: uuid.UUID, request: Request, edits: dict | None = None,
                profile: PatientProfile = Depends(profile_editor), auth: AuthContext = Depends(get_auth),
                db: Session = Depends(get_db)):
    f = db.get(ExtractedFact, fact_id)
    if f is None or f.profile_id != profile.id:
        raise HTTPException(404, "Not found")
    if f.review_status != ReviewStatus.pending:
        raise HTTPException(409, "Already reviewed")
    p = {**f.payload, **(edits or {})}
    common = dict(profile_id=profile.id, provenance=Provenance.document_extracted, verification=Verification.confirmed,
                  source_document_id=f.document_id, source_page=f.source_page, source_excerpt=f.source_excerpt,
                  extraction_method=f.method, confirmed_at=utcnow(),
                  notes="Edited by user during review" if edits else None)
    if f.fact_type == FactType.lab:
        row = LabResult(analyte=p["analyte"], display_name=p.get("display_name") or p["analyte"],
                        value_numeric=p.get("value_numeric"), value_text=p.get("value_text"), unit=p.get("unit"),
                        reference_low=p.get("reference_low"), reference_high=p.get("reference_high"),
                        reference_text=p.get("reference_text"), collected_on=_d(p.get("collected_on")), **common)
    elif f.fact_type == FactType.condition:
        row = Condition(concept=p.get("concept"), name=p["name"], assertion=Assertion(p.get("assertion", "present")),
                        onset_date=_d(p.get("onset_date")), **common)
    elif f.fact_type == FactType.procedure:
        row = Procedure(concept=p.get("concept"), name=p["name"], assertion=Assertion(p.get("assertion", "present")),
                        performed_on=_d(p.get("performed_on")), **common)
    elif f.fact_type == FactType.medication:
        row = Medication(concept=p.get("concept"), name=p["name"], status=MedicationStatus(p.get("status", "current")),
                         dose=p.get("dose"), **common)
    else:
        row = BiomarkerResult(name=p["name"], concept=p.get("concept"), result=p["result"],
                              interpretation=p.get("interpretation"), **common)
    db.add(row)
    db.flush()
    f.review_status = ReviewStatus.accepted
    f.reviewed_at = utcnow()
    f.created_fact_id = row.id
    if edits:
        f.payload = p
    audit.record(db, "extracted_fact.accept", actor_id=auth.user.id, request=request, resource_type="extracted_fact",
                 resource_id=f.id, profile_id=profile.id, meta={"fact_type": f.fact_type.value})
    db.commit()
    return fact_out(f)


@router.post("/extracted-facts/{fact_id}/reject")
def reject_fact(fact_id: uuid.UUID, request: Request, profile: PatientProfile = Depends(profile_editor),
                auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    f = db.get(ExtractedFact, fact_id)
    if f is None or f.profile_id != profile.id:
        raise HTTPException(404, "Not found")
    f.review_status = ReviewStatus.rejected
    f.reviewed_at = utcnow()
    audit.record(db, "extracted_fact.reject", actor_id=auth.user.id, request=request, resource_type="extracted_fact",
                 resource_id=f.id, profile_id=profile.id, meta={"fact_type": f.fact_type.value})
    db.commit()
    return fact_out(f)
