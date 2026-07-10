"""
Candidate-facing recruitment pipeline routes.
All stage-sensitive routes use the @require_stage decorator.
"""
import json
import random
import datetime
import threading
import logging
import time
import requests
import cloudinary.utils
from zoneinfo import ZoneInfo
from functools import wraps

from flask import (Blueprint, request, jsonify, render_template,
                   session, redirect, url_for, g, Response)

from db import DBConnection
from services.notifications import send_notification
from services.upload import (validate_file, enqueue_upload, get_job_status,
                              ALLOWED_CV_MIMETYPES, ALLOWED_DOC_MIMETYPES)
from services.screening import apply_screening
from services.meetings import create_meeting

recruitment = Blueprint("recruitment", __name__)
LOCAL_TZ = ZoneInfo("Africa/Lagos")
logger = logging.getLogger(__name__)


def _inline_candidate_asset(public_id: str, stored_url: str):
    """Return an authenticated candidate asset inline, including legacy raw files."""
    resource_type = "raw" if "/raw/upload/" in (stored_url or "") else "image"
    try:
        signed_url, _ = cloudinary.utils.cloudinary_url(
            public_id, resource_type=resource_type, type="authenticated",
            sign_url=True, expires_at=int(time.time()) + 300,
        )
        if resource_type == "image":
            return redirect(signed_url, code=302)
        upstream = requests.get(signed_url, timeout=20)
        if upstream.status_code != 200:
            logger.error("Candidate preview fetch failed: status=%s public_id=%s",
                         upstream.status_code, public_id)
            return "We couldn't display this file. Please try again.", 502
        return Response(
            upstream.content,
            mimetype=upstream.headers.get("Content-Type", "application/octet-stream"),
            headers={"Content-Disposition": "inline"},
        )
    except Exception:
        logger.exception("Candidate preview failed for public_id=%s", public_id)
        return "We couldn't display this file. Please try again.", 502

def get_or_create_cloudinary_folder(candidate_id: int) -> str:
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cloudinary_folder, email FROM candidates WHERE id = %s;", (candidate_id,))
            row = cur.fetchone()
            if row:
                folder, email = row
                if folder:
                    return folder
                import datetime
                now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                clean_email = email.replace("@", "_").replace(".", "_") if email else str(candidate_id)
                new_folder = f"candidates/{clean_email}-{now_str}"
                cur.execute("UPDATE candidates SET cloudinary_folder = %s WHERE id = %s;", (new_folder, candidate_id))
                conn.commit()
                return new_folder
    return f"candidates/{candidate_id}"

@recruitment.before_request
def handle_ref_token():
    ref = request.args.get("ref")
    if ref:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, email FROM candidates WHERE ref_token = %s;", (ref,))
                cand = cur.fetchone()
                if cand:
                    session["candidate_id"] = cand[0]
                    session["candidate_email"] = cand[1]

@recruitment.route("/resume/<ref_token>")
def resume_candidate(ref_token):
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email, stage FROM candidates WHERE ref_token = %s;", (ref_token,))
            cand = cur.fetchone()
    if cand:
        session["candidate_id"] = cand[0]
        session["candidate_email"] = cand[1]
        stage = cand[2] or "applied"
        return _stage_redirect(stage)
    return redirect(url_for("recruitment.apply"))


# ── Stage → route mapping ─────────────────────────────────────────────────────

STAGE_ROUTES = {
    "applied":                 "recruitment.dashboard",
    "screening_failed":        "recruitment.dashboard",
    "screening_flagged":       "recruitment.dashboard",
    "screening_passed":        "recruitment.dashboard",
    "assessment_in_progress":  "recruitment.assessment",
    "assessment_failed":       "recruitment.dashboard",
    "assessment_passed":       "recruitment.schedule",
    "interview_slot_pending":  "recruitment.schedule",
    "interview_scheduled":     "recruitment.dashboard",
    "documents_pending":       "recruitment.documents",
    "documents_submitted":     "recruitment.dashboard",
    "interview_completed":     "recruitment.dashboard",
    "offered":                 "recruitment.dashboard",
    "rejected":                "recruitment.dashboard",
    "application_expired":     "recruitment.dashboard",
    "assessment_expired":      "recruitment.dashboard",
    "booking_expired":         "recruitment.dashboard",
    "documents_expired":       "recruitment.dashboard",
}

REQUIRED_DOCUMENTS = [
    "nysc_certificate",
    "id_card",
    "credentials",
    "birth_certificate",
    "passport",
]


