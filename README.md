# Mainstreet MFB Quiz and Recruitment App

Mainstreet MFB Quiz and Recruitment App is a Flask web application for running candidate aptitude tests and managing an end-to-end recruitment pipeline. It supports public candidate applications, automated eligibility screening, timed assessments, interview slot booking, document uploads, Gmail email notifications, and admin controls for hiring teams.

The app is designed around two connected products:

- Aptitude test portal: a whitelist-based quiz flow with identity uploads, timed questions, scoring, and admin reporting.
- Recruitment pipeline: a broader hiring workflow from application submission through screening, assessment, interview scheduling, document collection, final offer, or rejection.

## Phase Plan

### Phase 1: Core Application and Assessment

Phase 1 should make the app usable for a controlled aptitude test or first-stage recruitment round.

It includes:

- Candidate landing page and registration flow.
- Email whitelist checks for quiz access.
- Candidate photo and ID upload through Cloudinary.
- Timed aptitude test with numerical, verbal, and logical questions.
- Server-side scoring and pass/fail calculation.
- Tab-switch tracking during assessment.
- Candidate result display after submission.
- Admin login protected by an admin token.
- Admin settings for exam status, timer, pass mark, and title.
- Admin question management with create, update, delete, reorder, JSON import, and CSV import.
- Admin whitelist management with single and bulk email import.
- Admin result dashboard with search, sorting, summary metrics, CSV export, and image preview.
- PostgreSQL persistence using the `NEON_DATABASE_URL` connection string.
- Cloudinary storage for candidate images and uploaded files.

### Phase 2: Full Recruitment Pipeline

Phase 2 expands the app into a full hiring workflow.

It includes:

- Public application form with full name, email, phone number, date of birth, NYSC status, role, location, and CV upload.
- Automated eligibility screening from configurable rules.
- Candidate dashboard that reflects the candidate's current stage.
- Stage tracking and audit history.
- Gmail SMTP notifications for application, screening, assessment, interview, document, offer, and rejection events.
- Assessment start, resume, timeout, and submission flow tied to recruitment stages.
- Interviewer management.
- Availability rule management.
- Automatic generation of interview slots from interviewer availability.
- Candidate interview slot booking.
- Jitsi Meet meeting-link generation for interviews.
- Interview page with meeting details and configurable instructions.
- Required document upload and submission.
- Admin recruitment dashboard for candidate management, stage overrides, interview slots, stage configuration, email logs, resend actions, and document verification.
- Background jobs for slot generation and deadline expiry.
- External cron endpoints protected by `JOB_SECRET`.

## User Roles

### Candidate

Candidates should be able to:

- Apply for the recruitment program.
- Upload a CV during application.
- See their application status from a dashboard.
- Receive email updates at each important stage.
- Start or resume the assessment when eligible.
- Complete a timed assessment.
- View whether they passed or failed.
- Book an interview slot after passing the assessment.
- Join an interview meeting from the interview page.
- Upload required documents when requested.
- Log out of the recruitment session.

### Admin

Admins should be able to:

- Log in with the configured `ADMIN_TOKEN`.
- Manage quiz settings.
- Manage questions and quizzes.
- Manage candidate whitelist entries.
- Review quiz results and export them.
- Preview uploaded candidate images and CVs.
- View recruitment candidates.
- Open candidate detail records.
- Manually move candidates between stages.
- Trigger notification emails when moving candidates.
- Manage interviewers.
- Create and update interviewer availability.
- Generate interview slots.
- Block or unblock slots.
- Add or remove interview panel members.
- Update recruitment stage configuration.
- Review email delivery logs.
- Resend failed emails.
- Review and verify candidate documents.

## Candidate Flows

### Quiz Flow

1. Candidate opens `/`.
2. Candidate enters full name and email.
3. App checks whether:
   - the exam is open,
   - the email is whitelisted,
   - the candidate has not already submitted.
