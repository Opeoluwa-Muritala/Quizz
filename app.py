import os
import time
import datetime
import secrets
import hmac
import csv
import io
import json
import requests
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, Response, g
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader
import cloudinary.utils

# Load environment variables before importing db (which reads NEON_DATABASE_URL)
load_dotenv()

# Single connection pool — defined in db.py, imported here so all modules share it
from db import DBConnection, close_request_connection  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    print("WARNING: FLASK_SECRET_KEY not set. Generating ephemeral key.")
    app.secret_key = secrets.token_hex(32)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

ADMIN_SESSION_TIMEOUT_MINUTES = 30
MAX_ADMIN_DEVICES = 2


# Initialize Cloudinary
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

def init_db():
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Create candidates table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    id                 SERIAL PRIMARY KEY,
                    full_name          TEXT NOT NULL,
                    email              TEXT NOT NULL UNIQUE,
                    selfie_url         TEXT,
                    id_card_url        TEXT,
                    cloudinary_folder  TEXT,
                    created_at         TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                ALTER TABLE candidates
                ADD COLUMN IF NOT EXISTS selfie_url TEXT,
                ADD COLUMN IF NOT EXISTS id_card_url TEXT,
                ADD COLUMN IF NOT EXISTS cloudinary_folder TEXT,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS phone_number TEXT,
                ADD COLUMN IF NOT EXISTS role TEXT,
                ADD COLUMN IF NOT EXISTS location TEXT,
                ADD COLUMN IF NOT EXISTS pre_test_responses JSONB DEFAULT '{}'::jsonb;
            """)
            # Create questions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id         SERIAL PRIMARY KEY,
                    section    TEXT NOT NULL CHECK (section IN ('Numerical','Verbal','Logical')),
                    stem       TEXT NOT NULL,
                    option_a   TEXT NOT NULL,
                    option_b   TEXT NOT NULL,
                    option_c   TEXT NOT NULL,
                    option_d   TEXT NOT NULL,
                    answer     SMALLINT NOT NULL CHECK (answer BETWEEN 0 AND 3),
                    active     BOOLEAN DEFAULT TRUE,
                    position   INTEGER,
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                ALTER TABLE questions
                ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE;
            """)
            cur.execute("UPDATE questions SET is_default = TRUE WHERE id <= 50;")
            # Create exam_results table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exam_results (
                    id               SERIAL PRIMARY KEY,
                    candidate_id     INTEGER REFERENCES candidates(id),
                    score_percent    NUMERIC(5,2),
                    score_fraction   TEXT,
                    pass_fail        TEXT CHECK (pass_fail IN ('PASS','FAIL')),
                    time_taken_secs  INTEGER,
                    tab_switches     INTEGER DEFAULT 0,
                    breakdown_json   JSONB,
                    submitted_at     TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Older databases used time_taken_seconds. Keep the app's API column name stable.
            cur.execute("""
                DO $$
                BEGIN
                    ALTER TABLE exam_results
                    ADD COLUMN IF NOT EXISTS time_taken_secs INTEGER;

                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'exam_results'
                          AND column_name = 'time_taken_seconds'
                    ) THEN
                        ALTER TABLE exam_results
                        ALTER COLUMN time_taken_seconds DROP NOT NULL;

                        UPDATE exam_results
                        SET time_taken_secs = COALESCE(time_taken_secs, time_taken_seconds);
                    END IF;
                END $$;
            """)
            # Create whitelist table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    id        SERIAL PRIMARY KEY,
                    email     TEXT NOT NULL UNIQUE,
                    added_at  TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Create exam_settings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exam_settings (
                    id                   INTEGER PRIMARY KEY DEFAULT 1,
                    exam_open            BOOLEAN DEFAULT FALSE,
                    seconds_per_question INTEGER DEFAULT 60,
                    pass_mark_percent    NUMERIC(5,2) DEFAULT 50,
                    require_identity_verification BOOLEAN DEFAULT TRUE,
                    pre_test_fields       JSONB DEFAULT '[]'::jsonb,
                    recruitment_portal_open BOOLEAN DEFAULT TRUE,
                    updated_at           TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                ALTER TABLE exam_settings
                    ADD COLUMN IF NOT EXISTS require_identity_verification BOOLEAN DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS pre_test_fields JSONB DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS recruitment_portal_open BOOLEAN DEFAULT TRUE;
            """)

            # Create quizzes table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS quizzes (
                    id             SERIAL PRIMARY KEY,
                    number         INTEGER NOT NULL UNIQUE,
                    title          TEXT NOT NULL DEFAULT '',
                    active         BOOLEAN DEFAULT FALSE,
                    opens_at       TIMESTAMPTZ,
                    closes_at      TIMESTAMPTZ,
                    duration_minutes INTEGER,
                    pass_mark      NUMERIC(5,2) DEFAULT 50.0,
                    created_at     TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS quiz_id INTEGER REFERENCES quizzes(id);")
            cur.execute("ALTER TABLE exam_results ADD COLUMN IF NOT EXISTS quiz_id INTEGER REFERENCES quizzes(id);")

            # Create admin_sessions table for device tracking and inactivity timeouts
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    id             SERIAL PRIMARY KEY,
                    session_token  TEXT UNIQUE NOT NULL,
                    user_agent     TEXT,
                    ip_address     TEXT,
                    last_activity  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    active         BOOLEAN DEFAULT TRUE
                );
            """)

            # Create cohorts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cohorts (
                    id         SERIAL PRIMARY KEY,
                    name       TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                ALTER TABLE cohorts ADD COLUMN IF NOT EXISTS calendly_url TEXT;
            """)

            # Create candidate_otps table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS candidate_otps (
                    id         SERIAL PRIMARY KEY,
                    email      TEXT NOT NULL,
                    otp_hash   TEXT NOT NULL,
                    attempts   INTEGER DEFAULT 0,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # Create admin_login_attempts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_login_attempts (
                    id           SERIAL PRIMARY KEY,
                    ip_address   TEXT NOT NULL UNIQUE,
                    attempts     INTEGER DEFAULT 0,
                    locked_until TIMESTAMPTZ,
                    last_attempt TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # Alter whitelist table
            cur.execute("""
                ALTER TABLE whitelist
                    ADD COLUMN IF NOT EXISTS cohort_id INTEGER REFERENCES cohorts(id) ON DELETE CASCADE,
                    ADD COLUMN IF NOT EXISTS name TEXT;
            """)

            # Alter candidates table
            cur.execute("""
                ALTER TABLE candidates
                    ADD COLUMN IF NOT EXISTS cohort_id INTEGER REFERENCES cohorts(id) ON DELETE SET NULL;
            """)

            # Alter quizzes table
            cur.execute("""
                ALTER TABLE quizzes
                    ADD COLUMN IF NOT EXISTS cohort_id INTEGER REFERENCES cohorts(id) ON DELETE CASCADE;
            """)
            cur.execute("""
                ALTER TABLE scores
                    ADD COLUMN IF NOT EXISTS quiz_id INTEGER REFERENCES quizzes(id) ON DELETE CASCADE;
            """)
            # Drop the unique constraint on number if exists
            cur.execute("""
                ALTER TABLE quizzes DROP CONSTRAINT IF EXISTS quizzes_number_key;
            """)

            # Seed 'Cohort 1' if missing
            cur.execute("SELECT id FROM cohorts WHERE name = 'Cohort 1';")
            cohort1_row = cur.fetchone()
            if not cohort1_row:
                cur.execute("INSERT INTO cohorts (name) VALUES ('Cohort 1') RETURNING id;")
                cohort1_id = cur.fetchone()[0]
            else:
                cohort1_id = cohort1_row[0]

            # Populate NULL cohort_ids with Cohort 1
            cur.execute("UPDATE whitelist SET cohort_id = %s WHERE cohort_id IS NULL;", (cohort1_id,))
            cur.execute("UPDATE candidates SET cohort_id = %s WHERE cohort_id IS NULL;", (cohort1_id,))
            cur.execute("UPDATE quizzes SET cohort_id = %s WHERE cohort_id IS NULL;", (cohort1_id,))
            
            # Map legacy scores rows (where quiz_id is null) to default Quiz 1 under Cohort 1
            cur.execute("SELECT id FROM quizzes WHERE cohort_id = %s LIMIT 1;", (cohort1_id,))
            q1_row = cur.fetchone()
            if q1_row:
                cur.execute("UPDATE scores SET quiz_id = %s WHERE quiz_id IS NULL;", (q1_row[0],))
            
            # Seed exam_settings if missing
            cur.execute("SELECT count(*) FROM exam_settings WHERE id = 1;")
            if cur.fetchone()[0] == 0:
                from config import PASS_MARK_PERCENT, SECONDS_PER_QUESTION
                cur.execute("""
                    INSERT INTO exam_settings (id, exam_open, seconds_per_question, pass_mark_percent, recruitment_portal_open)
                    VALUES (1, FALSE, %s, %s, TRUE);
                """, (SECONDS_PER_QUESTION, PASS_MARK_PERCENT))
            
            # Seed questions if empty
            cur.execute("SELECT count(*) FROM questions;")
            if cur.fetchone()[0] == 0:
                from config import QUESTIONS
                for q in QUESTIONS:
                    cur.execute("""
                        INSERT INTO questions (id, section, stem, option_a, option_b, option_c, option_d, answer, active, position, is_default)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE);
                    """, (
                        q["id"],
                        q["section"],
                        q["stem"],
                        q["options"][0],
                        q["options"][1],
                        q["options"][2],
                        q["options"][3],
                        q["answer"],
                        q.get("active", True),
                        q["id"]
                    ))
                # Update serial sequence
                cur.execute("SELECT setval('questions_id_seq', COALESCE((SELECT MAX(id)+1 FROM questions), 1), false);")

            # Seed whitelist if empty
            cur.execute("SELECT count(*) FROM whitelist;")
            if cur.fetchone()[0] == 0:
                from config import WHITELIST_SEEDS
                for email in WHITELIST_SEEDS:
                    cur.execute("""
                        INSERT INTO whitelist (email)
                        VALUES (%s)
                        ON CONFLICT (email) DO NOTHING;
                    """, (email.lower().strip(),))

            # Seed Quiz 1 from default questions if no quizzes exist
            cur.execute("SELECT COUNT(*) FROM quizzes;")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO quizzes (number, title, active) VALUES (1, 'Quiz 1', TRUE) RETURNING id;")
                quiz1_id = cur.fetchone()[0]
                cur.execute("UPDATE questions SET quiz_id = %s WHERE quiz_id IS NULL;", (quiz1_id,))
        conn.commit()

# Global Recruitment Portal Status Gate
@app.before_request
def check_portal_status():
    # Only check for candidate-facing routes
    path = request.path
    # Exempt admin dashboard, static files, performance reporting, and login/assets
    if (path.startswith('/admin') or 
        path.startswith('/api/admin') or 
        path.startswith('/static') or 
        path == '/api/performance'):
        return None

    # Fetch settings
    try:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT recruitment_portal_open FROM exam_settings WHERE id = 1;")
                row = cur.fetchone()
                portal_open = row[0] if row else True
    except Exception as e:
        app.logger.error(f"Error checking portal status: {e}")
        portal_open = True

    if not portal_open:
        # If it is an API request, return JSON
        if request.path.startswith('/api/'):
            return jsonify({"error": "Recruitment is closed", "code": "recruitment_closed"}), 403
        # Otherwise, render recruitment_closed.html
        return render_template('recruitment_closed.html')

# Custom CSRF Protection
@app.before_request
def check_csrf():
    g.request_started_at = time.perf_counter()
    # Generate CSRF token on GET request if not present
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
        
    # We enforce CSRF validation on all state-changing methods: POST, PUT, DELETE
    if request.method in ['POST', 'PUT', 'DELETE']:
        # Retrieve token from request header or body
        token = request.headers.get('X-CSRF-Token')
        if not token:
            token = request.form.get('csrf_token')
        if not token and request.is_json:
            try:
                token = request.json.get('csrf_token')
            except:
                pass
                
        expected = session.get('csrf_token')
        if not expected or not token or not secrets.compare_digest(token, expected):
            return jsonify({"error": "CSRF token missing or invalid"}), 400


@app.after_request
def add_performance_headers(response):
    started = getattr(g, "request_started_at", None)
    if started is not None:
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = f'app;dur={duration_ms:.1f}'
        response.headers["X-Response-Time"] = f'{duration_ms:.1f}ms'
        app.logger.info("request method=%s path=%s status=%s duration_ms=%.1f bytes=%s",
                        request.method, request.path, response.status_code,
                        duration_ms, response.calculate_content_length() or 0)
    if request.endpoint == "static":
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.teardown_appcontext
def release_database_connection(error=None):
    close_request_connection(error)

# Helper to check admin authentication

def prune_expired_admin_sessions():
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                UPDATE admin_sessions
                SET active = FALSE
                WHERE active = TRUE
                  AND last_activity < NOW() - INTERVAL '{ADMIN_SESSION_TIMEOUT_MINUTES} minutes';
            """)
            conn.commit()


