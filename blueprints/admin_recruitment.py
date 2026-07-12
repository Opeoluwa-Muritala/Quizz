"""
Admin routes for the recruitment pipeline.
All routes require admin authentication via require_admin() from app.py.
"""
import threading
import datetime
import time
import requests
import logging
import cloudinary.utils
import csv
import io
import json

from flask import Blueprint, request, jsonify, session, Response, redirect

from db import DBConnection
from services.notifications import send_notification, resend_notification

logger = logging.getLogger(__name__)
from jobs.slot_generator import generate_slots
from services.schedules import generate_schedule_slots
from services.cache import cached_admin_json

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
@cached_admin_json(15)
def list_candidates():
    err = _require_admin()
    if err: return err

    stage_filter = request.args.get("stage", "")
    flag_filter  = request.args.get("flagged", "")
    cohort_filter = request.args.get("cohort_id", "")
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
    if cohort_filter:
        where_clauses.append("c.cohort_id = %s")
        params.append(int(cohort_filter))

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Keep the page query index-friendly. COUNT(*) OVER() forces a full
            # window scan before PostgreSQL can return the first page.
            cur.execute(f"SELECT COUNT(*) FROM candidates c {where_sql};", params)
            total = cur.fetchone()[0]
            cur.execute(f"""
                WITH candidate_page AS (
                    SELECT c.* FROM candidates c {where_sql}
                    ORDER BY c.created_at DESC LIMIT %s OFFSET %s
                )
                SELECT c.id, c.full_name, c.email, c.phone_number, c.dob,
                       c.nysc_status, c.stage, c.stage_updated_at,
                       c.eligibility_flag, c.eligibility_flag_reason,
                       c.cv_url, c.created_at,
                       s.score, s.pass_fail,
                       gs.start_time AS interview_time,
                       c.cohort_id, co.name AS cohort_name, c.interview_round
                FROM candidate_page c
                LEFT JOIN cohorts co ON c.cohort_id = co.id
                LEFT JOIN LATERAL (
                    SELECT score, pass_fail FROM scores
                    WHERE candidate_id = c.id
                    ORDER BY taken_at DESC LIMIT 1
                ) s ON TRUE
                LEFT JOIN LATERAL (
                    SELECT start_time FROM generated_slots
                    WHERE candidate_id = c.id AND is_booked = TRUE
                    ORDER BY start_time DESC LIMIT 1
                ) gs ON TRUE
                ORDER BY c.created_at DESC
            """, params + [per_page, offset])
            rows = cur.fetchall()

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
            "cohort_id": r[15],
            "cohort_name": r[16] or "Cohort 1", "interview_round": r[17],
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
                       c.cv_url, c.created_at, c.role, c.location,
                       c.cohort_id, co.name AS cohort_name, c.interview_round
                FROM candidates c 
                LEFT JOIN cohorts co ON c.cohort_id = co.id
                WHERE c.id = %s;
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
                SELECT id, doc_type, verified, upload_status, uploaded_at, public_id,
                       rejection_note
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

            # Query quizzes for candidate's cohort
            cohort_id_for_quizzes = cand[14]
            if not cohort_id_for_quizzes:
                cur.execute("SELECT id FROM cohorts WHERE name = 'Cohort 1';")
                crow = cur.fetchone()
                cohort_id_for_quizzes = crow[0] if crow else None

            cohort_quizzes = []
            if cohort_id_for_quizzes:
                cur.execute("""
                    SELECT id, title, pass_mark
                    FROM quizzes
                    WHERE cohort_id = %s AND active = TRUE
                    ORDER BY number ASC;
                """, (cohort_id_for_quizzes,))
                cohort_quizzes = [{"id": r[0], "title": r[1], "pass_mark": float(r[2])} for r in cur.fetchall()]

    return jsonify({
        "candidate": {
            "id": cand[0], "name": cand[1], "email": cand[2], "phone": cand[3],
            "dob": cand[4].isoformat() if cand[4] else None,
            "nysc_status": cand[5], "stage": cand[6],
            "stage_updated_at": cand[7].isoformat() if cand[7] else None,
            "eligibility_flag": cand[8], "flag_reason": cand[9],
            "cv_url": f"/api/admin/recruitment/candidates/{cand_id}/cv" if cand[10] else None,
            "created_at": cand[11].isoformat() if cand[11] else None,
            "role": cand[12], "location": cand[13],
            "cohort_id": cand[14], "cohort_name": cand[15] or "Cohort 1", "interview_round": cand[16],
        },
        "scores": [{
            "id": s[0], "label": s[1], "score": float(s[2]) if s[2] is not None else None,
            "fraction": s[3], "pass_fail": s[4],
            "started_at": s[5].isoformat() if s[5] else None,
            "taken_at": s[6].isoformat() if s[6] else None,
            "duration_s": s[7], "tab_switches": s[8],
        } for s in scores],
        "documents": [{
            "id": d[0], "doc_type": d[1],
            "url": f"/api/admin/recruitment/documents/file/{d[0]}" if d[5] else None,
            "verified": d[2],
            "status": "rejected" if d[6] else d[3],
            "uploaded_at": d[4].isoformat() if d[4] else None,
            "rejection_note": d[6],
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
            "by": h[3],
            "reason": None if (h[4] and "override" in h[4].lower()) else h[4],
        } for h in history],
        "cohort_quizzes": cohort_quizzes,
    })