def get_role_document_requirements(role: str | None) -> list[dict]:
    """Return the single employment-document requirement set used by every role."""
    role = "General"
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT document_type, label, accepted_formats, required, position
                FROM role_document_requirements
                WHERE role = %s
                ORDER BY position ASC;
            """, (role,))
            rows = cur.fetchall()

    if not rows:
        return [
            {"document_type": d, "label": d.replace("_", " ").title(),
             "accepted_formats": ["PDF", "JPG", "PNG"],
             "required": True, "position": idx}
            for idx, d in enumerate(REQUIRED_DOCUMENTS, 1)
        ]

    return [{
        "document_type": r[0],
        "label": r[1],
        "accepted_formats": [f for f in list(r[2] or ["PDF", "JPG", "PNG"])
                             if f in {"PDF", "JPG", "JPEG", "PNG"}],
        "required": r[3],
        "position": r[4],
    } for r in rows]


def _stage_redirect(stage: str):
    route = STAGE_ROUTES.get(stage, "recruitment.dashboard")
    return redirect(url_for(route))


def require_stage(*allowed_stages):
    """Decorator: gate a route to candidates whose current stage is in allowed_stages."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            candidate_id = session.get("candidate_id")
            if not candidate_id:
                return redirect(url_for("recruitment.apply"))

            with DBConnection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT stage, email FROM candidates WHERE id = %s",
                        (candidate_id,)
                    )
                    row = cur.fetchone()

            if not row:
                session.pop("candidate_id", None)
                return redirect(url_for("recruitment.apply"))

            current_stage = row[0] or "applied"
            candidate_email = row[1]
            g.candidate_stage = current_stage
            g.candidate_id = candidate_id

            if current_stage not in allowed_stages:
                return _stage_redirect(current_stage)

            # Stage time-gating validation
            STAGE_CONFIG_MAP = {
                "applied": "application",
                "screening_passed": "assessment",
                "screening_flagged": "assessment",
                "assessment_in_progress": "assessment",
                "interview_slot_pending": "interview",
                "interview_scheduled": "interview",
                "documents_pending": "documents",
                "documents_submitted": "documents",
                "offered": "decision"
            }
            stage_config_name = STAGE_CONFIG_MAP.get(current_stage)
            if stage_config_name:
                with DBConnection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT opens_at, closes_at
                            FROM stage_config
                            WHERE stage_name = %s
                            ORDER BY cycle_id DESC LIMIT 1;
                        """, (stage_config_name,))
                        cfg = cur.fetchone()
                if cfg:
                    opens_at, closes_at = cfg
                    now = datetime.datetime.now(datetime.timezone.utc)
                    
                    is_locked = False
                    is_closed = False
                    
                    if opens_at and now < opens_at:
                        is_locked = True
                    if closes_at and now > closes_at:
                        is_closed = True
                        
                    if is_locked or is_closed:
                        # Bypass time gating if:
                        # 1. Candidate is a test/preview candidate (email match)
                        # 2. Stage transition was manually overridden by an admin
                        bypass = False
                        if candidate_email and ("test" in candidate_email.lower() or "preview" in candidate_email.lower()):
                            bypass = True
                        else:
                            with DBConnection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        SELECT changed_by FROM candidate_stage_history
                                        WHERE candidate_id = %s AND to_stage = %s
                                        ORDER BY changed_at DESC LIMIT 1;
                                    """, (candidate_id, current_stage))
                                    history_row = cur.fetchone()
                                    if history_row and history_row[0] == 'admin':
                                        bypass = True
                        
                        if not bypass:
                            if is_locked:
                                opens_str = opens_at.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M %p WAT")
                                return render_template("stage_locked.html", stage_label=stage_config_name.capitalize(), opens_at=opens_str, closed=False)
                            else:
                                return render_template("stage_locked.html", stage_label=stage_config_name.capitalize(), closed=True)

            return f(*args, **kwargs)
        return decorated
    return decorator


def _transition_stage(candidate_id: int, new_stage: str, changed_by: str = "system",
                      reason: str = None, conn=None):
    """Atomically advance a candidate's stage and write audit history."""
    def _execute(cur):
        cur.execute(
            "SELECT stage FROM candidates WHERE id = %s FOR UPDATE;",
            (candidate_id,)
        )
        old_stage = (cur.fetchone() or [None])[0]
        cur.execute("""
            UPDATE candidates
            SET stage = %s, stage_updated_at = NOW()
            WHERE id = %s;
        """, (new_stage, candidate_id))
        cur.execute("""
            INSERT INTO candidate_stage_history
                (candidate_id, from_stage, to_stage, changed_by, reason)
            VALUES (%s, %s, %s, %s, %s);
        """, (candidate_id, old_stage, new_stage, changed_by, reason))

    if conn:
        with conn.cursor() as cur:
            _execute(cur)
    else:
        with DBConnection() as conn2:
            with conn2.cursor() as cur:
                _execute(cur)
            conn2.commit()


# ── Pages ─────────────────────────────────────────────────────────────────────

