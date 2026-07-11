"""
Centralised email notification service.
All stage-transition emails go through send_notification().
Every attempt is logged to email_log.
Sends via Gmail SMTP using an App Password.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from db import DBConnection

load_dotenv()

GMAIL_USER     = os.environ.get("GMAIL_USER", "").strip()
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
FROM_EMAIL     = f"Mainstreet MFB HR <{GMAIL_USER}>"
APP_BASE_URL   = os.environ.get("APP_BASE_URL", "https://quizz-xi-two.vercel.app")


# ── Email template builder ────────────────────────────────────────────────────

def _build_email(name: str, event_type: str, data: dict, ref_token: str = None) -> tuple[str, str]:
    base_style = """
        font-family: 'IBM Plex Sans', Arial, sans-serif;
        color: #1a1a2e; max-width: 600px; margin: 0 auto; padding: 32px 24px;
    """
    header = f"""
        <div style="background:#1a1a2e;padding:20px 24px;border-radius:8px 8px 0 0">
          <span style="color:#fff;font-size:18px;font-weight:700;">Mainstreet MFB — Recruitment</span>
        </div>
    """

    bodies = {
        "application_submitted": (
            "Application Received – Executive Trainee Program",
            f"""<p>Dear {name},</p>
            <p>Thank you for applying to the <strong>Executive Trainee Program</strong>.
            We have received your application and will review it shortly.</p>
            <p>You will receive an email once your eligibility screening is complete.</p>"""
        ),
        "screening_passed": (
            "Application Shortlisted – Assessment Invitation",
            f"""<p>Dear {name},</p>
            <p>Congratulations! Your application has passed our initial screening.
            You are invited to take the <strong>online assessment</strong>.</p>
            <p><a href="{APP_BASE_URL}/dashboard" style="background:#1a1a2e;color:#fff;padding:12px 24px;
            border-radius:6px;text-decoration:none;display:inline-block;margin-top:12px;">
            Go to Your Dashboard</a></p>
            <p>The assessment is timed. Ensure you are in a quiet environment before starting.</p>"""
        ),
        "screening_failed": (
            "Application Status Update",
            f"""<p>Dear {name},</p>
            <p>Thank you for your interest in the Executive Trainee Program.
            After careful review, we are unable to proceed with your application at this time.</p>
            <p>We appreciate the time you invested and wish you the best in your career journey.</p>"""
        ),
        "screening_flagged": (
            "Application Under Review",
            f"""<p>Dear {name},</p>
            <p>Your application is currently under manual review. We will be in touch
            with an update within 2–3 business days.</p>"""
        ),
        "assessment_available": (
            "Your Assessment is Now Open",
            f"""<p>Dear {name},</p>
            <p>Your online assessment for the Executive Trainee Program is now available.
            Please log in to your dashboard to begin.</p>
            <p><a href="{APP_BASE_URL}/dashboard" style="background:#1a1a2e;color:#fff;padding:12px 24px;
            border-radius:6px;text-decoration:none;display:inline-block;margin-top:12px;">
            Start Assessment</a></p>
            <p>The assessment window closes on <strong>{data.get('closes_at', 'a scheduled date')}</strong>.
            Duration: <strong>{data.get('duration_minutes', 60)} minutes</strong>.</p>"""
        ),
        "assessment_passed": (
            "Assessment Result – Congratulations!",
            f"""<p>Dear {name},</p>
            <p>You have successfully passed the assessment stage.
            The next step is an <strong>interview</strong>.</p>
            <p>Please log in to your dashboard to schedule your interview slot.</p>
            <p><a href="{APP_BASE_URL}/schedule" style="background:#1a1a2e;color:#fff;padding:12px 24px;
            border-radius:6px;text-decoration:none;display:inline-block;margin-top:12px;">
            Schedule Interview</a></p>"""
        ),
        "assessment_failed": (
            "Assessment Result",
            f"""<p>Dear {name},</p>
            <p>Thank you for completing the assessment. Unfortunately, you did not meet the
            minimum score required to proceed to the next stage.</p>
            <p>We appreciate your effort and wish you the best in your future endeavours.</p>"""
        ),
        "interview_slot_available": (
            "Schedule Your Interview",
            f"""<p>Dear {name},</p>
            <p>Interview slots are now available for you to book. Please select a time
            that works for you before the deadline.</p>
            <p><a href="{APP_BASE_URL}/schedule" style="background:#1a1a2e;color:#fff;padding:12px 24px;
            border-radius:6px;text-decoration:none;display:inline-block;margin-top:12px;">
            Book Interview Slot</a></p>"""
        ),
        "interview_booked": (
            "Interview Confirmed",
            f"""<p>Dear {name},</p>
            <p>Your interview has been confirmed for
            <strong>{data.get('interview_time', 'the scheduled time')}</strong>.</p>
            <p>Meeting link: <a href="{data.get('meeting_link', '#')}">{data.get('meeting_link', 'See dashboard')}</a></p>
            <p>Please join 5 minutes early and ensure your camera and microphone are working.</p>
            <p><a href="{APP_BASE_URL}/dashboard" style="background:#1a1a2e;color:#fff;padding:12px 24px;
            border-radius:6px;text-decoration:none;display:inline-block;margin-top:12px;">
            View Dashboard</a></p>"""
        ),
        "interview_rescheduled": (
            "Interview Rescheduled",
            f"""<p>Dear {name},</p>
            <p>Your interview has been rescheduled to
            <strong>{data.get('interview_time', 'the new scheduled time')}</strong>.</p>
            <p>Meeting link: <a href="{data.get('meeting_link', '#')}">{data.get('meeting_link', 'See dashboard')}</a></p>
            <p>Please update your calendar and join 5 minutes early.</p>
            <p><a href="{APP_BASE_URL}/dashboard" style="background:#1a1a2e;color:#fff;padding:12px 24px;
            border-radius:6px;text-decoration:none;display:inline-block;margin-top:12px;">
            View Dashboard</a></p>"""
        ),
        "documents_required": (
            "Action Required – Upload Supporting Documents",
            f"""<p>Dear {name},</p>
            <p>Please upload the following documents to continue your application:</p>
            <ul>{''.join(f'<li>{d}</li>' for d in data.get('required_docs', ['Required documents']))}</ul>
            <p><a href="{APP_BASE_URL}/documents" style="background:#1a1a2e;color:#fff;padding:12px 24px;
            border-radius:6px;text-decoration:none;display:inline-block;margin-top:12px;">
            Upload Documents</a></p>
            <p>Deadline: <strong>{data.get('deadline', 'As soon as possible')}</strong></p>"""
        ),
        "offered": (
            "Congratulations – Offer of Employment",
            f"""<p>Dear {name},</p>
            <p>We are delighted to offer you a position in the
            <strong>Executive Trainee Program</strong> at Mainstreet Microfinance Bank.</p>
            <p>HR will be in touch shortly with your formal offer letter and next steps.</p>"""
        ),
        "rejected": (
            "Application Status – Final Decision",
            f"""<p>Dear {name},</p>
            <p>Thank you for participating in our recruitment process. After careful consideration,
            we are unable to offer you a position at this time.</p>
            <p>We wish you every success in your career.</p>"""
        ),
    }

    subject, body_content = bodies.get(
        event_type,
        ("Recruitment Update", f"<p>Dear {name},</p><p>Your application status has been updated.</p>")
    )

    html = f"""
    <!DOCTYPE html><html><body>
    <div style="{base_style}">
      {header}
      <div style="background:#f9f9fb;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e5e5ef">
        {body_content}
        <hr style="border:none;border-top:1px solid #e5e5ef;margin:24px 0">
        <p style="font-size:12px;color:#888">
          Mainstreet Microfinance Bank · Recruitment Team<br>
          This is an automated message – please do not reply directly.
        </p>
      </div>
    </div>
    </body></html>
    """
    if ref_token:
        for path in ["/dashboard", "/schedule", "/documents", "/assessment", "/interview"]:
            html = html.replace(f"{APP_BASE_URL}{path}", f"{APP_BASE_URL}{path}?ref={ref_token}")
            html = html.replace(f"{APP_BASE_URL}{path}/", f"{APP_BASE_URL}{path}?ref={ref_token}")
    return subject, html


# ── Public API ────────────────────────────────────────────────────────────────

def send_notification(candidate_id: int, stage: str, event_type: str,
                      extra_data: dict = None) -> tuple[bool, int | None]:
    """Send an email for a stage transition and log the attempt."""
    extra_data = extra_data or {}

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT full_name, email, ref_token FROM candidates WHERE id = %s", (candidate_id,))
            row = cur.fetchone()

    if not row:
        return False, None

    name, email, ref_token = row
    subject, html = _build_email(name, event_type, extra_data, ref_token)

    status = "sent"
    error_message = None

    if GMAIL_USER and GMAIL_PASSWORD:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = FROM_EMAIL
            msg["To"]      = email
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
                smtp.login(GMAIL_USER, GMAIL_PASSWORD)
                smtp.sendmail(GMAIL_USER, email, msg.as_string())
        except Exception as exc:
            status = "failed"
            error_message = str(exc)[:500]
    else:
        status = "skipped"
        error_message = "GMAIL_USER or GMAIL_APP_PASSWORD is not configured."
        print(f"[EMAIL] {event_type} → {email} | {subject}")

    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO email_log
                    (candidate_id, stage, event_type, recipient_email, status, error_message, template_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (candidate_id, stage, event_type, email, status, error_message, event_type))
            log_id = cur.fetchone()[0]
        conn.commit()

    return status == "sent", log_id


def resend_notification(log_id: int) -> tuple[bool, int | None]:
    """Resend a previously failed notification."""
    with DBConnection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT candidate_id, stage, event_type
                FROM email_log WHERE id = %s;
            """, (log_id,))
            row = cur.fetchone()

    if not row:
        return False, None

    candidate_id, stage, event_type = row
    return send_notification(candidate_id, stage, event_type)


