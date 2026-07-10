"""
Synchronous Cloudinary upload service for Serverless compatibility.
Uploads run inline in the request handler so they block until completed.
"""
import os
import uuid
import cloudinary
import cloudinary.uploader
from db import DBConnection

ALLOWED_CV_MIMETYPES = {"application/pdf", "application/msword",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
ALLOWED_DOC_MIMETYPES = ALLOWED_CV_MIMETYPES | {"image/jpeg", "image/png"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_file(file_bytes: bytes, mimetype: str, allowed: set) -> str | None:
    """Return error string or None if valid."""
    if len(file_bytes) > MAX_FILE_BYTES:
        return f"File exceeds 10 MB limit ({len(file_bytes)//1024//1024} MB uploaded)."
    if mimetype not in allowed:
        return f"File type '{mimetype}' not allowed. Accepted: {', '.join(allowed)}."
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
    except Exception as exc:
        status = "failed"
        error_msg = str(exc)

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