@recruitment.route("/login", methods=["GET", "POST"])
def login():
    if session.get("candidate_id"):
        return redirect(url_for("recruitment.dashboard"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            error = "Email address is required."
        else:
            with DBConnection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, email, stage FROM candidates WHERE LOWER(email) = %s;", (email,))
                    row = cur.fetchone()
            if row:
                session["candidate_id"] = row[0]
                session["candidate_email"] = row[1]
                return _stage_redirect(row[2] or "applied")
            else:
                error = "No candidate application found with that email address. Please apply first."

    return render_template("login.html", error=error)


@recruitment.route("/apply")
def apply():
    if session.get("candidate_id"):
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT stage FROM candidates WHERE id = %s;", (session["candidate_id"],))
                row = cur.fetchone()
        stage = row[0] if row else "applied"
        return _stage_redirect(stage)

    # Fetch settings from DB
    DEFAULT_FIELDS = {
        "full_name": {"enabled": True, "required": True},
        "email": {"enabled": True, "required": True},
        "phone_number": {"enabled": True, "required": True},
        "dob": {"enabled": True, "required": True},
        "location": {"enabled": True, "required": False},
        "department": {"enabled": True, "required": False},
    }

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pre_test_fields FROM exam_settings WHERE id = 1;")
            db_row = cur.fetchone()
            pre_test_fields = db_row[0] if db_row and db_row[0] else []

    fields_config = {**DEFAULT_FIELDS}
    for f in pre_test_fields:
        key = f.get("key")
        if key in fields_config:
            # Full name and email are always enabled and required
            if key in ("full_name", "email"):
                continue
            fields_config[key] = {
                "enabled": bool(f.get("enabled", True)),
                "required": bool(f.get("required", True))
            }

    return render_template("apply.html", fields_config=fields_config)


@recruitment.route("/dashboard")
@require_stage(*list(STAGE_ROUTES.keys()))
def dashboard():
    candidate_id = g.candidate_id
    stage = g.candidate_stage

    # Stage-aware redirection fallback
    target_route = STAGE_ROUTES.get(stage, "recruitment.dashboard")
    if target_route != "recruitment.dashboard":
        return redirect(url_for(target_route))

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT full_name, email, phone_number, dob, nysc_status,
                       cv_url, eligibility_flag, eligibility_flag_reason,
                       stage_updated_at, created_at, role
                FROM candidates WHERE id = %s;
            """, (candidate_id,))
            cand = cur.fetchone()

            # Slot info for interview stages
            slot_info = None
            if stage in ("interview_scheduled", "interview_completed"):
                cur.execute("""
                    SELECT gs.start_time, gs.end_time, gs.meeting_link,
                           gs.meeting_provider, i.name as interviewer_name
                    FROM generated_slots gs
                    LEFT JOIN interviewers i ON gs.interviewer_id = i.id
                    WHERE gs.candidate_id = %s AND gs.is_booked = TRUE
                    ORDER BY gs.start_time DESC LIMIT 1;
                """, (candidate_id,))
                slot_info = cur.fetchone()

            # Score info
            latest_score = None
            cur.execute("""
                SELECT score, score_fraction, pass_fail, taken_at
                FROM scores WHERE candidate_id = %s
                ORDER BY taken_at DESC LIMIT 1;
            """, (candidate_id,))
            latest_score = cur.fetchone()

            # Document upload status
            docs = []
            cur.execute("""
                SELECT doc_type, url, verified, upload_status
                FROM candidate_documents WHERE candidate_id = %s;
            """, (candidate_id,))
            docs = cur.fetchall()

            # Stage config for current pipeline info
            cur.execute("""
                SELECT stage_name, opens_at, closes_at, duration_minutes,
                       relative_deadline_hours
                FROM stage_config
                ORDER BY id;
            """)
            stage_configs = cur.fetchall()

            cur.execute("""
                SELECT from_stage, to_stage, changed_at, changed_by, reason
                FROM candidate_stage_history
                WHERE candidate_id = %s
                ORDER BY changed_at DESC
                LIMIT 20;
            """, (candidate_id,))
            stage_history = cur.fetchall()

            # Clean and format stage history list
            stage_history_formatted = []
            for item in stage_history:
                from_s, to_s, ch_at, ch_by, reason = item
                ch_at_str = ch_at.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M %p").lower() if ch_at else ""
                
                # Hide admin override reasons
                clean_reason = None
                if reason and "override" not in reason.lower():
                    clean_reason = reason
                    
                stage_history_formatted.append((from_s, to_s, ch_at_str, ch_by, clean_reason))

            stage_windows = {}
            for sc in stage_configs:
                s_name = sc[0]
                opens = sc[1]
                closes = sc[2]
                opens_str = opens.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M %p").lower() if opens else None
                closes_str = closes.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M %p").lower() if closes else None
                stage_windows[s_name] = {
                    "opens_at": opens_str,
                    "closes_at": closes_str
                }

    return render_template(
        "candidate_dashboard.html",
        candidate=cand,
        stage=stage,
        slot_info=slot_info,
        latest_score=latest_score,
        docs=docs,
        stage_configs=stage_configs,
        stage_history=stage_history_formatted,
        stage_windows=stage_windows,
        required_docs=get_role_document_requirements(cand[10] if cand else None),
        now=datetime.datetime.utcnow(),
    )


@recruitment.route("/assessment")
@require_stage("screening_passed", "screening_flagged", "assessment_in_progress")
def assessment():
    candidate_id = g.candidate_id
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT email, full_name, phone_number, role, location
                FROM candidates WHERE id = %s;
            """, (candidate_id,))
            cand = cur.fetchone()

    if cand:
        email, full_name, phone_number, role, location = cand
    else:
        email, full_name, phone_number, role, location = "", "", "", "", ""

    return render_template(
        "assessment.html",
        stage=g.candidate_stage,
        email=email,
        full_name=full_name,
        phone_number=phone_number,
        role=role,
        location=location
    )


@recruitment.route("/schedule")
@require_stage("assessment_passed", "interview_slot_pending")
def schedule():
    return render_template("schedule_interview.html")


@recruitment.route("/documents")
@require_stage("documents_pending", "documents_submitted")
def documents():
    candidate_id = g.candidate_id

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM candidates WHERE id = %s;", (candidate_id,))
            cand_role = (cur.fetchone() or [None])[0]
            cur.execute("""
                SELECT doc_type, url, verified, upload_status, uploaded_at, rejection_note, id
                FROM candidate_documents WHERE candidate_id = %s;
            """, (candidate_id,))
            uploaded = cur.fetchall()

    required_docs = get_role_document_requirements(cand_role)
    submitted = {row[0]: row for row in uploaded}
    return render_template(
        "upload_documents.html",
        required_docs=required_docs,
        submitted=submitted,
    )


@recruitment.route("/interview")
@require_stage("interview_scheduled", "interview_completed")
def interview():
    candidate_id = g.candidate_id

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT gs.start_time, gs.end_time, gs.meeting_link, gs.meeting_provider,
                       i.name, i.email
                FROM generated_slots gs
                LEFT JOIN interviewers i ON gs.interviewer_id = i.id
                WHERE gs.candidate_id = %s AND gs.is_booked = TRUE
                ORDER BY gs.start_time DESC LIMIT 1;
            """, (candidate_id,))
            slot = cur.fetchone()

            # Admin-configurable instructions block
            cur.execute("""
                SELECT interview_instructions FROM stage_config
                WHERE stage_name = 'interview' LIMIT 1;
            """)
            row = cur.fetchone()
            instructions = (row[0] if row and row[0] else
                            "Test your camera and microphone before joining. "
                            "Please join 5 minutes early.")

    join_active = False
    if slot and slot[0]:
        delta = slot[0] - datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        join_active = delta.total_seconds() <= 900  # within 15 min

    return render_template(
        "interview.html",
        slot=slot,
        join_active=join_active,
        instructions=instructions,
    )


# ── Application submission ────────────────────────────────────────────────────

@recruitment.route("/api/apply", methods=["POST"])
def api_apply():
    # Support multipart (file upload) or JSON
    if request.content_type and "multipart" in request.content_type:
        data = request.form
        cv_file = request.files.get("cv_file")
    else:
        data = request.json or {}
        cv_file = None

    full_name    = data.get("full_name", "").strip()
    email        = data.get("email", "").strip().lower()
    phone_number = data.get("phone_number", "").strip()
    dob_str      = data.get("dob", "").strip()
    nysc_status  = data.get("nysc_status", "").strip()
    role         = data.get("role", "").strip()
    location     = data.get("location", "").strip()

    # Fetch settings from DB to enforce dynamic validation
    DEFAULT_FIELDS = {
        "full_name": {"enabled": True, "required": True},
        "email": {"enabled": True, "required": True},
        "phone_number": {"enabled": True, "required": True},
        "dob": {"enabled": True, "required": True},
        "location": {"enabled": True, "required": False},
        "department": {"enabled": True, "required": False},
    }

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pre_test_fields FROM exam_settings WHERE id = 1;")
            db_row = cur.fetchone()
            pre_test_fields = db_row[0] if db_row and db_row[0] else []

    fields_config = {**DEFAULT_FIELDS}
    for f in pre_test_fields:
        key = f.get("key")
        if key in fields_config:
            if key in ("full_name", "email"):
                continue
            fields_config[key] = {
                "enabled": bool(f.get("enabled", True)),
                "required": bool(f.get("required", True))
            }

    # Core required fields validation
    if not full_name or not email:
        return jsonify({"error": "Full name and email are required."}), 400

    # Dynamic validations
    if fields_config["phone_number"]["enabled"]:
        if fields_config["phone_number"]["required"] and not phone_number:
            return jsonify({"error": "Phone number is required."}), 400
    else:
        phone_number = None

    dob = None
    if fields_config["dob"]["enabled"]:
        if fields_config["dob"]["required"] and not dob_str:
            return jsonify({"error": "Date of birth is required."}), 400
        if dob_str:
            try:
                dob = datetime.date.fromisoformat(dob_str)
            except ValueError:
                return jsonify({"error": "Invalid date of birth format. Use YYYY-MM-DD."}), 400
    else:
        dob_str = None

    if not nysc_status:
        return jsonify({"error": "NYSC status is required."}), 400
    valid_nysc = ["exempted", "completed", "serving", "not_started"]
    if nysc_status not in valid_nysc:
        return jsonify({"error": f"NYSC status must be one of: {', '.join(valid_nysc)}"}), 400

    if fields_config["department"]["enabled"]:
        if fields_config["department"]["required"] and not role:
            return jsonify({"error": "Role applied for is required."}), 400
    else:
        role = None

    if fields_config["location"]["enabled"]:
        if fields_config["location"]["required"] and not location:
            return jsonify({"error": "Location preference is required."}), 400
    else:
        location = None

    # Validate CV file
    cv_file_bytes = None
    cv_mimetype   = None
    if cv_file:
        cv_file_bytes = cv_file.read()
        cv_mimetype   = cv_file.mimetype
        err = validate_file(cv_file_bytes, cv_mimetype, ALLOWED_CV_MIMETYPES,
                            cv_file.filename)
        if err:
            return jsonify({"error": err}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Check for duplicate application
            cur.execute("SELECT id, stage FROM candidates WHERE email = %s;", (email,))
            existing = cur.fetchone()

            if existing:
                # Allow re-apply only if they haven't progressed past application
                if existing[1] not in ("applied", None):
                    return jsonify({
                        "error": "An application for this email already exists."
                    }), 400
                candidate_id = existing[0]
                cur.execute("""
                    UPDATE candidates
                    SET full_name = %s, phone_number = %s, dob = %s,
                        nysc_status = %s, role = %s, location = %s,
                        stage = 'applied', stage_updated_at = NOW()
                    WHERE id = %s;
                """, (full_name, phone_number, dob, nysc_status, role, location, candidate_id))
            else:
                import secrets
                ref_token = secrets.token_hex(6)
                cur.execute("""
                    INSERT INTO candidates
                        (full_name, email, phone_number, dob, nysc_status,
                         role, location, stage, stage_updated_at, ref_token)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'applied', NOW(), %s)
                    RETURNING id;
                """, (full_name, email, phone_number, dob, nysc_status, role, location, ref_token))
                candidate_id = cur.fetchone()[0]
        conn.commit()

    session["candidate_id"] = candidate_id
    session["candidate_email"] = email

    # Fire CV upload synchronously if file was provided
    upload_job_id = None
    if cv_file_bytes:
        folder = get_or_create_cloudinary_folder(candidate_id)
        upload_job_id = enqueue_upload(
            cv_file_bytes, folder, "cv",
            candidate_id=candidate_id,
            resource_type="image",
            target_field="cv_url",
        )

    # Run eligibility screening synchronously for serverless environment
    new_stage = apply_screening(candidate_id)
    event_map = {
        "screening_passed":  "screening_passed",
        "screening_flagged": "screening_flagged",
        "screening_failed":  "screening_failed",
    }
    try:
        send_notification(candidate_id, new_stage, "application_submitted")
        send_notification(candidate_id, new_stage, event_map.get(new_stage, "application_submitted"))
    except Exception as e:
        print(f"Error sending notifications during apply: {e}")

    return jsonify({
        "status": "success",
        "candidate_id": candidate_id,
        "upload_job_id": upload_job_id,
        "message": "Application received. Eligibility screening in progress.",
    })


# ── Upload status polling ─────────────────────────────────────────────────────

@recruitment.route("/api/upload-status/<job_id>")
def upload_status(job_id):
    result = get_job_status(job_id)
    if not result:
        return jsonify({"error": "Job not found."}), 404
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401
    # Upload job identifiers are not authorization tokens.
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM upload_jobs WHERE id = %s AND candidate_id = %s;",
                        (job_id, candidate_id))
            if not cur.fetchone():
                return jsonify({"error": "Job not found."}), 404
    return jsonify(result)


@recruitment.route("/api/candidate/cv/preview")
def candidate_cv_preview():
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return "Please sign in to view this file.", 401
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uj.public_id, c.cv_url
                FROM candidates c
                JOIN upload_jobs uj ON uj.candidate_id = c.id
                WHERE c.id = %s AND uj.target_field = 'cv_url'
                  AND uj.status = 'done' AND uj.public_id IS NOT NULL
                ORDER BY uj.updated_at DESC LIMIT 1;
            """, (candidate_id,))
            row = cur.fetchone()
    if not row:
        return "This file is not available yet.", 404
    return _inline_candidate_asset(row[0], row[1])


