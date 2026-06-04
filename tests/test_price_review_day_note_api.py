import unittest
from datetime import date
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class FakePriceReviewService:
    def __init__(self):
        self.saved = []

    def save_adjustment_day_note(self, adjust_date, note):
        if len(note.strip()) > 1000:
            raise ValueError("note must be 1000 characters or fewer")
        clean_note = note.strip()
        self.saved.append((adjust_date, clean_note))
        return clean_note


class PriceReviewDayNoteApiTests(unittest.TestCase):
    def setUp(self):
        self.service = FakePriceReviewService()

    def test_put_day_note_saves_note(self):
        with patch("app.main.price_review_service", self.service):
            response = main.api_price_adjustments_daily_note(
                "2026-06-03",
                main.AdjustmentDayNotePayload(note="  促销前统一下调  "),
            )

        self.assertEqual(response, {"date": "2026-06-03", "note": "促销前统一下调"})
        self.assertEqual(self.service.saved, [(date(2026, 6, 3), "促销前统一下调")])

    def test_put_day_note_rejects_invalid_date(self):
        with patch("app.main.price_review_service", self.service), self.assertRaises(HTTPException) as ctx:
            main.api_price_adjustments_daily_note(
                "not-a-date",
                main.AdjustmentDayNotePayload(note="调价原因"),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self.service.saved, [])

    def test_put_day_note_rejects_long_note(self):
        with patch("app.main.price_review_service", self.service), self.assertRaises(HTTPException) as ctx:
            main.api_price_adjustments_daily_note(
                "2026-06-03",
                main.AdjustmentDayNotePayload(note="x" * 1001),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self.service.saved, [])


if __name__ == "__main__":
    unittest.main()