4. Candidate uploads ID and selfie images.
5. App uploads the images to Cloudinary.
6. Candidate starts the assessment.
7. App serves active questions only.
8. Candidate submits answers.
9. App scores answers server-side and records:
   - score percentage,
   - score fraction,
   - pass/fail status,
   - time taken,
   - tab switches,
   - section breakdown.
10. Candidate sees result and reference number.

### Recruitment Flow

1. Candidate opens `/apply`.
2. Candidate submits personal details and optionally uploads a CV.
3. App stores the candidate and starts the CV upload job if a file was provided.
4. App runs eligibility screening.
5. Candidate moves to one of:
   - `screening_passed`,
   - `screening_flagged`,
   - `screening_failed`.
6. App sends Gmail notifications for application receipt and screening outcome.
7. Eligible candidates start the assessment.
8. Passed candidates move to `interview_slot_pending`.
9. Candidate selects an available interview slot.
10. App books the slot, creates a Jitsi Meet link, and emails the booking details.
11. Candidate can view interview details at `/interview`.
12. Admin may request documents by moving the candidate to `documents_pending`.
13. Candidate uploads required documents and submits them for review.
14. Admin completes the process by moving the candidate to `offered` or `rejected`.

## Recruitment Stages

The app supports these candidate stages:

- `applied`
- `screening_passed`
- `screening_flagged`
- `screening_failed`
- `assessment_in_progress`
- `assessment_passed`
- `assessment_failed`
- `interview_slot_pending`
- `interview_scheduled`
- `documents_pending`
- `documents_submitted`
- `interview_completed`
- `offered`
- `rejected`
- `application_expired`
- `assessment_expired`
- `booking_expired`
- `documents_expired`

Each stage change should be recorded in `candidate_stage_history`.

## Email Notifications

Email is sent through Gmail SMTP using an app password.

Required variables:

```env
GMAIL_USER=your-gmail-address@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password
APP_BASE_URL=https://your-public-app-url
```

Supported notification events include:

- `application_submitted`
- `screening_passed`
- `screening_failed`
- `screening_flagged`
- `assessment_available`
- `assessment_passed`
- `assessment_failed`
- `interview_slot_available`
- `interview_booked`
- `documents_required`
- `offered`
- `rejected`

Every email attempt should be stored in `email_log` with recipient, event type, status, error message, and template name.

If `GMAIL_APP_PASSWORD` is missing, the notification service logs the email action to the server console instead of sending through Gmail.

## Application Time, Deadlines, and Time Zone

The app stores important timestamps in PostgreSQL as timestamp fields, including:

- candidate creation time,
- stage update time,
- assessment start time,
- assessment submission time,
- generated interview slot start and end time,
- email sent time,
- upload job update time.

Interview slot calendar filtering uses the `Africa/Lagos` time zone for candidate-facing month views. Interview booking emails display times as WAT.

Stage deadlines are configured in `stage_config` using:

- `opens_at`: optional absolute opening time.
- `closes_at`: optional absolute closing time.
- `relative_deadline_hours`: deadline counted from when a candidate entered a stage.
- `duration_minutes`: assessment duration.

The deadline expiry job checks candidates periodically and moves overdue candidates to the correct expired stage.

## Background Jobs

The app starts APScheduler jobs when available:

- Generate interview slots daily at 01:00.
- Expire overdue candidates every 30 minutes.

The app also exposes protected job endpoints for external schedulers:

- `POST /api/jobs/generate-slots`
- `POST /api/jobs/expire-deadlines`

Requests to job endpoints must provide the configured job secret.

```env
JOB_SECRET=replace-with-a-strong-secret
```

## Meeting Scheduling

Interview slots are generated from `availability_rules`.

Admins define:

- interviewer,
- rule type,
- day of week or date range,
- start time,
- end time,
- slot duration,
- buffer minutes,
- booking lead time.

When a candidate books a slot, the app:

- locks the selected slot,
- confirms it is not booked or blocked,
- enforces lead time,
- generates a unique Jitsi Meet room URL,
- stores the meeting link,
- moves the candidate to `interview_scheduled`,
- sends an interview confirmation email.

## File Uploads

