"""
Admin routes for the recruitment pipeline.
All routes require admin authentication via require_admin() from app.py.
"""
import threading
import datetime

from flask import Blueprint, request, jsonify, session

from db import DBConnection
from services.notifications import send_notification, resend_notification
from jobs.slot_generator import generate_slots

admin_rec = Blueprint("admin_rec", __name__)

# Imported lazily from app.py to avoid circular imports
def _require_admin():
    from app import require_admin
    return require_admin()


VALID_STAGES = [
    "applied", "screening_failed", "screening_flagged", "screening_passed",
    "assessment_in_progress", "assessment_failed", "assessment_passed",
    "interview_slot_pending", "interview_scheduled",
    "documents_pending", "documents_submitted",
    "interview_completed", "offered", "rejected",
    "application_expired", "assessment_expired", "booking_expired", "documents_expired",
]

STAGE_EMAIL_EVENT = {
    "screening_passed":  "screening_passed",
    "screening_failed":  "screening_failed",
    "assessment_passed": "assessment_passed",
    "assessment_failed": "assessment_failed",
    "interview_slot_pending": "interview_slot_available",
    "documents_pending": "documents_required",
    "offered":  "offered",
    "rejected": "rejected",
}


# ── Candidates ────────────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/candidates")
def list_candidates():
    err = _require_admin()
    if err: return err

    stage_filter = request.args.get("stage", "")
    flag_filter  = request.args.get("flagged", "")
    page     = int(request.args.get("page", 1))
    per_page = 50
    offset   = (page - 1) * per_page

    where_clauses = []
    params = []
    if stage_filter:
        where_clauses.append("c.stage = %s")
        params.append(stage_filter)
    if flag_filter == "1":
        where_clauses.append("c.eligibility_flag = TRUE")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT c.id, c.full_name, c.email, c.phone_number, c.dob,
                       c.nysc_status, c.stage, c.stage_updated_at,
                       c.eligibility_flag, c.eligibility_flag_reason,
                       c.cv_url, c.created_at,
                       s.score, s.pass_fail,
                       gs.start_time AS interview_time
                FROM candidates c
                LEFT JOIN LATERAL (
                    SELECT score, pass_fail FROM scores
                    WHERE candidate_id = c.id
                    ORDER BY taken_at DESC LIMIT 1
                ) s ON TRUE
                LEFT JOIN generated_slots gs ON gs.candidate_id = c.id AND gs.is_booked = TRUE
                {where_sql}
                ORDER BY c.created_at DESC
                LIMIT %s OFFSET %s;
            """, params + [per_page, offset])
            rows = cur.fetchall()

            cur.execute(f"""
                SELECT COUNT(*) FROM candidates c {where_sql};
            """, params)
            total = cur.fetchone()[0]

    candidates = []
    for r in rows:
        candidates.append({
            "id": r[0], "name": r[1], "email": r[2], "phone": r[3],
            "dob": r[4].isoformat() if r[4] else None,
            "nysc_status": r[5], "stage": r[6],
            "stage_updated_at": r[7].isoformat() if r[7] else None,
            "eligibility_flag": r[8], "eligibility_flag_reason": r[9],
            "cv_url": r[10],
            "created_at": r[11].isoformat() if r[11] else None,
            "latest_score": float(r[12]) if r[12] is not None else None,
            "latest_pass_fail": r[13],
            "interview_time": r[14].isoformat() if r[14] else None,
        })

    return jsonify({"candidates": candidates, "total": total, "page": page, "per_page": per_page})


@admin_rec.route("/api/admin/recruitment/candidates/<int:cand_id>")
def get_candidate(cand_id):
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.full_name, c.email, c.phone_number, c.dob,
                       c.nysc_status, c.stage, c.stage_updated_at,
                       c.eligibility_flag, c.eligibility_flag_reason,
                       c.cv_url, c.created_at, c.role, c.location
                FROM candidates c WHERE c.id = %s;
            """, (cand_id,))
            cand = cur.fetchone()

            if not cand:
                return jsonify({"error": "Candidate not found."}), 404

            cur.execute("""
                SELECT id, stage_label, score, score_fraction, pass_fail,
                       started_at, taken_at, duration_seconds, tab_switches
                FROM scores WHERE candidate_id = %s ORDER BY started_at DESC;
            """, (cand_id,))
            scores = cur.fetchall()

            cur.execute("""
                SELECT id, doc_type, url, verified, upload_status, uploaded_at
                FROM candidate_documents WHERE candidate_id = %s;
            """, (cand_id,))
            docs = cur.fetchall()

            cur.execute("""
                SELECT gs.id, gs.start_time, gs.end_time, gs.meeting_link,
                       gs.meeting_provider, i.name
                FROM generated_slots gs
                LEFT JOIN interviewers i ON gs.interviewer_id = i.id
                WHERE gs.candidate_id = %s ORDER BY gs.start_time DESC;
            """, (cand_id,))
            slots = cur.fetchall()

            cur.execute("""
                SELECT from_stage, to_stage, changed_at, changed_by, reason
                FROM candidate_stage_history WHERE candidate_id = %s
                ORDER BY changed_at ASC;
            """, (cand_id,))
            history = cur.fetchall()

    return jsonify({
        "candidate": {
            "id": cand[0], "name": cand[1], "email": cand[2], "phone": cand[3],
            "dob": cand[4].isoformat() if cand[4] else None,
            "nysc_status": cand[5], "stage": cand[6],
            "stage_updated_at": cand[7].isoformat() if cand[7] else None,
            "eligibility_flag": cand[8], "flag_reason": cand[9],
            "cv_url": cand[10],
            "created_at": cand[11].isoformat() if cand[11] else None,
            "role": cand[12], "location": cand[13],
        },
        "scores": [{
            "id": s[0], "label": s[1], "score": float(s[2]) if s[2] is not None else None,
            "fraction": s[3], "pass_fail": s[4],
            "started_at": s[5].isoformat() if s[5] else None,
            "taken_at": s[6].isoformat() if s[6] else None,
            "duration_s": s[7], "tab_switches": s[8],
        } for s in scores],
        "documents": [{
            "id": d[0], "doc_type": d[1], "url": d[2],
            "verified": d[3], "status": d[4],
            "uploaded_at": d[5].isoformat() if d[5] else None,
        } for d in docs],
        "interview_slots": [{
            "id": sl[0],
            "start_time": sl[1].isoformat() if sl[1] else None,
            "end_time": sl[2].isoformat() if sl[2] else None,
            "meeting_link": sl[3], "meeting_provider": sl[4], "interviewer": sl[5],
        } for sl in slots],
        "stage_history": [{
            "from": h[0], "to": h[1],
            "at": h[2].isoformat() if h[2] else None,
            "by": h[3], "reason": h[4],
        } for h in history],
    })


