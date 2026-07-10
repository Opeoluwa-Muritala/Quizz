import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# We expect the pooler connection string is provided in NEON_DATABASE_URL
_db_url = os.environ.get("NEON_DATABASE_URL")

class DBConnection:
    def __init__(self):
        self.conn = None

    def __enter__(self):
        if not _db_url:
            raise Exception("NEON_DATABASE_URL environment variable is not set.")
        # Open a new connection per request. Since Neon handles pools via PgBouncer (pooler),
        # this is fast and serverless-friendly.
        self.conn = psycopg2.connect(_db_url)
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


def check_interviewer_overlap(conn, interviewer_id, start_time, end_time, exclude_slot_id=None):
    """
    Check if an interviewer has any overlapping active (not blocked) slots.
    Returns the colliding slot dict or None.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, start_time, end_time FROM generated_slots
            WHERE interviewer_id = %s
              AND is_blocked = FALSE
              AND start_time < %s AND end_time > %s
              AND (%s IS NULL OR id != %s)
        """, (interviewer_id, end_time, start_time, exclude_slot_id, exclude_slot_id))
        row = cur.fetchone()
        if row:
            return {"id": row[0], "start_time": row[1], "end_time": row[2]}
        return None

