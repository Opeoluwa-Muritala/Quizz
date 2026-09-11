"""Job validation and read models, shared by public and admin routes."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from psycopg2.extras import RealDictCursor
from talent_portal.db import DBConnection

EMPLOYMENT_TYPES = ('Full-time', 'Part-time', 'Contract', 'Temporary', 'Internship')
STATUSES = ('draft', 'published', 'closed')
LOCAL_TZ = ZoneInfo('Africa/Lagos')


def validate_job(data):
    cleaned, errors = {}, {}
    for key, maximum in {'title':160, 'department':120, 'location':180,
                         'description':12000, 'requirements':12000}.items():
        value = data.get(key, '')
        if not isinstance(value, str):
            errors[key] = 'Enter text for this field.'
            value = ''
        value = value.strip()
        if not value:
            errors[key] = 'This field is required.'
        elif len(value) > maximum or '\x00' in value:
            errors[key] = f'Use no more than {maximum:,} characters and no null characters.'
        cleaned[key] = value
    employment_type = data.get('employment_type', '')
    if employment_type not in EMPLOYMENT_TYPES:
        errors['employment_type'] = 'Select an employment type.'
    cleaned['employment_type'] = employment_type
    deadline = data.get('application_deadline', '')
    cleaned['application_deadline'] = None
    if deadline:
        try:
            parsed = datetime.fromisoformat(deadline)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=LOCAL_TZ)
            cleaned['application_deadline'] = parsed.astimezone(timezone.utc)
        except (ValueError, TypeError):
            errors['application_deadline'] = 'Enter a valid date and time (WAT).'
    return cleaned, errors


def deadline_is_past(job):
    deadline = job.get('application_deadline')
    return bool(deadline and deadline <= datetime.now(timezone.utc))


def decorate_job(job):
    job = dict(job)
    deadline = job.get('application_deadline')
    job['deadline_input'] = deadline.astimezone(LOCAL_TZ).strftime('%Y-%m-%dT%H:%M') if deadline else ''
    job['deadline_label'] = deadline.astimezone(LOCAL_TZ).strftime('%d %b %Y, %H:%M WAT') if deadline else 'No deadline'
    job['accepting'] = job['status'] == 'published' and not deadline_is_past(job)
    job['display_status'] = 'deadline passed' if job['status'] == 'published' and not job['accepting'] else job['status']
    return job


def list_open_jobs():
    with DBConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT * FROM job_postings WHERE status='published'
                AND (application_deadline IS NULL OR application_deadline > NOW())
                ORDER BY published_at DESC, id DESC""")
            return [decorate_job(row) for row in cur.fetchall()]


def get_job(job_id):
    with DBConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM job_postings WHERE id=%s', (job_id,))
            row = cur.fetchone()
            return decorate_job(row) if row else None