@admin_rec.route("/api/admin/recruitment/candidates/<int:cand_id>/stage", methods=["POST"])
def set_candidate_stage(cand_id):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    new_stage = data.get("stage", "").strip()
    reason    = data.get("reason", "admin override").strip()
    notify    = data.get("notify", True)
    interview_round = data.get("interview_round")

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
                SET stage = %s, interview_round = COALESCE(%s, interview_round), stage_updated_at = NOW()
                WHERE id = %s;
            """, (new_stage, interview_round or None, cand_id))
            cur.execute("""
                INSERT INTO candidate_stage_history
                    (candidate_id, from_stage, to_stage, changed_by, reason)
                VALUES (%s, %s, %s, 'admin', %s);
            """, (cand_id, old_stage, new_stage, reason))
        conn.commit()

    if new_stage == 'screening_passed':
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email, cohort_id, full_name FROM candidates WHERE id = %s;", (cand_id,))
                row = cur.fetchone()
                if row:
                    email, cohort_id, full_name = row
                    if not cohort_id:
                        cur.execute("SELECT id FROM cohorts WHERE name = 'Cohort 1';")
                        crow = cur.fetchone()
                        cohort_id = crow[0] if crow else None
                        if cohort_id:
                            cur.execute("UPDATE candidates SET cohort_id = %s WHERE id = %s;", (cohort_id, cand_id))
                    cur.execute("""
                        INSERT INTO whitelist (email, name, cohort_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (email) DO UPDATE
                        SET name = COALESCE(whitelist.name, EXCLUDED.name),
                            cohort_id = COALESCE(whitelist.cohort_id, EXCLUDED.cohort_id);
                    """, (email, full_name, cohort_id))
            conn.commit()

    if notify and new_stage in STAGE_EMAIL_EVENT:
        event = STAGE_EMAIL_EVENT[new_stage]
        try:
            send_notification(cand_id, new_stage, event)
        except Exception as e:
            print(f"Error sending notification to {cand_id}: {e}")

    return jsonify({"status": "success", "old_stage": old_stage, "new_stage": new_stage})


@admin_rec.route("/api/admin/recruitment/candidates/bulk", methods=["POST"])
def bulk_candidate_updates():
    """Apply table selections or a CSV (email,target_stage,interview_round) safely."""
    err = _require_admin()
    if err: return err
    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    if request.files.get("file"):
        try:
            rows = list(csv.DictReader(io.StringIO(request.files["file"].read().decode("utf-8-sig"))))
        except (UnicodeDecodeError, csv.Error):
            return jsonify({"error": "Upload a UTF-8 CSV with email,target_stage headers."}), 400
    if data.get("candidate_ids"):
        rows = [{"id": cid, "target_stage": data.get("target_stage"), "interview_round": data.get("interview_round")}
                for cid in data["candidate_ids"]]
    if not rows:
        return jsonify({"error": "Provide CSV rows or candidate_ids."}), 400

    results, seen = [], set()
    notifications = []
    with DBConnection() as conn:
        with conn.cursor() as cur:
            for index, raw in enumerate(rows, 1):
                email = (raw.get("email") or "").strip().lower()
                cid = raw.get("id")
                stage = (raw.get("target_stage") or raw.get("stage") or "").strip()
                round_name = (raw.get("interview_round") or "").strip() or None
                key = email or str(cid or "")
                if not key or not stage or stage not in VALID_STAGES:
                    results.append({"row": index, "status": "invalid", "error": "Valid email/id and target_stage are required."}); continue
                if key in seen:
                    results.append({"row": index, "status": "duplicate", "error": "Duplicate input row."}); continue
                seen.add(key)
                cur.execute("SELECT id, stage FROM candidates WHERE " + ("id = %s" if cid else "LOWER(email) = %s"), (int(cid) if cid else email,))
                candidate = cur.fetchone()
                if not candidate:
                    results.append({"row": index, "status": "unknown", "email": email}); continue
                candidate_id, old_stage = candidate
                cur.execute("""UPDATE candidates SET stage=%s, interview_round=COALESCE(%s, interview_round),
                               stage_updated_at=NOW() WHERE id=%s""", (stage, round_name, candidate_id))
                cur.execute("""INSERT INTO candidate_stage_history(candidate_id,from_stage,to_stage,changed_by,reason)
                               VALUES(%s,%s,%s,'admin','bulk update')""", (candidate_id, old_stage, stage))
                results.append({"row": index, "status": "updated", "id": candidate_id, "old_stage": old_stage, "new_stage": stage})
                if stage in STAGE_EMAIL_EVENT: notifications.append((candidate_id, stage, STAGE_EMAIL_EVENT[stage]))
        conn.commit()
    for candidate_id, stage, event in notifications:
        try: send_notification(candidate_id, stage, event)
        except Exception: logger.exception("Bulk notification failed for candidate_id=%s", candidate_id)
    return jsonify({"status": "success", "results": results,
                    "updated": sum(r["status"] == "updated" for r in results)})


# ── Interviewers ──────────────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/interviewers", methods=["GET", "POST"])
@cached_admin_json(30)
def interviewers():
    err = _require_admin()
    if err: return err

    if request.method == "GET":
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, email, active, meeting_provider,
                           google_calendar_id, zoom_user_id, color, created_at
                    FROM interviewers ORDER BY name;
                """)
                rows = cur.fetchall()
        return jsonify([{
            "id": r[0], "name": r[1], "email": r[2], "active": r[3],
            "meeting_provider": r[4], "google_calendar_id": r[5],
            "zoom_user_id": r[6], "color": r[7],
            "created_at": r[8].isoformat() if r[8] else None,
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
            cur.execute("SELECT COUNT(*) FROM interviewers;")
            count = cur.fetchone()[0]
            colors_palette = ['#89268B', '#1E7A45', '#B8790A', '#2B6CB0', '#319795', '#D53F8C', '#4A5568']
            color = colors_palette[count % len(colors_palette)]

            cur.execute("""
                INSERT INTO interviewers
                    (name, email, meeting_provider, google_calendar_id, zoom_user_id, color)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (name, email, provider, gcal_id, zoom_uid, color))
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

def _schedule_payload(cur, schedule_id=None):
    where, params = ("WHERE s.id = %s", [schedule_id]) if schedule_id else ("", [])
    cur.execute(f"""
        SELECT s.id,s.title,s.role,s.interview_round,s.schedule_type,s.start_date,s.end_date,
               s.active_days,s.availability_windows,s.duration_minutes,s.buffer_minutes,
               s.booking_lead_time_hours,s.daily_booking_cap,s.interviewer_booking_cap,
               s.booking_mode,s.published,s.generated_at,
               (SELECT COUNT(*) FROM generated_slots x WHERE x.schedule_id=s.id AND x.is_booked=FALSE),
               (SELECT COUNT(*) FROM generated_slots x WHERE x.schedule_id=s.id AND x.is_booked=TRUE),
               (SELECT COUNT(*) FROM candidates x WHERE x.role=s.role AND x.interview_round=s.interview_round AND x.stage='interview_slot_pending')
        FROM interview_schedules s
        {where}
        ORDER BY s.created_at DESC
    """, params)
    rows = cur.fetchall()
    sch_ids = [r[0] for r in rows]
    interviewers_by_sch = {}
    
    if sch_ids:
        cur.execute("""
            SELECT si.schedule_id, i.id, i.name, i.email, i.color FROM schedule_interviewers si
            JOIN interviewers i ON i.id = si.interviewer_id
            WHERE si.schedule_id IN %s ORDER BY si.position
        """, (tuple(sch_ids),))
        for row in cur.fetchall():
            interviewers_by_sch.setdefault(row[0], []).append({
                "id": row[1], "name": row[2], "email": row[3], "color": row[4]
            })

    schedules = []
    for r in rows:
        sch_id = r[0]
        schedules.append({"id":sch_id,"title":r[1],"role":r[2],"round":r[3],"type":r[4],
            "start_date":r[5].isoformat() if r[5] else None,"end_date":r[6].isoformat() if r[6] else None,
            "active_days":r[7] or [],"recurrence_days":r[7] or [],"hours":r[8] or {},"duration":r[9],"buffer":r[10],
            "notice":r[11],"max_bookings":r[12],"max_interviewer_bookings":r[13],
            "mode":"robin" if r[14]=="round_robin" else r[14],"published":r[15],
            "status":"Active" if r[15] and (not r[6] or r[6] >= datetime.date.today()) else "Ended",
            "generated_at":r[16].isoformat() if r[16] else None,"slots":r[17]+r[18],"booked":r[18],"waiting":r[19],
            "interviewers": interviewers_by_sch.get(sch_id, [])})
    return schedules


def _validate_schedule(data):
    title, role, round_name = (data.get("title") or "").strip(), (data.get("role") or "").strip(), (data.get("round") or data.get("interview_round") or "").strip()
    interviewer_ids = [int(x) for x in data.get("interviewer_ids", [i.get("id") for i in data.get("interviewers", [])]) if x]
    hours = data.get("hours") or data.get("availability_windows") or {}
    schedule_type = data.get("type", data.get("schedule_type", "range"))
    if not title or not role or not round_name or not interviewer_ids or schedule_type not in ("range", "recurring"):
        return None, "title, role, interview round, schedule type, and one interviewer are required."
    active_days = [int(x) for x in data.get("active_days", data.get("recurrence_days", []))]
    if not active_days or not isinstance(hours, dict): return None, "Select days and availability windows."
    for windows in hours.values():
        for w in windows:
            if not w.get("start") or not w.get("end") or w["start"] >= w["end"]: return None, "Each availability window needs a valid start and end time."
    mode = data.get("mode", data.get("booking_mode", "single"))
    mode = "round_robin" if mode == "robin" else mode
    if mode not in ("single", "collective", "round_robin"): return None, "Invalid booking mode."
    if len(interviewer_ids) == 1: mode = "single"
    return {"title":title,"role":role,"round":round_name,"type":schedule_type,"interviewer_ids":interviewer_ids,
            "hours":hours,"active_days":active_days,"mode":mode}, None


@admin_rec.route("/api/admin/recruitment/schedules", methods=["GET", "POST"])
@cached_admin_json(20)
def schedules():
    err = _require_admin()
    if err: return err
    if request.method == "GET":
        with DBConnection() as conn:
            with conn.cursor() as cur: return jsonify(_schedule_payload(cur))
    cfg, error = _validate_schedule(request.json or {})
    if error: return jsonify({"error":error}), 400
    data = request.json or {}
    try:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM interviewers WHERE id = ANY(%s) AND active=TRUE", (cfg["interviewer_ids"],))
                if cur.fetchone()[0] != len(set(cfg["interviewer_ids"])): return jsonify({"error":"One or more interviewers are inactive or unknown."}), 400
                cur.execute("""INSERT INTO interview_schedules(title,role,interview_round,schedule_type,start_date,end_date,active_days,availability_windows,
                    duration_minutes,buffer_minutes,booking_lead_time_hours,daily_booking_cap,interviewer_booking_cap,booking_mode,published)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING id""",
                    (cfg["title"],cfg["role"],cfg["round"],cfg["type"],data.get("start_date"),data.get("end_date") or data.get("recur_end_date"),cfg["active_days"],json.dumps(cfg["hours"]),
                     data.get("duration",30),data.get("buffer",10),data.get("notice",24),data.get("max_bookings"),data.get("max_interviewer_bookings"),cfg["mode"]))
                sid=cur.fetchone()[0]
                for pos,iid in enumerate(cfg["interviewer_ids"]): cur.execute("INSERT INTO schedule_interviewers(schedule_id,interviewer_id,position) VALUES(%s,%s,%s)",(sid,iid,pos))
                created=generate_schedule_slots(conn,sid)
            conn.commit()
        return jsonify({"status":"success","id":sid,"slots_generated":created}),201
    except (ValueError, TypeError): return jsonify({"error":"Invalid schedule values."}),400


@admin_rec.route("/api/admin/recruitment/schedules/<int:schedule_id>", methods=["GET", "PUT", "DELETE"])
def schedule_detail(schedule_id):
    err = _require_admin()
    if err: return err
    if request.method == "GET":
        with DBConnection() as conn:
            with conn.cursor() as cur:
                result=_schedule_payload(cur,schedule_id)
                return jsonify(result[0]) if result else (jsonify({"error":"Schedule not found."}),404)
    if request.method == "DELETE":
        with DBConnection() as conn:
            with conn.cursor() as cur: cur.execute("UPDATE interview_schedules SET published=FALSE,updated_at=NOW() WHERE id=%s",(schedule_id,))
            conn.commit()
        return jsonify({"status":"success"})
    cfg,error=_validate_schedule(request.json or {})
    if error:return jsonify({"error":error}),400
    data=request.json or {}
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM generated_slots WHERE schedule_id=%s AND is_booked=TRUE",(schedule_id,)); booked=cur.fetchone()[0]
            cur.execute("""UPDATE interview_schedules SET title=%s,role=%s,interview_round=%s,schedule_type=%s,start_date=%s,end_date=%s,active_days=%s,availability_windows=%s,
              duration_minutes=%s,buffer_minutes=%s,booking_lead_time_hours=%s,daily_booking_cap=%s,interviewer_booking_cap=%s,booking_mode=%s,published=TRUE,updated_at=NOW() WHERE id=%s""",
              (cfg["title"],cfg["role"],cfg["round"],cfg["type"],data.get("start_date"),data.get("end_date") or data.get("recur_end_date"),cfg["active_days"],json.dumps(cfg["hours"]),data.get("duration",30),data.get("buffer",10),data.get("notice",24),data.get("max_bookings"),data.get("max_interviewer_bookings"),cfg["mode"],schedule_id))
            if not cur.rowcount:return jsonify({"error":"Schedule not found."}),404
            cur.execute("DELETE FROM schedule_interviewers WHERE schedule_id=%s",(schedule_id,))
            for pos,iid in enumerate(cfg["interviewer_ids"]):cur.execute("INSERT INTO schedule_interviewers(schedule_id,interviewer_id,position) VALUES(%s,%s,%s)",(schedule_id,iid,pos))
            # Remove only future, unbooked old slots; booked appointments are preserved.
            cur.execute("DELETE FROM generated_slots WHERE schedule_id=%s AND is_booked=FALSE AND start_time>NOW()",(schedule_id,))
            created=generate_schedule_slots(conn,schedule_id)
        conn.commit()
    return jsonify({"status":"success","slots_generated":created,"booked_slots_preserved":booked})


@admin_rec.route("/api/admin/recruitment/schedules/preview", methods=["POST"])
def schedule_preview():
    err = _require_admin()
    if err: return err
    cfg,error=_validate_schedule(request.json or {})
    if error:return jsonify({"error":error}),400
    # Client already renders a rich preview; this endpoint returns an authoritative count pattern.
    data=request.json or {}; duration=int(data.get("duration",30)); buffer=int(data.get("buffer",10)); total=0
    for wins in cfg["hours"].values():
        for w in wins:
            a=datetime.time.fromisoformat(w["start"]); b=datetime.time.fromisoformat(w["end"])
            total += max(0, (int((datetime.datetime.combine(datetime.date.today(),b)-datetime.datetime.combine(datetime.date.today(),a)).seconds//60)-duration)//(duration+buffer)+1)
    return jsonify({"slots_per_matching_day":total,"booking_mode":cfg["mode"],"timezone":"Africa/Lagos"})


@admin_rec.route("/api/admin/recruitment/schedules/candidate-count")
@cached_admin_json(15)
def schedule_candidate_count():
    err = _require_admin()
    if err:return err
    role=request.args.get("role",""); round_name=request.args.get("round","")
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM candidates WHERE role=%s AND interview_round=%s AND stage='interview_slot_pending'",(role,round_name))
            return jsonify({"count":cur.fetchone()[0]})

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

    # Trigger slot generation synchronously for serverless environment
    try:
        generate_slots(weeks_ahead=4)
    except Exception as e:
        print(f"Error generating slots: {e}")

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
@cached_admin_json(15)
def list_slots():
    err = _require_admin()
    if err: return err

    from_str = request.args.get("start_date") or request.args.get("from")
    to_str   = request.args.get("end_date") or request.args.get("to")
    if not from_str or not to_str:
        from_str = datetime.date.today().isoformat()
        to_str = (datetime.date.today() + datetime.timedelta(days=28)).isoformat()

    try:
        start_d = datetime.date.fromisoformat(from_str)
        end_d = datetime.date.fromisoformat(to_str)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    if end_d < start_d:
        return jsonify({"error": "end_date cannot be before start_date"}), 400

    delta = end_d - start_d
    if delta.days > 62:
        return jsonify({"error": "Date range cannot exceed 62 days"}), 400

    import pytz
    lagos_tz = pytz.timezone('Africa/Lagos')
    start_dt = lagos_tz.localize(datetime.datetime.combine(start_d, datetime.time.min))
    end_dt = lagos_tz.localize(datetime.datetime.combine(end_d, datetime.time.max))

    interviewer_ids = request.args.getlist("interviewer_id")
    if interviewer_ids:
        try:
            interviewer_ids = [int(x) for x in interviewer_ids]
        except ValueError:
            return jsonify({"error": "Invalid interviewer_id"}), 400

    where_clauses = ["sl.start_time >= %s", "sl.start_time <= %s"]
    params = [start_dt, end_dt]

    if interviewer_ids:
        where_clauses.append("sl.interviewer_id = ANY(%s)")
        params.append(interviewer_ids)

    where_sql = " AND ".join(where_clauses)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                WITH slot_list AS (
                    SELECT gs.id, gs.start_time, gs.end_time, gs.is_booked, gs.is_blocked,
                           gs.meeting_link, gs.meeting_provider, gs.interviewer_id, gs.candidate_id, gs.title,
                           LEAD(gs.start_time) OVER (PARTITION BY gs.interviewer_id ORDER BY gs.start_time) AS next_start_time
                    FROM generated_slots gs
                )
                SELECT sl.id, sl.start_time, sl.end_time, sl.is_booked, sl.is_blocked, sl.meeting_link, sl.meeting_provider,
                       i.name AS primary_interviewer, i.id AS interviewer_id, i.color AS interviewer_color,
                       c.full_name AS candidate_name, c.email AS candidate_email, c.role AS candidate_role, c.id AS candidate_id,
                       sl.title,
                       COALESCE(
                           STRING_AGG(pi.name, ', ' ORDER BY pi.name),
                           i.name
                       ) AS all_interviewers,
                       sl.next_start_time
                FROM slot_list sl
                JOIN interviewers i ON sl.interviewer_id = i.id
                LEFT JOIN candidates c ON sl.candidate_id = c.id
                LEFT JOIN slot_interviewers si ON si.slot_id = sl.id
                LEFT JOIN interviewers pi ON pi.id = si.interviewer_id
                WHERE {where_sql}
                GROUP BY sl.id, sl.start_time, sl.end_time, sl.is_booked, sl.is_blocked, sl.meeting_link, sl.meeting_provider,
                         i.name, i.id, i.color, c.full_name, c.email, c.role, c.id, sl.title, sl.next_start_time
                ORDER BY sl.start_time;
            """, params)
            rows = cur.fetchall()

    results = []
    for r in rows:
        (s_id, s_start, s_end, is_booked, is_blocked, meeting_link, meeting_provider,
         i_name, i_id, i_color, c_name, c_email, c_role, c_id, title, all_interviewers, next_start) = r

        # Apply Lagos timezone offset
        start_lagos = s_start.astimezone(lagos_tz)
        end_lagos = s_end.astimezone(lagos_tz)

        # Computed title fallback
        if not title:
            title = f"{i_name} — {start_lagos.strftime('%I:%M %p')}"

        # Status mapping
        status = "open"
        if is_blocked:
            status = "blocked"
        elif is_booked:
            status = "booked"

        # Candidate mapping
        candidate = None
        if is_booked:
            candidate = {
                "id": c_id,
                "name": c_name,
                "email": c_email,
                "role": c_role
            }

        # break_after_minutes
        break_after_minutes = None
        if next_start:
            break_after_minutes = int((next_start - s_end).total_seconds() / 60)

        results.append({
            "id": s_id,
            "title": title,
            "start_time": start_lagos.isoformat(),
            "end_time": end_lagos.isoformat(),
            "status": status,
            "meeting_provider": meeting_provider,
            "interviewer": {
                "id": i_id,
                "name": i_name,
                "color": i_color or "#6B6470",
                "all_names": all_interviewers
            },
            "candidate": candidate,
            "meeting_link": meeting_link,
            "break_after_minutes": break_after_minutes,
            # include raw bools for backwards compatibility
            "is_booked": is_booked,
            "is_blocked": is_blocked,
            "candidate_name": c_name,
            "candidate_id": c_id,
            "candidate_email": c_email,
            "candidate_role": c_role,
            "interviewers": all_interviewers,
            "interviewer_id": i_id,
            "interviewer": i_name
        })

    return jsonify(results)


@admin_rec.route("/api/admin/recruitment/slots/<int:slot_id>/block", methods=["POST"])
def block_slot(slot_id):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    blocked = data.get("blocked", True)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE generated_slots SET is_blocked = %s WHERE id = %s AND is_booked = FALSE;
            """, (blocked, slot_id))
        conn.commit()

    return jsonify({"status": "success", "blocked": blocked})


@admin_rec.route("/api/admin/recruitment/slots", methods=["POST"])
def create_manual_slot():
    """Create one interview slot with one primary interviewer and optional panelists."""
    err = _require_admin()
    if err: return err

    data = request.json or {}
    interviewer_ids = list(dict.fromkeys(data.get("interviewer_ids") or []))
    start_raw, end_raw = data.get("start_time"), data.get("end_time")
    title = (data.get("title") or "").strip() or None
    if not interviewer_ids or not start_raw or not end_raw:
        return jsonify({"error": "Select at least one interviewer and a start and end time."}), 400
    try:
        interviewer_ids = [int(i) for i in interviewer_ids]
        from zoneinfo import ZoneInfo
        wat = ZoneInfo("Africa/Lagos")
        start = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        end = datetime.datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        if start.tzinfo is None: start = start.replace(tzinfo=wat)
        if end.tzinfo is None: end = end.replace(tzinfo=wat)
    except (TypeError, ValueError):
        return jsonify({"error": "Use valid start and end date-times."}), 400
    if end <= start:
        return jsonify({"error": "End time must be after the start time."}), 400

    split_automatically = data.get("split_automatically", False)
    duration = data.get("meeting_length")
    buffer = data.get("gap_length", 0)

    if split_automatically:
        try:
            duration = int(duration)
            buffer = int(buffer)
            if duration <= 0:
                return jsonify({"error": "Meeting length must be greater than 0."}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid meeting length or gap length."}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM interviewers WHERE id = ANY(%s) AND active = TRUE;", (interviewer_ids,))
            active_ids = {row[0] for row in cur.fetchall()}
            if active_ids != set(interviewer_ids):
                return jsonify({"error": "One or more selected interviewers are inactive or unavailable."}), 400

            range_end_raw = data.get("range_end_date")
            range_end = None
            if split_automatically and range_end_raw:
                try:
                    range_end = datetime.date.fromisoformat(range_end_raw)
                except ValueError:
                    return jsonify({"error": "Invalid end date format."}), 400

            active_days = data.get("active_days", [0, 1, 2, 3, 4, 5, 6])
            try:
                active_days = [int(x) for x in active_days]
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid active weekdays list."}), 400

            slots_to_create = []
            if split_automatically:
                start_date = start.date()
                end_limit_date = range_end if range_end else start_date
                
                if end_limit_date < start_date:
                    return jsonify({"error": "Date range end must be on or after the start date."}), 400
                if (end_limit_date - start_date).days > 60:
                    return jsonify({"error": "Date range cannot exceed 60 days."}), 400

                daily_duration = end - start
                current_date = start_date
                while current_date <= end_limit_date:
                    # Check weekday filter: Monday=1, ..., Saturday=6, Sunday=0
                    js_day_num = (current_date.weekday() + 1) % 7
                    if js_day_num not in active_days:
                        current_date += datetime.timedelta(days=1)
                        continue

                    day_start = datetime.datetime.combine(current_date, start.time(), tzinfo=start.tzinfo)
                    day_end = day_start + daily_duration
                    
                    current_start = day_start
                    step = datetime.timedelta(minutes=duration + buffer)
                    while current_start + datetime.timedelta(minutes=duration) <= day_end:
                        current_end = current_start + datetime.timedelta(minutes=duration)
                        slots_to_create.append((current_start, current_end))
                        current_start += step
                    current_date += datetime.timedelta(days=1)
            else:
                slots_to_create.append((start, end))

            if not slots_to_create:
                return jsonify({"error": "No slots fit within the specified time range."}), 400

            created_ids = []
            for s_start, s_end in slots_to_create:
                cur.execute("""
                    SELECT i.name FROM generated_slots gs
                    JOIN interviewers i ON i.id = gs.interviewer_id
                    WHERE gs.interviewer_id = ANY(%s) AND gs.is_blocked = FALSE
                      AND gs.start_time < %s AND gs.end_time > %s
                    UNION
                    SELECT i.name FROM slot_interviewers si
                    JOIN generated_slots gs ON gs.id = si.slot_id
                    JOIN interviewers i ON i.id = si.interviewer_id
                    WHERE si.interviewer_id = ANY(%s) AND gs.is_blocked = FALSE
                      AND gs.start_time < %s AND gs.end_time > %s;
                """, (interviewer_ids, s_end, s_start, interviewer_ids, s_end, s_start))
                conflicts = [row[0] for row in cur.fetchall()]
                if conflicts:
                    return jsonify({"error": f"Time overlaps an existing slot for: {', '.join(conflicts)}."}), 409

                cur.execute("""
                    INSERT INTO generated_slots (interviewer_id, start_time, end_time, title)
                    VALUES (%s, %s, %s, %s) RETURNING id;
                """, (interviewer_ids[0], s_start, s_end, title))
                slot_id = cur.fetchone()[0]
                created_ids.append(slot_id)
                for interviewer_id in interviewer_ids[1:]:
                    cur.execute("INSERT INTO slot_interviewers (slot_id, interviewer_id) VALUES (%s, %s);",
                                (slot_id, interviewer_id))
        conn.commit()
    return jsonify({"status": "success", "slot_ids": created_ids}), 201


@admin_rec.route("/api/admin/recruitment/slots/batch-block", methods=["POST"])
def batch_block():
    err = _require_admin()
    if err: return err

    data = request.json or {}
    slot_ids = data.get("slot_ids")
    blocked = data.get("blocked", True)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            if slot_ids is not None:
                if not slot_ids:
                    return jsonify({"status": "success", "blocked": 0, "skipped_booked": 0})
                
                cur.execute("""
                    SELECT COUNT(*) FROM generated_slots
                    WHERE id = ANY(%s) AND is_booked = TRUE;
                """, (slot_ids,))
                skipped_booked = cur.fetchone()[0]

                cur.execute("""
                    UPDATE generated_slots
                    SET is_blocked = %s
                    WHERE id = ANY(%s) AND is_booked = FALSE;
                """, (blocked, slot_ids))
                updated_count = cur.rowcount
            else:
                interviewer_id = data.get("interviewer_id")
                start_str = data.get("start_time")
                end_str = data.get("end_time")
                if not interviewer_id or not start_str or not end_str:
                    return jsonify({"error": "Must specify either slot_ids or interviewer_id/start_time/end_time range."}), 400

                start_t = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end_t = datetime.datetime.fromisoformat(end_str.replace("Z", "+00:00"))

                cur.execute("""
                    SELECT COUNT(*) FROM generated_slots
                    WHERE interviewer_id = %s
                      AND start_time >= %s AND end_time <= %s
                      AND is_booked = TRUE;
                """, (interviewer_id, start_t, end_t))
                skipped_booked = cur.fetchone()[0]

                cur.execute("""
                    UPDATE generated_slots
                    SET is_blocked = %s
                    WHERE interviewer_id = %s
                      AND start_time >= %s AND end_time <= %s
                      AND is_booked = FALSE;
                """, (blocked, interviewer_id, start_t, end_t))
                updated_count = cur.rowcount

        conn.commit()

    return jsonify({
        "status": "success",
        "blocked" if blocked else "unblocked": updated_count,
        "skipped_booked": skipped_booked
    })


@admin_rec.route("/api/admin/recruitment/slots/bulk-block", methods=["POST"])
def bulk_block():
    return batch_block()


@admin_rec.route("/api/admin/recruitment/slots/bulk-unblock", methods=["POST"])
def bulk_unblock():
    # Force blocked parameter to False
    if request.is_json:
        req_data = request.get_json()
        req_data["blocked"] = False
        request.json = req_data
    return batch_block()


@admin_rec.route("/api/admin/recruitment/slots/rules")
def get_slot_rules():
    err = _require_admin()
    if err: return err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # 1. Fetch legacy availability_rules
            cur.execute("""
                SELECT ar.id, ar.interviewer_id, i.name, ar.start_time, ar.end_time,
                       ar.slot_duration_minutes, ar.buffer_minutes
                FROM availability_rules ar
                JOIN interviewers i ON ar.interviewer_id = i.id
                WHERE ar.active = TRUE;
            """)
            legacy_rows = cur.fetchall()
            
            # 2. Fetch new active interview_schedules
            cur.execute("""
                SELECT s.id, s.title, s.duration_minutes, s.buffer_minutes, s.availability_windows,
                       string_agg(i.name, ', ' ORDER BY si.position) AS interviewer_names
                FROM interview_schedules s
                JOIN schedule_interviewers si ON s.id = si.schedule_id
                JOIN interviewers i ON si.interviewer_id = i.id
                WHERE s.published = TRUE AND (s.end_date IS NULL OR s.end_date >= CURRENT_DATE)
                GROUP BY s.id, s.title, s.duration_minutes, s.buffer_minutes, s.availability_windows;
            """)
            sch_rows = cur.fetchall()

    results = []
    
    # Process legacy rules
    for r in legacy_rows:
        results.append({
            "id": r[0],
            "interviewer_id": r[1],
            "interviewer_name": r[2],
            "start_time": str(r[3]),
            "end_time": str(r[4]),
            "slot_duration": r[5],
            "buffer": r[6],
        })

    # Process new schedules
    for r in sch_rows:
        sch_id, title, duration, buffer, windows, names = r
        start_time = "09:00"
        end_time = "17:00"
        try:
            if isinstance(windows, str):
                import json
                win_dict = json.loads(windows)
            else:
                win_dict = windows
            if win_dict:
                for day, wlist in sorted(win_dict.items()):
                    if wlist and len(wlist) > 0:
                        start_time = wlist[0].get("start", "09:00")
                        end_time = wlist[0].get("end", "17:00")
                        break
        except Exception:
            pass

        results.append({
            "id": f"sch-{sch_id}",
            "interviewer_id": None,
            "interviewer_name": names or "Panel",
            "start_time": start_time if ":" in start_time else f"{start_time}:00",
            "end_time": end_time if ":" in end_time else f"{end_time}:00",
            "slot_duration": duration,
            "buffer": buffer,
        })

    return jsonify(results)


@admin_rec.route("/api/admin/recruitment/slots/<int:slot_id>", methods=["PUT", "PATCH"])
def update_slot(slot_id):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    title = data.get("title")
    start_str = data.get("start_time")
    end_str = data.get("end_time")
    confirm_reschedule = data.get("confirm_reschedule", False)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # 1. Fetch current state of the slot
            cur.execute("""
                SELECT gs.start_time, gs.end_time, gs.is_booked, gs.is_blocked, 
                       gs.candidate_id, gs.interviewer_id, i.name AS interviewer_name, gs.meeting_link
                FROM generated_slots gs
                JOIN interviewers i ON gs.interviewer_id = i.id
                WHERE gs.id = %s;
            """, (slot_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Slot not found."}), 404

            old_start, old_end, is_booked, is_blocked, candidate_id, interviewer_id, interviewer_name, meeting_link = row

            updates = []
            params = []

            # Update title if present
            if "title" in data:
                updates.append("title = %s")
                params.append(title)

            # Check time updates
            time_changing = False
            new_start = old_start
            new_end = old_end

            if start_str or end_str:
                if is_blocked:
                    return jsonify({"error": "Blocked slots cannot be rescheduled. Unblock first."}), 400

                if start_str:
                    new_start = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    if new_start != old_start:
                        time_changing = True
                if end_str:
                    new_end = datetime.datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    if new_end != old_end:
                        time_changing = True

            if time_changing:
                # Run overlap check
                from db import check_interviewer_overlap
                collision = check_interviewer_overlap(conn, interviewer_id, new_start, new_end, exclude_slot_id=slot_id)
                if collision:
                    return jsonify({
                        "status": "conflict",
                        "error": "Time range overlaps with another active slot for this interviewer.",
                        "collision": {
                            "id": collision["id"],
                            "start_time": collision["start_time"].isoformat(),
                            "end_time": collision["end_time"].isoformat()
                        }
                    }), 409

                # If booked and time is changing, require confirm_reschedule
                if is_booked:
                    if not confirm_reschedule:
                        return jsonify({
                            "status": "requires_confirmation",
                            "error": "Rescheduling a booked slot requires explicit candidate notification confirmation."
                        }), 409

                # Apply time updates
                updates.append("start_time = %s")
                params.append(new_start)
                updates.append("end_time = %s")
                params.append(new_end)

            if updates:
                params.append(slot_id)
                query = f"UPDATE generated_slots SET {', '.join(updates)} WHERE id = %s;"
                cur.execute(query, tuple(params))
            
            conn.commit()

    # Trigger reschedule email if booked and times were updated and confirmed
    if is_booked and time_changing and confirm_reschedule and candidate_id:
        try:
            from zoneinfo import ZoneInfo
            wat_tz = ZoneInfo("Africa/Lagos")
            wat_time = new_start.astimezone(wat_tz).strftime("%A %d %B %Y at %H:%M WAT")
            from services.notifications import send_notification
            send_notification(candidate_id, "interview", "interview_rescheduled", {
                "interview_time": wat_time,
                "meeting_link": meeting_link or ""
            })
        except Exception as e:
            print(f"Error sending reschedule notification: {e}")

    return jsonify({"status": "success"})


@admin_rec.route("/api/admin/recruitment/slots/summary")
def slots_summary():
    err = _require_admin()
    if err: return err

    from_str = request.args.get("start_date") or request.args.get("from")
    to_str   = request.args.get("end_date") or request.args.get("to")
    if not from_str or not to_str:
        return jsonify({"error": "start_date and end_date parameters are required."}), 400

    try:
        start_d = datetime.date.fromisoformat(from_str)
        end_d = datetime.date.fromisoformat(to_str)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    if end_d < start_d:
        return jsonify({"error": "end_date cannot be before start_date"}), 400

    delta = end_d - start_d
    if delta.days > 62:
        return jsonify({"error": "Date range cannot exceed 62 days"}), 400

    import pytz
    lagos_tz = pytz.timezone('Africa/Lagos')
    start_dt = lagos_tz.localize(datetime.datetime.combine(start_d, datetime.time.min))
    end_dt = lagos_tz.localize(datetime.datetime.combine(end_d, datetime.time.max))

    interviewer_ids = request.args.getlist("interviewer_id")
    if interviewer_ids:
        try:
            interviewer_ids = [int(x) for x in interviewer_ids]
        except ValueError:
            return jsonify({"error": "Invalid interviewer_id"}), 400

    where_clauses = ["start_time >= %s", "start_time <= %s"]
    params = [start_dt, end_dt]

    if interviewer_ids:
        where_clauses.append("interviewer_id = ANY(%s)")
        params.append(interviewer_ids)

    where_sql = " AND ".join(where_clauses)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT 
                    DATE(start_time AT TIME ZONE 'Africa/Lagos') AS day,
                    CASE 
                        WHEN is_blocked = TRUE THEN 'blocked'
                        WHEN is_booked = TRUE THEN 'booked'
                        ELSE 'open'
                    END AS status,
                    COUNT(*) AS cnt
                FROM generated_slots
                WHERE {where_sql}
                GROUP BY day, status
                ORDER BY day;
            """, params)
            rows = cur.fetchall()

    totals = {"open": 0, "booked": 0, "blocked": 0}
    by_day_map = {}

    for day, status, count in rows:
        day_str = day.isoformat()
        if day_str not in by_day_map:
            by_day_map[day_str] = {"date": day_str, "open": 0, "booked": 0, "blocked": 0}
        
        by_day_map[day_str][status] = count
        totals[status] += count

    by_day = list(by_day_map.values())
    by_day.sort(key=lambda x: x["date"])

    return jsonify({
        "totals": totals,
        "by_day": by_day
    })


@admin_rec.route("/api/admin/recruitment/slots/export")
def export_slots():
    err = _require_admin()
    if err: return err

    from_str = request.args.get("start_date") or request.args.get("from")
    to_str   = request.args.get("end_date") or request.args.get("to")
    if not from_str or not to_str:
        return jsonify({"error": "start_date and end_date date parameters are required."}), 400

    try:
        start_d = datetime.date.fromisoformat(from_str)
        end_d = datetime.date.fromisoformat(to_str)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    if end_d < start_d:
        return jsonify({"error": "end_date cannot be before start_date"}), 400

    delta = end_d - start_d
    if delta.days > 62:
        return jsonify({"error": "Date range cannot exceed 62 days"}), 400

    import pytz
    lagos_tz = pytz.timezone('Africa/Lagos')
    start_dt = lagos_tz.localize(datetime.datetime.combine(start_d, datetime.time.min))
    end_dt = lagos_tz.localize(datetime.datetime.combine(end_d, datetime.time.max))

    interviewer_ids = request.args.getlist("interviewer_id")
    if interviewer_ids:
        try:
            interviewer_ids = [int(x) for x in interviewer_ids]
        except ValueError:
            return jsonify({"error": "Invalid interviewer_id"}), 400

    export_format = request.args.get("format", "csv").lower()

    where_clauses = ["gs.start_time >= %s", "gs.start_time <= %s"]
    params = [start_dt, end_dt]

    if interviewer_ids:
        where_clauses.append("gs.interviewer_id = ANY(%s)")
        params.append(interviewer_ids)

    where_sql = " AND ".join(where_clauses)

    # Database fetching
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT gs.id, gs.start_time, gs.end_time, gs.is_booked, gs.is_blocked,
                       i.name AS primary_interviewer,
                       c.full_name AS candidate_name, c.email AS candidate_email, c.role AS candidate_role,
                       gs.title,
                       COALESCE(
                           STRING_AGG(pi.name, ', ' ORDER BY pi.name),
                           i.name
                       ) AS all_interviewers
                FROM generated_slots gs
                JOIN interviewers i ON gs.interviewer_id = i.id
                LEFT JOIN candidates c ON gs.candidate_id = c.id
                LEFT JOIN slot_interviewers si ON si.slot_id = gs.id
                LEFT JOIN interviewers pi ON pi.id = si.interviewer_id
                WHERE {where_sql}
                GROUP BY gs.id, gs.start_time, gs.end_time, gs.is_booked, gs.is_blocked,
                         i.name, c.full_name, c.email, c.role, gs.title
                ORDER BY gs.start_time;
            """, params)
            rows = cur.fetchall()

    data_list = []
    for r in rows:
        (s_id, s_start, s_end, is_booked, is_blocked, i_name, c_name, c_email, c_role, title, all_interviewers) = r
        start_lagos = s_start.astimezone(lagos_tz)
        end_lagos = s_end.astimezone(lagos_tz)

        # Computed title
        if not title:
            title = f"{i_name} — {start_lagos.strftime('%I:%M %p')}"

        status = "Open"
        if is_blocked:
            status = "Blocked"
        elif is_booked:
            status = f"Booked by {c_name or 'Unknown'} ({c_role or 'General'})"

        data_list.append({
            "id": s_id,
            "title": title,
            "start_time": start_lagos.isoformat(),
            "end_time": end_lagos.isoformat(),
            "status": status,
            "interviewer": all_interviewers,
            "candidate_name": c_name or "—",
            "candidate_email": c_email or "—",
            "candidate_role": c_role or "—"
        })

    if export_format == "json":
        return jsonify(data_list)

    # Otherwise stream CSV
    import io
    import csv

    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(['Slot ID', 'Title', 'Start Time (WAT)', 'End Time (WAT)', 'Status', 'Interviewer / Panel', 'Candidate Name', 'Candidate Email', 'Candidate Role'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)

        for item in data_list:
            writer.writerow([
                item["id"],
                item["title"],
                item["start_time"],
                item["end_time"],
                item["status"],
                item["interviewer"],
                item["candidate_name"],
                item["candidate_email"],
                item["candidate_role"]
            ])
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    headers = {
        'Content-Disposition': 'attachment; filename=interview_slots_export.csv',
        'Content-Type': 'text/csv'
    }
    return Response(generate(), headers=headers)


@admin_rec.route("/api/admin/recruitment/slots/generate", methods=["POST"])
def trigger_slot_generation():
    err = _require_admin()
    if err: return err

    data = request.json or {}
    weeks = data.get("weeks_ahead", 4)

    try:
        generate_slots(weeks_ahead=weeks)
    except Exception as e:
        print(f"Error generating slots: {e}")

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


@admin_rec.route("/api/admin/recruitment/stage-config/<stage_name>/open", methods=["POST"])
def stage_config_open(stage_name):
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # 1. Close all other stages (only one stage can be open at a time)
            cur.execute("""
                UPDATE stage_config
                SET closes_at = NOW()
                WHERE stage_name <> %s;
            """, (stage_name,))
            # 2. Open this stage
            cur.execute("""
                UPDATE stage_config
                SET opens_at = NOW(),
                    closes_at = NULL
                WHERE stage_name = %s;
            """, (stage_name,))
        conn.commit()

    return jsonify({"status": "success"})


@admin_rec.route("/api/admin/recruitment/stage-config/<stage_name>/close", methods=["POST"])
def stage_config_close(stage_name):
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE stage_config
                SET closes_at = NOW()
                WHERE stage_name = %s;
            """, (stage_name,))
        conn.commit()

    return jsonify({"status": "success"})


@admin_rec.route("/api/admin/recruitment/stage-config/<stage_name>/next", methods=["POST"])
def stage_config_next(stage_name):
    err = _require_admin()
    if err: return err

    STAGE_PIPELINE_ORDER = ['application', 'screening', 'assessment', 'interview', 'documents', 'final_decision']
    try:
        current_idx = STAGE_PIPELINE_ORDER.index(stage_name)
    except ValueError:
        return jsonify({"error": f"Invalid stage name '{stage_name}'."}), 400

    if current_idx + 1 >= len(STAGE_PIPELINE_ORDER):
        return jsonify({"error": "No next stage available."}), 400

    next_stage = STAGE_PIPELINE_ORDER[current_idx + 1]

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # 1. Close all stages
            cur.execute("""
                UPDATE stage_config
                SET closes_at = NOW();
            """)
            # 2. Open next stage
            cur.execute("""
                UPDATE stage_config
                SET opens_at = NOW(),
                    closes_at = NULL
                WHERE stage_name = %s;
            """, (next_stage,))
        conn.commit()

    return jsonify({"status": "success", "next_stage": next_stage})


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

    ok, new_log_id = resend_notification(log_id)
    return jsonify({"status": "success" if ok else "failed", "log_id": new_log_id})


# ── Documents admin view ──────────────────────────────────────────────────────

@admin_rec.route("/api/admin/recruitment/candidates/<int:cand_id>/cv")
def proxy_candidate_cv(cand_id):
    err = _require_admin()
    if err: return err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uj.public_id, c.cv_url FROM candidates c
                JOIN upload_jobs uj ON uj.candidate_id = c.id
                WHERE c.id = %s AND uj.target_field = 'cv_url'
                  AND uj.status = 'done' AND uj.public_id IS NOT NULL
                ORDER BY uj.updated_at DESC LIMIT 1;
            """, (cand_id,))
            row = cur.fetchone()
    if not row:
        return "This file is not available.", 404
    public_id, stored_url = row
    resource_type = "raw" if "/raw/upload/" in (stored_url or "") else "image"
    try:
        signed_url, _ = cloudinary.utils.cloudinary_url(
            public_id, resource_type=resource_type, type="authenticated",
            sign_url=True, expires_at=int(time.time()) + 300)
        if resource_type == "image":
            return redirect(signed_url, code=302)
        resp = requests.get(signed_url, timeout=20)
        if resp.status_code != 200:
            logger.error("Admin CV fetch failed: candidate=%s status=%s", cand_id, resp.status_code)
            return "We couldn't display this file. Please try again.", 502
        return Response(resp.content,
                        mimetype=resp.headers.get("Content-Type", "application/octet-stream"),
                        headers={"Content-Disposition": "inline"})
    except Exception:
        logger.exception("Admin CV preview failed: candidate=%s", cand_id)
        return "We couldn't display this file. Please try again.", 502


@admin_rec.route("/api/admin/recruitment/documents/<int:cand_id>")
def candidate_documents(cand_id):
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM candidates WHERE id = %s;", (cand_id,))
            cand = cur.fetchone()
            role = cand[0] if cand else None

            cur.execute("""
                SELECT document_type, label, accepted_formats, required, position
                FROM role_document_requirements
                WHERE role = %s
                ORDER BY position, id;
            """, (role,))
            requirements = cur.fetchall()
            if not requirements and role != "General":
                cur.execute("""
                    SELECT document_type, label, accepted_formats, required, position
                    FROM role_document_requirements
                    WHERE role = 'General'
                    ORDER BY position, id;
                """)
                requirements = cur.fetchall()

            cur.execute("""
                SELECT id, doc_type, verified, upload_status, uploaded_at, public_id,
                       rejection_note, rejected_at
                FROM candidate_documents WHERE candidate_id = %s;
            """, (cand_id,))
            rows = cur.fetchall()

    by_type = {r[1]: r for r in rows}
    doc_types = [r[0] for r in requirements] or list(by_type.keys())
    payload = []
    for doc_type in doc_types:
        req = next((r for r in requirements if r[0] == doc_type), None)
        row = by_type.get(doc_type)
        if row:
            payload.append({
                "id": row[0],
                "doc_type": row[1],
                "label": req[1] if req else row[1].replace("_", " ").title(),
                "accepted_formats": req[2] if req else [],
                "required": req[3] if req else True,
                "verified": row[2],
                "status": "rejected" if row[6] else row[3],
                "uploaded_at": row[4].isoformat() if row[4] else None,
                "public_id": row[5],
                "rejection_note": row[6],
                "rejected_at": row[7].isoformat() if row[7] else None,
                "view_url": f"/api/admin/recruitment/documents/file/{row[0]}" if row[5] else None,
            })
        else:
            payload.append({
                "id": None,
                "doc_type": doc_type,
                "label": req[1] if req else doc_type.replace("_", " ").title(),
                "accepted_formats": req[2] if req else [],
                "required": req[3] if req else True,
                "verified": False,
                "status": "not_uploaded",
                "uploaded_at": None,
                "public_id": None,
                "rejection_note": None,
                "rejected_at": None,
                "view_url": None,
            })
    return jsonify(payload)


@admin_rec.route("/api/admin/recruitment/documents/file/<int:doc_id>")
def proxy_candidate_document(doc_id):
    err = _require_admin()
    if err: return err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT public_id, url FROM candidate_documents
                WHERE id = %s AND public_id IS NOT NULL;
            """, (doc_id,))
            row = cur.fetchone()

    if not row:
        return "Document not found", 404

    public_id, stored_url = row
    resource_type = "raw" if stored_url and "/raw/upload/" in stored_url else "image"
    try:
        signed_url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            resource_type=resource_type,
            type="authenticated",
            sign_url=True,
            expires_at=int(time.time()) + 300,
        )
        if resource_type == "image":
            return redirect(signed_url, code=302)
        resp = requests.get(signed_url, timeout=20)
        if resp.status_code != 200:
            return "Failed to fetch file", resp.status_code
        return Response(
            resp.content,
            mimetype=resp.headers.get("Content-Type", "application/octet-stream"),
            headers={"Content-Disposition": "inline"},
        )
    except Exception as exc:
        print(f"[document-proxy] Error: {exc}")
        return "Failed to load file", 502