def check_admin_login_lockout(ip_address):
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT attempts, locked_until FROM admin_login_attempts
                WHERE ip_address = %s;
            """, (ip_address,))
            row = cur.fetchone()
            if row:
                attempts, locked_until = row
                if locked_until and datetime.datetime.now(datetime.timezone.utc) < locked_until:
                    # Lagos WAT timezone calculation (UTC + 1 hour)
                    wat_time = locked_until + datetime.timedelta(hours=1)
                    return False, f"Too many failed login attempts. IP locked out until {wat_time.strftime('%Y-%m-%d %I:%M %p').lower()} WAT."
            return True, None


def record_admin_login_attempt(ip_address, success):
    with DBConnection() as conn:
        with conn.cursor() as cur:
            if success:
                cur.execute("""
                    INSERT INTO admin_login_attempts (ip_address, attempts, last_attempt)
                    VALUES (%s, 0, NOW())
                    ON CONFLICT (ip_address) DO UPDATE
                    SET attempts = 0, locked_until = NULL, last_attempt = NOW();
                """, (ip_address,))
            else:
                cur.execute("""
                    INSERT INTO admin_login_attempts (ip_address, attempts, last_attempt)
                    VALUES (%s, 1, NOW())
                    ON CONFLICT (ip_address) DO UPDATE
                    SET attempts = admin_login_attempts.attempts + 1,
                        locked_until = CASE 
                            WHEN admin_login_attempts.attempts + 1 >= 5 THEN NOW() + INTERVAL '15 minutes'
                            ELSE NULL 
                        END,
                        last_attempt = NOW();
                """, (ip_address,))
        conn.commit()


def get_admin_device_fingerprint():
    user_agent = request.headers.get('User-Agent', '').strip()
    ip_address = request.remote_addr or 'unknown'
    return user_agent, ip_address


def get_current_admin_session_id():
    session_token = session.get('admin_session_token')
    if not session_token:
        return None

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id
                FROM admin_sessions
                WHERE session_token = %s
                  AND active = TRUE
                  AND last_activity >= NOW() - INTERVAL '{ADMIN_SESSION_TIMEOUT_MINUTES} minutes';
            """, (session_token,))
            row = cur.fetchone()
            if not row:
                return None

            admin_session_id = row[0]
            cur.execute("UPDATE admin_sessions SET last_activity = NOW() WHERE id = %s;", (admin_session_id,))
        conn.commit()

    return admin_session_id


def require_admin():
    if not session.get('admin') or not session.get('admin_session_token'):
        return jsonify({"error": "Unauthorized"}), 401

    if not get_current_admin_session_id():
        session.pop('admin', None)
        session.pop('admin_session_token', None)
        return jsonify({"error": "Unauthorized"}), 401

    return None


# Context processor to expose CSRF token to templates
@app.context_processor
def inject_csrf():
    return {'csrf_token': session.get('csrf_token')}

# ── Public Candidate Routes ───────────────────────────────────────────

@app.route('/')
def index():
    if session.get("candidate_id"):
        return redirect(url_for("recruitment.dashboard"))
    return render_template("index.html")


@app.route('/api/performance', methods=['POST'])
def record_browser_performance():
    data = request.get_json(silent=True) or {}
    allowed = {key: data.get(key) for key in
               ('path', 'ttfb', 'fcp', 'lcp', 'load', 'transfer_size')}
    app.logger.info("browser_performance %s", json.dumps(allowed, separators=(',', ':')))
    return ('', 204)

