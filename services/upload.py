"""
Synchronous Cloudinary upload service for Serverless compatibility.
Uploads run inline in the request handler so they block until completed.
"""
import os
import uuid
import logging
from pathlib import Path
import cloudinary
import cloudinary.uploader
from db import DBConnection

logger = logging.getLogger(__name__)

ALLOWED_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
ALLOWED_CV_MIMETYPES = set(ALLOWED_FILE_TYPES.values())
ALLOWED_DOC_MIMETYPES = ALLOWED_CV_MIMETYPES
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_file(file_bytes: bytes, mimetype: str, allowed: set,
                  filename: str = "") -> str | None:
    """Return error string or None if valid."""
    if not file_bytes:
        return "The selected file is empty."
    if len(file_bytes) > MAX_FILE_BYTES:
        return f"File exceeds 10 MB limit ({len(file_bytes)//1024//1024} MB uploaded)."
    if mimetype not in allowed:
        return "Only PDF, JPEG, and PNG files are allowed."
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_FILE_TYPES:
        return "Only .pdf, .jpg, .jpeg, and .png files are allowed."
    if ALLOWED_FILE_TYPES[extension] != mimetype:
        return "This file does not appear to be a valid PDF, JPG, or PNG."
    signatures_valid = {
        "application/pdf": file_bytes.startswith(b"%PDF-"),
        "image/jpeg": file_bytes.startswith(b"\xff\xd8\xff"),
        "image/png": file_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
    }
    if not signatures_valid.get(mimetype, False):
        return "This file appears to be damaged or in an unsupported format."
    return None


def enqueue_upload(file_bytes: bytes, folder: str, public_id: str,
                   candidate_id: int, resource_type: str = "auto",
                   doc_type: str | None = None,
                   target_field: str | None = None) -> str:
    """
    Perform the upload synchronously. Registers the job as 'done' or 'failed' immediately,
    persisting the results to candidates or candidate_documents.
    Returns job_id.
    """
    job_id = str(uuid.uuid4())
    url = None
    pid = None
    error_msg = None
    status = "done"

    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            folder=folder,
            public_id=public_id,
            resource_type=resource_type,
            type="authenticated",
        )
        url = result.get("secure_url", "")
        pid = result.get("public_id", "")
        if (not url.startswith("https://") or "/image/upload/" not in url
                or "fl_attachment" in url):
            raise ValueError("Cloudinary returned a URL that cannot be previewed inline.")
    except Exception as exc:
        logger.exception("Cloudinary upload failed for candidate_id=%s, doc_type=%s",
                         candidate_id, doc_type or target_field)
        status = "failed"
        error_msg = "We couldn't upload this file. Please try again."

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Insert completed/failed upload job record
            cur.execute("""
                INSERT INTO upload_jobs (id, candidate_id, doc_type, target_field, status, url, public_id, error, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
            """, (job_id, candidate_id, doc_type, target_field, status, url, pid, error_msg))

            if status == "done":
                # Persist URL to candidates or candidate_documents
                if target_field == "cv_url":
                    cur.execute("UPDATE candidates SET cv_url = %s WHERE id = %s;",
                                (url, candidate_id))
                elif doc_type:
                    # Check if candidate_document row exists, if not insert it, else update it
                    cur.execute("""
                        INSERT INTO candidate_documents (candidate_id, doc_type, url, public_id, upload_status, uploaded_at)
                        VALUES (%s, %s, %s, %s, 'done', NOW())
                        ON CONFLICT (candidate_id, doc_type)
                        DO UPDATE SET url = EXCLUDED.url, public_id = EXCLUDED.public_id, upload_status = 'done', uploaded_at = NOW();
                    """, (candidate_id, doc_type, url, pid))
            else:
                # Mark as failed in documents if doc_type was passed
                if doc_type:
                    cur.execute("""
                        INSERT INTO candidate_documents (candidate_id, doc_type, upload_status, uploaded_at)
                        VALUES (%s, %s, 'failed', NOW())
                        ON CONFLICT (candidate_id, doc_type)
                        DO UPDATE SET upload_status = 'failed', uploaded_at = NOW();
                    """, (candidate_id, doc_type))
        conn.commit()

    return job_id


def get_job_status(job_id: str) -> dict | None:
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT status, url, error, updated_at FROM upload_jobs WHERE id = %s;
            """, (job_id,))
            row = cur.fetchone()

    if not row:
        return None
    return {
        "job_id": job_id,
        "status": row[0],
        "url": row[1],
        "error": row[2],
        "updated_at": row[3].isoformat() if row[3] else None,
    }
