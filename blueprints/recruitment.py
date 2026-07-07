"""
Candidate-facing recruitment pipeline routes.
All stage-sensitive routes use the @require_stage decorator.
"""
import json
import random
import datetime
import threading
from functools import wraps

from flask import (Blueprint, request, jsonify, render_template,
                   session, redirect, url_for, g)

from db import DBConnection
from services.notifications import send_notification
from services.upload import (validate_file, enqueue_upload, get_job_status,
                              ALLOWED_CV_MIMETYPES, ALLOWED_DOC_MIMETYPES)
from services.screening import apply_screening
from services.meetings import create_meeting

recruitment = Blueprint("recruitment", __name__)

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
                        "SELECT stage FROM candidates WHERE id = %s",
                        (candidate_id,)
                    )
                    row = cur.fetchone()

            if not row:
                session.pop("candidate_id", None)
                return redirect(url_for("recruitment.apply"))

            current_stage = row[0] or "applied"
            g.candidate_stage = current_stage
            g.candidate_id = candidate_id

            if current_stage not in allowed_stages:
                return _stage_redirect(current_stage)

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

@recruitment.route("/apply")
def apply():
    if session.get("candidate_id"):
        return redirect(url_for("recruitment.dashboard"))
    return render_template("apply.html")


@recruitment.route("/dashboard")
@require_stage(*list(STAGE_ROUTES.keys()))
def dashboard():
    candidate_id = g.candidate_id
    stage = g.candidate_stage

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT full_name, email, phone_number, dob, nysc_status,
                       cv_url, eligibility_flag, eligibility_flag_reason,
                       stage_updated_at, created_at
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

    return render_template(
        "candidate_dashboard.html",
        candidate=cand,
        stage=stage,
        slot_info=slot_info,
        latest_score=latest_score,
        docs=docs,
        stage_configs=stage_configs,
        required_docs=REQUIRED_DOCUMENTS,
        now=datetime.datetime.utcnow(),
    )