@app.route('/api/check-email', methods=['POST'])
def check_email():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    full_name = data.get('full_name', '').strip()
    phone_number = data.get('phone_number', '').strip()
    role = data.get('role', '').strip()
    location = data.get('location', '').strip()
    
    if not email or not full_name:
        return jsonify({"error": "Full name and email are required"}), 400
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # 1. Check if exam is open
            cur.execute("SELECT exam_open FROM exam_settings WHERE id = 1;")
            settings = cur.fetchone()
            if not settings or not settings[0]:
                return jsonify({"error": "The exam portal is currently closed. Please contact HR."}), 400
                
            # 2. Check whitelist
            cur.execute("SELECT 1 FROM whitelist WHERE LOWER(email) = LOWER(%s);", (email,))
            if not cur.fetchone():
                return jsonify({"error": "This email is not registered for this exam. Please contact HR."}), 400

            # 3. Determine active quiz
            cur.execute("SELECT id, number FROM quizzes WHERE active = TRUE ORDER BY number ASC LIMIT 1;")
            quiz_row = cur.fetchone()
            if not quiz_row:
                return jsonify({"error": "No quiz is currently active. Please contact HR."}), 400
            active_quiz_id, active_quiz_num = quiz_row[0], quiz_row[1]

            # 4. Check already submitted (per-quiz)
            cur.execute("""
                SELECT 1 FROM exam_results ER
                JOIN candidates C ON ER.candidate_id = C.id
                WHERE LOWER(C.email) = LOWER(%s) AND ER.quiz_id = %s;
            """, (email, active_quiz_id))
            if cur.fetchone():
                return jsonify({"error": f"You have already completed Quiz {active_quiz_num}. Please wait for the next quiz."}), 400

            cur.execute("""
                SELECT require_identity_verification, pre_test_fields
                FROM exam_settings WHERE id = 1;
            """)
            verification_row = cur.fetchone()

    session['active_quiz_id'] = active_quiz_id
    return jsonify({
        "status": "success",
        "message": "Email verified successfully.",
        "quiz_number": active_quiz_num,
        "require_identity_verification": verification_row[0] if verification_row else True,
        "pre_test_fields": (verification_row[1] if verification_row else []) or [],
    })

@app.route('/api/exam-summary', methods=['GET'])
def exam_summary():
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT exam_open, seconds_per_question, pass_mark_percent,
                       require_identity_verification, pre_test_fields, recruitment_portal_open
                FROM exam_settings
                WHERE id = 1;
            """)
            settings = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM questions WHERE active = TRUE;")
            active_question_count = cur.fetchone()[0]

    if not settings:
        return jsonify({"error": "Settings not initialized"}), 500

    return jsonify({
        "exam_open": settings[0],
        "seconds_per_question": settings[1],
        "pass_mark_percent": float(settings[2]),
        "total_questions": active_question_count,
        "require_identity_verification": settings[3],
        "pre_test_fields": settings[4] or [],
        "recruitment_portal_open": settings[5]
    })

@app.route('/api/upload-photos', methods=['POST'])
def upload_photos():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    full_name = data.get('full_name', '').strip()
    phone_number = data.get('phone_number', '').strip()
    role = data.get('role', '').strip()
    location = data.get('location', '').strip()
    selfie_b64 = data.get('selfie_b64')
    id_card_b64 = data.get('id_card_b64')
    pre_test_responses = data.get('pre_test_responses') or {}
    
    if not email or not full_name:
        return jsonify({"error": "Missing registration details or images"}), 400
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Run same checks as check-email
            cur.execute("SELECT exam_open, require_identity_verification FROM exam_settings WHERE id = 1;")
            settings = cur.fetchone()
            # Allow recruitment candidates with active sessions to upload even if the global exam is closed
            if not settings or (not settings[0] and not session.get('candidate_id')):
                return jsonify({"error": "The exam portal is currently closed. Please contact HR."}), 400
            require_identity = bool(settings[1])

            if require_identity and (not selfie_b64 or not id_card_b64):
                return jsonify({"error": "Missing verification images"}), 400
                
            cur.execute("SELECT 1 FROM whitelist WHERE LOWER(email) = LOWER(%s);", (email,))
            if not cur.fetchone():
                return jsonify({"error": "This email is not registered for this exam. Please contact HR."}), 400
                
            cur.execute("""
                SELECT 1 FROM exam_results ER
                JOIN candidates C ON ER.candidate_id = C.id
                WHERE LOWER(C.email) = LOWER(%s);
            """, (email,))
            if cur.fetchone():
                return jsonify({"error": "A submission for this email has already been recorded."}), 400
                
            selfie_url = None
            id_card_url = None
            folder_name = None

            # Perform Cloudinary uploads only when identity verification is enabled.
            now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M")
            folder_name = f"exams/{email}-{now_str}"
            
            if require_identity:
                try:
                    selfie_upload = cloudinary.uploader.upload(
                        selfie_b64,
                        folder=folder_name,
                        public_id="selfie",
                        type="authenticated"
                    )
                    selfie_url = selfie_upload.get('secure_url')

                    id_card_upload = cloudinary.uploader.upload(
                        id_card_b64,
                        folder=folder_name,
                        public_id="id_card",
                        type="authenticated"
                    )
                    id_card_url = id_card_upload.get('secure_url')
                except Exception as e:
                    print(f"Cloudinary upload error: {e}")
                    return jsonify({"error": "Failed to upload verification documents. Please try again."}), 500
                
            # Upsert Candidate record
            cur.execute("SELECT id FROM candidates WHERE LOWER(email) = LOWER(%s);", (email,))
            cand_row = cur.fetchone()
            if cand_row:
                candidate_id = cand_row[0]
                cur.execute("""
                    UPDATE candidates
                    SET full_name = %s,
                        phone_number = %s,
                        role = %s,
                        location = %s,
                        selfie_url = COALESCE(%s, selfie_url),
                        id_card_url = COALESCE(%s, id_card_url),
                        cloudinary_folder = COALESCE(%s, cloudinary_folder),
                        pre_test_responses = %s
                    WHERE id = %s;
                """, (full_name, phone_number, role, location, selfie_url, id_card_url,
                      folder_name, json.dumps(pre_test_responses), candidate_id))
            else:
                cur.execute("""
                    INSERT INTO candidates
                        (full_name, email, phone_number, role, location,
                         selfie_url, id_card_url, cloudinary_folder, pre_test_responses)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (full_name, email, phone_number, role, location, selfie_url, id_card_url,
                      folder_name, json.dumps(pre_test_responses)))
                candidate_id = cur.fetchone()[0]
                
        conn.commit()
        
    # Store candidate details in session
    session['candidate_id'] = candidate_id
    session['candidate_email'] = email
    
    return jsonify({"candidate_id": candidate_id})

@app.route('/api/questions', methods=['GET'])
def get_candidate_questions():
    candidate_id = session.get('candidate_id')
    if not candidate_id:
        return jsonify({"error": "Session verification failed. Please register again."}), 401
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Check if exam is open
            cur.execute("SELECT exam_open FROM exam_settings WHERE id = 1;")
            settings = cur.fetchone()
            if not settings or not settings[0]:
                return jsonify({"error": "The exam portal is currently closed."}), 403
                
            # Fetch active questions (filtered by active quiz if available)
            quiz_id = session.get('active_quiz_id')
            if quiz_id:
                cur.execute("""
                    SELECT id, section, stem, option_a, option_b, option_c, option_d, position
                    FROM questions
                    WHERE active = TRUE AND quiz_id = %s
                    ORDER BY section, position ASC;
                """, (quiz_id,))
            else:
                cur.execute("""
                    SELECT id, section, stem, option_a, option_b, option_c, option_d, position
                    FROM questions WHERE active = TRUE ORDER BY section, position ASC;
                """)
            rows = cur.fetchall()
            
    # Structure questions
    import random
    questions_by_sec = {"Numerical": [], "Verbal": [], "Logical": []}
    for row in rows:
        q = {
            "id": row[0],
            "section": row[1],
            "stem": row[2],
            "options": [row[3], row[4], row[5], row[6]],
            "position": row[7]
        }
        if q["section"] in questions_by_sec:
            questions_by_sec[q["section"]].append(q)
            
    # Shuffle within each section
    for sec in questions_by_sec:
        random.shuffle(questions_by_sec[sec])
        
    # Combine in sequence: Numerical -> Verbal -> Logical
    shuffled_list = questions_by_sec["Numerical"] + questions_by_sec["Verbal"] + questions_by_sec["Logical"]
    
    return jsonify(shuffled_list)