@admin_rec.route("/api/admin/recruitment/documents/<int:doc_id>/verify", methods=["POST"])
def verify_document(doc_id):
    err = _require_admin()
    if err: return err

    data = request.json or {}
    action = data.get("action", "approve")
    verified = bool(data.get("verified", action == "approve"))
    rejection_note = (data.get("rejection_note") or "").strip()

    with DBConnection() as conn:
        with conn.cursor() as cur:
            if action == "reject" or not verified:
                cur.execute("""
                    UPDATE candidate_documents
                    SET verified = FALSE,
                        rejection_note = %s,
                        rejected_at = NOW()
                    WHERE id = %s;
                """, (rejection_note or "Document rejected. Please replace and resubmit.", doc_id))
            else:
                cur.execute("""
                    UPDATE candidate_documents
                    SET verified = TRUE,
                        rejection_note = NULL,
                        rejected_at = NULL
                    WHERE id = %s;
                """, (doc_id,))
        conn.commit()

    return jsonify({"status": "success", "verified": verified})


@admin_rec.route("/api/admin/recruitment/role-document-requirements", methods=["GET", "POST", "PUT"])
def role_document_requirements():
    err = _require_admin()
    if err: return err

    if request.method == "GET":
        role = "General"
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, role, document_type, label, accepted_formats, required, position
                    FROM role_document_requirements
                    WHERE role = %s
                    ORDER BY position ASC;
                """, (role,))
                rows = cur.fetchall()
        return jsonify({"role": role, "documents": [{
            "id": r[0],
            "role": r[1],
            "document_type": r[2],
            "label": r[3],
            "accepted_formats": list(r[4] or []),
            "required": r[5],
            "position": r[6],
        } for r in rows]})

    data = request.json or {}
    role = "General"
    docs = data.get("documents") or []
    if len(docs) != 5:
        return jsonify({"error": "Exactly 5 employment documents are required."}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM role_document_requirements WHERE role = %s;", (role,))
            for idx, doc in enumerate(docs, 1):
                label = (doc.get("label") or "").strip()
                document_type = (doc.get("document_type") or label.lower().replace(" ", "_")).strip()
                formats = [f for f in (doc.get("accepted_formats") or ["PDF", "JPG", "PNG"])
                           if f in {"PDF", "JPG", "JPEG", "PNG"}]
                if not label or not document_type:
                    return jsonify({"error": "Each document needs a label."}), 400
                cur.execute("""
                    INSERT INTO role_document_requirements
                        (role, document_type, label, accepted_formats, required, position)
                    VALUES (%s, %s, %s, %s, TRUE, %s);
                """, (role, document_type, label, formats, idx))
        conn.commit()

    return jsonify({"status": "success", "role": role})


@admin_rec.route("/api/admin/recruitment/candidates/<int:cand_id>/assign-quiz", methods=["POST"])
def assign_or_reset_quiz(cand_id):
    err = _require_admin()
    if err:
        return err

    data = request.json or {}
    quiz_id = data.get("quiz_id")
    if not quiz_id:
        return jsonify({"error": "Quiz ID is required."}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Check candidate cohort mapping
            cur.execute("SELECT cohort_id, email, full_name, stage FROM candidates WHERE id = %s;", (cand_id,))
            cand_row = cur.fetchone()
            if not cand_row:
                return jsonify({"error": "Candidate not found."}), 404
            cohort_id, email, full_name, stage = cand_row

            # Check if quiz exists
            cur.execute("SELECT title, cohort_id FROM quizzes WHERE id = %s;", (quiz_id,))
            quiz_row = cur.fetchone()
            if not quiz_row:
                return jsonify({"error": "Quiz not found."}), 404
            q_title, q_cohort_id = quiz_row

            # Enforce cohort matching (but default to Cohort 1 if none set)
            effective_cohort = cohort_id
            if not effective_cohort:
                cur.execute("SELECT id FROM cohorts WHERE name = 'Cohort 1';")
                crow = cur.fetchone()
                effective_cohort = crow[0] if crow else None

            # Reset logic: delete previous exam_results and scores attempts
            cur.execute("DELETE FROM exam_results WHERE candidate_id = %s AND quiz_id = %s;", (cand_id, quiz_id))
            cur.execute("DELETE FROM scores WHERE candidate_id = %s AND quiz_id = %s;", (cand_id, quiz_id))

            # Update candidate stage to screening_passed so they can view and take it on their dashboard
            if stage not in ("screening_passed", "screening_flagged", "assessment_in_progress"):
                cur.execute("""
                    UPDATE candidates
                    SET stage = 'screening_passed', stage_updated_at = NOW()
                    WHERE id = %s;
                """, (cand_id,))
                cur.execute("""
                    INSERT INTO candidate_stage_history
                        (candidate_id, from_stage, to_stage, changed_by, reason)
                    VALUES (%s, %s, 'screening_passed', 'admin', %s);
                """, (cand_id, stage, f"Assigned assessment: {q_title}"))

            # Also ensure whitelist contains candidate to allow OTP login
            cur.execute("""
                INSERT INTO whitelist (email, name, cohort_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                SET name = COALESCE(whitelist.name, EXCLUDED.name),
                    cohort_id = COALESCE(whitelist.cohort_id, EXCLUDED.cohort_id);
            """, (email, full_name, effective_cohort))

        conn.commit()

    return jsonify({"status": "success", "message": f"Quiz '{q_title}' assigned successfully."})


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
