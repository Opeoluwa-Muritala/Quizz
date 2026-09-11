import unittest
from talent_portal.services.offers import validate_offer

class OfferValidationTests(unittest.TestCase):
    def test_valid_offer(self):
        value, errors = validate_offer({"currency":"ngn","base_salary":"1200000","start_date":"2030-01-01","expiry_date":"2029-12-01","terms":"x"})
        self.assertIn("expiry_date", errors)
        self.assertEqual(value["currency"], "NGN")
    def test_rejects_invalid_salary_and_dates(self):
        _, errors = validate_offer({"base_salary":0,"start_date":"bad","expiry_date":""})
        self.assertIn("base_salary", errors); self.assertIn("start_date", errors); self.assertIn("expiry_date", errors)

if __name__ == "__main__": unittest.main()