@recruitment.route("/api/candidate/documents/<int:doc_id>/preview")
def candidate_document_preview(doc_id):
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return "Please sign in to view this file.", 401
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT public_id, url FROM candidate_documents
                WHERE id = %s AND candidate_id = %s AND public_id IS NOT NULL;
            """, (doc_id, candidate_id))
            row = cur.fetchone()
    if not row:
        return "This file is not available.", 404
    return _inline_candidate_asset(row[0], row[1])


# ── Assessment endpoints ──────────────────────────────────────────────────────

@recruitment.route("/api/assessment/start", methods=["POST"])
def assessment_start():
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Fetch seconds_per_question from settings
            cur.execute("SELECT seconds_per_question FROM exam_settings WHERE id = 1;")
            settings_row = cur.fetchone()
            seconds_per_q = settings_row[0] if settings_row else 60

            cur.execute("SELECT stage FROM candidates WHERE id = %s FOR UPDATE;",
                        (candidate_id,))
            row = cur.fetchone()

            if not row:
                return jsonify({"error": "Candidate not found."}), 404

            stage = row[0]
            if stage not in ("screening_passed", "screening_flagged", "assessment_in_progress"):
                return jsonify({"error": f"Cannot start assessment in stage '{stage}'."}), 403

            # Check if already in progress with an unexpired attempt
            cur.execute("""
                SELECT id, started_at, duration_seconds, score
                FROM scores
                WHERE candidate_id = %s AND pass_fail IS NULL
                ORDER BY started_at DESC LIMIT 1;
            """, (candidate_id,))
            in_progress = cur.fetchone()

            if in_progress:
                # Resume existing attempt if still within time window
                score_id, started_at, duration_s, _ = in_progress
                elapsed = (datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
                           - started_at).total_seconds()
                # Get configured duration
                cur.execute("""
                    SELECT duration_minutes FROM stage_config
                    WHERE stage_name = 'assessment' ORDER BY cycle_id DESC LIMIT 1;
                """)
                cfg = cur.fetchone()
                allowed_secs = (cfg[0] * 60) if cfg and cfg[0] else 3600

                if elapsed > allowed_secs:
                    # Time's up — auto-fail this attempt
                    _auto_submit_assessment(candidate_id, score_id, conn, cur)
                    conn.commit()
                    return jsonify({"error": "Assessment time has expired."}), 403

                # Resume: return questions in original order
                cur.execute("SELECT question_order FROM scores WHERE id = %s;", (score_id,))
                q_order_row = cur.fetchone()
                question_ids = None
                if q_order_row and q_order_row[0]:
                    question_ids = (
                        q_order_row[0]
                        if isinstance(q_order_row[0], list)
                        else json.loads(q_order_row[0])
                    )

                questions = _fetch_ordered_questions(cur, question_ids)
                remaining_secs = int(allowed_secs - elapsed)

                return jsonify({
                    "score_id": score_id,
                    "questions": questions,
                    "remaining_seconds": remaining_secs,
                    "started_at": started_at.isoformat(),
                    "seconds_per_question": seconds_per_q,
                })

            # Fetch stage config for duration
            cur.execute("""
                SELECT duration_minutes FROM stage_config
                WHERE stage_name = 'assessment' ORDER BY cycle_id DESC LIMIT 1;
            """)
            cfg = cur.fetchone()
            duration_mins = (cfg[0] if cfg and cfg[0] else 60)

            # Fetch and shuffle questions deterministically
            cur.execute("""
                SELECT id, section, stem, option_a, option_b, option_c, option_d, position
                FROM questions WHERE active = TRUE
                ORDER BY section, position ASC;
            """)
            all_q = cur.fetchall()

            by_sec = {"Numerical": [], "Verbal": [], "Logical": []}
            for q in all_q:
                if q[1] in by_sec:
                    by_sec[q[1]].append(q)

            rng = random.Random(candidate_id)
            for sec in by_sec:
                rng.shuffle(by_sec[sec])

            ordered = by_sec["Numerical"] + by_sec["Verbal"] + by_sec["Logical"]
            question_ids = [q[0] for q in ordered]

            questions = [{
                "id": q[0], "section": q[1], "stem": q[2],
                "options": [q[3], q[4], q[5], q[6]],
            } for q in ordered]

            # Create scores row
            cur.execute("""
                INSERT INTO scores
                    (candidate_id, stage_label, started_at, duration_seconds, question_order)
                VALUES (%s, 'assessment_round_1', NOW(), %s, %s)
                RETURNING id;
            """, (candidate_id, duration_mins * 60, json.dumps(question_ids)))
            score_id = cur.fetchone()[0]

            # Advance stage to assessment_in_progress
            cur.execute("""
                UPDATE candidates
                SET stage = 'assessment_in_progress', stage_updated_at = NOW()
                WHERE id = %s;
            """, (candidate_id,))
            cur.execute("""
                INSERT INTO candidate_stage_history
                    (candidate_id, from_stage, to_stage, changed_by)
                VALUES (%s, %s, 'assessment_in_progress', 'system');
            """, (candidate_id, stage))

        conn.commit()

    return jsonify({
        "score_id": score_id,
        "questions": questions,
        "duration_seconds": duration_mins * 60,
        "seconds_per_question": seconds_per_q,
    })


def _fetch_ordered_questions(cur, question_ids: list | None) -> list:
    if not question_ids:
        cur.execute("""
            SELECT id, section, stem, option_a, option_b, option_c, option_d
            FROM questions WHERE active = TRUE ORDER BY section, position;
        """)
        rows = cur.fetchall()
    else:
        fmt = ",".join(["%s"] * len(question_ids))
        cur.execute(f"""
            SELECT id, section, stem, option_a, option_b, option_c, option_d
            FROM questions WHERE id IN ({fmt});
        """, question_ids)
        rows_map = {r[0]: r for r in cur.fetchall()}
        rows = [rows_map[qid] for qid in question_ids if qid in rows_map]

    return [{
        "id": r[0], "section": r[1], "stem": r[2],
        "options": [r[3], r[4], r[5], r[6]],
    } for r in rows]


def _auto_submit_assessment(candidate_id: int, score_id: int, conn, cur):
    """Mark an expired assessment as failed (called with existing conn/cursor)."""
    cur.execute("""
        SELECT pass_mark FROM stage_config
        WHERE stage_name = 'assessment' ORDER BY cycle_id DESC LIMIT 1;
    """)
    cfg = cur.fetchone()
    pass_mark = float(cfg[0]) if cfg and cfg[0] else 50.0

    cur.execute("""
        UPDATE scores
        SET score = 0, score_fraction = '0/0', pass_fail = 'FAIL',
            taken_at = NOW(), time_taken_secs = duration_seconds
        WHERE id = %s;
    """, (score_id,))

    new_stage = "assessment_failed"
    cur.execute("""
        UPDATE candidates
        SET stage = %s, stage_updated_at = NOW()
        WHERE id = %s;
    """, (new_stage, candidate_id))
    cur.execute("""
        INSERT INTO candidate_stage_history
            (candidate_id, from_stage, to_stage, changed_by, reason)
        VALUES (%s, 'assessment_in_progress', %s, 'system', 'time_expired');
    """, (candidate_id, new_stage))


@recruitment.route("/api/assessment/submit", methods=["POST"])
def assessment_submit():
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401

    data = request.json or {}
    score_id    = data.get("score_id")
    answers     = data.get("answers", [])
    tab_switches = data.get("tab_switches", 0)
    time_taken   = data.get("time_taken_secs", 0)

    if not score_id:
        return jsonify({"error": "Missing score_id."}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Verify this score row belongs to this candidate and is still open
            cur.execute("""
                SELECT started_at, duration_seconds, pass_fail, question_order
                FROM scores WHERE id = %s AND candidate_id = %s
                FOR UPDATE;
            """, (score_id, candidate_id))
            row = cur.fetchone()

            if not row:
                return jsonify({"error": "Score record not found."}), 404

            started_at, duration_s, already_graded, question_order_json = row

            if already_graded is not None:
                return jsonify({"error": "Assessment already submitted."}), 400

            # Server-side time enforcement
            elapsed = (datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
                       - started_at).total_seconds()
            if elapsed > (duration_s or 3600) + 30:  # 30s grace
                _auto_submit_assessment(candidate_id, score_id, conn, cur)
                conn.commit()
                return jsonify({"error": "Assessment time has expired."}), 403

            # Score the answers
            cur.execute("""
                SELECT id, section, answer FROM questions WHERE active = TRUE;
            """)
            q_map = {q[0]: {"section": q[1], "answer": q[2]} for q in cur.fetchall()}

            cur.execute("""
                SELECT pass_mark FROM stage_config
                WHERE stage_name = 'assessment' ORDER BY cycle_id DESC LIMIT 1;
            """)
            cfg = cur.fetchone()
            pass_mark = float(cfg[0]) if cfg and cfg[0] else 50.0

            ans_map = {a.get("question_id"): a for a in answers}
            total_correct = 0
            total_active  = len(q_map)
            breakdown = []

            for q_id, q_data in q_map.items():
                ans = ans_map.get(q_id)
                correct = q_data["answer"]
                section = q_data["section"]

                if ans:
                    given = ans.get("answer_given")
                    timed_out = ans.get("was_timeout", False)
                    spent = ans.get("time_spent_secs", 0)
                    if given is not None:
                        given = int(given)
                    is_correct = (given == correct) and not timed_out
                    if is_correct:
                        total_correct += 1
                else:
                    given, timed_out, spent, is_correct = None, True, 0, False

                breakdown.append({
                    "id": q_id, "section": section,
                    "answer_given": given, "correct_answer": correct,
                    "is_correct": is_correct, "was_timeout": timed_out,
                    "time_spent_secs": spent,
                })

            score_pct = round((total_correct / total_active * 100), 2) if total_active else 0
            score_frac = f"{total_correct}/{total_active}"
            pf = "PASS" if score_pct >= pass_mark else "FAIL"
            new_stage = "assessment_passed" if pf == "PASS" else "assessment_failed"

            cur.execute("""
                UPDATE scores
                SET score = %s, score_fraction = %s, pass_fail = %s,
                    taken_at = NOW(), time_taken_secs = %s,
                    tab_switches = %s, breakdown_json = %s
                WHERE id = %s;
            """, (score_pct, score_frac, pf, time_taken, tab_switches,
                  json.dumps(breakdown), score_id))

            # Advance candidate stage
            cur.execute("""
                UPDATE candidates SET stage = %s, stage_updated_at = NOW()
                WHERE id = %s;
            """, (new_stage, candidate_id))
            cur.execute("""
                INSERT INTO candidate_stage_history
                    (candidate_id, from_stage, to_stage, changed_by, reason)
                VALUES (%s, 'assessment_in_progress', %s, 'system', %s);
            """, (candidate_id, new_stage, f"score={score_pct}% pass_mark={pass_mark}%"))

            if new_stage == "assessment_passed":
                # Open interview slot booking
                cur.execute("""
                    UPDATE candidates SET stage = 'interview_slot_pending', stage_updated_at = NOW()
                    WHERE id = %s;
                """, (candidate_id,))
                cur.execute("""
                    INSERT INTO candidate_stage_history
                        (candidate_id, from_stage, to_stage, changed_by)
                    VALUES (%s, 'assessment_passed', 'interview_slot_pending', 'system');
                """, (candidate_id,))
                final_stage = "interview_slot_pending"
            else:
                final_stage = new_stage

        conn.commit()

    event = "assessment_passed" if pf == "PASS" else "assessment_failed"
    try:
        send_notification(candidate_id, final_stage, event)
    except Exception as e:
        print(f"Error sending assessment notification: {e}")

    return jsonify({
        "score_percent": score_pct,
        "score_fraction": score_frac,
        "pass_fail": pf,
        "breakdown": breakdown,
        "new_stage": final_stage,
    })


# ── Interview scheduling ──────────────────────────────────────────────────────

@recruitment.route("/api/slots")
def get_slots():
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401

    year  = request.args.get("year",  type=int, default=datetime.date.today().year)
    month = request.args.get("month", type=int, default=datetime.date.today().month)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT gs.id, gs.start_time, gs.end_time,
                       i.name AS interviewer_name,
                       gs.is_booked,
                       ar.booking_lead_time_hours
                FROM generated_slots gs
                JOIN interviewers i ON gs.interviewer_id = i.id
                LEFT JOIN availability_rules ar ON gs.availability_rule_id = ar.id
                WHERE gs.is_blocked = FALSE
                  AND gs.is_booked = FALSE
                  AND EXTRACT(YEAR  FROM gs.start_time AT TIME ZONE 'Africa/Lagos') = %s
                  AND EXTRACT(MONTH FROM gs.start_time AT TIME ZONE 'Africa/Lagos') = %s
                ORDER BY gs.start_time;
            """, (year, month))
            rows = cur.fetchall()

    now_utc = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    slots = []
    for r in rows:
        lead_hours = r[5] or 24
        bookable = (
            not r[4] and
            (r[1] - now_utc).total_seconds() > lead_hours * 3600
        )
        slots.append({
            "id": r[0],
            "start_time": r[1].isoformat(),
            "end_time":   r[2].isoformat(),
            "interviewer": r[3],
            "is_booked":   r[4],
            "bookable":    bookable,
        })

    return jsonify(slots)


