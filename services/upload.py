"""
Background Cloudinary upload service.
Uploads run in a daemon thread so the request returns immediately.
Callers poll /api/upload-status/<job_id> to learn when it's done.
"""
import os
import uuid
import threading
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


def _do_upload(job_id: str, file_bytes: bytes, folder: str, public_id: str,
               resource_type: str, candidate_id: int, doc_type: str | None,
               target_field: str | None):
    """Runs in a background thread. Updates upload_jobs on completion."""
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

        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE upload_jobs
                    SET status = 'done', url = %s, public_id = %s, updated_at = NOW()
                    WHERE id = %s;
                """, (url, pid, job_id))

                # Persist URL to candidates or candidate_documents
                if target_field == "cv_url":
                    cur.execute("UPDATE candidates SET cv_url = %s WHERE id = %s;",
                                (url, candidate_id))
                elif doc_type:
                    cur.execute("""
                        UPDATE candidate_documents
                        SET url = %s, public_id = %s, upload_status = 'done', uploaded_at = NOW()
                        WHERE candidate_id = %s AND doc_type = %s
                          AND upload_status = 'processing';
                    """, (url, pid, candidate_id, doc_type))
            conn.commit()

    except Exception as exc:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE upload_jobs
                    SET status = 'failed', error = %s, updated_at = NOW()
                    WHERE id = %s;
                """, (str(exc)[:500], job_id))
                if doc_type:
                    cur.execute("""
                        UPDATE candidate_documents
                        SET upload_status = 'failed'
                        WHERE candidate_id = %s AND doc_type = %s AND upload_status = 'processing';
                    """, (candidate_id, doc_type))
            conn.commit()


def enqueue_upload(file_bytes: bytes, folder: str, public_id: str,
                   candidate_id: int, resource_type: str = "auto",
                   doc_type: str | None = None,
                   target_field: str | None = None) -> str:
    """
    Register an upload job in the DB and start it in a background thread.
    Returns job_id for the caller to track status.
    """
    job_id = str(uuid.uuid4())

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO upload_jobs (id, candidate_id, doc_type, target_field, status)
                VALUES (%s, %s, %s, %s, 'processing');
            """, (job_id, candidate_id, doc_type, target_field))
            if doc_type:
                # Mark the document row as processing
                cur.execute("""
                    UPDATE candidate_documents
                    SET upload_status = 'processing'
                    WHERE candidate_id = %s AND doc_type = %s AND upload_status = 'pending';
                """, (candidate_id, doc_type))
        conn.commit()

    t = threading.Thread(
        target=_do_upload,
        args=(job_id, file_bytes, folder, public_id, resource_type,
              candidate_id, doc_type, target_field),
        daemon=True,
    )
    t.start()
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
