"""Stage 1 migration. Run against an existing recruitment database."""
from talent_portal.db import DBConnection

LEGACY_ROLES = (
    'Loan Officer (SME)', 'Operation', 'Information Technology and Systems (IT&S)',
    'Credit Risk', 'Audit', 'Human Resource', 'Recovery',
)


def migrate_job_postings(conn):
    """Idempotent, transactional migration; preserve existing candidate stages."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(74612001)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ats_migrations (
                name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS job_postings (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
                department TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                employment_type TEXT NOT NULL DEFAULT 'Full-time'
                    CHECK (employment_type IN ('Full-time','Part-time','Contract','Temporary','Internship')),
                description TEXT NOT NULL DEFAULT '',
                requirements TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','closed')),
                application_deadline TIMESTAMPTZ,
                legacy_role_key TEXT UNIQUE,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                published_at TIMESTAMPTZ,
                closed_at TIMESTAMPTZ
            );
            ALTER TABLE candidates ADD COLUMN IF NOT EXISTS job_id INTEGER
                REFERENCES job_postings(id) ON DELETE RESTRICT;
            CREATE INDEX IF NOT EXISTS idx_candidates_job ON candidates(job_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status_deadline ON job_postings(status, application_deadline);
        """)
        cur.execute("SELECT 1 FROM ats_migrations WHERE name = '001_job_postings'")
        if cur.fetchone():
            return
        cur.execute("SELECT recruitment_portal_open FROM exam_settings WHERE id = 1")
        row = cur.fetchone()
        status = 'published' if row is None or row[0] else 'closed'
        # Preserve application stage windows as per-job deadlines. A future
        # opening becomes a draft requiring deliberate publication, not early access.
        cur.execute("SELECT opens_at, closes_at FROM stage_config WHERE stage_name='application' ORDER BY cycle_id DESC LIMIT 1")
        window = cur.fetchone()
        cur.execute("SELECT NOW()")
        now = cur.fetchone()[0]
        deadline = window[1] if window else None
        if deadline and deadline <= now:
            status = 'closed'
        elif status == 'published' and window and window[0] and window[0] > now:
            status = 'draft'
        for title in LEGACY_ROLES:
            cur.execute("""
                INSERT INTO job_postings(title, location, legacy_role_key, status, application_deadline,
                                         published_at, closed_at)
                VALUES (%s, 'Multiple locations', %s, %s, %s,
                        CASE WHEN %s='published' THEN NOW() END,
                        CASE WHEN %s='closed' THEN NOW() END)
                ON CONFLICT (legacy_role_key) DO NOTHING
            """, (title, title.lower(), status, deadline, status, status))
        cur.execute("""
            UPDATE candidates c SET job_id = j.id FROM job_postings j
            WHERE c.job_id IS NULL AND LOWER(BTRIM(c.role)) = j.legacy_role_key;
            INSERT INTO ats_migrations(name) VALUES ('001_job_postings');
        """)


def init_job_postings_db():
    with DBConnection() as conn:
        migrate_job_postings(conn)
        conn.commit()


if __name__ == '__main__':
    init_job_postings_db()
    print('Job-posting migration complete.')