@recruitment.route("/assessment")
@require_stage("assessment_in_progress")
def assessment():
    return render_template("assessment.html")


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
            cur.execute("""
                SELECT doc_type, url, verified, upload_status, uploaded_at
                FROM candidate_documents WHERE candidate_id = %s;
            """, (candidate_id,))
            uploaded = cur.fetchall()

    submitted = {row[0]: row for row in uploaded}
    return render_template(
        "upload_documents.html",
        required_docs=REQUIRED_DOCUMENTS,
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

    if not all([full_name, email, phone_number, dob_str, nysc_status]):
        return jsonify({"error": "All fields are required."}), 400

    try:
        dob = datetime.date.fromisoformat(dob_str)
    except ValueError:
        return jsonify({"error": "Invalid date of birth format. Use YYYY-MM-DD."}), 400

    valid_nysc = ["exempted", "completed", "serving", "not_started"]
    if nysc_status not in valid_nysc:
        return jsonify({"error": f"NYSC status must be one of: {', '.join(valid_nysc)}"}), 400

    # Validate CV file
    cv_file_bytes = None
    cv_mimetype   = None
    if cv_file:
        cv_file_bytes = cv_file.read()
        cv_mimetype   = cv_file.mimetype
        err = validate_file(cv_file_bytes, cv_mimetype, ALLOWED_CV_MIMETYPES)
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
                cur.execute("""
                    INSERT INTO candidates
                        (full_name, email, phone_number, dob, nysc_status,
                         role, location, stage, stage_updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'applied', NOW())
                    RETURNING id;
                """, (full_name, email, phone_number, dob, nysc_status, role, location))
                candidate_id = cur.fetchone()[0]
        conn.commit()

    session["candidate_id"] = candidate_id
    session["candidate_email"] = email

    # Fire CV upload in background if file was provided
    upload_job_id = None
    if cv_file_bytes:
        folder = f"candidates/cv/{candidate_id}"
        upload_job_id = enqueue_upload(
            cv_file_bytes, folder, "cv",
            candidate_id=candidate_id,
            resource_type="raw",
            target_field="cv_url",
        )

    # Run eligibility screening in background thread
    def _screen_and_notify(cid):
        new_stage = apply_screening(cid)
        event_map = {
            "screening_passed":  "screening_passed",
            "screening_flagged": "screening_flagged",
            "screening_failed":  "screening_failed",
        }
        send_notification(cid, new_stage, "application_submitted")
        send_notification(cid, new_stage, event_map.get(new_stage, "application_submitted"))

    threading.Thread(target=_screen_and_notify, args=(candidate_id,), daemon=True).start()

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
    return jsonify(result)


# ── Assessment endpoints ──────────────────────────────────────────────────────

@recruitment.route("/api/assessment/start", methods=["POST"])
def assessment_start():
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "Not authenticated."}), 401

    with DBConnection() as conn:
        with conn.cursor() as cur:
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
                question_ids = json.loads(q_order_row[0]) if q_order_row and q_order_row[0] else None

                questions = _fetch_ordered_questions(cur, question_ids)
                remaining_secs = int(allowed_secs - elapsed)

                return jsonify({
                    "score_id": score_id,
                    "questions": questions,
                    "remaining_seconds": remaining_secs,
                    "started_at": started_at.isoformat(),
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
    threading.Thread(
        target=send_notification,
        args=(candidate_id, final_stage, event),
        daemon=True,
    ).start()

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
                FOR UPDATE;
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

    interview_time = slot_row[1].strftime("%A %d %B %Y at %H:%M WAT")
    threading.Thread(
        target=send_notification,
        args=(candidate_id, "interview_scheduled", "interview_booked",
              {"interview_time": interview_time, "meeting_link": meeting_link}),
        daemon=True,
    ).start()

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
            cur.execute("SELECT stage FROM candidates WHERE id = %s;", (candidate_id,))
            row = cur.fetchone()

    if not row or row[0] not in ("documents_pending", "documents_submitted",
                                  "interview_slot_pending", "interview_scheduled"):
        return jsonify({"error": "Document uploads are not open at your current stage."}), 403

    doc_type  = request.form.get("doc_type", "").strip()
    doc_file  = request.files.get("file")

    if not doc_type or doc_type not in REQUIRED_DOCUMENTS + ["other"]:
        return jsonify({"error": f"Invalid document type '{doc_type}'."}), 400

    if not doc_file:
        return jsonify({"error": "No file provided."}), 400

    file_bytes = doc_file.read()
    mimetype   = doc_file.mimetype
    err = validate_file(file_bytes, mimetype, ALLOWED_DOC_MIMETYPES)
    if err:
        return jsonify({"error": err}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Upsert a pending document row
            cur.execute("""
                INSERT INTO candidate_documents (candidate_id, doc_type, upload_status)
                VALUES (%s, %s, 'pending')
                ON CONFLICT DO NOTHING;
            """, (candidate_id, doc_type))
            # Ensure we have a row to update
            cur.execute("""
                SELECT id FROM candidate_documents
                WHERE candidate_id = %s AND doc_type = %s LIMIT 1;
            """, (candidate_id, doc_type))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO candidate_documents (candidate_id, doc_type, upload_status)
                    VALUES (%s, %s, 'pending');
                """, (candidate_id, doc_type))

            # Advance to documents_pending if not already in a later stage
            cur.execute("""
                UPDATE candidates
                SET stage = CASE
                    WHEN stage IN ('assessment_passed', 'interview_slot_pending',
                                   'interview_scheduled')
                    THEN 'documents_pending'
                    ELSE stage
                END,
                stage_updated_at = NOW()
                WHERE id = %s;
            """, (candidate_id,))
        conn.commit()

    folder = f"candidates/documents/{candidate_id}"
    job_id = enqueue_upload(
        file_bytes, folder, doc_type,
        candidate_id=candidate_id,
        resource_type="raw" if "pdf" in mimetype or "word" in mimetype else "image",
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