@admin_rec.route("/api/admin/recruitment/candidates/<int:cand_id>/stage", methods=["POST"])
def set_candidate_stage(cand_id):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    new_stage = data.get("stage", "").strip()
    reason    = data.get("reason", "admin override").strip()
    notify    = data.get("notify", True)

    if new_stage not in VALID_STAGES:
        return jsonify({"error": f"Invalid stage '{new_stage}'."}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stage FROM candidates WHERE id = %s;", (cand_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Candidate not found."}), 404
            old_stage = row[0]

            cur.execute("""
                UPDATE candidates
                SET stage = %s, stage_updated_at = NOW()
                WHERE id = %s;
            """, (new_stage, cand_id))
            cur.execute("""
                INSERT INTO candidate_stage_history
                    (candidate_id, from_stage, to_stage, changed_by, reason)
                VALUES (%s, %s, %s, 'admin', %s);
            """, (cand_id, old_stage, new_stage, reason))
        conn.commit()

    if new_stage == 'screening_passed':
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM candidates WHERE id = %s;", (cand_id,))
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "INSERT INTO whitelist (email) VALUES (%s) ON CONFLICT (email) DO NOTHING;",
                        (row[0],)
                    )
            conn.commit()

    if notify and new_stage in STAGE_EMAIL_EVENT:
        event = STAGE_EMAIL_EVENT[new_stage]
        threading.Thread(
            target=send_notification,
            args=(cand_id, new_stage, event),
            daemon=True,
        ).start()

    return jsonify({"status": "success", "old_stage": old_stage, "new_stage": new_stage})


# ── Interviewers ──────────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/interviewers", methods=["GET", "POST"])
def interviewers():
    err = _require_admin()
    if err: return err

    if request.method == "GET":
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, email, active, meeting_provider,
                           google_calendar_id, zoom_user_id, created_at
                    FROM interviewers ORDER BY name;
                """)
                rows = cur.fetchall()
        return jsonify([{
            "id": r[0], "name": r[1], "email": r[2], "active": r[3],
            "meeting_provider": r[4], "google_calendar_id": r[5],
            "zoom_user_id": r[6],
            "created_at": r[7].isoformat() if r[7] else None,
        } for r in rows])

    data = request.json or {}
    name     = data.get("name", "").strip()
    email    = data.get("email", "").strip().lower()
    provider = data.get("meeting_provider", "google_meet")
    gcal_id  = data.get("google_calendar_id", "")
    zoom_uid = data.get("zoom_user_id", "")

    if not name or not email:
        return jsonify({"error": "Name and email are required."}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO interviewers
                    (name, email, meeting_provider, google_calendar_id, zoom_user_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
            """, (name, email, provider, gcal_id, zoom_uid))
            new_id = cur.fetchone()[0]
        conn.commit()

    return jsonify({"status": "success", "id": new_id})