@app.route('/api/submit-results', methods=['POST'])
def submit_results():
    data = request.json or {}
    candidate_id = data.get('candidate_id')
    answers = data.get('answers', [])
    tab_switches = data.get('tab_switches', 0)
    time_taken_secs = data.get('time_taken_secs', 0)
    
    session_cand_id = session.get('candidate_id')
    if not session_cand_id or session_cand_id != candidate_id:
        return jsonify({"error": "Invalid candidate session."}), 401
        
    quiz_id = session.get('active_quiz_id')

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Check if already submitted (per-quiz)
            cur.execute("SELECT id FROM exam_results WHERE candidate_id = %s AND quiz_id IS NOT DISTINCT FROM %s;", (candidate_id, quiz_id))
            if cur.fetchone():
                return jsonify({"error": "A submission for this candidate has already been recorded."}), 400

            # Fetch active questions to score
            cur.execute("""
                SELECT id, section, answer
                FROM questions
                WHERE active = TRUE;
            """)
            questions_db = cur.fetchall()

            # Fetch passing rules — use quiz pass_mark if available, else fall back to exam_settings
            pass_mark = None
            if quiz_id:
                cur.execute("SELECT pass_mark FROM quizzes WHERE id = %s;", (quiz_id,))
                qrow = cur.fetchone()
                if qrow and qrow[0] is not None:
                    pass_mark = float(qrow[0])
            if pass_mark is None:
                cur.execute("SELECT pass_mark_percent FROM exam_settings WHERE id = 1;")
                pass_mark = float(cur.fetchone()[0])
            
            # Map database questions
            q_map = {q[0]: {"section": q[1], "answer": q[2]} for q in questions_db}
            total_active = len(q_map)
            
            if total_active == 0:
                return jsonify({"error": "No active questions found in system."}), 500
                
            # Map user answers
            ans_map = {ans.get('question_id'): ans for ans in answers}
            
            total_correct = 0
            breakdown = []
            
            # Score each active question
            for q_id, q_data in q_map.items():
                ans_given = ans_map.get(q_id)
                correct_ans = q_data["answer"]
                section = q_data["section"]
                
                if ans_given:
                    user_val = ans_given.get('answer_given')
                    was_timeout = ans_given.get('was_timeout', False)
                    time_spent = ans_given.get('time_spent_secs', 0)
                    
                    if user_val is not None:
                        user_val = int(user_val)
                        
                    is_correct = (user_val == correct_ans) and not was_timeout
                    if is_correct:
                        total_correct += 1
                else:
                    user_val = None
                    was_timeout = True
                    time_spent = 0
                    is_correct = False
                    
                breakdown.append({
                    "id": q_id,
                    "section": section,
                    "answer_given": user_val,
                    "correct_answer": correct_ans,
                    "is_correct": is_correct,
                    "was_timeout": was_timeout,
                    "time_spent_secs": time_spent
                })
                
            # Calculate percentages
            score_percent = round((total_correct / total_active) * 100, 2)
            score_fraction = f"{total_correct}/{total_active}"
            pass_fail = "PASS" if score_percent >= pass_mark else "FAIL"
            
            # Insert result
            cur.execute("""
                INSERT INTO exam_results (candidate_id, score_percent, score_fraction, pass_fail, time_taken_secs, tab_switches, breakdown_json, quiz_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                candidate_id,
                score_percent,
                score_fraction,
                pass_fail,
                time_taken_secs,
                tab_switches,
                json.dumps(breakdown),
                quiz_id
            ))
            
            # Fetch candidate info for response certificate
            cur.execute("SELECT full_name, email, created_at FROM candidates WHERE id = %s;", (candidate_id,))
            cand_info = cur.fetchone()
            
        conn.commit()
        
    # Clear candidate session on success
    session.pop('candidate_id', None)
    session.pop('candidate_email', None)
    session.pop('active_quiz_id', None)

    # Generate reference number: MMFB-YYYYMMDD-XXXX
    submitted_date = datetime.datetime.now()
    ref_num = f"MMFB-{submitted_date.strftime('%Y%m%d')}-{candidate_id:04d}"

    return jsonify({
        "score_percent": score_percent,
        "score_fraction": score_fraction,
        "pass_fail": pass_fail,
        "breakdown": breakdown,
        "candidate_name": cand_info[0] if cand_info else "Candidate",
        "candidate_email": cand_info[1] if cand_info else "",
        "ref_number": ref_num,
        "submitted_at": submitted_date.isoformat(),
        "quiz_number": quiz_id
    })


# ── Admin Panel Routes ───────────────────────────────────────────────

@app.route('/admin')
def admin_dashboard():
    if not session.get('admin') or not session.get('admin_session_token') or not get_current_admin_session_id():
        session.pop('admin', None)
        session.pop('admin_session_token', None)
        return redirect(url_for('admin_login'))

    import datetime
    def format_datetime_wat(dt):
        if not dt:
            return "-"
        if dt.tzinfo:
            dt = dt.astimezone(datetime.timezone.utc)
        wat_dt = dt + datetime.timedelta(hours=1)
        return wat_dt.strftime("%Y-%m-%d %I:%M %p").lower()

    settings = None
    try:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT exam_open, seconds_per_question, pass_mark_percent,
                           require_identity_verification, pre_test_fields, recruitment_portal_open,
                           updated_at
                    FROM exam_settings WHERE id = 1;
                """)
                row = cur.fetchone()
                if row:
                    settings = {
                        "exam_open": row[0],
                        "seconds_per_question": row[1],
                        "pass_mark_percent": float(row[2]),
                        "require_identity_verification": row[3],
                        "pre_test_fields": row[4],
                        "recruitment_portal_open": row[5],
                        "updated_at": format_datetime_wat(row[6]) if row[6] else "-"
                    }
    except Exception as e:
        app.logger.error(f"Error loading settings: {e}")

    return render_template('admin.html', authenticated=True, settings=settings)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        if session.get('admin') and session.get('admin_session_token') and get_current_admin_session_id():
            return redirect(url_for('admin_dashboard'))
        session.pop('admin', None)
        session.pop('admin_session_token', None)
        return render_template('admin.html', authenticated=False)
        
    # Handle login POST
    data = request.json or {}
    username = data.get('username', '').strip() or 'admin'
    password = data.get('password', '').strip() or data.get('token', '').strip()
    
    user_agent, ip_address = get_admin_device_fingerprint()
    
    # 1. Enforce IP lockout
    allowed, lockout_msg = check_admin_login_lockout(ip_address)
    if not allowed:
        return jsonify({"success": False, "error": lockout_msg}), 403
        
    # 2. Retrieve secure credentials
    expected_username = os.environ.get("ADMIN_USERNAME", "admin")
    env_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not env_hash:
        fallback_pass = os.environ.get("ADMIN_TOKEN", "admin123")
        env_hash = generate_password_hash(fallback_pass)
        
    username_ok = hmac.compare_digest(username.lower().encode('utf-8'), expected_username.lower().encode('utf-8'))
    password_ok = check_password_hash(env_hash, password)
    
    if not (username_ok and password_ok):
        record_admin_login_attempt(ip_address, False)
        return jsonify({"success": False, "error": "Incorrect username or password"}), 401
        
    record_admin_login_attempt(ip_address, True)

    with DBConnection() as conn:
        with conn.cursor() as cur:
            prune_expired_admin_sessions()

            cur.execute("""
                SELECT id, session_token
                FROM admin_sessions
                WHERE active = TRUE
                  AND user_agent = %s
                  AND ip_address = %s;
            """, (user_agent, ip_address))
            existing_session = cur.fetchone()

            cur.execute("SELECT COUNT(*) FROM admin_sessions WHERE active = TRUE;")
            active_sessions = cur.fetchone()[0]

            if existing_session:
                session_token = existing_session[1]
                cur.execute("UPDATE admin_sessions SET last_activity = NOW() WHERE id = %s;", (existing_session[0],))
            else:
                if active_sessions >= MAX_ADMIN_DEVICES:
                    return jsonify({
                        "success": False,
                        "error": "Maximum number of active admin devices reached. Logout from another device or wait for inactivity timeout."
                    }), 403

                session_token = secrets.token_urlsafe(32)
                cur.execute("""
                    INSERT INTO admin_sessions (session_token, user_agent, ip_address, last_activity, active)
                    VALUES (%s, %s, %s, NOW(), TRUE)
                    RETURNING id;
                """, (session_token, user_agent, ip_address))
                cur.fetchone()
        conn.commit()

    session['admin'] = True
    session['admin_session_token'] = session_token
    return jsonify({"success": True})

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session_token = session.get('admin_session_token')
    if session_token:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE admin_sessions SET active = FALSE WHERE session_token = %s;", (session_token,))
            conn.commit()

    session.pop('admin', None)
    session.pop('admin_session_token', None)
    return jsonify({"success": True})


