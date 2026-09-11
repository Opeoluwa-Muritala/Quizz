"""Create a short-lived Playwright state through the app's normal admin login."""
import json
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()
base_url = "http://127.0.0.1:5000"
session = requests.Session()
page = session.get(f"{base_url}/admin/login", timeout=15)
page.raise_for_status()
match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
if not match:
    raise RuntimeError("CSRF token not found")
response = session.post(
    f"{base_url}/admin/login",
    json={
        "username": os.environ.get("ADMIN_USERNAME", "admin"),
        "password": os.environ["ADMIN_TOKEN"],
    },
    headers={"X-CSRF-Token": match.group(1)},
    timeout=30,
)
payload = response.json()
if not response.ok or not payload.get("success"):
    raise RuntimeError(payload.get("error", "Admin login failed"))
cookies = [
    {
        "name": cookie.name,
        "value": cookie.value,
        "domain": "127.0.0.1",
        "path": cookie.path or "/",
        "httpOnly": True,
        "secure": False,
        "sameSite": "Lax",
    }
    for cookie in session.cookies
]
state_path = os.path.join(os.environ["TEMP"], "aptus-stage1-state.json")
with open(state_path, "w", encoding="utf-8") as handle:
    json.dump({"cookies": cookies, "origins": []}, handle)
print(state_path)