The app uses Cloudinary for candidate files.

Required variables:

```env
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
```

Supported upload types:

- CV: PDF, DOC, DOCX.
- Recruitment documents: PDF, DOC, DOCX, JPG, PNG.
- Quiz identity uploads: ID image and selfie image.

Maximum file size for recruitment upload jobs is 10 MB.

Uploads are processed in background threads and tracked in `upload_jobs`.

## Admin Security

Admin access is protected by `ADMIN_TOKEN`.

```env
ADMIN_TOKEN=replace-with-a-strong-token
```

Admin sessions:

- expire after inactivity,
- are tracked in `admin_sessions`,
- are limited to two active admin devices at a time.

Use a strong `FLASK_SECRET_KEY` in every deployed environment.

```env
FLASK_SECRET_KEY=replace-with-a-random-secret
```

## Environment Variables

Create a `.env` file in the project root.

```env
NEON_DATABASE_URL=postgresql://user:password@host:port/database
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
ADMIN_TOKEN=replace-with-a-strong-token
FLASK_SECRET_KEY=replace-with-a-random-secret
GMAIL_USER=your-gmail-address@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password
APP_BASE_URL=http://127.0.0.1:5000
JOB_SECRET=replace-with-a-strong-secret
```

Never commit real passwords, database URLs, Gmail app passwords, Cloudinary secrets, or admin tokens.

## Local Setup

Requirements:

- Python 3.11 or newer.
- PostgreSQL database, such as Neon.
- Cloudinary account.
- Gmail account with an app password for live email sending.

Install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Run locally:

```bash
python app.py
```

Open:

- Candidate quiz: `http://127.0.0.1:5000/`
- Recruitment application: `http://127.0.0.1:5000/apply`
- Candidate dashboard: `http://127.0.0.1:5000/dashboard`
- Admin dashboard: `http://127.0.0.1:5000/admin`
- Recruitment admin: `http://127.0.0.1:5000/admin/recruitment`

## Deployment

For production, run the app with a WSGI server such as Gunicorn:

```bash
gunicorn app:app --bind 0.0.0.0:5000
```

Production requirements:

- all environment variables configured on the host,
- public `APP_BASE_URL` set to the deployed app URL,
- working PostgreSQL connection,
- working Cloudinary credentials,
- working Gmail app password,
- HTTPS enabled by the platform,
- scheduled calls to job endpoints if APScheduler is not reliable on the host.

## Main Routes

### Candidate Quiz

- `GET /`
- `POST /api/check-email`
- `GET /api/exam-summary`
- `POST /api/upload-photos`
- `GET /api/questions`
- `POST /api/submit-results`

### Recruitment Candidate

- `GET /apply`
- `GET /dashboard`
- `GET /assessment`
- `GET /schedule`
- `GET /documents`
- `GET /interview`
- `POST /api/apply`
- `GET /api/upload-status/<job_id>`
- `POST /api/assessment/start`
- `POST /api/assessment/submit`
- `GET /api/slots`
- `POST /api/slots/<slot_id>/book`
- `POST /api/documents/upload`
- `POST /api/documents/submit`
- `POST /recruitment/logout`

### Admin Quiz

- `GET /admin`
- `GET|POST /admin/login`
- `POST /admin/logout`
- `GET|POST /api/admin/settings`
- `GET|POST /api/admin/questions`
- `PUT|DELETE /api/admin/questions/<id>`
- `POST /api/admin/questions/bulk`
- `POST /api/admin/questions/reorder`
- `GET|POST /api/admin/whitelist`
- `POST /api/admin/whitelist/bulk`
- `DELETE /api/admin/whitelist/<id>`
- `POST /api/admin/whitelist/clear`
- `GET|POST /api/admin/quizzes`
- `PUT|DELETE /api/admin/quizzes/<id>`
- `POST /api/admin/quizzes/<id>/activate`
- `GET /api/admin/quiz-results`
- `GET /api/admin/cv-view`
- `POST /api/admin/results/clear`
- `GET /api/admin/results`
- `GET /api/admin/export-csv`
- `GET /api/admin/image/<candidate_id>/<image_type>`

