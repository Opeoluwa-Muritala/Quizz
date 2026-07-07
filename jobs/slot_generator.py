"""
Generates interview slots from availability_rules for a rolling window.
Called by the scheduler and by admin_recruitment.trigger_slot_generation.
"""
import datetime
from db import DBConnection


def generate_slots(weeks_ahead: int = 4) -> int:
    """
    Expand all active availability_rules into generated_slots rows
    for the next `weeks_ahead` weeks. Returns the number of new slots created.
    """
    today    = datetime.date.today()
    end_date = today + datetime.timedelta(weeks=weeks_ahead)
    created  = 0

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, interviewer_id, rule_type, day_of_week,
                       date_from, date_to, start_time, end_time,
                       slot_duration_minutes, buffer_minutes
                FROM availability_rules
                WHERE active = TRUE;
            """)
            rules = cur.fetchall()

            for rule in rules:
                (rule_id, interviewer_id, rule_type, day_of_week,
                 date_from, date_to, start_t, end_t,
                 slot_dur, buffer_min) = rule

                # Determine the date range for this rule
                if rule_type == "date_range":
                    r_start = max(date_from or today, today)
                    r_end   = min(date_to   or end_date, end_date)
                else:  # recurring
                    r_start = today
                    r_end   = end_date

                # Walk each day in range
                current = r_start
                while current <= r_end:
                    # For recurring rules, skip days that don't match day_of_week
                    # 0=Monday, 6=Sunday (Python weekday() convention)
                    if rule_type == "recurring" and day_of_week is not None:
                        if current.weekday() != day_of_week:
                            current += datetime.timedelta(days=1)
                            continue

                    # Generate slots within start_time → end_time
                    slot_start = datetime.datetime.combine(current, start_t,
                                 tzinfo=datetime.timezone.utc)
                    day_end    = datetime.datetime.combine(current, end_t,
                                 tzinfo=datetime.timezone.utc)
                    step = datetime.timedelta(minutes=slot_dur + buffer_min)

                    while slot_start + datetime.timedelta(minutes=slot_dur) <= day_end:
                        slot_end = slot_start + datetime.timedelta(minutes=slot_dur)

                        try:
                            cur.execute("""
                                INSERT INTO generated_slots
                                    (availability_rule_id, interviewer_id,
                                     start_time, end_time)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (availability_rule_id, start_time) DO NOTHING;
                            """, (rule_id, interviewer_id, slot_start, slot_end))
                            if cur.rowcount:
                                created += 1
                        except Exception as exc:
                            print(f"[slot_generator] Error inserting slot: {exc}")

                        slot_start += step

                    current += datetime.timedelta(days=1)

        conn.commit()

    print(f"[slot_generator] Created {created} new slots (window={weeks_ahead}w).")
    return created
