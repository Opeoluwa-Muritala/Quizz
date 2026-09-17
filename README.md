# Aptus

Aptus is a Flask recruitment and assessment portal for managing job applications,
candidate screening, timed assessments, interviews, documents, and offers.
Candidates follow their progress from a personal dashboard; hiring teams manage
the pipeline from the admin workspace.

The repository supports Aptus and the original Mainstreet MFB brand profile.
Set `BRAND_PROFILE=aptus` to use Aptus. The code defaults to `mainstreet` when
that variable is omitted.

## Features

- **Job postings:** publish roles with departments, locations, employment types,
  requirements, and application deadlines.
- **Candidate applications:** collect applicant details, upload CVs, screen
  eligibility, and provide email OTP sign-in.
- **Assessments:** manage questions, quizzes, cohorts, and assignments; score
  timed attempts on the server and record tab switches.
- **Recruitment pipeline:** review candidate records, filter stages, update
  candidates individually or in bulk, and track stage history.
- **Interviews:** configure interviewers and availability, generate or create
  slots, book meetings, and record interview feedback.
- **Documents and offers:** review supporting documents, create versioned offers,
  and update offer status.
- **Reporting:** view candidate results and summary metrics, sort assessment
  scores, and export records.
- **Notifications:** send stage updates and login codes, with delivery logs and
  administrative resend controls.

## Local setup

Use Python 3.11 or newer and a PostgreSQL database. Cloudinary credentials are
needed for uploads, and a working email sender is needed for candidate OTP login.
Node.js is optional for development but required for the JavaScript syntax test.

Run these commands from the repository root.

### Install dependencies

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
source .venv/bin/activate
```

### Configure the environment

Create a local `.env` file. Replace the example values with your own configuration;
the application loads this file through `python-dotenv`.

```dotenv
BRAND_PROFILE=aptus
BRAND_SUPPORT_EMAIL=careers@example.com

NEON_DATABASE_URL=postgresql://user:password@host:5432/database
FLASK_SECRET_KEY=replace-with-a-long-random-secret
ADMIN_USERNAME=admin
ADMIN_TOKEN=replace-with-a-strong-admin-password
APP_BASE_URL=http://127.0.0.1:5000
JOB_SECRET=replace-with-a-separate-random-secret

CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

GMAIL_USER=your-sender@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password

DATABASE_POOL_MODE=persistent
DATABASE_POOL_MIN=1
DATABASE_POOL_MAX=2
RUN_DB_MIGRATIONS=false
DEMO_MODE=false
```

Keep real credentials in `.env` or your deployment platform's secret settings.
The repository ignores `.env` files.

| Variable | Behavior |
| --- | --- |
| `NEON_DATABASE_URL` | PostgreSQL connection string used by the application. |
| `FLASK_SECRET_KEY` | Stable signing key for sessions. Set explicitly across restarts and workers. |
| `ADMIN_USERNAME` | Admin login name; defaults to `admin`. |
| `ADMIN_PASSWORD_HASH` | Optional Werkzeug password hash; takes precedence over `ADMIN_TOKEN`. |
| `ADMIN_TOKEN` | Admin password fallback when no password hash is configured. Set explicitly. |
| `APP_BASE_URL` | Public application URL used in email links. |
| `JOB_SECRET` | Secret checked against the `X-Job-Secret` header on job requests. Set before exposing these endpoints. |
| `EMAIL_BASE_URL` | Optional HTTP email endpoint used if Gmail is unavailable or unconfigured. |
| `DATABASE_POOL_MODE` | Defaults to `persistent`; `serverless` opens connections without the persistent pool. |
| `DATABASE_POOL_MIN` / `DATABASE_POOL_MAX` | Persistent pool bounds. Defaults are 1 minimum, 2 maximum on Vercel, and 10 maximum elsewhere. |
| `DATABASE_CONNECT_TIMEOUT` | Connection timeout in seconds; defaults to 8 for persistent pooling and 5 otherwise. |
| `RUN_DB_MIGRATIONS` | Enables schema initialization during application import only when set to `true`. Defaults to `false`. |

### Initialize the database

For a new database or a schema update, enable migrations for one controlled
application import.

Windows PowerShell:

```powershell
$env:RUN_DB_MIGRATIONS = "true"
.\.venv\Scripts\python.exe -c "from app import app"
$env:RUN_DB_MIGRATIONS = "false"
```

macOS or Linux, with the virtual environment active:

```bash
RUN_DB_MIGRATIONS=true python -c "from app import app"
```

Initialization creates the core, recruitment, and job-posting schema. Inspect the
output for `[database bootstrap] Error`: bootstrap catches migration exceptions,
so a successful process exit alone does not establish that migrations succeeded.
Keep `RUN_DB_MIGRATIONS=false` for normal application workers.

### Start the app

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py
```

