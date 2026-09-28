"""Syllabus router — CRUD syllabus tree, auto-embedding, and vector re-indexing."""

from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.syllabus import SyllabusNode
from app.services.vector_store import vector_store

router = APIRouter()


class SyllabusNodeIn(BaseModel):
    subject: str | None = None
    unit: str
    topic: str
    sub_topic: str | None = None
    description: str


class SyllabusImportRequest(BaseModel):
    subject: str
    nodes: list[SyllabusNodeIn]


@router.get("")
async def get_syllabus(
    subject: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get the syllabus tree for a subject."""
    query = select(SyllabusNode)
    if subject:
        query = query.where(SyllabusNode.subject == subject)
    query = query.order_by(SyllabusNode.unit, SyllabusNode.topic)
    result = await db.execute(query)
    nodes = result.scalars().all()

    # Group into unit → topic → sub_topics tree
    tree = {}
    for node in nodes:
        if node.unit not in tree:
            tree[node.unit] = {"unit": node.unit, "topics": {}}
        unit_dict = tree[node.unit]["topics"]
        if node.topic not in unit_dict:
            unit_dict[node.topic] = {
                "topic": node.topic,
                "sub_topics": [],
                "node_id": node.node_id,
                "description": node.description,
                "embedded": node.embedding_id is not None,
            }
        if node.sub_topic:
            unit_dict[node.topic]["sub_topics"].append({
                "sub_topic": node.sub_topic,
                "node_id": node.node_id,
                "description": node.description,
                "embedded": node.embedding_id is not None,
            })

    return {
        "subject": subject,
        "units": [
            {
                "unit": u["unit"],
                "topics": list(u["topics"].values()),
            }
            for u in tree.values()
        ],
        "total_nodes": len(nodes),
    }


@router.post("/import", status_code=201)
async def import_syllabus(
    payload: SyllabusImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Import a batch of syllabus nodes and embed them into the vector store."""
    created_records = []
    vector_payload = []

    for item in payload.nodes:
        node_id = f"syl_{payload.subject.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
        node = SyllabusNode(
            node_id=node_id,
            subject=payload.subject,
            unit=item.unit,
            topic=item.topic,
            sub_topic=item.sub_topic,
            description=item.description,
            embedding_id=node_id,
        )
        db.add(node)
        created_records.append(node)
        vector_payload.append({
            "node_id": node_id,
            "subject": payload.subject,
            "unit": item.unit,
            "topic": item.topic,
            "sub_topic": item.sub_topic,
            "description": item.description,
            "text": node.embedding_text(),
        })

    await db.commit()

    # Index into vector store
    embedded_count = 0
    if vector_payload:
        try:
            embedded_count = await vector_store.upsert_syllabus_nodes(vector_payload)
        except Exception as e:
            pass

    return {
        "status": "success",
        "subject": payload.subject,
        "nodes_created": len(created_records),
        "embedded_count": embedded_count,
    }


@router.post("/reembed")
async def reembed_syllabus(
    subject: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Rebuild vector store index from database records."""
    query = select(SyllabusNode)
    if subject:
        query = query.where(SyllabusNode.subject == subject)
    res = await db.execute(query)
    nodes = res.scalars().all()

    vector_payload = [
        {
            "node_id": n.node_id,
            "subject": n.subject,
            "unit": n.unit,
            "topic": n.topic,
            "sub_topic": n.sub_topic,
            "description": n.description,
            "text": n.embedding_text(),
        }
        for n in nodes
    ]

    count = await vector_store.upsert_syllabus_nodes(vector_payload)
    return {
        "status": "complete",
        "message": f"Successfully re-embedded {count} syllabus nodes",
        "count": count,
    }


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_syllabus_node(
    node_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a syllabus node."""
    node = await db.get(SyllabusNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Syllabus node not found")
    await db.delete(node)
    await db.commit()
