"""Deployment-owned brand profiles. Branding never selects a database or tenant."""
from dataclasses import dataclass, replace
import os
import re


@dataclass(frozen=True)
class Brand:
    key: str
    name: str
    company_name: str
    program_name: str
    tagline: str
    support_email: str
    primary: str
    accent: str
    dark: str
    tint: str
    logo: str
    icon: str
    storage_key: str
    meeting_prefix: str

    @property
    def portal_title(self):
        return f"{self.name} Recruitment Portal"


PROFILES = {
    "mainstreet": Brand(
        key="mainstreet", name="Mainstreet MFB", company_name="Mainstreet Microfinance Bank",
        program_name="Executive Trainee Program",
        tagline="Build a rewarding career. Make a difference in microfinance banking.",
        support_email="recruitment@mainstreetmfb.com",
        primary="#89268B", accent="#89268B", dark="#421943", tint="#F4EAF4",
        logo="images/mainstreet/logo.png", icon="images/mainstreet/favicon-32x32.png",
        storage_key="mainstreet-recruitment", meeting_prefix="MainstreetInterview",
    ),
    "generic": Brand(
        key="aptus", name="Aptus", company_name="Aptus",
        program_name="Career Opportunities",
        tagline="Find the fit.",
        support_email="careers@example.com",
        primary="#241E4E", accent="#0FA3A3", dark="#241E4E", tint="#F7F7F5",
        logo="images/generic/mark.svg", icon="images/generic/mark.svg",
        storage_key="aptus-recruitment", meeting_prefix="AptusInterview",
    ),
}
PROFILES["aptus"] = PROFILES["generic"]
def load_brand(environ=None):
    env = os.environ if environ is None else environ
    key = env.get("BRAND_PROFILE", "mainstreet").strip().lower()
    if key not in PROFILES:
        raise ValueError("BRAND_PROFILE must be mainstreet, aptus, or generic")
    updates = {}
    for variable, field in {
        "BRAND_NAME": "name", "BRAND_COMPANY_NAME": "company_name",
        "BRAND_PROGRAM_NAME": "program_name", "BRAND_TAGLINE": "tagline",
        "BRAND_SUPPORT_EMAIL": "support_email",
    }.items():
        if variable in env:
            value = env[variable].strip()
            if not value or len(value) > 180 or any(ord(c) < 32 for c in value):
                raise ValueError(f"{variable} must be a single line of 1–180 characters")
            updates[field] = value
    if "support_email" in updates and not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", updates["support_email"]):
        raise ValueError("BRAND_SUPPORT_EMAIL must be an email address")
    for variable, field in {"BRAND_PRIMARY": "primary", "BRAND_ACCENT": "accent", "BRAND_DARK": "dark", "BRAND_TINT": "tint"}.items():
        if variable in env:
            value = env[variable].strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError(f"{variable} must be a six-digit hex color")
            updates[field] = value
    return replace(PROFILES[key], **updates)


def install_branding(app):
    brand = load_brand()
    app.config["BRAND"] = brand

    @app.context_processor
    def brand_context():
        return {"brand": app.config["BRAND"]}

    @app.get("/site.webmanifest")
    def webmanifest():
        from flask import jsonify, url_for
        active = app.config["BRAND"]
        return jsonify({
            "name": active.portal_title, "short_name": active.name,
            "start_url": "/", "display": "standalone",
            "theme_color": active.primary, "background_color": "#F6F7F5",
            "icons": [{"src": url_for("static", filename=active.icon),
                       "sizes": "any" if active.icon.endswith(".svg") else "32x32",
                       "type": "image/svg+xml" if active.icon.endswith(".svg") else "image/png"}],
        })
