from app.services.label_hub_change_data import LabelHubChangeDataService
from app.services.label_hub_data import LabelHubDataService


DETAILS = [
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 101, "sub_label_name": "明星产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 102, "sub_label_name": "潜力产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 103, "sub_label_name": "瘦狗产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 104, "sub_label_name": "问题产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 2, "label_name": "生命周期", "sub_label_id": 201, "sub_label_name": "成长期", "mutual_exclusion": "互斥", "status": "已启用"},
]


def internal_row(msku, child, lifecycle=201, store="StoreA"):
    return {
        "country_category": "欧洲站", "store": store, "msku": msku,
        "_by_parent": {1: {child}, 2: {lifecycle}},
        "_by_parent_period": {1: {"30d": {child}}, 2: {"current": {lifecycle}}},
    }


def payload(selected, baseline, role_count, issue_count=0, canonical_breakdowns=None):
    children = [
        {"id": child, "unique_msku_count": role_count.get(child, 0)}
        for child in (101, 102, 103, 104)
    ]
    return {
        "parent_label_id": 1,
        "overview": [{"id": 1, "unique_msku_count": len({row["msku"] for row in baseline}), "children": children}],
        "issue_counts": {"all": len({row["msku"] for row in selected}), "problem_role": issue_count},
        "breakdowns": [{
            "source": "remote_label", "key": "parent_1", "parent_id": 1,
            "buckets": [{"id": child, "msku_count": role_count.get(child, 0)} for child in (101, 102, 103, 104)],
        }],
        "_comparison_rows": selected,
        "_baseline_rows": baseline,
        "_canonical_breakdown_mskus": canonical_breakdowns or {},
    }


class FakeHub:
    def __init__(self):
        self.real = LabelHubDataService.__new__(LabelHubDataService)

    def get_meta(self):
        return {"comparison": {"current_date": "2026-07-19", "previous_date": "2026-07-18", "gap_days": 1, "available": True}}

    def _cached_details(self):
        return DETAILS

    def _analysis_categories(self, details, stats):
        return self.real._analysis_categories(details, stats)

    def parse_conditions(self, value):
        return self.real.parse_conditions(value)


def test_changes_reconcile_sets_sources_matrix_and_role_reason():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    previous_baseline = [internal_row("A", 104), internal_row("B", 104), internal_row("D", 101)]
    current_baseline = [internal_row("A", 102), internal_row("B", 102), internal_row("C", 101)]
    service._day_payload = lambda day, filters: (
        payload([current_baseline[0], current_baseline[1]], current_baseline, {101: 1, 102: 2}, 0)
        if day == "2026-07-19"
        else payload([previous_baseline[0], previous_baseline[2]], previous_baseline, {101: 1, 104: 2}, 1)
    )
    service._fetch_evidence = lambda *args: {
        ("2026-07-18", "欧洲站", "StoreA", "A"): {"daily_sales": 0.8, "tag_gross_margin": 0.047, "remote_sub_label_id": 104, "evidence_status": "matched"},
        ("2026-07-19", "欧洲站", "StoreA", "A"): {"daily_sales": 1.3, "tag_gross_margin": 0.121, "remote_sub_label_id": 102, "evidence_status": "matched"},
    }

    result = service.get_changes(metric_period="30d", parent_label_id=1, transition_period="30d")

    assert result["summary"] == {"current": 2, "previous": 2, "added": 1, "removed": 1, "unchanged": 1, "changed": 1, "net": 0}
    assert result["summary"]["previous"] + result["summary"]["added"] - result["summary"]["removed"] == result["summary"]["current"]
    assert sum(item["count"] for item in result["transition_matrix"]["cells"]) == 4
    row_a = next(row for row in result["rows"] if row["msku"] == "A")
    assert row_a["change_type"] == "changed"
    assert row_a["previous_layer_label"] == "问题产品"
    assert row_a["current_layer_label"] == "潜力产品"
    assert row_a["fact_status"] == "标签事实可比"
    assert row_a["previous_unit_scope"]
    assert row_a["current_unit_scope"]
    assert set(row_a["metric_profile"]) == {"sales_trend", "daily_sales_band", "margin_band", "sales_amount", "order_gross_profit", "order_gross_margin", "data_status"}
    assert row_a["sales_role_reason_code"] == "both_cross"
    assert "日销 0.80 → 1.30" in row_a["sales_role_reason"]
    assert result["overview_deltas"][0]["children"][1]["delta"] == 2
    assert result["breakdown_deltas"][0]["buckets"][1]["delta"] == 2


def test_nonconsecutive_scope_and_invalid_change_type():
    service = LabelHubChangeDataService()
    hub = FakeHub()
    hub.get_meta = lambda: {"comparison": {"current_date": "2026-07-19", "previous_date": "2026-07-16", "gap_days": 3, "available": True}}
    service._hub = hub
    service._day_payload = lambda day, filters: payload([], [], {}, 0)
    service._fetch_evidence = lambda *args: {}

    result = service.get_changes(metric_period="30d", parent_label_id=1)
    assert result["scope"]["comparison_label"] == "较上次数据"
    assert result["scope"]["gap_days"] == 3

    try:
        service.get_changes(metric_period="30d", parent_label_id=1, change_type="bad")
    except ValueError as exc:
        assert "change_type" in str(exc)
    else:
        raise AssertionError("invalid change_type should fail")


def test_one_day_data_keeps_current_dashboard_available():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    service._hub.get_meta = lambda: {"comparison": {"current_date": "2026-07-19", "previous_date": "", "gap_days": 0, "available": False}}
    result = service.get_changes(metric_period="30d")
    assert result["available"] is False
    assert result["rows"] == []


def test_layer_change_reuses_canonical_card_bucket_instead_of_any_matching_unit():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    current_baseline = [internal_row("A", 104), internal_row("A", 102, store="StoreB"), internal_row("B", 104)]
    previous_baseline = [internal_row("A", 104), internal_row("A", 102, store="StoreB"), internal_row("B", 104), internal_row("C", 104)]
    service._day_payload = lambda day, filters: (
        payload(
            current_baseline,
            current_baseline,
            {102: 1, 104: 1},
            canonical_breakdowns={1: {"104": {"B"}}},
        )
        if day == "2026-07-19"
        else payload(
            previous_baseline,
            previous_baseline,
            {102: 1, 104: 2},
            canonical_breakdowns={1: {"104": {"B", "C"}}},
        )
    )
    service._fetch_evidence = lambda *args: {}

    result = service.get_changes(
        metric_period="30d",
        parent_label_id=2,
        layer_change_parent=1,
        layer_change_bucket=104,
    )

    assert result["summary"]["current"] == 1
    assert result["summary"]["previous"] == 2
    assert result["summary"]["removed"] == 1
    assert sum(item["count"] for item in result["layer_transitions"]["entered"]) == result["summary"]["added"]
    assert sum(item["count"] for item in result["layer_transitions"]["left"]) == result["summary"]["removed"]
    row_c = next(row for row in result["rows"] if row["msku"] == "C")
    assert row_c["previous_layer_label"] == "问题产品"
    assert row_c["current_layer_label"] == "未命中"
    assert row_c["fact_status"] == "本次无标签事实"
    assert row_c["previous_combination_conditions"] == [{
        "dimension": "销售角色",
        "value": "问题产品",
        "matched": True,
        "target": "问题产品",
    }]
    assert row_c["current_combination_conditions"][0]["value"] == "无标签事实"
    assert row_c["current_combination_conditions"][0]["matched"] is False