# Settings CRUD
@app.route('/api/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    if request.method == 'GET':
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT exam_open, seconds_per_question, pass_mark_percent, updated_at,
                           require_identity_verification, pre_test_fields, recruitment_portal_open
                    FROM exam_settings WHERE id = 1;
                """)
                row = cur.fetchone()
        if not row:
            return jsonify({"error": "Settings not initialized"}), 500
        return jsonify({
            "exam_open": row[0],
            "seconds_per_question": row[1],
            "pass_mark_percent": float(row[2]),
            "updated_at": row[3].isoformat() if row[3] else None,
            "require_identity_verification": row[4],
            "pre_test_fields": row[5] or [],
            "recruitment_portal_open": row[6]
        })
        
    # Update settings
    data = request.json or {}
    exam_open = data.get('exam_open', False)
    seconds_per_q = int(data.get('seconds_per_question', 60))
    pass_mark = float(data.get('pass_mark_percent', 50))
    require_identity = bool(data.get('require_identity_verification', True))
    pre_test_fields = data.get('pre_test_fields', [])
    recruitment_portal_open = bool(data.get('recruitment_portal_open', True))
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE exam_settings
                SET exam_open = %s,
                    seconds_per_question = %s,
                    pass_mark_percent = %s,
                    require_identity_verification = %s,
                    pre_test_fields = %s,
                    recruitment_portal_open = %s,
                    updated_at = NOW()
                WHERE id = 1;
            """, (exam_open, seconds_per_q, pass_mark, require_identity, json.dumps(pre_test_fields), recruitment_portal_open))
        conn.commit()
        
    return jsonify({"status": "success", "message": "Settings updated successfully."})


# Questions CRUD
@app.route('/api/admin/questions', methods=['GET', 'POST'])
def admin_questions():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            if request.method == 'GET':
                cur.execute("""
                    SELECT id, section, stem, option_a, option_b, option_c, option_d, answer, active, position, is_default
                    FROM questions
                    ORDER BY section, position ASC, id ASC;
                """)
                rows = cur.fetchall()
                questions = []
                for r in rows:
                    questions.append({
                        "id": r[0],
                        "section": r[1],
                        "stem": r[2],
                        "options": [r[3], r[4], r[5], r[6]],
                        "answer": r[7],
                        "active": r[8],
                        "position": r[9],
                        "is_default": r[10]
                    })
                return jsonify(questions)
                
            # Create question
            data = request.json or {}
            section = data.get('section')
            stem = data.get('stem', '').strip()
            options = data.get('options', [])
            answer = data.get('answer')
            active = data.get('active', True)
            
            if not section or not stem or len(options) != 4 or answer is None:
                return jsonify({"error": "Missing or invalid question data"}), 400
                
            # Auto-position calculation: MAX(position)+1 in this section
            cur.execute("SELECT COALESCE(MAX(position), 0) FROM questions WHERE section = %s;", (section,))
            max_pos = cur.fetchone()[0]
            new_pos = max_pos + 1
            
            cur.execute("""
                INSERT INTO questions (section, stem, option_a, option_b, option_c, option_d, answer, active, position)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (section, stem, options[0], options[1], options[2], options[3], answer, active, new_pos))
            new_id = cur.fetchone()[0]
        conn.commit()
        
    return jsonify({"status": "success", "id": new_id, "message": "Question created successfully."})

@app.route('/api/admin/questions/<int:q_id>', methods=['PUT', 'DELETE'])
def admin_single_question(q_id):
    auth_err = require_admin()
    if auth_err: return auth_err
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            if request.method == 'PUT':
                data = request.json or {}
                section = data.get('section')
                stem = data.get('stem', '').strip()
                options = data.get('options', [])
                answer = data.get('answer')
                active = data.get('active', True)
                position = data.get('position')
                
                if not section or not stem or len(options) != 4 or answer is None:
                    return jsonify({"error": "Missing or invalid question data"}), 400
                    
                cur.execute("""
                    UPDATE questions
                    SET section = %s, stem = %s, option_a = %s, option_b = %s, option_c = %s, option_d = %s,
                        answer = %s, active = %s, position = %s, updated_at = NOW()
                    WHERE id = %s;
                """, (section, stem, options[0], options[1], options[2], options[3], answer, active, position, q_id))
                
                message = "Question updated successfully."
                
            elif request.method == 'DELETE':
                # Soft delete: set active = False
                cur.execute("UPDATE questions SET active = FALSE, updated_at = NOW() WHERE id = %s;", (q_id,))
                message = "Question soft-deleted successfully (marked inactive)."
                
        conn.commit()
        
    return jsonify({"status": "success", "message": message})

@app.route('/api/admin/questions/bulk', methods=['POST'])
def admin_questions_bulk():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    data = request.json or []
    if not isinstance(data, list):
        return jsonify({"error": "Expected a list of questions"}), 400
        
    added = 0
    skipped = 0
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            for item in data:
                section = item.get('section')
                stem = item.get('stem', '').strip()
                options = item.get('options', [])
                answer = item.get('answer')
                active = item.get('active', True)
                
                if not section or not stem or len(options) != 4 or answer is None:
                    skipped += 1
                    continue
                    
                # Duplicate check by stem
                cur.execute("SELECT 1 FROM questions WHERE LOWER(stem) = LOWER(%s);", (stem,))
                if cur.fetchone():
                    skipped += 1
                    continue
                    
                # Position calculation
                cur.execute("SELECT COALESCE(MAX(position), 0) FROM questions WHERE section = %s;", (section,))
                max_pos = cur.fetchone()[0]
                new_pos = max_pos + 1
                
                cur.execute("""
                    INSERT INTO questions (section, stem, option_a, option_b, option_c, option_d, answer, active, position)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (section, stem, options[0], options[1], options[2], options[3], answer, active, new_pos))
                added += 1
        conn.commit()
        
    return jsonify({"status": "success", "added": added, "skipped": skipped})

@app.route('/api/admin/questions/reorder', methods=['POST'])
def admin_questions_reorder():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    data = request.json or {}
    ordered_ids = data.get('ordered_ids', [])
    
    if not ordered_ids:
        return jsonify({"error": "Missing ordered_ids list"}), 400
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Update position sequence based on array order
            for idx, q_id in enumerate(ordered_ids):
                cur.execute("UPDATE questions SET position = %s WHERE id = %s;", (idx + 1, q_id))
        conn.commit()
        
    return jsonify({"status": "success", "message": "Questions reordered successfully."})


# Whitelist CRUD
@app.route('/api/admin/whitelist', methods=['GET', 'POST'])
def admin_whitelist():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            if request.method == 'GET':
                cur.execute("SELECT id, email, added_at FROM whitelist ORDER BY email ASC;")
                rows = cur.fetchall()
                res = [{"id": r[0], "email": r[1], "added_at": r[2].isoformat()} for r in rows]
                return jsonify(res)
                
            # Add single email
            data = request.json or {}
            email = data.get('email', '').strip().lower()
            if not email:
                return jsonify({"error": "Email is required"}), 400
                
            cur.execute("INSERT INTO whitelist (email) VALUES (%s) ON CONFLICT (email) DO NOTHING RETURNING id;", (email,))
            row = cur.fetchone()
            message = "Email added to whitelist." if row else "Email already whitelisted."
        conn.commit()
        
    return jsonify({"status": "success", "message": message})

