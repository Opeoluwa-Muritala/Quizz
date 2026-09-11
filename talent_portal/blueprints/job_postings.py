"""Shared-login admin job management and public job discovery."""
from flask import Blueprint, render_template, request, redirect, url_for, abort, session
from psycopg2.extras import RealDictCursor
from talent_portal.db import DBConnection
from talent_portal.services.job_postings import (
    EMPLOYMENT_TYPES, STATUSES, validate_job, decorate_job, get_job, list_open_jobs, deadline_is_past,
)

job_postings = Blueprint('job_postings', __name__)


@job_postings.before_request
def admin_guard():
    if request.path.startswith('/admin/'):
        from talent_portal.application import require_admin
        error = require_admin()
        if error:
            if request.method == 'GET':
                return redirect(url_for('admin_login'))
            return error


@job_postings.get('/admin/jobs')
def admin_jobs():
    status = request.args.get('status', '')
    if status and status not in STATUSES:
        abort(400)
    with DBConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT j.*, (SELECT COUNT(*) FROM candidates c WHERE c.job_id=j.id) AS candidate_count
                FROM job_postings j WHERE (%s='' OR j.status=%s) ORDER BY j.updated_at DESC, j.id DESC""", (status,status))
            jobs = [decorate_job(row) for row in cur.fetchall()]
            cur.execute("SELECT status, COUNT(*) AS count FROM job_postings GROUP BY status")
            counts = {row['status']:row['count'] for row in cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS count FROM candidates WHERE job_id IS NULL")
            unmatched = cur.fetchone()['count']
    return render_template('admin/jobs.html', jobs=jobs, counts=counts, status=status,
                           unmatched=unmatched, saved=request.args.get('saved') == '1')


def editor(job=None, errors=None, status=200):
    return render_template('admin/job_form.html', job=job or {}, errors=errors or {},
                           employment_types=EMPLOYMENT_TYPES,
                           saved=request.args.get('saved') == '1'), status


@job_postings.route('/admin/jobs/new', methods=['GET','POST'])
def create_job():
    if request.method == 'GET':
        return editor()
    data, errors = validate_job(request.form)
    if errors:
        return editor(dict(request.form), errors, 400)
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO job_postings(title,department,location,employment_type,description,requirements,application_deadline)
                VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id""", tuple(data[k] for k in
                ('title','department','location','employment_type','description','requirements','application_deadline')))
            job_id = cur.fetchone()[0]
        conn.commit()
    return redirect(url_for('job_postings.edit_job', job_id=job_id, saved=1), code=303)


@job_postings.route('/admin/jobs/<int:job_id>/edit', methods=['GET','POST'])
def edit_job(job_id):
    job = get_job(job_id)
    if job is None:
        abort(404)
    if request.method == 'GET':
        return editor(job)
    data, errors = validate_job(request.form)
    if job['status'] == 'published' and deadline_is_past(data):
        errors['application_deadline'] = 'Choose a future deadline, or close the job to stop applications.'
    try:
        version = int(request.form.get('version',''))
    except ValueError:
        version = -1
    if errors:
        return editor({**job, **dict(request.form), 'deadline_input':request.form.get('application_deadline','')}, errors, 400)
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE job_postings SET title=%s,department=%s,location=%s,employment_type=%s,
                description=%s,requirements=%s,application_deadline=%s,updated_at=NOW(),version=version+1
                WHERE id=%s AND version=%s""", tuple(data[k] for k in
                ('title','department','location','employment_type','description','requirements','application_deadline')) + (job_id,version))
            updated = cur.rowcount
        conn.commit()
    if not updated:
        return editor(get_job(job_id), {'form':'This job changed in another window. Review the latest version before saving again.'}, 409)
    return redirect(url_for('job_postings.edit_job', job_id=job_id, saved=1), code=303)


@job_postings.post('/admin/jobs/<int:job_id>/status')
def change_status(job_id):
    target = request.form.get('status')
    if target not in ('published','closed'):
        abort(400)
    try:
        version = int(request.form.get('version',''))
    except ValueError:
        abort(400)
    with DBConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM job_postings WHERE id=%s FOR UPDATE', (job_id,))
            row = cur.fetchone()
            if row is None:
                abort(404)
            job = decorate_job(row)
            errors = {}
            if version != job['version']:
                errors['form'] = 'This job changed in another window. Review the latest version and try again.'
            elif (job['status'],target) not in (('draft','published'),('published','closed'),('closed','published')):
                errors['form'] = 'That status change is not available. Review the current job status.'
            elif target == 'published':
                _, errors = validate_job({**job, 'application_deadline':job['deadline_input']})
                if deadline_is_past(job):
                    errors['application_deadline'] = 'Update the deadline before publishing or reopening this job.'
            if errors:
                return editor(job, errors, 409 if 'form' in errors else 400)
            cur.execute("""UPDATE job_postings SET status=%s, version=version+1, updated_at=NOW(),
                published_at=CASE WHEN %s='published' THEN NOW() ELSE published_at END,
                closed_at=CASE WHEN %s='closed' THEN NOW() ELSE NULL END WHERE id=%s""", (target,target,target,job_id))
        conn.commit()
    return redirect(url_for('job_postings.admin_jobs', saved=1), code=303)


@job_postings.get('/admin/jobs/<int:job_id>/preview')
def preview_job(job_id):
    job = get_job(job_id)
    if job is None:
        abort(404)
    return render_template('candidate/job_detail.html', job=job, preview=True)


@job_postings.get('/admin/jobs/legacy')
def legacy_candidates():
    # Historical rows remain visible without guessing which new job they belong to.
    try:
        page = max(1,int(request.args.get('page','1')))
    except ValueError:
        abort(400)
    with DBConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT COUNT(*) AS count FROM candidates WHERE job_id IS NULL')
            total = cur.fetchone()['count']
            cur.execute("""SELECT id,full_name,email,role,stage FROM candidates WHERE job_id IS NULL
                ORDER BY id LIMIT 50 OFFSET %s""", ((page-1)*50,))
            candidates = cur.fetchall()
    return render_template('admin/job_legacy.html', candidates=candidates, page=page, total=total)


@job_postings.get('/jobs')
def public_jobs():
    return render_template('candidate/jobs.html', jobs=list_open_jobs())


@job_postings.get('/jobs/<int:job_id>')
def public_job(job_id):
    job = get_job(job_id)
    if job is None or not job['accepting']:
        abort(404)
    return render_template('candidate/job_detail.html', job=job, preview=False)