@admin_rec.route("/api/admin/recruitment/interviewers/<int:iid>", methods=["PUT", "DELETE"])
def interviewer_detail(iid):
    err = _require_admin()
    if err: return err

    if request.method == "DELETE":
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE interviewers SET active = FALSE WHERE id = %s;", (iid,))
            conn.commit()
        return jsonify({"status": "success"})

    data = request.json or {}
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE interviewers
                SET name = COALESCE(%s, name),
                    email = COALESCE(%s, email),
                    active = COALESCE(%s, active),
                    meeting_provider = COALESCE(%s, meeting_provider),
                    google_calendar_id = COALESCE(%s, google_calendar_id),
                    zoom_user_id = COALESCE(%s, zoom_user_id)
                WHERE id = %s;
            """, (
                data.get("name"), data.get("email"),
                data.get("active"), data.get("meeting_provider"),
                data.get("google_calendar_id"), data.get("zoom_user_id"),
                iid,
            ))
        conn.commit()

    return jsonify({"status": "success"})


# ── Availability rules ────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/availability-rules", methods=["GET", "POST"])
def availability_rules():
    err = _require_admin()
    if err: return err

    if request.method == "GET":
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ar.id, ar.interviewer_id, i.name AS interviewer_name,
                           ar.rule_type, ar.day_of_week, ar.date_from, ar.date_to,
                           ar.start_time::text, ar.end_time::text,
                           ar.slot_duration_minutes, ar.buffer_minutes,
                           ar.booking_lead_time_hours, ar.active
                    FROM availability_rules ar
                    JOIN interviewers i ON ar.interviewer_id = i.id
                    ORDER BY ar.id;
                """)
                rows = cur.fetchall()
        return jsonify([{
            "id": r[0], "interviewer_id": r[1], "interviewer_name": r[2],
            "rule_type": r[3], "day_of_week": r[4],
            "date_from": r[5].isoformat() if r[5] else None,
            "date_to": r[6].isoformat() if r[6] else None,
            "start_time": r[7], "end_time": r[8],
            "slot_duration_minutes": r[9], "buffer_minutes": r[10],
            "booking_lead_time_hours": r[11], "active": r[12],
        } for r in rows])

    data = request.json or {}
    required = ["interviewer_id", "start_time", "end_time"]
    if not all(data.get(k) for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO availability_rules
                    (interviewer_id, rule_type, day_of_week, date_from, date_to,
                     start_time, end_time, slot_duration_minutes, buffer_minutes,
                     booking_lead_time_hours)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                data["interviewer_id"],
                data.get("rule_type", "recurring"),
                data.get("day_of_week"),
                data.get("date_from"),
                data.get("date_to"),
                data["start_time"],
                data["end_time"],
                data.get("slot_duration_minutes", 30),
                data.get("buffer_minutes", 10),
                data.get("booking_lead_time_hours", 24),
            ))
            rule_id = cur.fetchone()[0]
        conn.commit()

    # Trigger slot generation in background
    threading.Thread(target=generate_slots, kwargs={"weeks_ahead": 4}, daemon=True).start()

    return jsonify({"status": "success", "id": rule_id})


