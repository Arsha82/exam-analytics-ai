"""
Papers router — upload, list, detail, re-run OCR, delete.

Handles file upload (multipart), triggers the OCR pipeline via Celery,
and provides CRUD endpoints for paper records.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.paper import Paper, Question
from app.schemas.paper import PaperCreate, PaperListOut, PaperOut

router = APIRouter()


@router.post("/upload", response_model=PaperOut, status_code=201)
async def upload_paper(
    subject: str = Form(...),
    year: int = Form(...),
    total_marks: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a scanned paper file or ZIP archive and start the OCR/structuring pipeline."""
    from app.services.archive_extractor import archive_extractor
    from app.services.pipeline_runner import trigger_paper_pipeline_async

    is_zip = file.filename.lower().endswith(".zip") or file.content_type in (
        "application/zip",
        "application/x-zip-compressed",
    )

    if is_zip:
        zip_id = f"batch_{uuid.uuid4().hex[:6]}"
        upload_path = settings.upload_dir / f"{zip_id}_{file.filename}"
        content = await file.read()
        upload_path.write_bytes(content)

        extracted_docs = archive_extractor.unpack_archive(
            upload_path, default_subject=subject, default_year=year
        )
        if not extracted_docs:
            raise HTTPException(
                status_code=400,
                detail="No supported question paper files (.pdf, images) found in ZIP archive.",
            )

        created_papers = []
        for doc in extracted_docs:
            paper_id = f"{doc['year']}_{doc['subject'].lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
            paper = Paper(
                paper_id=paper_id,
                subject=doc["subject"],
                year=doc["year"],
                total_marks=total_marks,
                source_file=str(doc["file_path"]),
                ocr_status="pending",
            )
            db.add(paper)
            created_papers.append(paper)

        await db.commit()

        # Trigger async pipeline for each extracted document
        for p in created_papers:
            trigger_paper_pipeline_async(p.paper_id)

        first_paper = created_papers[0]
        await db.refresh(first_paper)
        return PaperOut(
            paper_id=first_paper.paper_id,
            subject=f"{first_paper.subject} (Batch of {len(created_papers)})",
            year=first_paper.year,
            total_marks=first_paper.total_marks,
            source_file=first_paper.source_file,
            ocr_status="pending",
            needs_review=False,
            question_count=0,
            created_at=first_paper.created_at,
        )

    # Standard single paper upload
    paper_id = f"{year}_{subject.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
    upload_path = settings.upload_dir / f"{paper_id}_{file.filename}"
    content = await file.read()
    upload_path.write_bytes(content)

    paper = Paper(
        paper_id=paper_id,
        subject=subject,
        year=year,
        total_marks=total_marks,
        source_file=str(upload_path),
        ocr_status="pending",
    )
    db.add(paper)
    await db.commit()
    await db.refresh(paper)

    trigger_paper_pipeline_async(paper_id)

    return PaperOut(
        paper_id=paper.paper_id,
        subject=paper.subject,
        year=paper.year,
        total_marks=paper.total_marks,
        source_file=paper.source_file,
        ocr_status=paper.ocr_status,
        needs_review=paper.needs_review,
        question_count=0,
        created_at=paper.created_at,
    )


@router.get("", response_model=PaperListOut)
async def list_papers(
    subject: str | None = None,
    year: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List papers with optional filters."""
    query = select(Paper)

    if subject:
        query = query.where(Paper.subject == subject)
    if year:
        query = query.where(Paper.year == year)
    if status:
        query = query.where(Paper.ocr_status == status)
    else:
        query = query.where(Paper.ocr_status != "split")

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(Paper.year.desc(), Paper.created_at.desc())
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    papers = result.scalars().all()

    # Get question counts
    paper_outs = []
    for p in papers:
        q_count_query = select(func.count()).where(Question.paper_id == p.paper_id)
        q_count = (await db.execute(q_count_query)).scalar() or 0
        paper_outs.append(
            PaperOut(
                paper_id=p.paper_id,
                subject=p.subject,
                year=p.year,
                total_marks=p.total_marks,
                source_file=p.source_file,
                ocr_status=p.ocr_status,
                needs_review=p.needs_review,
                question_count=q_count,
                created_at=p.created_at,
            )
        )

    return PaperListOut(papers=paper_outs, total=total)


@router.get("/{paper_id}", response_model=PaperOut)
async def get_paper(paper_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single paper by ID."""
    result = await db.execute(select(Paper).where(Paper.paper_id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    q_count = (
        await db.execute(
            select(func.count()).where(Question.paper_id == paper_id)
        )
    ).scalar() or 0

    return PaperOut(
        paper_id=paper.paper_id,
        subject=paper.subject,
        year=paper.year,
        total_marks=paper.total_marks,
        source_file=paper.source_file,
        ocr_status=paper.ocr_status,
        needs_review=paper.needs_review,
        question_count=q_count,
        created_at=paper.created_at,
    )


@router.post("/{paper_id}/rerun-ocr")
async def rerun_ocr(paper_id: str, db: AsyncSession = Depends(get_db)):
    """Re-trigger the OCR pipeline for a paper."""
    result = await db.execute(select(Paper).where(Paper.paper_id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    paper.ocr_status = "pending"
    paper.needs_review = False
    await db.commit()

    from app.services.pipeline_runner import trigger_paper_pipeline_async
    trigger_paper_pipeline_async(paper_id)
    return {"message": f"OCR pipeline re-triggered for {paper_id}", "status": "processing"}


@router.delete("/{paper_id}", status_code=204)
async def delete_paper(paper_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a paper and all its associated questions."""
    result = await db.execute(select(Paper).where(Paper.paper_id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Clean up file
    source_path = Path(paper.source_file)
    if source_path.exists():
        source_path.unlink()

    await db.delete(paper)