def send_otp_email(email: str, otp: str) -> bool:
    base_style = """
        font-family: 'IBM Plex Sans', Arial, sans-serif;
        color: #1a1a2e; max-width: 600px; margin: 0 auto; padding: 32px 24px;
    """
    header = """
        <div style="background:#89268B;padding:20px 24px;border-radius:8px 8px 0 0">
          <span style="color:#fff;font-size:18px;font-weight:700;">Mainstreet MFB — Recruitment</span>
        </div>
    """
    html = f"""
    <!DOCTYPE html><html><body>
    <div style="{base_style}">
      {header}
      <div style="background:#f9f9fb;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e5e5ef">
        <p>Hello,</p>
        <p>Your one-time verification passcode for the Mainstreet Recruitment Portal is:</p>
        <div style="background:#f3e7f4;padding:16px;text-align:center;font-size:28px;font-weight:700;letter-spacing:4px;border-radius:6px;margin:20px 0;color:#89268B;border:1px solid #89268B;">
          {otp}
        </div>
        <p>This code is valid for 10 minutes. Please do not share it with anyone.</p>
        <hr style="border:none;border-top:1px solid #e5e5ef;margin:24px 0">
        <p style="font-size:12px;color:#888">
          Mainstreet Microfinance Bank · Recruitment Team<br>
          This is an automated message – please do not reply directly.
        </p>
      </div>
    </div>
    </body></html>
    """
    subject = "Your Verification Code - Mainstreet Recruitment Portal"
    status = "sent"

    if GMAIL_USER and GMAIL_PASSWORD:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = FROM_EMAIL
            msg["To"]      = email
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
                smtp.login(GMAIL_USER, GMAIL_PASSWORD)
                smtp.sendmail(GMAIL_USER, email, msg.as_string())
        except Exception as exc:
            status = "failed"
            print(f"[EMAIL ERROR] Failed to send OTP to {email}: {exc}")
    else:
        status = "skipped"
        print(f"\n==================================================")
        print(f"[OTP EMAIL] To: {email}")
        print(f"[OTP EMAIL] Code: {otp}")
        print(f"==================================================\n")

    return status == "sent"