macOS or Linux, with the virtual environment active:

```bash
python app.py
```

Open [the local portal](http://127.0.0.1:5000) or
[admin sign-in](http://127.0.0.1:5000/admin/login).

## Branding and demo data

Brand profiles live in [talent_portal/branding.py](talent_portal/branding.py).
Supported values are `aptus`, `generic` (an Aptus alias), and `mainstreet`.

Deployment overrides include `BRAND_NAME`, `BRAND_COMPANY_NAME`,
`BRAND_PROGRAM_NAME`, `BRAND_TAGLINE`, and `BRAND_SUPPORT_EMAIL`.
Aptus UI changes must follow the palette and component rules in
[AGENTS.md](AGENTS.md).

Brand selection does not select a database or provide a general tenant boundary.
Configure the intended database explicitly for each deployment.

For an Aptus development database, initialize the schema first, then seed two
published jobs and four sample candidates from the repository root:

```powershell
$env:BRAND_PROFILE = "aptus"
.\.venv\Scripts\python.exe -m scripts.seed_aptus_demo
```

On macOS or Linux, use `BRAND_PROFILE=aptus python -m scripts.seed_aptus_demo`.
The seeder writes to the configured database and refuses a non-Aptus profile.
Keep demo records in a development or dedicated demo database.

Optional demo access uses `DEMO_MODE`, `DEMO_CANDIDATE_EMAILS`, and
`DEMO_ACCESS_CODE`. Demo admin credentials use `DEMO_ADMIN_USERNAME` and
`DEMO_ADMIN_PASSWORD_HASH` or `DEMO_ADMIN_TOKEN`. Configure these only for an
intentional demo deployment; seeding data does not configure login credentials.

## Main pages

| Audience | Route | Purpose |
| --- | --- | --- |
| Public | `/` | Recruitment landing page |
| Public | `/jobs` and `/jobs/<job_id>` | Open roles and job details |
| Candidate | `/apply` | Application form; accepts `?job_id=<id>` |
| Candidate | `/login` | Email OTP sign-in |
| Candidate | `/dashboard` | Application progress and available actions |
| Candidate | `/assessment` | Stage-controlled assessment |
| Candidate | `/schedule` and `/interview` | Interview booking and meeting details |
| Candidate | `/documents` | Supporting document uploads |
| Admin | `/admin/login` | Admin sign-in |
| Admin | `/admin` | Recruitment overview |
| Admin | `/admin/recruitment` | Candidate pipeline and recruitment operations |
| Admin | `/admin/jobs` | Job-posting management |
| Admin | `/admin/assessments` | Assessments and results |
| Admin | `/admin/settings` | Portal settings |

Candidate access depends on application state, configured stage windows, and
deadlines. The pipeline covers application, screening, assessment, interview
booking, document collection, and offer or rejection. Failed, flagged, and
expired states are recorded separately.

Admin sessions expire after 30 minutes of inactivity and allow at most two
active admin devices.

## Uploads and email

CVs and supporting documents use Cloudinary. The recruitment upload service
accepts PDF, JPG/JPEG, and PNG with a 3 MB final size limit. Images can be
compressed before storage. The candidate dashboard supports signed direct CV
uploads; background upload work is tracked in `upload_jobs`.

Candidate and admin preview routes check the active session. PDF delivery must
be enabled in Cloudinary for PDF previews; the code also supports legacy raw
assets through its preview handling.

Email delivery tries Gmail SMTP first, then `EMAIL_BASE_URL` when configured.
The HTTP service receives JSON containing `to`, `subject`, `text`, and `html`.
With neither sender configured, delivery is marked `skipped`. Stage notification
attempts are recorded in `email_log`.

Some upload and notification work runs in background threads. Verify completion
on the chosen host, especially when request workers have short lifetimes.

## Deployment and scheduled jobs

The stable WSGI entry point is `app:app`. On a Linux host with the dependencies
installed, run:

```bash
gunicorn app:app --bind 0.0.0.0:5000
```

Configure HTTPS, a public `APP_BASE_URL`, database and upload credentials, email
delivery, and explicit admin/session secrets. Run schema initialization as a
controlled step before normal workers serve traffic.

The application exposes these operational jobs:

| Method | Endpoint | Action |
| --- | --- | --- |
| `POST` | `/api/jobs/generate-slots` | Generate availability-rule and published-schedule slots |
| `POST` | `/api/jobs/expire-deadlines` | Move overdue candidates to expired stages |

An external scheduler must send `X-Job-Secret` matching `JOB_SECRET`.
The current startup code does not launch an in-process scheduler.

[vercel.json](vercel.json) declares daily schedules at `0 1 * * *` and
`0 2 * * *`, respectively. Those declarations alone do not establish working
job delivery: verify that the scheduler uses the required POST method and
authentication header, and check the endpoint responses.

Scheduling code uses `Africa/Lagos` for candidate-facing calendar logic and WAT
for interview time displays. Stage settings support opening and closing times,
relative deadlines, and assessment duration.

## Development

The frontend uses Jinja templates, CSS, and JavaScript without a separate
frontend build step. Read [AGENTS.md](AGENTS.md) before making UI changes;
[docs/frontend-design.md](docs/frontend-design.md) contains the design reference.

Run the existing tests from the repository root:

```powershell
$env:RUN_DB_MIGRATIONS = "false"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

On macOS or Linux, use
`RUN_DB_MIGRATIONS=false python -m unittest discover -s tests -v`.
Tests cover job-posting validation and routes, interview feedback, offer
validation, and recruitment inline-script parsing. The script parsing test skips
when Node.js is unavailable. These tests do not replace checks against live
database, email, and upload services.

### Commit messages

Use Conventional Commits:

```text
type(scope): short imperative description
```

Examples:

```text
feat(recruitment): add interview feedback
fix(admin): correct candidate result totals
refactor(scheduling): simplify slot selection
docs(readme): update setup and configuration
```

Use `feat` for new behavior, `fix` for corrections, `refactor` for restructuring,
`perf` for performance work, `docs` for documentation, `test` for tests,
`style` for styling or formatting, and `build`, `ci`, or `chore` for maintenance.
Describe the actual change rather than using messages such as "fix" or
"implemented." This is a contribution convention; no commit-message hook is
currently configured.

## Project structure

```text
app.py                              Flask, Gunicorn, and Vercel entry point
talent_portal/
  application.py                    App setup, quiz/admin routes, bootstrap
  branding.py                       Deployment brand profiles
  defaults.py                       Initial quiz settings and seed data
  db.py                             PostgreSQL connections and pooling
  migrations.py                     Recruitment schema migrations
  blueprints/
    recruitment.py                  Candidate recruitment routes
    admin_recruitment.py            Admin pipeline, feedback, and offers
    job_postings.py                  Public jobs and admin job management
  schema/job_postings.py            Job-posting schema initialization
  services/                         Screening, uploads, email, schedules, offers
  jobs/                             Slot generation and deadline expiry
  templates/                        Candidate, admin, shared, and error pages
  static/                           CSS, JavaScript, and brand assets
scripts/seed_aptus_demo.py           Aptus development/demo records
tests/                              Unit and route tests
docs/frontend-design.md             Design reference
AGENTS.md                           Repository design guardrails
requirements.txt                    Python dependencies
vercel.json                         Declared cron schedules
```
