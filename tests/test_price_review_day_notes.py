import unittest
from datetime import date
from unittest.mock import patch

from app.services import price_review_data
from app.services.price_review_data import PriceReviewService


class FakeDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 6, 4)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        params = params or {}
        normalized = " ".join(sql.lower().split())
        self.connection.statements.append((normalized, dict(params)))

        if "max(dt_date)" in normalized:
            self._rows = [{"max_date": self.connection.latest_data_date}]
            return
        if "from price_review_adjustment_source" in normalized and "group by adjust_date" in normalized:
            self._rows = [
                {"adjust_date": item_date, "total": total}
                for item_date, total in self.connection.counts.items()
            ]
            return
        if "from price_review_adjustment_day_notes" in normalized and "adjust_date between" in normalized:
            self._rows = [
                {"adjust_date": item_date, "note": note}
                for item_date, note in self.connection.notes.items()
            ]
            return
        if normalized.startswith("insert into price_review_adjustment_day_notes"):
            self.connection.notes[params["adjust_date"]] = params["note"]
            self._rows = []
            return
        if normalized.startswith("delete from price_review_adjustment_day_notes"):
            self.connection.notes.pop(params["adjust_date"], None)
            self._rows = []
            return
        if normalized.startswith("create table if not exists price_review_adjustment_day_notes"):
            self.connection.ensure_called = True
            self._rows = []
            return
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self):
        self.latest_data_date = date(2026, 6, 4)
        self.counts = {
            date(2026, 6, 2): 70,
            date(2026, 6, 3): 980,
        }
        self.notes = {}
        self.statements = []
        self.ensure_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)


class PriceReviewDayNotesTests(unittest.TestCase):
    def setUp(self):
        self.service = PriceReviewService()
        self.connection = FakeConnection()
        self.service.connect = lambda: self.connection

    def test_daily_adjustment_counts_include_empty_note_by_default(self):
        with patch.object(price_review_data, "date", FakeDate):
            items = self.service.get_daily_adjustment_counts(days=3)

        by_date = {item["date"]: item for item in items}
        self.assertEqual(by_date["2026-06-02"]["count"], 70)
        self.assertEqual(by_date["2026-06-02"]["note"], "")
        self.assertEqual(by_date["2026-06-04"]["note"], "")

    def test_daily_adjustment_counts_include_saved_note_for_matching_date(self):
        self.connection.notes[date(2026, 6, 3)] = "促销前统一下调"

        with patch.object(price_review_data, "date", FakeDate):
            items = self.service.get_daily_adjustment_counts(days=3)

        by_date = {item["date"]: item for item in items}
        self.assertEqual(by_date["2026-06-03"]["note"], "促销前统一下调")
        self.assertEqual(by_date["2026-06-02"]["note"], "")

    def test_daily_adjustment_counts_can_load_all_history(self):
        self.connection.counts[date(2026, 4, 23)] = 7

        with patch.object(price_review_data, "date", FakeDate):
            items = self.service.get_daily_adjustment_counts(days=30, include_all=True)

        by_date = {item["date"]: item for item in items}
        self.assertEqual(by_date["2026-04-23"]["count"], 7)
        count_statements = [
            sql for sql, _ in self.connection.statements
            if "from price_review_adjustment_source" in sql and "group by adjust_date" in sql
        ]
        self.assertEqual(len(count_statements), 1)
        self.assertNotIn("where adjust_date between", count_statements[0])

    def test_save_day_note_trims_and_clears_empty_note(self):
        self.service.save_adjustment_day_note(date(2026, 6, 3), "  备货压力释放  ")
        self.assertTrue(self.connection.ensure_called)
        self.assertEqual(self.connection.notes[date(2026, 6, 3)], "备货压力释放")

        self.service.save_adjustment_day_note(date(2026, 6, 3), "   ")
        self.assertNotIn(date(2026, 6, 3), self.connection.notes)

    def test_save_day_note_rejects_long_note(self):
        with self.assertRaises(ValueError):
            self.service.save_adjustment_day_note(date(2026, 6, 3), "x" * 1001)


if __name__ == "__main__":
    unittest.main()