@app.route('/api/admin/whitelist/bulk', methods=['POST'])
def admin_whitelist_bulk():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    data = request.json or {}
    emails = data.get('emails', [])
    
    added = 0
    skipped = 0
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            for email in emails:
                email = email.strip().lower()
                if not email:
                    skipped += 1
                    continue
                cur.execute("SELECT 1 FROM whitelist WHERE email = %s;", (email,))
                if cur.fetchone():
                    skipped += 1
                else:
                    cur.execute("INSERT INTO whitelist (email) VALUES (%s);", (email,))
                    added += 1
        conn.commit()
        
    return jsonify({"status": "success", "added": added, "skipped": skipped})

@app.route('/api/admin/whitelist/<int:w_id>', methods=['DELETE'])
def admin_delete_whitelist(w_id):
    auth_err = require_admin()
    if auth_err: return auth_err
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whitelist WHERE id = %s;", (w_id,))
        conn.commit()
        
    return jsonify({"status": "success", "message": "Email removed from whitelist."})

@app.route('/api/admin/whitelist/clear', methods=['POST'])
def admin_clear_whitelist():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whitelist;")
        conn.commit()
        
    return jsonify({"status": "success", "message": "All whitelisted emails removed successfully."})


@app.route('/api/admin/quizzes', methods=['GET', 'POST'])
def admin_quizzes():
    auth_err = require_admin()
    if auth_err: return auth_err

    if request.method == 'GET':
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT q.id, q.number, q.title, q.active, q.opens_at, q.closes_at,
                           q.duration_minutes, q.pass_mark, q.created_at,
                           COUNT(qs.id) AS question_count,
                           COUNT(DISTINCT er.candidate_id) AS attempts
                    FROM quizzes q
                    LEFT JOIN questions qs ON qs.quiz_id = q.id AND qs.active = TRUE
                    LEFT JOIN exam_results er ON er.quiz_id = q.id
                    GROUP BY q.id ORDER BY q.number;
                """)
                rows = cur.fetchall()
        return jsonify([{
            "id": r[0], "number": r[1], "title": r[2], "active": r[3],
            "opens_at": r[4].isoformat() if r[4] else None,
            "closes_at": r[5].isoformat() if r[5] else None,
            "duration_minutes": r[6], "pass_mark": float(r[7]) if r[7] else None,
            "created_at": r[8].isoformat() if r[8] else None,
            "question_count": r[9], "attempts": r[10],
        } for r in rows])

    data = request.json or {}
    number = data.get('number')
    title  = data.get('title', '').strip() or f"Quiz {number}"
    if not number:
        return jsonify({"error": "number required"}), 400

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO quizzes (number, title, pass_mark, duration_minutes, opens_at, closes_at)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
            """, (number, title,
                  data.get('pass_mark', 50.0),
                  data.get('duration_minutes'),
                  data.get('opens_at') or None,
                  data.get('closes_at') or None))
            new_id = cur.fetchone()[0]
        conn.commit()
    return jsonify({"status": "success", "id": new_id})


@app.route('/api/admin/quizzes/<int:qid>', methods=['PUT', 'DELETE'])
def admin_quiz_detail(qid):
    auth_err = require_admin()
    if auth_err: return auth_err

    if request.method == 'DELETE':
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM quizzes WHERE id = %s;", (qid,))
            conn.commit()
        return jsonify({"status": "success"})

    data = request.json or {}
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE quizzes SET
                    title = COALESCE(%s, title),
                    pass_mark = COALESCE(%s, pass_mark),
                    duration_minutes = COALESCE(%s, duration_minutes),
                    opens_at = COALESCE(%s::timestamptz, opens_at),
                    closes_at = COALESCE(%s::timestamptz, closes_at)
                WHERE id = %s;
            """, (data.get('title'), data.get('pass_mark'),
                  data.get('duration_minutes'),
                  data.get('opens_at'), data.get('closes_at'), qid))
        conn.commit()
    return jsonify({"status": "success"})


@app.route('/api/admin/quizzes/<int:qid>/activate', methods=['POST'])
def admin_quiz_activate(qid):
    auth_err = require_admin()
    if auth_err: return auth_err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE quizzes SET active = FALSE;")
            cur.execute("UPDATE quizzes SET active = TRUE WHERE id = %s;", (qid,))
        conn.commit()
    return jsonify({"status": "success"})


@app.route('/api/admin/quiz-results')
def admin_quiz_results():
    auth_err = require_admin()
    if auth_err: return auth_err

    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Per-candidate averages across all quizzes
            cur.execute("""
                SELECT c.id, c.full_name, c.email,
                       COUNT(er.id) AS quizzes_taken,
                       ROUND(AVG(er.score_percent), 2) AS avg_score,
                       ARRAY_AGG(
                           q.number || ':' || er.score_percent::text
                           ORDER BY q.number
                       ) AS quiz_scores
                FROM candidates c
                JOIN exam_results er ON er.candidate_id = c.id
                JOIN quizzes q ON q.id = er.quiz_id
                GROUP BY c.id, c.full_name, c.email
                ORDER BY avg_score DESC;
            """)
            rows = cur.fetchall()
    return jsonify([{
        "candidate_id": r[0], "name": r[1], "email": r[2],
        "quizzes_taken": r[3], "avg_score": float(r[4]),
        "quiz_scores": r[5],
    } for r in rows])


@app.route('/api/admin/cv-view')
def admin_cv_view():
    """Proxy Cloudinary CV PDF to browser with inline Content-Disposition."""
    if not session.get('admin'):
        return "Unauthorized", 401
    url = request.args.get('url', '').strip()
    if not url or 'cloudinary.com' not in url:
        return "Invalid URL", 400
    try:
        r = requests.get(url, timeout=20)
        return Response(
            r.content,
            mimetype='application/pdf',
            headers={'Content-Disposition': 'inline; filename="cv.pdf"'}
        )
    except Exception as e:
        print(f"[cv-view] Error: {e}")
        return "Failed to fetch CV", 502


@app.route('/api/admin/results/clear', methods=['POST'])
def admin_clear_results():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Delete results first due to foreign key constraint
            cur.execute("DELETE FROM exam_results;")
            cur.execute("DELETE FROM candidates;")
        conn.commit()
        
    return jsonify({"status": "success", "message": "All exam results and candidate registrations have been cleared."})


# Candidates & Results
@app.route('/api/admin/results')
def admin_results():
    auth_err = require_admin()
    if auth_err: return auth_err
    
    # Sortable columns: name, email, date
    sort_column = request.args.get('sort', 'created_at')
    sort_order = request.args.get('order', 'DESC').upper()
    page = int(request.args.get('page', 1))
    per_page = 25
    offset = (page - 1) * per_page
    
    allowed_cols = {
        'name': 'C.full_name',
        'email': 'C.email',
        'created_at': 'C.created_at'
    }
    col_sql = allowed_cols.get(sort_column, 'C.created_at')
    if sort_order not in ['ASC', 'DESC']:
        sort_order = 'DESC'
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Get total number of candidates
            cur.execute("SELECT COUNT(*) FROM candidates;")
            total_cand = cur.fetchone()[0]
            
            # Fetch all quizzes first to map quiz_id to title
            cur.execute("SELECT id, title, number FROM quizzes;")
            quiz_map = {row[0]: (row[1] or f"Quiz #{row[2]}") for row in cur.fetchall()}
            
            # Fetch candidates paginated
            query = f"""
                SELECT C.id, C.full_name, C.email, C.phone_number, C.role, C.location, C.created_at, C.stage
                FROM candidates C
                ORDER BY {col_sql} {sort_order}
                LIMIT %s OFFSET %s;
            """
            cur.execute(query, (per_page, offset))
            cand_rows = cur.fetchall()
            
            results = []
            total_passed = 0
            total_failed = 0
            
            for r in cand_rows:
                cand_id, name, email, phone, role, location, created_at, stage = r
                
                # Fetch exam_results (dashboard/legacy)
                cur.execute("""
                    SELECT score_percent, score_fraction, pass_fail, submitted_at, quiz_id, tab_switches, time_taken_secs
                    FROM exam_results WHERE candidate_id = %s;
                """, (cand_id,))
                legacy_rows = cur.fetchall()
                
                # Fetch pipeline scores
                cur.execute("""
                    SELECT score, score_fraction, pass_fail, taken_at, stage_label, tab_switches, time_taken_secs
                    FROM scores WHERE candidate_id = %s;
                """, (cand_id,))
                pipeline_rows = cur.fetchall()
                
                scores_list = []
                for lr in legacy_rows:
                    scores_list.append({
                        "title": quiz_map.get(lr[4], f"Quiz #{lr[4]}"),
                        "source": "exam_results",
                        "score_percent": float(lr[0]),
                        "score_fraction": lr[1],
                        "pass_fail": lr[2],
                        "submitted_at": lr[3].isoformat() if lr[3] else None,
                        "tab_switches": lr[5],
                        "time_taken_secs": lr[6]
                    })
                    
                for pr in pipeline_rows:
                    scores_list.append({
                        "title": f"Pipeline - {pr[4].replace('_', ' ').title()}",
                        "source": "scores",
                        "score_percent": float(pr[0]) if pr[0] is not None else 0.0,
                        "score_fraction": pr[1] or "",
                        "pass_fail": pr[2] or "PENDING",
                        "submitted_at": pr[3].isoformat() if pr[3] else None,
                        "tab_switches": pr[5] or 0,
                        "time_taken_secs": pr[6] or 0
                    })
                
                # Determine overall status
                overall_status = "PENDING"
                if scores_list:
                    if any(s["pass_fail"] == "FAIL" for s in scores_list):
                        overall_status = "FAIL"
                        total_failed += 1
                    elif all(s["pass_fail"] == "PASS" for s in scores_list):
                        overall_status = "PASS"
                        total_passed += 1
                
                results.append({
                    "id": cand_id, # maintain backward compatibility with client expectations
                    "candidate_id": cand_id,
                    "name": name,
                    "email": email,
                    "phone_number": phone or "",
                    "role": role or "",
                    "location": location or "",
                    "created_at": created_at.isoformat(),
                    "submitted_at": created_at.isoformat(), # mock to prevent client errors
                    "stage": stage,
                    "scores": scores_list,
                    "overall_status": overall_status,
                    "pass_fail": overall_status,
                    "score_percent": scores_list[0]["score_percent"] if scores_list else 0.0,
                    "score_fraction": scores_list[0]["score_fraction"] if scores_list else "-",
                    "time_taken_secs": scores_list[0]["time_taken_secs"] if scores_list else 0,
                    "tab_switches": scores_list[0]["tab_switches"] if scores_list else 0
                })
                
            summary = {
                "total": total_cand,
                "passed": total_passed,
                "failed": total_failed,
                "avg_score": 0.0,
                "avg_time": 0
            }
            all_scores = [s["score_percent"] for r in results for s in r["scores"]]
            if all_scores:
                summary["avg_score"] = round(sum(all_scores) / len(all_scores), 2)
            all_times = [s["time_taken_secs"] for r in results for s in r["scores"] if s["time_taken_secs"]]
            if all_times:
                summary["avg_time"] = int(sum(all_times) / len(all_times))
                
    return jsonify({
        "summary": summary,
        "results": results,
        "page": page,
        "per_page": per_page
    })

@app.route('/api/admin/export-csv')
def admin_export_csv():
    if not session.get('admin'):
        return "Unauthorized", 401
        
    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        
        # Write headers
        writer.writerow(['Candidate Name', 'Email', 'Phone Number', 'Role', 'Location', 'Score %', 'Score (Fraction)', 'Pass/Fail', 'Time Taken (s)', 'Tab Switches', 'Submitted At'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT C.full_name, C.email, C.phone_number, C.role, C.location, ER.score_percent, ER.score_fraction, ER.pass_fail, ER.time_taken_secs, ER.tab_switches, ER.submitted_at
                    FROM exam_results ER
                    JOIN candidates C ON ER.candidate_id = C.id
                    ORDER BY ER.submitted_at DESC;
                """)
                while True:
                    rows = cur.fetchmany(100)
                    if not rows:
                        break
                    for r in rows:
                        writer.writerow([r[0], r[1], r[2], r[3], r[4], float(r[5]), r[6], r[7], r[8], r[9], r[10].isoformat()])
                        yield data.getvalue()
                        data.seek(0)
                        data.truncate(0)
                        
    headers = {
        'Content-Disposition': 'attachment; filename=exam_results.csv',
        'Content-Type': 'text/csv'
    }
    return Response(generate(), headers=headers)

