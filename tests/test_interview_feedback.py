import unittest

from talent_portal.services.interview_feedback import validate_feedback


VALID = {
    "slot_id": 12,
    "ratings": {
        "communication": 4,
        "problem_solving": 5,
        "role_knowledge": 3,
        "collaboration": 4,
        "ownership": 4,
    },
    "recommendation": "hire",
    "notes": "Clear examples and thoughtful follow-up questions.",
}


class InterviewFeedbackValidationTests(unittest.TestCase):
    def test_accepts_complete_scorecard(self):
        cleaned, errors = validate_feedback(VALID)
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["ratings"]["problem_solving"], 5)
        self.assertEqual(cleaned["slot_id"], 12)

    def test_rejects_missing_rating_and_invalid_recommendation(self):
        payload = {**VALID, "ratings": {**VALID["ratings"], "ownership": 0}, "recommendation": "maybe"}
        _, errors = validate_feedback(payload)
        self.assertIn("ratings.ownership", errors)
        self.assertIn("recommendation", errors)

    def test_rejects_oversized_notes_and_missing_slot(self):
        _, errors = validate_feedback({**VALID, "slot_id": None, "notes": "x" * 2001})
        self.assertIn("slot_id", errors)
        self.assertIn("notes", errors)


if __name__ == "__main__":
    unittest.main()
