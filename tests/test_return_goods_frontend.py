from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_return_goods_snapshot_date_display_does_not_shift_to_next_day():
    script = (ROOT / "app" / "static" / "js" / "return_goods.js").read_text(encoding="utf-8")

    assert "function displayDateForSnapshot(snapshotDate)" in script
    assert "return snapshotDate || \"\";" in script
    assert "return addDays(snapshotDate, 1);" not in script
    assert "setSnapshotDateLabel(displayDateForSnapshot(state.snapshot_date));" in script
    assert 'data-snapshot-date="\' + snapshotDate + \'"' in script
    assert "总览、矩阵和明细均截至统计日 \" + (displayDateForSnapshot(payload.snapshot_date) || \"-\")" in script


def test_return_goods_detail_drawer_only_opens_from_explicit_controls():
    script = (ROOT / "app" / "static" / "js" / "return_goods.js").read_text(encoding="utf-8")

    assert "onRowClicked" not in script
    assert 'event.target.closest("[data-return-detail]")' in script
    assert 'data-return-detail="country"' in script
    assert 'data-return-detail="button"' in script


def test_return_goods_main_overview_includes_d21_followup_status():
    script = (ROOT / "app" / "static" / "js" / "return_goods.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "app" / "static" / "css" / "return_goods.css").read_text(encoding="utf-8")

    assert 'miniMetric("D21持续追踪", overview.followup_active_msku_count' in script
    assert ".return-goods-main-metrics > :first-child" in stylesheet


def test_severe_recovery_card_explains_recent_trend_rules():
    script = (ROOT / "app" / "static" / "js" / "return_goods.js").read_text(encoding="utf-8")

    assert "严重恢复不足与近期趋势" in script
    assert "最近连续3个自然日" in script
    assert "断货前21天平均日销的50%" in script
    assert "曾经连续3个自然日达到改善标准" in script
    assert "辅助趋势标签，不参与严重恢复不足MSKU的分类加总" in script


def test_return_goods_overview_cards_use_weighted_uniform_layout():
    stylesheet = (ROOT / "app" / "static" / "css" / "return_goods.css").read_text(encoding="utf-8")

    assert "minmax(250px, 1.08fr)" in stylesheet
    assert "minmax(270px, 1.12fr)" in stylesheet
    assert "height: 316px;" in stylesheet
    assert ".return-goods-command-card > .return-goods-followup-all" in stylesheet
    assert "@media (max-width: 1750px)" in stylesheet
