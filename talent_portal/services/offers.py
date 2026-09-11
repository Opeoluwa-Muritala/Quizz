from datetime import date

OFFER_STATUSES = ("draft", "sent", "accepted", "declined", "negotiating", "withdrawn")
APPROVAL_STATUSES = ("draft", "pending_approval", "approved")


def validate_offer(payload):
    payload = payload or {}
    errors = {}
    currency = str(payload.get("currency") or "NGN").strip().upper()
    if len(currency) != 3 or not currency.isalpha(): errors["currency"] = "Use a three-letter currency code."
    salary_raw = payload.get("base_salary")
    try: salary = float(salary_raw)
    except (TypeError, ValueError): salary = 0
    if salary <= 0 or salary > 10_000_000_000: errors["base_salary"] = "Enter a valid positive salary."
    start_date = str(payload.get("start_date") or "").strip()
    expiry_date = str(payload.get("expiry_date") or "").strip()
    for key, value in (("start_date", start_date), ("expiry_date", expiry_date)):
        try: date.fromisoformat(value)
        except ValueError: errors[key] = "Use YYYY-MM-DD."
    if start_date and expiry_date:
        try:
            if date.fromisoformat(expiry_date) < date.fromisoformat(start_date): errors["expiry_date"] = "Expiry cannot be before the start date."
        except ValueError: pass
    terms = str(payload.get("terms") or "").strip()
    if len(terms) > 5000: errors["terms"] = "Keep terms to 5,000 characters or fewer."
    return {"currency": currency, "base_salary": salary, "start_date": start_date, "expiry_date": expiry_date, "terms": terms}, errors
