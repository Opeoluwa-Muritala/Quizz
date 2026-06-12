import os
import time
import datetime
import secrets
import hmac
import csv
import io
import json
import requests
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, Response
from psycopg2 import pool
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    # Fallback to random key for testing/dev, log a warning
    print("WARNING: FLASK_SECRET_KEY not set. Generating ephemeral key.")
    app.secret_key = secrets.token_hex(32)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

ADMIN_SESSION_TIMEOUT_MINUTES = 30
MAX_ADMIN_DEVICES = 2

# Initialize PostgreSQL Connection Pool
db_url = os.environ.get("NEON_DATABASE_URL")
connection_pool = None
try:
    if db_url:
        connection_pool = pool.ThreadedConnectionPool(1, 20, db_url)
    else:
        print("ERROR: NEON_DATABASE_URL is not set.")
except Exception as e:
    print(f"Error creating connection pool: {e}")

# Initialize Cloudinary
import cloudinary
import cloudinary.uploader
import cloudinary.utils

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

# Database helper context manager
class DBConnection:
    def __enter__(self):
        if not connection_pool:
            raise Exception("Database connection pool is not initialized. Check NEON_DATABASE_URL.")
        self.conn = connection_pool.getconn()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, 'conn') and self.conn:
            connection_pool.putconn(self.conn)

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
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
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
                    updated_at           TIMESTAMPTZ DEFAULT NOW()
                );
            """)

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
            
            # Seed exam_settings if missing
            cur.execute("SELECT count(*) FROM exam_settings WHERE id = 1;")
            if cur.fetchone()[0] == 0:
                from config import PASS_MARK_PERCENT, SECONDS_PER_QUESTION
                cur.execute("""
                    INSERT INTO exam_settings (id, exam_open, seconds_per_question, pass_mark_percent)
                    VALUES (1, FALSE, %s, %s);
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
        conn.commit()

# Custom CSRF Protection
@app.before_request
def check_csrf():
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
    return render_template('index.html')

@app.route('/api/check-email', methods=['POST'])
def check_email():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    full_name = data.get('full_name', '').strip()
    
    if not email:
        return jsonify({"error": "Email is required"}), 400
        
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
                
            # 3. Check already submitted
            cur.execute("""
                SELECT 1 FROM exam_results ER
                JOIN candidates C ON ER.candidate_id = C.id
                WHERE LOWER(C.email) = LOWER(%s);
            """, (email,))
            if cur.fetchone():
                return jsonify({"error": "A submission for this email has already been recorded."}), 400
                
    return jsonify({"status": "success", "message": "Email verified successfully."})

@app.route('/api/exam-summary', methods=['GET'])
def exam_summary():
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT exam_open, seconds_per_question, pass_mark_percent
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
        "total_questions": active_question_count
    })

@app.route('/api/upload-photos', methods=['POST'])
def upload_photos():
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    full_name = data.get('full_name', '').strip()
    selfie_b64 = data.get('selfie_b64')
    id_card_b64 = data.get('id_card_b64')
    
    if not email or not full_name or not selfie_b64 or not id_card_b64:
        return jsonify({"error": "Missing registration details or images"}), 400
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Run same checks as check-email
            cur.execute("SELECT exam_open FROM exam_settings WHERE id = 1;")
            settings = cur.fetchone()
            if not settings or not settings[0]:
                return jsonify({"error": "The exam portal is currently closed. Please contact HR."}), 400
                
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
                
            # Perform Cloudinary Uploads
            now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M")
            folder_name = f"exams/{email}-{now_str}"
            
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
                    SET full_name = %s, selfie_url = %s, id_card_url = %s, cloudinary_folder = %s
                    WHERE id = %s;
                """, (full_name, selfie_url, id_card_url, folder_name, candidate_id))
            else:
                cur.execute("""
                    INSERT INTO candidates (full_name, email, selfie_url, id_card_url, cloudinary_folder)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                """, (full_name, email, selfie_url, id_card_url, folder_name))
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
                
            # Fetch active questions
            cur.execute("""
                SELECT id, section, stem, option_a, option_b, option_c, option_d, position
                FROM questions
                WHERE active = TRUE
                ORDER BY section, position ASC;
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
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Check if already submitted
            cur.execute("SELECT id FROM exam_results WHERE candidate_id = %s;", (candidate_id,))
            if cur.fetchone():
                return jsonify({"error": "A submission for this candidate has already been recorded."}), 400
                
            # Fetch active questions to score
            cur.execute("""
                SELECT id, section, answer
                FROM questions
                WHERE active = TRUE;
            """)
            questions_db = cur.fetchall()
            
            # Fetch passing rules
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
                INSERT INTO exam_results (candidate_id, score_percent, score_fraction, pass_fail, time_taken_secs, tab_switches, breakdown_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                candidate_id,
                score_percent,
                score_fraction,
                pass_fail,
                time_taken_secs,
                tab_switches,
                json.dumps(breakdown)
            ))
            
            # Fetch candidate info for response certificate
            cur.execute("SELECT full_name, email, created_at FROM candidates WHERE id = %s;", (candidate_id,))
            cand_info = cur.fetchone()
            
        conn.commit()
        
    # Clear candidate session on success
    session.pop('candidate_id', None)
    session.pop('candidate_email', None)
    
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
        "submitted_at": submitted_date.isoformat()
    })


