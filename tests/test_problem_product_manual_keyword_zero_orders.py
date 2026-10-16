"""Zero-order manual keyword decisions use mature click counts only."""

import pytest

from scripts.problem_product_ad_rules import build_ad_action


@pytest.mark.parametrize(
    ("clicks", "expected_action", "expected_rate"),
    [
        (11, "观察", None),
        (12, "降低竞价", -0.10),
        (33, "降低竞价", -0.10),
        (34, "降低竞价", -0.15),
    ],
)
def test_zero_order_manual_keyword_uses_click_band_without_price_or_aov(
    clicks: int, expected_action: str, expected_rate: float | None
) -> None:
    decision = build_ad_action(
        {
            "path": "manual_keyword",
            "clicks": clicks,
            "orders": 0,
            "current_bid": 1.00,
            "cost": 0,
        }
    )

    assert decision["action"] == expected_action
    if expected_rate is not None:
        assert decision["change_rate"] == expected_rate


def test_missing_mature_orders_do_not_count_as_zero_orders() -> None:
    decision = build_ad_action(
        {"path": "manual_keyword", "clicks": 34, "orders": None, "current_bid": 1.00}
    )

    assert decision["action"] == "观察"
    assert any("订单" in reason for reason in decision["blocked_reasons"])
