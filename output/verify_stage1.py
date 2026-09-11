"""Read-only verification for the stage-1 online migration."""
from talent_portal.db import DBConnection

with DBConnection() as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT status, COUNT(1) FROM job_postings GROUP BY status ORDER BY status")
        print("job status counts:", cursor.fetchall())
        cursor.execute("SELECT COUNT(1) FROM candidates WHERE job_id IS NOT NULL")
        print("linked candidates:", cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(1) FROM candidates WHERE job_id IS NULL")
        print("unmatched candidates:", cursor.fetchone()[0])
