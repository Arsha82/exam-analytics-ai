"""
PYQ Analyzer — Vector Store Service.

Uses ChromaDB backed by nomic-embed-text embeddings from Ollama.
Manages collections for syllabus topic search and question similarity/duplicate detection.
"""

import logging
import os
from typing import Any
import numpy as np

# Disable ChromaDB telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.services.ollama import ollama_service

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Manages ChromaDB vector collections for syllabus and question embeddings."""

    def __init__(self):
        settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(settings.chroma_persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.syllabus_col = self.client.get_or_create_collection(
            name="syllabus_nodes",
            metadata={"description": "Syllabus topic unit embeddings"},
        )
        self.questions_col = self.client.get_or_create_collection(
            name="question_vectors",
            metadata={"description": "PYQ question text embeddings for duplicate and similarity search"},
        )

    async def upsert_syllabus_nodes(self, nodes: list[dict[str, Any]]) -> int:
        """
        Embed and index a list of syllabus nodes.
        nodes: list of dicts with: node_id, subject, unit, topic, sub_topic, description, text
        """
        if not nodes:
            return 0

        texts = [n["text"] for n in nodes]
        ids = [n["node_id"] for n in nodes]
        metadatas = [
            {
                "subject": n.get("subject", ""),
                "unit": n.get("unit", ""),
                "topic": n.get("topic", ""),
                "sub_topic": n.get("sub_topic") or "",
            }
            for n in nodes
        ]

        embeddings = await ollama_service.embed(texts)
        self.syllabus_col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        return len(ids)

    async def search_syllabus(
        self,
        query_text: str,
        subject: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Semantic search across syllabus nodes for a question's text.
        Returns top-k candidate nodes with similarity scores (0.0 - 1.0).
        """
        count = self.syllabus_col.count()
        if count == 0:
            return []

        embeddings = await ollama_service.embed([query_text])
        if not embeddings or not embeddings[0]:
            return []

        where_filter = {"subject": subject} if subject else None
        
        # Ensure k does not exceed collection count
        k = min(top_k, count)
        results = self.syllabus_col.query(
            query_embeddings=embeddings,
            n_results=k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        candidates = []
        if results and results["ids"] and len(results["ids"][0]) > 0:
            ids = results["ids"][0]
            docs = results["documents"][0] if results.get("documents") else [""] * len(ids)
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)

            for i in range(len(ids)):
                # Chroma cosine distance: cosine_distance = 1 - cosine_similarity
                # So similarity = max(0.0, 1.0 - distance)
                dist = distances[i] if i < len(distances) else 1.0
                similarity = max(0.0, min(1.0, 1.0 - (dist / 2.0) if dist > 1.0 else 1.0 - dist))
                
                candidates.append({
                    "node_id": ids[i],
                    "text": docs[i],
                    "unit": metas[i].get("unit", ""),
                    "topic": metas[i].get("topic", ""),
                    "sub_topic": metas[i].get("sub_topic", ""),
                    "similarity": round(float(similarity), 4),
                })

        # Sort by highest similarity
        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        return candidates

    async def upsert_questions(self, questions: list[dict[str, Any]]) -> int:
        """
        Embed and index question records.
        """
        if not questions:
            return 0

        texts = [q["text"] for q in questions]
        ids = [q["question_id"] for q in questions]
        metadatas = [
            {
                "paper_id": q.get("paper_id", ""),
                "year": int(q.get("year", 0)),
                "marks": float(q.get("marks", 0.0)),
                "unit": q.get("unit_guess") or "",
            }
            for q in questions
        ]

        embeddings = await ollama_service.embed(texts)
        self.questions_col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        return len(ids)

    async def find_similar_questions(
        self,
        query_text: str,
        top_k: int = 5,
        exclude_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find most similar historical questions to a given query."""
        count = self.questions_col.count()
        if count == 0:
            return []

        embeddings = await ollama_service.embed([query_text])
        if not embeddings or not embeddings[0]:
            return []

        k = min(top_k + (1 if exclude_id else 0), count)
        results = self.questions_col.query(
            query_embeddings=embeddings,
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

        matches = []
        if results and results["ids"] and len(results["ids"][0]) > 0:
            ids = results["ids"][0]
            docs = results["documents"][0] if results.get("documents") else [""] * len(ids)
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
            distances = results["distances"][0] if results.get("distances") else [1.0] * len(ids)

            for i in range(len(ids)):
                qid = ids[i]
                if exclude_id and qid == exclude_id:
                    continue
                dist = distances[i] if i < len(distances) else 1.0
                similarity = max(0.0, min(1.0, 1.0 - (dist / 2.0) if dist > 1.0 else 1.0 - dist))
                matches.append({
                    "question_id": qid,
                    "text": docs[i],
                    "year": metas[i].get("year", 0),
                    "marks": metas[i].get("marks", 0.0),
                    "unit": metas[i].get("unit", ""),
                    "similarity": round(float(similarity), 4),
                })
        return matches


vector_store = VectorStoreService()