@app.route('/api/admin/image/<int:candidate_id>/<string:image_type>')
def admin_get_image(candidate_id, image_type):
    if not session.get('admin'):
        return "Unauthorized", 401
        
    if image_type not in ['selfie', 'idcard']:
        return "Invalid image type", 400
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cloudinary_folder FROM candidates WHERE id = %s;", (candidate_id,))
            row = cur.fetchone()
            
    if not row or not row[0]:
        return "Candidate files not found", 404
        
    folder_name = row[0]
    resource_name = "id_card" if image_type == "idcard" else "selfie"
    public_id = f"{folder_name}/{resource_name}"
    
    try:
        # Generate Signed URL (300 seconds expiry)
        signed_url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            type="authenticated",
            sign_url=True,
            expires_at=int(time.time()) + 300
        )
        
        # Proxy file bytes back to browser
        resp = requests.get(signed_url, timeout=10)
        if resp.status_code != 200:
            return "Failed to fetch image from Cloudinary", resp.status_code
            
        return Response(resp.content, mimetype=resp.headers.get('Content-Type', 'image/jpeg'))
    except Exception as e:
        print(f"Proxy image error: {e}")
        return "Internal server error reading document bytes", 500


def _bootstrap():
    """Run all DB migrations and register blueprints. Called once at startup."""
    if os.environ.get("RUN_DB_MIGRATIONS", "false").lower() == "true":
        try:
            init_db()
            from migrations import init_recruitment_db
            init_recruitment_db()
        except Exception as e:
            print(f"[database bootstrap] Error: {e}")

    # Register recruitment blueprints
    try:
        from blueprints.recruitment import recruitment
        from blueprints.admin_recruitment import admin_rec
        app.register_blueprint(recruitment)
        app.register_blueprint(admin_rec)
    except Exception as e:
        print(f"[blueprint registration] Error: {e}")




# ── Job endpoints (callable by Vercel Cron or external scheduler) ──────────────

@app.route("/api/jobs/generate-slots", methods=["POST"])
def job_generate_slots():
    secret = os.environ.get("JOB_SECRET", "")
    provided = request.headers.get("X-Job-Secret", "")
    if secret and not hmac.compare_digest(secret.encode(), provided.encode()):
        return jsonify({"error": "Unauthorized"}), 401
    from jobs.slot_generator import generate_slots
    count = generate_slots(weeks_ahead=4)
    return jsonify({"created": count})


@app.route("/api/jobs/expire-deadlines", methods=["POST"])
def job_expire_deadlines():
    secret = os.environ.get("JOB_SECRET", "")
    provided = request.headers.get("X-Job-Secret", "")
    if secret and not hmac.compare_digest(secret.encode(), provided.encode()):
        return jsonify({"error": "Unauthorized"}), 401
    from jobs.deadline_expiry import expire_past_deadlines
    count = expire_past_deadlines()
    return jsonify({"transitioned": count})


# ── Cohort & Quiz CRUD APIs ──────────────────────────────────────────────────

