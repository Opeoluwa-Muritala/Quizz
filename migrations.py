"""
Recruitment pipeline database migrations.
Run once at app startup via init_recruitment_db().
"""
from db import DBConnection


def init_recruitment_db():
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # ── Extend candidates table ─────────────────────────────────
            cur.execute("""
                ALTER TABLE candidates
                    ADD COLUMN IF NOT EXISTS dob DATE,
                    ADD COLUMN IF NOT EXISTS nysc_status TEXT,
                    ADD COLUMN IF NOT EXISTS cv_url TEXT,
                    ADD COLUMN IF NOT EXISTS stage TEXT DEFAULT 'applied',
                    ADD COLUMN IF NOT EXISTS stage_updated_at TIMESTAMPTZ DEFAULT NOW(),
                    ADD COLUMN IF NOT EXISTS eligibility_flag BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS eligibility_flag_reason TEXT;
            """)

            # ── scores – one row per assessment attempt ─────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scores (
                    id               SERIAL PRIMARY KEY,
                    candidate_id     INTEGER REFERENCES candidates(id),
                    stage_label      TEXT NOT NULL DEFAULT 'assessment_round_1',
                    score            NUMERIC(5,2),
                    score_fraction   TEXT,
                    pass_fail        TEXT,
                    taken_at         TIMESTAMPTZ,
                    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    duration_seconds INTEGER,
                    tab_switches     INTEGER DEFAULT 0,
                    breakdown_json   JSONB,
                    time_taken_secs  INTEGER,
                    question_order   JSONB
                );
            """)

            # ── candidate_documents ─────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS candidate_documents (
                    id            SERIAL PRIMARY KEY,
                    candidate_id  INTEGER REFERENCES candidates(id),
                    doc_type      TEXT NOT NULL,
                    url           TEXT,
                    public_id     TEXT,
                    uploaded_at   TIMESTAMPTZ DEFAULT NOW(),
                    verified      BOOLEAN DEFAULT FALSE,
                    upload_status TEXT DEFAULT 'pending',
                    rejection_note TEXT,
                    rejected_at   TIMESTAMPTZ
                );
            """)
            cur.execute("""
                ALTER TABLE candidate_documents
                    ADD COLUMN IF NOT EXISTS rejection_note TEXT,
                    ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ;
            """)
            cur.execute("""
                DELETE FROM candidate_documents a
                USING candidate_documents b
                WHERE a.candidate_id = b.candidate_id
                  AND a.doc_type = b.doc_type
                  AND a.id < b.id;
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_documents_candidate_doc_type
                ON candidate_documents (candidate_id, doc_type);
            """)

            # ── interviewers ────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS interviewers (
                    id                 SERIAL PRIMARY KEY,
                    name               TEXT NOT NULL,
                    email              TEXT NOT NULL UNIQUE,
                    active             BOOLEAN DEFAULT TRUE,
                    meeting_provider   TEXT DEFAULT 'google_meet',
                    google_calendar_id TEXT,
                    zoom_user_id       TEXT,
                    created_at         TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # ── availability_rules ──────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS availability_rules (
                    id                      SERIAL PRIMARY KEY,
                    interviewer_id          INTEGER REFERENCES interviewers(id),
                    rule_type               TEXT DEFAULT 'recurring',
                    day_of_week             INTEGER,
                    date_from               DATE,
                    date_to                 DATE,
                    start_time              TIME NOT NULL,
                    end_time                TIME NOT NULL,
                    slot_duration_minutes   INTEGER NOT NULL DEFAULT 30,
                    buffer_minutes          INTEGER NOT NULL DEFAULT 10,
                    booking_lead_time_hours INTEGER NOT NULL DEFAULT 24,
                    active                  BOOLEAN DEFAULT TRUE,
                    created_at              TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # ── generated_slots ─────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS generated_slots (
                    id                   SERIAL PRIMARY KEY,
                    availability_rule_id INTEGER REFERENCES availability_rules(id),
                    interviewer_id       INTEGER REFERENCES interviewers(id),
                    start_time           TIMESTAMPTZ NOT NULL,
                    end_time             TIMESTAMPTZ NOT NULL,
                    is_booked            BOOLEAN DEFAULT FALSE,
                    is_blocked           BOOLEAN DEFAULT FALSE,
                    candidate_id         INTEGER REFERENCES candidates(id),
                    meeting_link         TEXT,
                    external_event_id    TEXT,
                    meeting_provider     TEXT,
                    created_at           TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (availability_rule_id, start_time)
                );
            """)

            # ── stage_config ────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stage_config (
                    id                       SERIAL PRIMARY KEY,
                    cycle_id                 INTEGER DEFAULT 1,
                    stage_name               TEXT NOT NULL,
                    opens_at                 TIMESTAMPTZ,
                    closes_at                TIMESTAMPTZ,
                    duration_minutes         INTEGER,
                    relative_deadline_hours  INTEGER,
                    pass_mark                NUMERIC(5,2) DEFAULT 50.0,
                    min_age                  INTEGER DEFAULT 18,
                    max_age                  INTEGER DEFAULT 35,
                    accepted_nysc_statuses   TEXT[] DEFAULT ARRAY['completed','exempted'],
                    screening_mode           TEXT DEFAULT 'soft',
                    created_at               TIMESTAMPTZ DEFAULT NOW(),
                    updated_at               TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (cycle_id, stage_name)
                );
            """)

            # ── email_log ───────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_log (
                    id              SERIAL PRIMARY KEY,
                    candidate_id    INTEGER REFERENCES candidates(id),
                    stage           TEXT,
                    event_type      TEXT NOT NULL,
                    recipient_email TEXT,
                    sent_at         TIMESTAMPTZ DEFAULT NOW(),
                    status          TEXT DEFAULT 'sent',
                    error_message   TEXT,
                    template_used   TEXT
                );
            """)

            # ── recruitment_cycles ──────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS recruitment_cycles (
                    id         SERIAL PRIMARY KEY,
                    name       TEXT NOT NULL,
                    active     BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # ── candidate_stage_history ─────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS candidate_stage_history (
                    id           SERIAL PRIMARY KEY,
                    candidate_id INTEGER REFERENCES candidates(id),
                    from_stage   TEXT,
                    to_stage     TEXT NOT NULL,
                    changed_at   TIMESTAMPTZ DEFAULT NOW(),
                    changed_by   TEXT DEFAULT 'system',
                    reason       TEXT
                );
            """)

            # ── upload_jobs – tracks async background uploads ───────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS upload_jobs (
                    id           TEXT PRIMARY KEY,
                    candidate_id INTEGER REFERENCES candidates(id),
                    doc_type     TEXT,
                    target_field TEXT,
                    status       TEXT DEFAULT 'pending',
                    url          TEXT,
                    public_id    TEXT,
                    error        TEXT,
                    created_at   TIMESTAMPTZ DEFAULT NOW(),
                    updated_at   TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # ── role_document_requirements – 5 configurable employment docs per role ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS role_document_requirements (
                    id               SERIAL PRIMARY KEY,
                    role             TEXT NOT NULL,
                    document_type    TEXT NOT NULL,
                    label            TEXT NOT NULL,
                    accepted_formats TEXT[] NOT NULL DEFAULT ARRAY['PDF','DOC','DOCX','JPG','PNG'],
                    required         BOOLEAN NOT NULL DEFAULT TRUE,
                    position         INTEGER NOT NULL,
                    created_at       TIMESTAMPTZ DEFAULT NOW(),
                    updated_at       TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (role, document_type)
                );
            """)

            # ── slot_interviewers – panel members for each slot ─────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS slot_interviewers (
                    slot_id       INTEGER REFERENCES generated_slots(id) ON DELETE CASCADE,
                    interviewer_id INTEGER REFERENCES interviewers(id) ON DELETE CASCADE,
                    added_at      TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (slot_id, interviewer_id)
                );
            """)

            # ── add interview_instructions column if missing ────────────
            cur.execute("""
                ALTER TABLE stage_config
                ADD COLUMN IF NOT EXISTS interview_instructions TEXT;
            """)

            # ── seed default recruitment cycle ──────────────────────────
            cur.execute("SELECT COUNT(*) FROM recruitment_cycles;")
            if cur.fetchone()[0] == 0:
                cur.execute("""
                    INSERT INTO recruitment_cycles (name, active)
                    VALUES ('Executive Trainee 2026', TRUE);
                """)

            # ── seed default stage_config rows ──────────────────────────
            cur.execute("SELECT COUNT(*) FROM stage_config;")
            if cur.fetchone()[0] == 0:
                defaults = [
                    # stage_name, duration_minutes, relative_deadline_hours, pass_mark, min_age, max_age
                    ("application",      None, None, None, 18, 35),
                    ("screening",        None, None, None, 18, 35),
                    ("assessment",       60,   72,   50.0, 18, 35),
                    ("interview",        None, 72,   None, 18, 35),
                    ("documents",        None, 72,   None, 18, 35),
                    ("final_decision",   None, None, None, 18, 35),
                ]
                for row in defaults:
                    cur.execute("""
                        INSERT INTO stage_config
                            (cycle_id, stage_name, duration_minutes, relative_deadline_hours,
                             pass_mark, min_age, max_age)
                        VALUES (1, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (cycle_id, stage_name) DO NOTHING;
                    """, row)

            cur.execute("SELECT COUNT(*) FROM role_document_requirements;")
            if cur.fetchone()[0] == 0:
                default_roles = [
                    "Loan Officer", "Operations", "IT&S", "Audit", "Credit Risk",
                    "HR", "Recovery", "General"
                ]
                default_docs = [
                    ("nysc_certificate", "NYSC certificate", 1),
                    ("guarantor_form", "Guarantor form", 2),
                    ("utility_bill", "Utility bill", 3),
                    ("bank_statement", "Bank statement", 4),
                    ("passport_photograph", "Passport photograph", 5),
                ]
                for role in default_roles:
                    for doc_type, label, position in default_docs:
                        cur.execute("""
                            INSERT INTO role_document_requirements
                                (role, document_type, label, accepted_formats, required, position)
                            VALUES (%s, %s, %s, ARRAY['PDF','DOC','DOCX','JPG','PNG'], TRUE, %s)
                            ON CONFLICT (role, document_type) DO NOTHING;
                        """, (role, doc_type, label, position))

        conn.commit()