@admin_rec.route("/api/admin/recruitment/availability-rules/<int:rid>", methods=["PUT", "DELETE"])
def availability_rule_detail(rid):
    err = _require_admin()
    if err: return err

    if request.method == "DELETE":
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE availability_rules SET active = FALSE WHERE id = %s;", (rid,))
            conn.commit()
        return jsonify({"status": "success"})

    data = request.json or {}
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE availability_rules
                SET rule_type = COALESCE(%s, rule_type),
                    day_of_week = COALESCE(%s, day_of_week),
                    date_from = COALESCE(%s, date_from),
                    date_to = COALESCE(%s, date_to),
                    start_time = COALESCE(%s, start_time),
                    end_time = COALESCE(%s, end_time),
                    slot_duration_minutes = COALESCE(%s, slot_duration_minutes),
                    buffer_minutes = COALESCE(%s, buffer_minutes),
                    booking_lead_time_hours = COALESCE(%s, booking_lead_time_hours),
                    active = COALESCE(%s, active)
                WHERE id = %s;
            """, (
                data.get("rule_type"), data.get("day_of_week"),
                data.get("date_from"), data.get("date_to"),
                data.get("start_time"), data.get("end_time"),
                data.get("slot_duration_minutes"), data.get("buffer_minutes"),
                data.get("booking_lead_time_hours"), data.get("active"),
                rid,
            ))
        conn.commit()

    return jsonify({"status": "success"})


# ── Generated slots ───────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/slots")
def list_slots():
    err = _require_admin()
    if err: return err

    from_dt = request.args.get("from", datetime.date.today().isoformat())
    to_dt   = request.args.get("to",
                (datetime.date.today() + datetime.timedelta(days=28)).isoformat())

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT gs.id, gs.start_time, gs.end_time, gs.is_booked, gs.is_blocked,
                       gs.meeting_link, gs.meeting_provider,
                       i.name AS primary_interviewer,
                       c.full_name AS candidate_name, c.email AS candidate_email,
                       COALESCE(
                           STRING_AGG(pi.name, ', ' ORDER BY pi.name),
                           i.name
                       ) AS all_interviewers
                FROM generated_slots gs
                JOIN interviewers i ON gs.interviewer_id = i.id
                LEFT JOIN candidates c ON gs.candidate_id = c.id
                LEFT JOIN slot_interviewers si ON si.slot_id = gs.id
                LEFT JOIN interviewers pi ON pi.id = si.interviewer_id
                WHERE gs.start_time >= %s AND gs.start_time < %s
                GROUP BY gs.id, gs.start_time, gs.end_time, gs.is_booked, gs.is_blocked,
                         gs.meeting_link, gs.meeting_provider, i.name,
                         c.full_name, c.email
                ORDER BY gs.start_time;
            """, (from_dt, to_dt))
            rows = cur.fetchall()

    return jsonify([{
        "id": r[0],
        "start_time": r[1].isoformat(),
        "end_time":   r[2].isoformat(),
        "is_booked":  r[3], "is_blocked": r[4],
        "meeting_link": r[5], "meeting_provider": r[6],
        "interviewer": r[7],
        "candidate_name": r[8], "candidate_email": r[9],
        "interviewers": r[10],
    } for r in rows])


@admin_rec.route("/api/admin/recruitment/slots/<int:slot_id>/block", methods=["POST"])
def block_slot(slot_id):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    blocked = data.get("blocked", True)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE generated_slots SET is_blocked = %s WHERE id = %s;
            """, (blocked, slot_id))
        conn.commit()

    return jsonify({"status": "success", "blocked": blocked})


@admin_rec.route("/api/admin/recruitment/slots/generate", methods=["POST"])
def trigger_slot_generation():
    err = _require_admin()
    if err: return err

    data = request.json or {}
    weeks = data.get("weeks_ahead", 4)

    threading.Thread(
        target=generate_slots, kwargs={"weeks_ahead": weeks}, daemon=True
    ).start()

    return jsonify({"status": "success", "message": f"Slot generation started for {weeks} weeks."})


# ── Slot panelists ────────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/slots/<int:slot_id>/interviewers", methods=["GET", "POST"])
def slot_interviewers(slot_id):
    err = _require_admin()
    if err: return err

    if request.method == "GET":
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT si.interviewer_id, i.name, i.email
                    FROM slot_interviewers si
                    JOIN interviewers i ON i.id = si.interviewer_id
                    WHERE si.slot_id = %s
                    ORDER BY i.name;
                """, (slot_id,))
                rows = cur.fetchall()
        return jsonify([{"interviewer_id": r[0], "name": r[1], "email": r[2]} for r in rows])

    data = request.json or {}
    iid = data.get("interviewer_id")
    if not iid:
        return jsonify({"error": "interviewer_id required"}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO slot_interviewers (slot_id, interviewer_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING;
            """, (slot_id, iid))
        conn.commit()

    return jsonify({"status": "success"})


@admin_rec.route("/api/admin/recruitment/slots/<int:slot_id>/interviewers/<int:iid>", methods=["DELETE"])
def remove_slot_interviewer(slot_id, iid):
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM slot_interviewers WHERE slot_id = %s AND interviewer_id = %s;
            """, (slot_id, iid))
        conn.commit()

    return jsonify({"status": "success"})


# ── Stage config ──────────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/stage-config")
def get_stage_config():
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, cycle_id, stage_name, opens_at, closes_at,
                       duration_minutes, relative_deadline_hours, pass_mark,
                       min_age, max_age, accepted_nysc_statuses, screening_mode,
                       updated_at
                FROM stage_config ORDER BY id;
            """)
            rows = cur.fetchall()

    return jsonify([{
        "id": r[0], "cycle_id": r[1], "stage_name": r[2],
        "opens_at":  r[3].isoformat() if r[3] else None,
        "closes_at": r[4].isoformat() if r[4] else None,
        "duration_minutes": r[5],
        "relative_deadline_hours": r[6],
        "pass_mark": float(r[7]) if r[7] is not None else None,
        "min_age": r[8], "max_age": r[9],
        "accepted_nysc_statuses": list(r[10]) if r[10] else [],
        "screening_mode": r[11],
        "updated_at": r[12].isoformat() if r[12] else None,
    } for r in rows])


@admin_rec.route("/api/admin/recruitment/stage-config/<stage_name>", methods=["PUT"])
def update_stage_config(stage_name):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    cycle_id = data.get("cycle_id", 1)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE stage_config
                SET opens_at = COALESCE(%s::timestamptz, opens_at),
                    closes_at = COALESCE(%s::timestamptz, closes_at),
                    duration_minutes = COALESCE(%s, duration_minutes),
                    relative_deadline_hours = COALESCE(%s, relative_deadline_hours),
                    pass_mark = COALESCE(%s, pass_mark),
                    min_age = COALESCE(%s, min_age),
                    max_age = COALESCE(%s, max_age),
                    accepted_nysc_statuses = COALESCE(%s, accepted_nysc_statuses),
                    screening_mode = COALESCE(%s, screening_mode),
                    updated_at = NOW()
                WHERE stage_name = %s AND cycle_id = %s;
            """, (
                data.get("opens_at"), data.get("closes_at"),
                data.get("duration_minutes"),
                data.get("relative_deadline_hours"),
                data.get("pass_mark"),
                data.get("min_age"), data.get("max_age"),
                data.get("accepted_nysc_statuses"),
                data.get("screening_mode"),
                stage_name, cycle_id,
            ))
        conn.commit()

    return jsonify({"status": "success"})


