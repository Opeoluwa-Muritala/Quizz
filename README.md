# Mainstreet MFB Aptitude Test Portal

A Python Flask-based aptitude test platform for candidate registration, identity verification, timed exams, and administrative question management.

This repository includes:

- `app.py` — Flask application and API server
- `config.py` — seeded exam settings, question bank, and whitelist entries
- `requirements.txt` — Python dependencies
- `templates/` — candidate and admin HTML templates
- `static/` — JavaScript, CSS, and image assets

---

## Overview

The portal supports two main flows:

1. **Candidate exam workflow**
   - register with full name and email
   - whitelist verification and exam availability check
   - upload government ID and capture/upload a selfie
   - read instructions and take a timed, section-based exam
   - receive immediate pass/fail results and a downloadable certificate

2. **Admin dashboard**
   - secure login using an admin access token
   - control exam availability, timer, and pass mark
   - manage question bank with add/edit/delete/reorder capabilities
   - bulk import questions via JSON or CSV
   - manage whitelist email access
   - review candidate results and export CSV
   - preview verification images from Cloudinary

---

## Features

- Flask backend with PostgreSQL persistence
- Cloudinary-based image upload for selfie and ID storage
- Candidate session protection for exam endpoints
- Exam open/close toggle and pass mark configuration
- Active question bank with numerical, verbal, and logical sections
- Timed single-pass exam; unanswered questions are marked incorrect
- Tab-switch detection and tracking in exam sessions
- CSV export of results from the admin dashboard
- Automatic database table creation and seeding on first run

---

## Prerequisites

- Python 3.11+ installed
- PostgreSQL server available
- Cloudinary account
- Recommended: a virtual environment for Python dependencies

---

## Installation

1. Open a terminal in the project root.
2. Create and activate a virtual environment:

```bash
python -m venv .venv
.\.venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with the following variables:

```env
FLASK_SECRET_KEY=your-secret-key
NEON_DATABASE_URL=postgresql://user:password@host:port/database
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
ADMIN_TOKEN=your-admin-token
```

Notes:

- `FLASK_SECRET_KEY` is used to secure session cookies.
- `NEON_DATABASE_URL` must point to a working PostgreSQL database.
- If `ADMIN_TOKEN` is omitted, the default admin token is `admin123`.

---

## Running Locally

Start the application:

```bash
python app.py
```

Open in your browser:

- Candidate portal: `http://127.0.0.1:5000/`
- Admin dashboard: `http://127.0.0.1:5000/admin`

The app will initialize database tables and seed the question bank / whitelist on first launch.

---

## Production Deployment

For production, use a WSGI server such as Gunicorn and set `FLASK_DEBUG` to `False` if you add it manually.

Example:

```bash
gunicorn app:app --bind 0.0.0.0:5000
```

Ensure your environment variables are configured in the host environment and that the PostgreSQL and Cloudinary accounts are reachable from production.

---

## Configuration

### `config.py`

This file seeds database defaults when the server boots:

- `EXAM_TITLE` — exam display title
- `PASS_MARK_PERCENT` — default passing percentage
- `SECONDS_PER_QUESTION` — default timer per question
- `WHITELIST_SEEDS` — initial allowed candidate emails
- `QUESTIONS` — initial question bank

All seeded data is written only if the corresponding tables are empty.

---

## Candidate Flow

1. Visit `/`
2. Enter full name and registered email
3. The backend verifies:
   - exam is currently open
   - email exists in the whitelist
   - the candidate has not already submitted
4. Upload ID card image
5. Capture a live selfie or upload a selfie image
6. Read the exam instructions and begin the test
7. Answer questions in a forward-only timed sequence
8. Submit and receive a score, pass/fail result, and reference number

---

## Admin Flow

1. Visit `/admin`
2. Authenticate with the admin token
3. Manage settings, questions, whitelist, and candidate results
4. Use CSV export to download exam results

Admin routes are protected by a session flag and require the correct `ADMIN_TOKEN`.

---

## Backend API Endpoints

Candidate-facing endpoints:

- `POST /api/check-email` — validate registration email and exam availability
- `GET /api/exam-summary` — fetch current exam settings
- `POST /api/upload-photos` — upload selfie and ID to Cloudinary
- `GET /api/questions` — fetch active exam questions
- `POST /api/submit-results` — submit exam answers and store results

Admin endpoints:

- `GET/POST /api/admin/settings`
- `GET/POST /api/admin/questions`
- `PUT/DELETE /api/admin/questions/<id>`
- `POST /api/admin/questions/bulk`
- `POST /api/admin/questions/reorder`
- `GET/POST /api/admin/whitelist`
- `POST /api/admin/whitelist/bulk`
- `DELETE /api/admin/whitelist/<id>`
- `GET /api/admin/results`
- `GET /api/admin/export-csv`
- `GET /api/admin/image/<candidate_id>/<image_type>`

---

## Database Schema

The app manages these tables automatically:

- `candidates`
- `questions`
- `exam_results`
- `whitelist`
- `exam_settings`

The database schema is created and migrated on startup by `init_db()` in `app.py`.

---

## Notes & Best Practices

- Use a strong `ADMIN_TOKEN` before exposing `/admin` publicly.
- Keep `FLASK_SECRET_KEY` secret.
- Ensure Cloudinary credentials are valid; image uploads fail otherwise.
- The candidate exam uses session state, so browser cookies must be enabled.
- If remote Postgres requires SSL, include that in `NEON_DATABASE_URL`.

---

## Project Structure

- `app.py` — Flask server and API logic
- `config.py` — initial seeds and exam defaults
- `requirements.txt` — dependency list
- `templates/` — Flask HTML templates
- `static/` — frontend Javascript, CSS, and logo

---

## Contact

If you need help customizing the question set, adjusting the whitelist, or changing the exam logic, update `config.py` or ask for assistance.