@recruitment.route("/api/slots/<int:slot_id>/book", methods=["POST"])
def book_slot(slot_id):
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stage FROM candidates WHERE id = %s;", (candidate_id,))
            row = cur.fetchone()
            if not row or row[0] not in ("interview_slot_pending", "assessment_passed"):
                return jsonify({"error": "Cannot book a slot at your current stage."}), 403

            # Atomic slot claim with row lock
            cur.execute("""
                SELECT gs.id, gs.start_time, gs.end_time, gs.is_booked, gs.is_blocked,
                       i.id AS interviewer_id, i.name, i.email, i.meeting_provider,
                       i.google_calendar_id, i.zoom_user_id,
                       ar.booking_lead_time_hours
                FROM generated_slots gs
                JOIN interviewers i ON gs.interviewer_id = i.id
                LEFT JOIN availability_rules ar ON gs.availability_rule_id = ar.id
                WHERE gs.id = %s
                FOR UPDATE OF gs;
            """, (slot_id,))
            slot_row = cur.fetchone()

            if not slot_row:
                return jsonify({"error": "Slot not found."}), 404

            if slot_row[3]:  # is_booked
                return jsonify({"error": "This slot has already been taken. Please choose another."}), 409

            if slot_row[4]:  # is_blocked
                return jsonify({"error": "This slot is not available."}), 409

            lead_hours = slot_row[11] or 24
            now_utc = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
            if (slot_row[1] - now_utc).total_seconds() < lead_hours * 3600:
                return jsonify({"error": "This slot is within the booking lead-time window."}), 409

            # Build dicts for meeting creation
            slot_dict = {"id": slot_row[0], "start_time": slot_row[1], "end_time": slot_row[2]}
            interviewer_dict = {
                "id": slot_row[5], "name": slot_row[6], "email": slot_row[7],
                "meeting_provider": slot_row[8],
                "google_calendar_id": slot_row[9], "zoom_user_id": slot_row[10],
            }
            cur.execute("SELECT full_name, email FROM candidates WHERE id = %s;", (candidate_id,))
            cand_row = cur.fetchone()
            candidate_dict = {"name": cand_row[0], "email": cand_row[1]}

            # Create meeting
            meeting_link = ""
            external_event_id = ""
            try:
                result = create_meeting(slot_dict, interviewer_dict, candidate_dict)
                meeting_link      = result.get("meeting_link", "")
                external_event_id = result.get("external_event_id", "")
            except Exception as exc:
                print(f"[WARNING] Meeting creation failed: {exc}. Proceeding without link.")

            # Mark slot as booked
            cur.execute("""
                UPDATE generated_slots
                SET is_booked = TRUE, candidate_id = %s,
                    meeting_link = %s, external_event_id = %s,
                    meeting_provider = %s
                WHERE id = %s;
            """, (candidate_id, meeting_link, external_event_id,
                  interviewer_dict["meeting_provider"], slot_id))

            # Advance candidate stage
            cur.execute("""
                UPDATE candidates
                SET stage = 'interview_scheduled', stage_updated_at = NOW()
                WHERE id = %s;
            """, (candidate_id,))
            cur.execute("""
                INSERT INTO candidate_stage_history
                    (candidate_id, from_stage, to_stage, changed_by)
                VALUES (%s, 'interview_slot_pending', 'interview_scheduled', 'system');
            """, (candidate_id,))

        conn.commit()

    interview_time = slot_row[1].astimezone(LOCAL_TZ).strftime("%A %d %B %Y at %H:%M WAT")
    try:
        send_notification(candidate_id, "interview_scheduled", "interview_booked",
                          {"interview_time": interview_time, "meeting_link": meeting_link})
    except Exception as e:
        print(f"Error sending booking notification: {e}")

    return jsonify({
        "status": "success",
        "message": "Interview booked successfully.",
        "slot_id": slot_id,
        "start_time": slot_row[1].isoformat(),
        "meeting_link": meeting_link,
    })


