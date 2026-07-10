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
