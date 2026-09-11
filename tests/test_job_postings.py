import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("RUN_DB_MIGRATIONS", "false")
os.environ.setdefault("FLASK_SECRET_KEY", "stage-one-test-secret")

from talent_portal.application import app
from talent_portal.services.job_postings import EMPLOYMENT_TYPES, validate_job


def job_record(**overrides):
    record = {
        "id": 7, "title": "Operations Analyst", "department": "Operations",
        "location": "Lagos", "employment_type": "Full-time",
        "description": "Improve reliable day-to-day operations.",
        "requirements": "Clear communication\nStrong analytical skills",
        "status": "published", "display_status": "published", "version": 1,
        "application_deadline": datetime.now(timezone.utc) + timedelta(days=10),
        "deadline_input": "2030-01-01T12:00", "deadline_label": "01 Jan 2030, 12:00 WAT",
        "accepting": True,
    }
    record.update(overrides)
    return record


class FakeCursor:
    def __init__(self):
        self.rowcount = 1
        self.statements = []

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, statement, params=None): self.statements.append((statement, params))
    def fetchone(self): return (41,)


class FakeConnection:
    def __init__(self): self.cursor_instance = FakeCursor(); self.committed = False
    def cursor(self, *args, **kwargs): return self.cursor_instance
    def commit(self): self.committed = True


class FakeDBContext:
    def __init__(self, connection): self.connection = connection
    def __enter__(self): return self.connection
    def __exit__(self, *args): return False


class JobValidationTests(unittest.TestCase):
    def test_valid_job_normalizes_wat_deadline(self):
        cleaned, errors = validate_job({
            "title": " Analyst ", "department": "Risk", "location": "Lagos",
            "employment_type": EMPLOYMENT_TYPES[0], "description": "A clear role.",
            "requirements": "Attention to detail", "application_deadline": "2030-01-01T12:00",
        })
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["title"], "Analyst")
        self.assertIsNotNone(cleaned["application_deadline"].tzinfo)

    def test_required_fields_and_employment_type_are_allowlisted(self):
        _, errors = validate_job({"employment_type": "Permanent<script>"})
        self.assertIn("title", errors)
        self.assertIn("employment_type", errors)


class JobRouteTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY="stage-one-test-secret")
        self.client = app.test_client()

    def set_csrf(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "csrf-test-token"

    @patch("talent_portal.blueprints.job_postings.list_open_jobs")
    def test_public_listing_renders_only_service_results(self, list_jobs):
        list_jobs.return_value = [job_record()]
        response = self.client.get("/jobs")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Operations Analyst", response.data)

    @patch("talent_portal.blueprints.job_postings.get_job")
    def test_closed_job_is_not_public(self, get_job):
        get_job.return_value = job_record(status="closed", display_status="closed", accepting=False)
        self.assertEqual(self.client.get("/jobs/7").status_code, 404)

    @patch("talent_portal.application.require_admin", return_value=None)
    @patch("talent_portal.blueprints.job_postings.get_job")
    def test_admin_can_preview_draft(self, get_job, _require_admin):
        get_job.return_value = job_record(status="draft", display_status="draft", accepting=False)
        response = self.client.get("/admin/jobs/7/preview")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin preview", response.data)

    @patch("talent_portal.application.require_admin", return_value=None)
    def test_create_rejects_incomplete_job(self, _require_admin):
        self.set_csrf()
        response = self.client.post("/admin/jobs/new", data={"csrf_token":"csrf-test-token"})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"This field is required", response.data)

    @patch("talent_portal.application.require_admin", return_value=None)
    def test_create_persists_draft_and_redirects(self, _require_admin):
        self.set_csrf()
        connection = FakeConnection()
        payload = {
            "csrf_token":"csrf-test-token", "title":"Analyst", "department":"Risk",
            "location":"Lagos", "employment_type":"Full-time",
            "description":"Evaluate operational risk.", "requirements":"Analytical skills",
            "application_deadline":"",
        }
        with patch("talent_portal.blueprints.job_postings.DBConnection",
                   return_value=FakeDBContext(connection)):
            response = self.client.post("/admin/jobs/new", data=payload)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(connection.committed)
        self.assertIn("INSERT INTO job_postings", connection.cursor_instance.statements[0][0])

    @patch("talent_portal.blueprints.recruitment.get_job")
    def test_application_rejects_closed_job_before_candidate_write(self, get_job):
        self.set_csrf()
        get_job.return_value = job_record(status="closed", accepting=False)
        with patch("talent_portal.blueprints.recruitment.send_notification_async") as send_mail:
            response = self.client.post("/api/apply", json={
                "csrf_token":"csrf-test-token", "full_name":"Ada Candidate",
                "email":"ada@example.com", "phone_number":"08000000000",
                "house_address":"1 Example Street", "dob":"1998-01-01",
                "nysc_status":"completed", "job_id":7,
            })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "job_closed")
        send_mail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
