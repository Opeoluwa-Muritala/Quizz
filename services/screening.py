"""
Eligibility screening service.
Reads rules from stage_config and applies them to a candidate.
"""
import datetime
from db import DBConnection


def _get_screening_rules() -> dict:
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT min_age, max_age, accepted_nysc_statuses, screening_mode
                FROM stage_config
                WHERE stage_name = 'screening'
                ORDER BY cycle_id DESC
                LIMIT 1;
            """)
            row = cur.fetchone()

    if not row:
        return {"min_age": 18, "max_age": 35,
                "accepted_nysc_statuses": ["completed", "exempted"],
                "screening_mode": "soft"}
    return {
        "min_age": row[0] or 18,
        "max_age": row[1] or 35,
        "accepted_nysc_statuses": list(row[2] or ["completed", "exempted"]),
        "screening_mode": row[3] or "soft",
    }


def _compute_age(dob: datetime.date) -> int:
    today = datetime.date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def run_screening(candidate_id: int) -> tuple[str, str | None]:
    """
    Evaluate eligibility for a candidate.

    Returns (new_stage, reason):
      - new_stage: 'screening_passed' | 'screening_flagged' | 'screening_failed'
      - reason: human-readable explanation, or None if passed cleanly
    """
    rules = _get_screening_rules()

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT dob, nysc_status FROM candidates WHERE id = %s;
            """, (candidate_id,))
            row = cur.fetchone()

    if not row:
        return "screening_failed", "Candidate record not found."

    dob, nysc_status = row
    flags = []

    if dob:
        age = _compute_age(dob)
        if age < rules["min_age"]:
            flags.append(f"Age {age} is below minimum of {rules['min_age']}.")
        elif age > rules["max_age"]:
            flags.append(f"Age {age} exceeds maximum of {rules['max_age']}.")
    else:
        flags.append("Date of birth not provided.")

    if nysc_status:
        if nysc_status not in rules["accepted_nysc_statuses"]:
            flags.append(
                f"NYSC status '{nysc_status}' is not in accepted values: "
                f"{', '.join(rules['accepted_nysc_statuses'])}."
            )
    else:
        flags.append("NYSC status not provided.")

    if not flags:
        return "screening_passed", None

    reason = " ".join(flags)
    mode = rules["screening_mode"]

    if mode == "hard":
        return "screening_failed", reason

    # soft mode → flag for manual review, candidate still proceeds
    return "screening_flagged", reason


def apply_screening(candidate_id: int) -> str:
    """
    Run screening, persist result, return new stage string.
    Caller is responsible for sending the appropriate notification.
    """
    new_stage, reason = run_screening(candidate_id)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE candidates
                SET stage = %s,
                    stage_updated_at = NOW(),
                    eligibility_flag = %s,
                    eligibility_flag_reason = %s
                WHERE id = %s;
            """, (
                new_stage,
                bool(reason),
                reason,
                candidate_id,
            ))
            cur.execute("""
                INSERT INTO candidate_stage_history (candidate_id, from_stage, to_stage, reason)
                SELECT %s, stage, %s, %s
                FROM candidates WHERE id = %s;
            """, (candidate_id, new_stage, reason or "auto-screening", candidate_id))
        conn.commit()

    if new_stage == 'screening_passed':
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM candidates WHERE id = %s;", (candidate_id,))
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "INSERT INTO whitelist (email) VALUES (%s) ON CONFLICT (email) DO NOTHING;",
                        (row[0],)
                    )
            conn.commit()

    return new_stage