### Admin Recruitment

- `GET /admin/recruitment`
- `GET /api/admin/recruitment/candidates`
- `GET /api/admin/recruitment/candidates/<id>`
- `POST /api/admin/recruitment/candidates/<id>/stage`
- `GET|POST /api/admin/recruitment/interviewers`
- `PUT|DELETE /api/admin/recruitment/interviewers/<id>`
- `GET|POST /api/admin/recruitment/availability-rules`
- `PUT|DELETE /api/admin/recruitment/availability-rules/<id>`
- `GET /api/admin/recruitment/slots`
- `POST /api/admin/recruitment/slots/<slot_id>/block`
- `POST /api/admin/recruitment/slots/generate`
- `GET|POST /api/admin/recruitment/slots/<slot_id>/interviewers`
- `DELETE /api/admin/recruitment/slots/<slot_id>/interviewers/<interviewer_id>`
- `GET /api/admin/recruitment/stage-config`
- `PUT /api/admin/recruitment/stage-config/<stage_name>`
- `GET /api/admin/recruitment/email-log`
- `POST /api/admin/recruitment/email-log/<log_id>/resend`
- `GET /api/admin/recruitment/documents/<candidate_id>`
- `POST /api/admin/recruitment/documents/<document_id>/verify`

### Jobs

- `POST /api/jobs/generate-slots`
- `POST /api/jobs/expire-deadlines`

## Database

The app initializes and migrates the required tables at startup.

Core tables include:

- `candidates`
- `questions`
- `exam_results`
- `whitelist`
- `exam_settings`
- `admin_sessions`
- `scores`
- `candidate_documents`
- `interviewers`
- `availability_rules`
- `generated_slots`
- `stage_config`
- `email_log`
- `recruitment_cycles`
- `candidate_stage_history`
- `upload_jobs`
- `slot_interviewers`

## Operational Checklist

Before using the app in production:

- Confirm `NEON_DATABASE_URL` connects successfully.
- Confirm Cloudinary uploads work.
- Confirm `GMAIL_USER` and `GMAIL_APP_PASSWORD` send email successfully.
- Confirm `APP_BASE_URL` points to the public app URL.
- Set a strong `ADMIN_TOKEN`.
- Set a strong `FLASK_SECRET_KEY`.
- Set `JOB_SECRET` before enabling external cron jobs.
- Create or verify quiz questions.
- Configure whitelist entries if running the quiz flow.
- Configure screening rules in recruitment stage settings.
- Create interviewers.
- Create availability rules.
- Generate interview slots.
- Test one candidate application from apply through email notification.
- Test one assessment from start through submission.
- Test one interview booking.
- Review email logs for failed sends.

## Project Structure

```text
app.py                         Main Flask app, quiz routes, admin routes, app startup
config.py                      Seed quiz settings, questions, whitelist entries
db.py                          PostgreSQL connection pool
migrations.py                  Recruitment database migrations
blueprints/recruitment.py      Candidate recruitment routes
blueprints/admin_recruitment.py Admin recruitment routes
services/notifications.py      Gmail email templates and send logic
services/screening.py          Eligibility screening rules
services/upload.py             Cloudinary background upload jobs
services/meetings.py           Jitsi Meet link generation
jobs/slot_generator.py         Interview slot generation job
jobs/deadline_expiry.py        Candidate deadline expiry job
templates/                     HTML templates
static/                        CSS, JavaScript, icons, and logo
requirements.txt               Python dependencies
```

## Current Implementation Notes

- Gmail app password support is already wired through `GMAIL_APP_PASSWORD`.
- Email send attempts are logged in `email_log`.
- Meeting links currently use Jitsi Meet, which does not require a paid API key.
- The app uses background threads for upload and notification work.
- The app uses PostgreSQL as the source of truth.
- Time-sensitive recruitment calendar views use `Africa/Lagos` for month filtering.
- Keep `.env` local and private.