@app.route('/api/admin/cohorts', methods=['GET'])
def admin_cohorts():
    auth_err = require_admin()
    if auth_err: return auth_err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.name, c.created_at,
                       (SELECT COUNT(*) FROM whitelist w WHERE w.cohort_id = c.id) as candidate_count,
                       (SELECT COUNT(*) FROM quizzes q WHERE q.cohort_id = c.id) as test_count
                FROM cohorts c
                ORDER BY c.name ASC;
            """)
            rows = cur.fetchall()
            res = [{
                "id": r[0],
                "name": r[1],
                "created_at": r[2].isoformat(),
                "candidate_count": r[3],
                "test_count": r[4]
            } for r in rows]
            return jsonify(res)


@app.route('/api/admin/cohorts', methods=['POST'])
def admin_create_cohort():
    auth_err = require_admin()
    if auth_err: return auth_err
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"error": "Cohort name is required"}), 400
    try:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO cohorts (name) VALUES (%s) RETURNING id, name, created_at;", (name,))
                row = cur.fetchone()
            conn.commit()
        return jsonify({"success": True, "cohort": {"id": row[0], "name": row[1], "created_at": row[2].isoformat()}})
    except Exception as e:
        return jsonify({"error": "Cohort name must be unique."}), 400


@app.route('/api/admin/cohorts/<int:cid>', methods=['PUT'])
def admin_rename_cohort(cid):
    auth_err = require_admin()
    if auth_err: return auth_err
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"error": "Cohort name is required"}), 400
    try:
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE cohorts SET name = %s WHERE id = %s RETURNING id, name;", (name, cid))
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Cohort not found"}), 404
            conn.commit()
        return jsonify({"success": True, "cohort": {"id": row[0], "name": row[1]}})
    except Exception as e:
        return jsonify({"error": "Cohort name must be unique."}), 400


@app.route('/api/admin/cohorts/<int:cid>', methods=['DELETE'])
def admin_delete_cohort(cid):
    auth_err = require_admin()
    if auth_err: return auth_err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cohorts WHERE id = %s RETURNING id;", (cid,))
            if not cur.fetchone():
                return jsonify({"error": "Cohort not found"}), 404
        conn.commit()
    return jsonify({"success": True, "message": "Cohort deleted successfully."})


@app.route('/api/admin/cohorts/<int:cid>/candidates', methods=['GET'])
def admin_cohort_candidates(cid):
    auth_err = require_admin()
    if auth_err: return auth_err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email, name, added_at FROM whitelist WHERE cohort_id = %s ORDER BY email ASC;", (cid,))
            rows = cur.fetchall()
            res = [{
                "id": r[0],
                "email": r[1],
                "name": r[2] or "",
                "added_at": r[3].isoformat()
            } for r in rows]
            return jsonify(res)


@app.route('/api/admin/cohorts/<int:cid>/candidates', methods=['POST'])
def admin_add_cohort_candidate(cid):
    auth_err = require_admin()
    if auth_err: return auth_err
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    name = data.get('name', '').strip()
    if not email:
        return jsonify({"error": "Email is required"}), 400
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Check if email already in whitelist
            cur.execute("SELECT id, cohort_id FROM whitelist WHERE LOWER(email) = LOWER(%s);", (email,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE whitelist SET cohort_id = %s, name = %s WHERE id = %s;", (cid, name, row[0]))
            else:
                cur.execute("INSERT INTO whitelist (email, name, cohort_id) VALUES (%s, %s, %s);", (email, name, cid))
            cur.execute("UPDATE candidates SET cohort_id = %s WHERE LOWER(email) = LOWER(%s);", (cid, email))
        conn.commit()
    return jsonify({"success": True, "message": "Candidate added to cohort whitelist."})


@app.route('/api/admin/cohorts/<int:cid>/candidates/bulk', methods=['POST'])
def admin_bulk_add_cohort_candidates(cid):
    auth_err = require_admin()
    if auth_err: return auth_err
    data = request.json or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "No data provided"}), 400
        
    added = 0
    lines = text.split('\n')
    with DBConnection() as conn:
        with conn.cursor() as cur:
            for line in lines:
                line = line.strip()
                if not line: continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 2:
                    name = parts[0]
                    email = parts[1].lower()
                else:
                    name = ""
                    email = parts[0].lower()
                    
                if '@' not in email:
                    continue
                    
                cur.execute("SELECT id FROM whitelist WHERE LOWER(email) = LOWER(%s);", (email,))
                row = cur.fetchone()
                if row:
                    cur.execute("UPDATE whitelist SET cohort_id = %s, name = %s WHERE id = %s;", (cid, name, row[0]))
                else:
                    cur.execute("INSERT INTO whitelist (email, name, cohort_id) VALUES (%s, %s, %s);", (email, name, cid))
                cur.execute("UPDATE candidates SET cohort_id = %s WHERE LOWER(email) = LOWER(%s);", (cid, email))
                added += 1
        conn.commit()
    return jsonify({"success": True, "added": added})


@app.route('/api/admin/cohorts/<int:cid>/quizzes', methods=['GET'])
def admin_cohort_quizzes(cid):
    auth_err = require_admin()
    if auth_err: return auth_err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, number, title, active, opens_at, closes_at, duration_minutes, pass_mark
                FROM quizzes WHERE cohort_id = %s ORDER BY number ASC;
            """, (cid,))
            rows = cur.fetchall()
            res = [{
                "id": r[0],
                "number": r[1],
                "title": r[2] or "",
                "active": r[3],
                "opens_at": r[4].isoformat() if r[4] else None,
                "closes_at": r[5].isoformat() if r[5] else None,
                "duration_minutes": r[6],
                "pass_mark": float(r[7])
            } for r in rows]
            return jsonify(res)


@app.route('/api/admin/cohorts/<int:cid>/quizzes', methods=['POST'])
def admin_create_cohort_quiz(cid):
    auth_err = require_admin()
    if auth_err: return auth_err
    data = request.json or {}
    title = data.get('title', '').strip()
    duration = int(data.get('duration_minutes', 60))
    pass_mark = float(data.get('pass_mark', 50.0))
    opens_at = data.get('opens_at') or None
    closes_at = data.get('closes_at') or None
    active = bool(data.get('active', False))
    
    if not title:
        return jsonify({"error": "Title is required"}), 400
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(number), 0) FROM quizzes WHERE cohort_id = %s;", (cid,))
            max_num = cur.fetchone()[0]
            next_num = max_num + 1
            
            cur.execute("""
                INSERT INTO quizzes (number, title, duration_minutes, pass_mark, opens_at, closes_at, active, cohort_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (next_num, title, duration, pass_mark, opens_at, closes_at, active, cid))
            qid = cur.fetchone()[0]
        conn.commit()
    return jsonify({"success": True, "quiz_id": qid})


@app.route('/api/admin/quizzes/<int:qid>', methods=['PUT'])
def admin_update_quiz(qid):
    auth_err = require_admin()
    if auth_err: return auth_err
    data = request.json or {}
    title = data.get('title', '').strip()
    duration = int(data.get('duration_minutes', 60))
    pass_mark = float(data.get('pass_mark', 50.0))
    opens_at = data.get('opens_at') or None
    closes_at = data.get('closes_at') or None
    active = bool(data.get('active', False))
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE quizzes
                SET title = %s, duration_minutes = %s, pass_mark = %s, opens_at = %s, closes_at = %s, active = %s
                WHERE id = %s RETURNING id;
            """, (title, duration, pass_mark, opens_at, closes_at, active, qid))
            if not cur.fetchone():
                return jsonify({"error": "Quiz not found"}), 404
        conn.commit()
    return jsonify({"success": True})


@app.route('/api/admin/quizzes/<int:qid>', methods=['DELETE'])
def admin_delete_quiz(qid):
    auth_err = require_admin()
    if auth_err: return auth_err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM quizzes WHERE id = %s RETURNING id;", (qid,))
            if not cur.fetchone():
                return jsonify({"error": "Quiz not found"}), 404
        conn.commit()
    return jsonify({"success": True})


@app.route('/api/admin/quizzes/<int:qid>/questions', methods=['GET'])
def admin_quiz_questions(qid):
    auth_err = require_admin()
    if auth_err: return auth_err
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, section, stem, quiz_id
                FROM questions
                ORDER BY section ASC, position ASC;
            """)
            rows = cur.fetchall()
            res = [{
                "id": r[0],
                "section": r[1],
                "stem": r[2],
                "assigned": (r[3] == qid)
            } for r in rows]
            return jsonify(res)


@app.route('/api/admin/quizzes/<int:qid>/questions', methods=['PUT'])
def admin_quiz_questions_update(qid):
    auth_err = require_admin()
    if auth_err: return auth_err
    data = request.json or {}
    question_ids = data.get('question_ids', [])
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            if question_ids:
                cur.execute("UPDATE questions SET quiz_id = NULL WHERE quiz_id = %s AND id NOT IN %s;", (qid, tuple(question_ids)))
                cur.execute("UPDATE questions SET quiz_id = %s WHERE id IN %s;", (qid, tuple(question_ids)))
            else:
                cur.execute("UPDATE questions SET quiz_id = NULL WHERE quiz_id = %s;", (qid,))
        conn.commit()
    return jsonify({"success": True})


if __name__ == '__main__':
    _bootstrap()
    app.run(host='127.0.0.1', port=5000, debug=True)
else:
    # Running under gunicorn / Vercel
    _bootstrap()