# ── Admin Panel Routes ───────────────────────────────────────────────

@app.route('/admin')
def admin_dashboard():
    if not session.get('admin') or not session.get('admin_session_token') or not get_current_admin_session_id():
        session.pop('admin', None)
        session.pop('admin_session_token', None)
        return redirect(url_for('admin_login'))
    return render_template('admin.html', authenticated=True)

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
    token = data.get('token', '').strip()
    
    admin_token = os.environ.get("ADMIN_TOKEN", "admin123")
    
    # Constant-time comparison
    if not hmac.compare_digest(token.encode('utf-8'), admin_token.encode('utf-8')):
        return jsonify({"success": False, "error": "Incorrect access token"}), 401

    user_agent, ip_address = get_admin_device_fingerprint()

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
                cur.execute("SELECT exam_open, seconds_per_question, pass_mark_percent, updated_at FROM exam_settings WHERE id = 1;")
                row = cur.fetchone()
        if not row:
            return jsonify({"error": "Settings not initialized"}), 500
        return jsonify({
            "exam_open": row[0],
            "seconds_per_question": row[1],
            "pass_mark_percent": float(row[2]),
            "updated_at": row[3].isoformat()
        })
        
    # Update settings
    data = request.json or {}
    exam_open = data.get('exam_open', False)
    seconds_per_q = int(data.get('seconds_per_question', 60))
    pass_mark = float(data.get('pass_mark_percent', 50))
    
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE exam_settings
                SET exam_open = %s, seconds_per_question = %s, pass_mark_percent = %s, updated_at = NOW()
                WHERE id = 1;
            """, (exam_open, seconds_per_q, pass_mark))
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
    
    # Sortable columns: name, email, score, time, date, switches
    sort_column = request.args.get('sort', 'submitted_at')
    sort_order = request.args.get('order', 'DESC').upper()
    page = int(request.args.get('page', 1))
    per_page = 25
    offset = (page - 1) * per_page
    
    # Mapping request strings to SQL
    allowed_cols = {
        'name': 'C.full_name',
        'email': 'C.email',
        'score': 'ER.score_percent',
        'time': 'ER.time_taken_secs',
        'switches': 'ER.tab_switches',
        'submitted_at': 'ER.submitted_at'
    }
    col_sql = allowed_cols.get(sort_column, 'ER.submitted_at')
    if sort_order not in ['ASC', 'DESC']:
        sort_order = 'DESC'
        
    with DBConnection() as conn:
        with conn.cursor() as cur:
            # Total counts
            cur.execute("""
                SELECT 
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN pass_fail = 'PASS' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN pass_fail = 'FAIL' THEN 1 ELSE 0 END), 0),
                    COALESCE(ROUND(AVG(score_percent), 2), 0),
                    COALESCE(ROUND(AVG(time_taken_secs), 0), 0)
                FROM exam_results;
            """)
            summary_row = cur.fetchone()
            summary = {
                "total": summary_row[0],
                "passed": summary_row[1],
                "failed": summary_row[2],
                "avg_score": float(summary_row[3]),
                "avg_time": int(summary_row[4])
            }
            
            # Fetch results
            query = f"""
                SELECT ER.id, C.full_name, C.email, ER.score_percent, ER.score_fraction,
                       ER.pass_fail, ER.time_taken_secs, ER.tab_switches, ER.submitted_at, C.id
                FROM exam_results ER
                JOIN candidates C ON ER.candidate_id = C.id
                ORDER BY {col_sql} {sort_order}
                LIMIT %s OFFSET %s;
            """
            cur.execute(query, (per_page, offset))
            rows = cur.fetchall()
            
            results = []
            for r in rows:
                results.append({
                    "id": r[0],
                    "name": r[1],
                    "email": r[2],
                    "score_percent": float(r[3]),
                    "score_fraction": r[4],
                    "pass_fail": r[5],
                    "time_taken_secs": r[6],
                    "tab_switches": r[7],
                    "submitted_at": r[8].isoformat(),
                    "candidate_id": r[9]
                })
                
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
        writer.writerow(['Candidate Name', 'Email', 'Score %', 'Score (Fraction)', 'Pass/Fail', 'Time Taken (s)', 'Tab Switches', 'Submitted At'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT C.full_name, C.email, ER.score_percent, ER.score_fraction, ER.pass_fail, ER.time_taken_secs, ER.tab_switches, ER.submitted_at
                    FROM exam_results ER
                    JOIN candidates C ON ER.candidate_id = C.id
                    ORDER BY ER.submitted_at DESC;
                """)
                while True:
                    rows = cur.fetchmany(100)
                    if not rows:
                        break
                    for r in rows:
                        writer.writerow([r[0], r[1], float(r[2]), r[3], r[4], r[5], r[6], r[7].isoformat()])
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


if __name__ == '__main__':
    # Initialise Tables & Seeding
    try:
        init_db()
    except Exception as e:
        print(f"Database initialization error on boot: {e}")
        
    app.run(host='127.0.0.1', port=5000, debug=True)