# ── Document upload ───────────────────────────────────────────────────────────

@recruitment.route("/api/documents/upload", methods=["POST"])
def upload_document():
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stage, role FROM candidates WHERE id = %s;", (candidate_id,))
            row = cur.fetchone()

    if not row or row[0] not in ("documents_pending", "documents_submitted"):
        return jsonify({"error": "Document uploads are not open at your current stage."}), 403
    allowed_docs = [d["document_type"] for d in get_role_document_requirements(row[1])]

    doc_type  = request.form.get("doc_type", "").strip()
    doc_file  = request.files.get("file")

    if not doc_type or doc_type not in allowed_docs:
        return jsonify({"error": f"Invalid document type '{doc_type}'."}), 400

    if not doc_file:
        return jsonify({"error": "No file provided."}), 400

    file_bytes = doc_file.read()
    mimetype   = doc_file.mimetype
    err = validate_file(file_bytes, mimetype, ALLOWED_DOC_MIMETYPES,
                        doc_file.filename)
    if err:
        return jsonify({"error": err}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Upsert a pending document row
            cur.execute("""
                INSERT INTO candidate_documents (candidate_id, doc_type, upload_status)
                VALUES (%s, %s, 'pending')
                ON CONFLICT (candidate_id, doc_type) DO UPDATE
                SET upload_status = 'pending',
                    verified = FALSE,
                    rejection_note = NULL,
                    rejected_at = NULL;
            """, (candidate_id, doc_type))
        conn.commit()

    folder = get_or_create_cloudinary_folder(candidate_id)
    job_id = enqueue_upload(
        file_bytes, folder, doc_type,
        candidate_id=candidate_id,
        resource_type="image",
        doc_type=doc_type,
    )

    return jsonify({
        "status": "processing",
        "doc_type": doc_type,
        "upload_job_id": job_id,
        "message": "Upload in progress.",
    })


@recruitment.route("/api/documents/submit", methods=["POST"])
def submit_documents():
    """Called when candidate marks all documents as uploaded."""
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stage FROM candidates WHERE id = %s;", (candidate_id,))
            row = cur.fetchone()
            if not row or row[0] != "documents_pending":
                return jsonify({"error": "Cannot submit documents at this stage."}), 403

            cur.execute("SELECT role FROM candidates WHERE id = %s;", (candidate_id,))
            role = (cur.fetchone() or [None])[0]
            required = [d["document_type"] for d in get_role_document_requirements(role) if d["required"]]
            cur.execute("""
                SELECT doc_type FROM candidate_documents
                WHERE candidate_id = %s AND upload_status = 'done' AND url IS NOT NULL;
            """, (candidate_id,))
            uploaded = {r[0] for r in cur.fetchall()}
            missing = [d for d in required if d not in uploaded]
            if missing:
                return jsonify({"error": "Upload all required employment documents before submitting."}), 400

            cur.execute("""
                UPDATE candidates
                SET stage = 'documents_submitted', stage_updated_at = NOW()
                WHERE id = %s;
            """, (candidate_id,))
            cur.execute("""
                INSERT INTO candidate_stage_history
                    (candidate_id, from_stage, to_stage, changed_by)
                VALUES (%s, 'documents_pending', 'documents_submitted', 'candidate');
            """, (candidate_id,))
        conn.commit()

    return jsonify({"status": "success", "message": "Documents submitted for review."})


# ── Logout ────────────────────────────────────────────────────────────────────

@recruitment.route("/recruitment/logout", methods=["POST"])
def logout():
    session.pop("candidate_id", None)
    session.pop("candidate_email", None)
    return jsonify({"status": "success"})
