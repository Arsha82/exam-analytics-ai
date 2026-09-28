"""
PYQ Analyzer — Archive Extractor Service.

Safely unpacks ZIP archives containing question papers (PDFs, images),
guards against ZipSlip path-traversal attacks, extracts files into the uploads directory,
and infers initial metadata (subject, year, session) from directory trees and filenames.
"""

import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import uuid
import zipfile

from app.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff"}


class ArchiveExtractor:
    """Service to unpack ZIP archives safely and discover question paper documents."""

    @staticmethod
    def is_safe_path(base_dir: Path, target_path: Path) -> bool:
        """Prevent ZipSlip path traversal."""
        try:
            target_path.resolve().relative_to(base_dir.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def infer_metadata_from_name(
        rel_path: str, default_subject: str = "General", default_year: int = 2024
    ) -> dict[str, Any]:
        """
        Infer subject, year, and session month from filepath / directory structure.
        Examples:
        - "Mathematics/2023_May_Endsem.pdf" -> subject="Mathematics", year=2023, session="May"
        - "Physics_2022.pdf" -> subject="Physics", year=2022
        - "CSE/Data_Structures/2021.pdf" -> subject="Data Structures", year=2021
        """
        p = Path(rel_path)
        parts = list(p.parts)
        stem = p.stem

        # 1. Search for 4-digit year (1990 - 2035)
        year_match = re.search(r"\b(19\d{2}|20[0-3]\d)\b", rel_path)
        inferred_year = int(year_match.group(1)) if year_match else default_year

        # 2. Search for session month / semester
        month_match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|midsem|endsem|summer|winter|spring|autumn)\b",
            rel_path,
            re.IGNORECASE,
        )
        inferred_month = month_match.group(1).capitalize() if month_match else None

        # 3. Infer subject from folder name or file prefix
        inferred_subject = default_subject
        if len(parts) > 1:
            # Use immediate parent directory or grandparent
            folder_subject = parts[-2].replace("_", " ").strip()
            # If folder is not just a year, use it as subject
            if not re.match(r"^\d{4}$", folder_subject) and len(folder_subject) > 2:
                inferred_subject = folder_subject
            elif len(parts) > 2:
                inferred_subject = parts[-3].replace("_", " ").strip()
        else:
            # Try parsing from filename before year e.g. "Physics_2022" -> "Physics"
            clean_stem = re.sub(r"\b(19\d{2}|20[0-3]\d)\b", "", stem)
            clean_stem = re.sub(
                r"\b(january|february|march|april|may|june|july|august|september|october|november|december|midsem|endsem)\b",
                "",
                clean_stem,
                flags=re.IGNORECASE,
            )
            clean_stem = re.sub(r"[_\-]+", " ", clean_stem).strip()
            if len(clean_stem) >= 3:
                inferred_subject = clean_stem.title()

        return {
            "subject": inferred_subject,
            "year": inferred_year,
            "session_month": inferred_month,
        }

    def unpack_archive(
        self,
        archive_path: Path,
        default_subject: str = "General",
        default_year: int = 2024,
    ) -> list[dict[str, Any]]:
        """
        Unpack a ZIP file and return list of discovered document files with inferred metadata.
        """
        if not zipfile.is_zipfile(str(archive_path)):
            raise ValueError(f"File {archive_path.name} is not a valid ZIP archive")

        extracted_docs: list[dict[str, Any]] = []

        with zipfile.ZipFile(str(archive_path), "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue

                member_path = Path(member.filename)
                ext = member_path.suffix.lower()

                # Filter only supported document and image types
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                # Generate a unique destination file path in upload_dir
                safe_name = re.sub(r"[^\w\-.]", "_", member_path.name)
                dest_filename = f"batch_{uuid.uuid4().hex[:6]}_{safe_name}"
                dest_path = settings.upload_dir / dest_filename

                # Security check
                if not self.is_safe_path(settings.upload_dir, dest_path):
                    logger.warning(f"Blocked potential ZipSlip path: {member.filename}")
                    continue

                # Extract file contents safely
                with zf.open(member) as source_file, open(dest_path, "wb") as target_file:
                    target_file.write(source_file.read())

                meta = self.infer_metadata_from_name(
                    member.filename,
                    default_subject=default_subject,
                    default_year=default_year,
                )

                extracted_docs.append({
                    "file_path": dest_path,
                    "filename": member_path.name,
                    "original_path_in_zip": member.filename,
                    "subject": meta["subject"],
                    "year": meta["year"],
                    "session_month": meta["session_month"],
                    "size_bytes": dest_path.stat().st_size,
                })

        logger.info(f"Unpacked {len(extracted_docs)} document(s) from ZIP {archive_path.name}")
        return extracted_docs


archive_extractor = ArchiveExtractor()
