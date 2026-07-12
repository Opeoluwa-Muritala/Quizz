"""Background Cloudinary upload service."""
import os
import uuid
import logging
import io
import threading
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
MAX_FILE_BYTES = 3 * 1024 * 1024  # 3 MB
MAX_IMAGE_DIMENSION = 2200
JPEG_QUALITY = 82


def validate_file(file_bytes: bytes, mimetype: str, allowed: set,
                  filename: str = "", enforce_size: bool = True) -> str | None:
    """Return error string or None if valid."""
    if not file_bytes:
        return "The selected file is empty."
    if enforce_size and len(file_bytes) > MAX_FILE_BYTES:
        return f"File exceeds the 3 MB limit ({len(file_bytes)//1024//1024} MB uploaded)."
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


def compress_image(file_bytes: bytes, mimetype: str) -> tuple[bytes, str]:
    """Downsize camera images before Cloudinary upload; PDFs are never altered."""
    if mimetype not in {"image/jpeg", "image/png"}:
        return file_bytes, mimetype
    try:
        from PIL import Image, ImageOps
    except ImportError:
        # Deployments install Pillow from requirements.txt. Do not reject a
        # valid file solely because a local development environment lacks it.
        logger.warning("Pillow is unavailable; uploading image without compression")
        return file_bytes, mimetype
    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
            # JPEG is substantially smaller for photos/scans. Flatten PNG
            # transparency onto white so identity/document scans remain legible.
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                background = Image.new("RGB", image.size, "white")
                alpha = image.convert("RGBA").getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
            compressed = output.getvalue()
            # Do not inflate small illustrations/screenshots by converting them.
            if len(compressed) >= len(file_bytes):
                return file_bytes, mimetype
            return compressed, "image/jpeg"
    except Exception:
        logger.exception("Image compression failed; using original upload")
        return file_bytes, mimetype


def prepare_upload_file(file_bytes: bytes, mimetype: str, allowed: set,
                        filename: str = "") -> tuple[bytes, str, str | None]:
    """Validate content, compress images, then enforce the final upload limit."""
    error = validate_file(file_bytes, mimetype, allowed, filename, enforce_size=False)
    if error:
        return file_bytes, mimetype, error
    file_bytes, mimetype = compress_image(file_bytes, mimetype)
    if len(file_bytes) > MAX_FILE_BYTES:
        return file_bytes, mimetype, f"File remains above the 3 MB upload limit after compression."
    return file_bytes, mimetype, None


def _process_upload(job_id: str, file_bytes: bytes, folder: str, public_id: str,
                    candidate_id: int, resource_type: str, doc_type: str | None,
                    target_field: str | None) -> None:
    """Upload a queued file and persist its eventual result."""
    url = None
    pid = None
    error_msg = None
    status = "done"

    try:
        upload_mimetype = (
            "application/pdf" if file_bytes.startswith(b"%PDF-") else
            "image/jpeg" if file_bytes.startswith(b"\xff\xd8\xff") else
            "image/png" if file_bytes.startswith(b"\x89PNG\r\n\x1a\n") else
            "application/octet-stream"
        )
        file_bytes, _ = compress_image(file_bytes, upload_mimetype)
        if len(file_bytes) > MAX_FILE_BYTES:
            raise ValueError("File remains above the 3 MB upload limit after compression.")
        result = cloudinary.uploader.upload(
            file_bytes,
            folder=folder,
            public_id=public_id,
            resource_type=resource_type,
            type="authenticated",
        )
        url = result.get("secure_url", "")
        pid = result.get("public_id", "")
        if (not url.startswith("https://") or "fl_attachment" in url):
            raise ValueError("Cloudinary returned a URL that cannot be previewed inline.")
    except Exception as exc:
        logger.exception("Cloudinary upload failed for candidate_id=%s, doc_type=%s",
                         candidate_id, doc_type or target_field)
        status = "failed"
        error_msg = "We couldn't upload this file. Please try again."

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE upload_jobs
                SET status = %s, url = %s, public_id = %s, error = %s, updated_at = NOW()
                WHERE id = %s;
            """, (status, url, pid, error_msg, job_id))

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



def enqueue_upload(file_bytes: bytes, folder: str, public_id: str,
                   candidate_id: int, resource_type: str = "auto",
                   doc_type: str | None = None,
                   target_field: str | None = None) -> str:
    """Register an upload, then perform the Cloudinary call off the request path."""
    job_id = str(uuid.uuid4())
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO upload_jobs
                    (id, candidate_id, doc_type, target_field, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'pending', NOW(), NOW());
            """, (job_id, candidate_id, doc_type, target_field))
        conn.commit()

    threading.Thread(
        target=_process_upload,
        args=(job_id, file_bytes, folder, public_id, candidate_id, resource_type, doc_type, target_field),
        name=f"cloudinary-upload-{job_id[:8]}",
        daemon=True,
    ).start()
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
