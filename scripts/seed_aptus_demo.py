"""Seed isolated Aptus demo records. Never run this for Mainstreet."""
from datetime import datetime, timedelta, timezone
import os

from dotenv import load_dotenv
load_dotenv()

from talent_portal.branding import load_brand
from talent_portal.db import DBConnection

brand = load_brand()
if brand.key != "aptus":
    raise SystemExit("Refusing demo seed: BRAND_PROFILE must be aptus.")

jobs = [
    ("Operations Analyst", "Operations", "Lagos", "Full-time", "Improve reliable day-to-day operations.", "Clear communication and analytical thinking.", "aptus-demo-operations"),
    ("People Experience Associate", "People", "Lagos", "Full-time", "Help candidates and colleagues move through a fair process.", "Empathy, organisation, and follow-through.", "aptus-demo-people"),
]
candidates = [
    ("Ada Okafor", "ada.demo@aptus.example", "08000000001", "Operations Analyst", "Lagos", "assessment_passed"),
    ("Chidi Bello", "chidi.demo@aptus.example", "08000000002", "Operations Analyst", "Lagos", "interview_completed"),
    ("Zainab Yusuf", "zainab.demo@aptus.example", "08000000003", "People Experience Associate", "Lagos", "offered"),
    ("Emeka Nwosu", "emeka.demo@aptus.example", "08000000004", "People Experience Associate", "Abuja", "screening_flagged"),
]

with DBConnection() as conn:
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS aptus_demo_seed (email TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        job_ids = {}
        for title, department, location, employment, description, requirements, key in jobs:
            cur.execute("""INSERT INTO job_postings(title,department,location,employment_type,description,requirements,status,application_deadline,legacy_role_key,published_at)
                VALUES(%s,%s,%s,%s,%s,%s,'published',%s,%s,NOW())
                ON CONFLICT (legacy_role_key) DO UPDATE SET status='published', updated_at=NOW()
                RETURNING id""", (title, department, location, employment, description, requirements,
                                    datetime.now(timezone.utc) + timedelta(days=30), key))
            job_ids[title] = cur.fetchone()[0]
        for name, email, phone, role, location, stage in candidates:
            cur.execute("SELECT id FROM candidates WHERE LOWER(email)=LOWER(%s)", (email,))
            existing = cur.fetchone()
            if not existing:
                cur.execute("""INSERT INTO candidates(full_name,email,phone_number,role,location,job_id,stage,stage_updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,NOW()) RETURNING id""",
                    (name, email, phone, role, location, job_ids[role], stage))
                cur.execute("INSERT INTO aptus_demo_seed(email) VALUES(%s) ON CONFLICT DO NOTHING", (email,))
            cur.execute("UPDATE candidates SET dob=COALESCE(dob,'1995-01-01'), nysc_status=COALESCE(nysc_status,'completed') WHERE LOWER(email)=LOWER(%s)", (email,))
    conn.commit()

print("Aptus demo seed complete: 2 jobs and 4 marked demo candidates.")
