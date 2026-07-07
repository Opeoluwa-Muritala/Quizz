"""
Deadline expiry job.
Runs periodically to find candidates who've passed their stage deadline
and auto-transitions them to the appropriate expired stage.
"""
import datetime
import threading
from db import DBConnection
from services.notifications import send_notification


EXPIRY_MAP = {
    "applied":              ("application_expired",  "application"),
    "assessment_in_progress": ("assessment_expired", "assessment"),
    "interview_slot_pending": ("booking_expired",    "interview"),
    "documents_pending":    ("documents_expired",    "documents"),
}

EXPIRY_NOTIFICATION = {
    "application_expired":  None,
    "assessment_expired":   None,
    "booking_expired":      None,
    "documents_expired":    None,
}


def _get_deadline(stage: str, stage_updated_at: datetime.datetime) -> datetime.datetime | None:
    """
    Calculate the deadline for a candidate's current stage.
    Uses stage_config.closes_at (absolute) or relative_deadline_hours (per-candidate).
    """
    stage_key_map = {
        "applied":                "application",
        "assessment_in_progress": "assessment",
        "interview_slot_pending": "interview",
        "documents_pending":      "documents",
    }
    config_stage = stage_key_map.get(stage)
    if not config_stage:
        return None

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT closes_at, relative_deadline_hours
                FROM stage_config
                WHERE stage_name = %s
                ORDER BY cycle_id DESC LIMIT 1;
            """, (config_stage,))
            row = cur.fetchone()

    if not row:
        return None

    closes_at, rel_hours = row

    # Absolute deadline takes priority
    if closes_at:
        return closes_at

    # Relative: N hours from when the candidate entered this stage
    if rel_hours and stage_updated_at:
        if stage_updated_at.tzinfo is None:
            stage_updated_at = stage_updated_at.replace(tzinfo=datetime.timezone.utc)
        return stage_updated_at + datetime.timedelta(hours=rel_hours)

    return None


def expire_past_deadlines() -> int:
    """
    Find candidates past their stage deadline and transition them.
    Returns the count of transitioned candidates.
    """
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    transitioned = 0

    with DBConnection() as conn:
        with conn.cursor() as cur:
            stage_list = list(EXPIRY_MAP.keys())
            fmt = ",".join(["%s"] * len(stage_list))
            cur.execute(f"""
                SELECT id, stage, stage_updated_at
                FROM candidates
                WHERE stage IN ({fmt});
            """, stage_list)
            candidates = cur.fetchall()

    expired_candidates = []
    for cand_id, stage, updated_at in candidates:
        if updated_at and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=datetime.timezone.utc)
        deadline = _get_deadline(stage, updated_at)
        if deadline and now > deadline:
            expired_candidates.append((cand_id, stage))

    if not expired_candidates:
        return 0

    with DBConnection() as conn:
        with conn.cursor() as cur:
            for cand_id, old_stage in expired_candidates:
                new_stage, _ = EXPIRY_MAP[old_stage]
                cur.execute("""
                    UPDATE candidates
                    SET stage = %s, stage_updated_at = NOW()
                    WHERE id = %s AND stage = %s;
                """, (new_stage, cand_id, old_stage))
                if cur.rowcount:
                    cur.execute("""
                        INSERT INTO candidate_stage_history
                            (candidate_id, from_stage, to_stage, changed_by, reason)
                        VALUES (%s, %s, %s, 'system', 'deadline_expired');
                    """, (cand_id, old_stage, new_stage))
                    transitioned += 1
        conn.commit()

    # Send notifications for each expired candidate (fire-and-forget)
    for cand_id, old_stage in expired_candidates[:transitioned]:
        new_stage, _ = EXPIRY_MAP[old_stage]
        event = EXPIRY_NOTIFICATION.get(new_stage)
        if event:
            threading.Thread(
                target=send_notification,
                args=(cand_id, new_stage, event),
                daemon=True,
            ).start()

    print(f"[deadline_expiry] Transitioned {transitioned} candidates to expired stages.")
    return transitioned
