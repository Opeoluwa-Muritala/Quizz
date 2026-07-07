import os
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

_db_url = os.environ.get("NEON_DATABASE_URL")
connection_pool = None

try:
    if _db_url:
        connection_pool = pool.ThreadedConnectionPool(1, 20, _db_url)
    else:
        print("ERROR: NEON_DATABASE_URL not set.")
except Exception as e:
    print(f"Error creating connection pool: {e}")


class DBConnection:
    def __enter__(self):
        if not connection_pool:
            raise Exception("Database connection pool not initialized. Check NEON_DATABASE_URL.")
        self.conn = connection_pool.getconn()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "conn") and self.conn:
            connection_pool.putconn(self.conn)
