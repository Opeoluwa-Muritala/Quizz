"""Persisted interview-schedule expansion (all wall-clock times are Africa/Lagos)."""
import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Africa/Lagos")
UTC = datetime.timezone.utc


def _windows(value, day):
    """JSONB keys arrive as strings; tolerate an empty/malformed schedule."""
    return (value or {}).get(str(day), (value or {}).get(day, [])) or []


def generate_schedule_slots(conn, schedule_id: int, horizon_days: int = 90) -> int:
    """Generate only unbooked schedule slots. Booked slots are never altered."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, title, interview_round, schedule_type, start_date, end_date, active_days,
                   availability_windows, duration_minutes, buffer_minutes,
                   booking_lead_time_hours, daily_booking_cap, booking_mode
            FROM interview_schedules WHERE id = %s AND published = TRUE
        """, (schedule_id,))
        schedule = cur.fetchone()
        if not schedule:
            return 0
        (sid, title, interview_round, schedule_type, start_date, end_date, active_days, windows,
         duration, buffer, lead, daily_cap, mode) = schedule
        cur.execute("""
            SELECT si.interviewer_id FROM schedule_interviewers si
            JOIN interviewers i ON i.id = si.interviewer_id
            WHERE si.schedule_id = %s AND i.active = TRUE ORDER BY si.position, si.interviewer_id
        """, (sid,))
        interviewers = [r[0] for r in cur.fetchall()]
        if not interviewers:
            return 0

        today = datetime.datetime.now(LOCAL_TZ).date()
        first = max(start_date or today, today)
        last = end_date or (today + datetime.timedelta(days=horizon_days))
        last = min(last, today + datetime.timedelta(days=horizon_days))
        created = 0
        day = first
        robin_index = 0
        while day <= last:
            # Python weekday is Mon=0; UI/Postgres schedule data uses Sun=0, Mon=1.
            ui_day = (day.weekday() + 1) % 7
            if ui_day not in (active_days or []):
                day += datetime.timedelta(days=1)
                continue
            made_today = 0
            for window in _windows(windows, ui_day):
                try:
                    start_t = datetime.time.fromisoformat(window["start"])
                    end_t = datetime.time.fromisoformat(window["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                at = datetime.datetime.combine(day, start_t, tzinfo=LOCAL_TZ)
                end_at = datetime.datetime.combine(day, end_t, tzinfo=LOCAL_TZ)
                while at + datetime.timedelta(minutes=duration) <= end_at:
                    if daily_cap and made_today >= daily_cap:
                        break
                    slot_end = at + datetime.timedelta(minutes=duration)
                    primary = interviewers[robin_index % len(interviewers)] if mode == "round_robin" else interviewers[0]
                    # Do not create a slot that conflicts with any required interviewer.
                    required = [primary] if mode in ("single", "round_robin") else interviewers
                    conflict = False
                    for interviewer_id in required:
                        cur.execute("""
                            SELECT 1 FROM generated_slots gs
                            LEFT JOIN slot_interviewers spi ON spi.slot_id = gs.id
                            WHERE (gs.interviewer_id = %s OR spi.interviewer_id = %s)
                              AND NOT (gs.end_time <= %s OR gs.start_time >= %s)
                            LIMIT 1
                        """, (interviewer_id, interviewer_id, at.astimezone(UTC), slot_end.astimezone(UTC)))
                        if cur.fetchone():
                            conflict = True
                            break
                    if not conflict:
                        cur.execute("""
                            INSERT INTO generated_slots
                              (schedule_id, interviewer_id, start_time, end_time, title,
                               interview_round, booking_mode, booking_lead_time_hours, daily_booking_cap)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (schedule_id, start_time) WHERE schedule_id IS NOT NULL DO NOTHING
                            RETURNING id
                        """, (sid, primary, at.astimezone(UTC), slot_end.astimezone(UTC), title,
                              interview_round, mode, lead, daily_cap))
                        row = cur.fetchone()
                        if row:
                            slot_id = row[0]
                            if mode == "collective":
                                for interviewer_id in interviewers:
                                    cur.execute("INSERT INTO slot_interviewers (slot_id, interviewer_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (slot_id, interviewer_id))
                            created += 1
                            made_today += 1
                            robin_index += 1
                    at += datetime.timedelta(minutes=duration + buffer)
            day += datetime.timedelta(days=1)
        cur.execute("UPDATE interview_schedules SET generated_at = NOW(), updated_at = NOW() WHERE id = %s", (sid,))
        return created