# ── Email log ─────────────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/email-log")
def email_log():
    err = _require_admin()
    if err: return err

    page = int(request.args.get("page", 1))
    per_page = 50
    offset = (page - 1) * per_page

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT el.id, el.candidate_id, c.full_name, el.stage,
                       el.event_type, el.recipient_email, el.sent_at,
                       el.status, el.error_message
                FROM email_log el
                LEFT JOIN candidates c ON el.candidate_id = c.id
                ORDER BY el.sent_at DESC
                LIMIT %s OFFSET %s;
            """, (per_page, offset))
            rows = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM email_log;")
            total = cur.fetchone()[0]

    return jsonify({
        "logs": [{
            "id": r[0], "candidate_id": r[1], "candidate_name": r[2],
            "stage": r[3], "event_type": r[4], "recipient": r[5],
            "sent_at": r[6].isoformat() if r[6] else None,
            "status": r[7], "error": r[8],
        } for r in rows],
        "total": total, "page": page, "per_page": per_page,
    })


@admin_rec.route("/api/admin/recruitment/email-log/<int:log_id>/resend", methods=["POST"])
def resend_email(log_id):
    err = _require_admin()
    if err: return err

    ok = resend_notification(log_id)
    return jsonify({"status": "success" if ok else "failed"})


# ── Documents admin view ──────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/documents/<int:cand_id>")
def candidate_documents(cand_id):
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, doc_type, url, verified, upload_status, uploaded_at, public_id
                FROM candidate_documents WHERE candidate_id = %s;
            """, (cand_id,))
            rows = cur.fetchall()

    return jsonify([{
        "id": r[0], "doc_type": r[1], "url": r[2],
        "verified": r[3], "status": r[4],
        "uploaded_at": r[5].isoformat() if r[5] else None,
        "public_id": r[6],
    } for r in rows])


@admin_rec.route("/api/admin/recruitment/documents/<int:doc_id>/verify", methods=["POST"])
def verify_document(doc_id):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    verified = bool(data.get("verified", True))

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE candidate_documents SET verified = %s WHERE id = %s;
            """, (verified, doc_id))
        conn.commit()

    return jsonify({"status": "success", "verified": verified})


# ── Admin recruitment dashboard page ─────────────────────────────────────────

@admin_rec.route("/admin/recruitment")
def admin_recruitment_page():
    from flask import render_template, session, redirect, url_for
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    err = _require_admin()
    if err:
        return redirect(url_for("admin_login"))
    return render_template("admin_recruitment.html")
