import os
import time
import psycopg2
from psycopg2 import OperationalError
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

# We expect the pooler connection string is provided in NEON_DATABASE_URL
_db_url = os.environ.get("NEON_DATABASE_URL")
_default_pool_mode = "serverless" if os.environ.get("VERCEL") else "persistent"
_pool_mode = os.environ.get("DATABASE_POOL_MODE", _default_pool_mode).lower()
_pool = None


def _persistent_pool():
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            int(os.environ.get("DATABASE_POOL_MIN", "1")),
            int(os.environ.get("DATABASE_POOL_MAX", "10")),
            _db_url,
        )
    return _pool


def _new_connection():
    if _pool_mode == "persistent":
        conn = _persistent_pool().getconn()
        if not conn.closed:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.rollback()
                return conn
            except OperationalError:
                _persistent_pool().putconn(conn, close=True)
        return _persistent_pool().getconn()

    last_error = None
    for attempt in range(2):
        try:
            return psycopg2.connect(
                _db_url,
                connect_timeout=int(os.environ.get("DATABASE_CONNECT_TIMEOUT", "5")),
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
            )
        except OperationalError as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.2)
    raise last_error


def close_request_connection(error=None):
    """Release the connection shared by all DBConnection blocks in one request."""
    try:
        from flask import g
        conn = g.pop("_db_connection", None)
    except RuntimeError:
        conn = None
    if not conn:
        return
    try:
        if not conn.closed:
            conn.rollback()
    finally:
        if _pool_mode == "persistent":
            _persistent_pool().putconn(conn, close=bool(conn.closed))
        else:
            conn.close()

class DBConnection:
    def __init__(self):
        self.conn = None

    def __enter__(self):
        if not _db_url:
            raise Exception("NEON_DATABASE_URL environment variable is not set.")
        try:
            from flask import g, has_request_context
            if has_request_context():
                self.conn = getattr(g, "_db_connection", None)
                if self.conn is None or self.conn.closed:
                    self.conn = _new_connection()
                    g._db_connection = self.conn
                self.request_scoped = True
            else:
                self.conn = _new_connection()
                self.request_scoped = False
        except RuntimeError:
            self.conn = _new_connection()
            self.request_scoped = False
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn and exc_type:
            self.conn.rollback()
        if self.conn and not getattr(self, "request_scoped", False):
            try:
                if not self.conn.closed:
                    self.conn.rollback()
                if _pool_mode == "persistent":
                    _persistent_pool().putconn(self.conn, close=bool(self.conn.closed))
                else:
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
