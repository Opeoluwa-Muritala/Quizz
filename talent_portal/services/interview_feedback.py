"""Validation rules for admin interview scorecards."""

COMPETENCIES = (
    ("communication", "Communication"),
    ("problem_solving", "Problem solving"),
    ("role_knowledge", "Role knowledge"),
    ("collaboration", "Collaboration"),
    ("ownership", "Ownership"),
)
RECOMMENDATIONS = ("strong_hire", "hire", "no_decision", "do_not_hire")


def validate_feedback(payload):
    payload = payload or {}
    ratings = payload.get("ratings")
    errors = {}
    if not isinstance(ratings, dict):
        errors["ratings"] = "Rate every competency from 1 to 5."
        ratings = {}
    cleaned_ratings = {}
    for key, _label in COMPETENCIES:
        value = ratings.get(key)
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = None
        if value not in range(1, 6):
            errors[f"ratings.{key}"] = "Choose a rating from 1 to 5."
        else:
            cleaned_ratings[key] = value

    recommendation = str(payload.get("recommendation") or "").strip()
    if recommendation not in RECOMMENDATIONS:
        errors["recommendation"] = "Choose a valid recommendation."

    notes = str(payload.get("notes") or "").strip()
    if len(notes) > 2000:
        errors["notes"] = "Keep feedback to 2,000 characters or fewer."

    try:
        slot_id = int(payload.get("slot_id"))
        if slot_id < 1:
            raise ValueError
    except (TypeError, ValueError):
        errors["slot_id"] = "Select the completed interview slot."
        slot_id = None

    return {
        "ratings": cleaned_ratings,
        "recommendation": recommendation,
        "notes": notes,
        "slot_id": slot_id,
    }, errors
