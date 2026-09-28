"""
ORM model for the syllabus tree — units, topics, sub-topics.

Each leaf node gets embedded into the syllabus_vectors index.
The correlation agent (7.4) queries this tree to map questions to topics.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SyllabusNode(Base):
    """A node in the syllabus hierarchy (unit → topic → sub-topic)."""

    __tablename__ = "syllabus_nodes"

    node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    sub_topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Filled when embedded into syllabus_vectors
    embedding_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    def embedding_text(self) -> str:
        """Text representation used for generating the embedding vector."""
        parts = [f"{self.unit}: {self.topic}"]
        if self.sub_topic:
            parts.append(f"- {self.sub_topic}")
        parts.append(f". {self.description}")
        return " ".join(parts)

    def __repr__(self) -> str:
        return f"<SyllabusNode {self.unit}/{self.topic}>"
