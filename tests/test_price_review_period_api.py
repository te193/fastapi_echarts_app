from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class RecordingPriceReviewService:
    def __init__(self):
        self.calls = []

    def get_overview_payload(self, **filters):
        self.calls.append(filters)
        return {"compare_days": filters["compare_days"]}


def test_operating_effect_api_defaults_to_three_days_and_keeps_explicit_periods():
    service = RecordingPriceReviewService()
    client = TestClient(main.app)

    with patch("app.main.price_review_service", service):
        default_response = client.get("/api/price-review/overview?adjust_date=2026-08-14")
        explicit_response = client.get(
            "/api/price-review/overview?adjust_date=2026-08-14&compare_days=7"
        )

    assert default_response.status_code == 200
    assert default_response.json()["compare_days"] == 3
    assert explicit_response.status_code == 200
    assert explicit_response.json()["compare_days"] == 7
    assert [call["compare_days"] for call in service.calls] == [3, 7]


def test_operating_effect_api_accepts_three_days_but_rejects_shorter_windows():
    service = RecordingPriceReviewService()
    client = TestClient(main.app)

    with patch("app.main.price_review_service", service):
        accepted = client.get(
            "/api/price-review/overview?adjust_date=2026-08-14&compare_days=3"
        )
        rejected = client.get(
            "/api/price-review/overview?adjust_date=2026-08-14&compare_days=2"
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 422
