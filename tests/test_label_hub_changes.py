from app.services.label_hub_change_data import LabelHubChangeDataService
from app.services.label_hub_data import LabelHubDataService


DETAILS = [
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 101, "sub_label_name": "明星产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 102, "sub_label_name": "潜力产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 103, "sub_label_name": "瘦狗产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 1, "label_name": "销售角色", "sub_label_id": 104, "sub_label_name": "问题产品", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 2, "label_name": "生命周期", "sub_label_id": 201, "sub_label_name": "成长期", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 2, "label_name": "生命周期", "sub_label_id": 203, "sub_label_name": "成长期", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 2, "label_name": "生命周期", "sub_label_id": 204, "sub_label_name": "成熟期", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 3, "label_name": "运营状态", "sub_label_id": 301, "sub_label_name": "正常在售", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 3, "label_name": "运营状态", "sub_label_id": 302, "sub_label_name": "停售", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 8, "label_name": "库存水平", "sub_label_id": 801, "sub_label_name": "低库存", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 8, "label_name": "库存水平", "sub_label_id": 802, "sub_label_name": "中库存", "mutual_exclusion": "互斥", "status": "已启用"},
    {"label_id": 8, "label_name": "库存水平", "sub_label_id": 803, "sub_label_name": "高库存", "mutual_exclusion": "互斥", "status": "已启用"},
]


def internal_row(msku, child, lifecycle=201, store="StoreA", country="欧洲站", operation=None):
    by_parent = {1: {child}, 2: {lifecycle}}
    by_parent_period = {1: {"30d": {child}}, 2: {"current": {lifecycle}}}
    if operation is not None:
        by_parent[3] = {operation}
        by_parent_period[3] = {"current": {operation}}
    return {
        "country_category": country, "store": store, "msku": msku,
        "_by_parent": by_parent,
        "_by_parent_period": by_parent_period,
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
        "_canonical_breakdown_units": canonical_breakdowns or {},
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

    assert result["summary"] == {"current": 2, "previous": 2, "added": 1, "removed": 1, "unchanged": 1, "changed": 1, "net": 0, "unique_msku_count": 3}
    assert result["summary"]["previous"] + result["summary"]["added"] - result["summary"]["removed"] == result["summary"]["current"]
    assert result["combination_summary"]["previous"] == result["summary"]["previous"]
    assert result["combination_summary"]["current"] == result["summary"]["current"]
    assert result["combination_summary"]["net"] == result["summary"]["net"]
    assert sum(item["count"] for item in result["combination_summary"]["reason_summary"]) == 3
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
    assert row_a["evidence_state"] == "confirmed"
    assert row_a["previous_evidence"]["daily_sales"] == 0.8
    assert row_a["current_evidence"]["margin_rate"] == 0.121
    assert "previous_metric_profile" in row_a
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
            canonical_breakdowns={1: {"104": {("欧洲站", "StoreA", "B")}}},
        )
        if day == "2026-07-19"
        else payload(
            previous_baseline,
            previous_baseline,
            {102: 1, 104: 2},
            canonical_breakdowns={1: {"104": {("欧洲站", "StoreA", "B"), ("欧洲站", "StoreA", "C")}}},
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
    transition = result["layer_transitions"]["left"][0]
    assert transition["main_reason"] == "记录消失"
    assert transition["evidence_counts"]["pending"] == 1
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


def test_layer_route_names_the_other_label_that_actually_changed():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    previous_baseline = [
        internal_row("A", 102, operation=301),
        internal_row("C", 102, operation=302),
    ]
    current_baseline = [
        internal_row("A", 102, operation=302),
        internal_row("C", 102, operation=301),
    ]
    canonical_units = {("欧洲站", "StoreA", "A"), ("欧洲站", "StoreA", "C")}
    service._day_payload = lambda day, filters: (
        payload(
            [current_baseline[1]],
            current_baseline,
            {102: 2},
            canonical_breakdowns={1: {"102": canonical_units}},
        )
        if day == "2026-07-19"
        else payload(
            [previous_baseline[0]],
            previous_baseline,
            {102: 2},
            canonical_breakdowns={1: {"102": canonical_units}},
        )
    )
    service._fetch_evidence = lambda *args: {}

    result = service.get_changes(
        metric_period="30d",
        parent_label_id=1,
        layer_change_parent=1,
        layer_change_bucket=102,
    )

    entered = result["layer_transitions"]["entered"][0]
    assert entered["previous_label"] == entered["current_label"] == "潜力产品"
    assert entered["changed_dimension"] == "运营状态"
    assert entered["changed_previous_label"] == "停售"
    assert entered["changed_current_label"] == "正常在售"
    left = result["layer_transitions"]["left"][0]
    assert left["changed_dimension"] == "运营状态"
    assert left["changed_previous_label"] == "正常在售"
    assert left["changed_current_label"] == "停售"

    filtered = service.get_changes(
        metric_period="30d",
        parent_label_id=1,
        layer_change_parent=1,
        layer_change_bucket=102,
        layer_transition_parent=3,
        layer_transition_previous="停售",
        layer_transition_current="正常在售",
    )
    assert filtered["total"] == 1
    assert filtered["rows"][0]["msku"] == "C"


def test_layer_route_detail_reuses_normalized_period_transition():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    unit = ("欧洲站", "StoreA", "A")
    previous = internal_row("A", 103)
    previous["_by_parent_period"][1] = {"30d": {102}, "7d": {103}}
    current = internal_row("A", 103)
    current["_by_parent_period"][1] = {"30d": {104}, "7d": {103}}

    service._day_payload = lambda day, filters: (
        payload(
            [current],
            [current],
            {104: 1},
            canonical_breakdowns={1: {"104": {unit}}},
        )
        if day == "2026-07-19"
        else payload(
            [],
            [previous],
            {102: 1},
            canonical_breakdowns={1: {"104": set()}},
        )
    )
    service._fetch_evidence = lambda *args: {}

    result = service.get_changes(
        metric_period="30d",
        parent_label_id=1,
        layer_change_parent=1,
        layer_change_bucket=104,
        layer_change_period="30d",
    )
    route = result["layer_transitions"]["entered"][0]
    assert route["previous_label"] == "潜力产品"
    assert route["current_label"] == "问题产品"
    assert route["count"] == 1

    filtered = service.get_changes(
        metric_period="30d",
        parent_label_id=1,
        layer_change_parent=1,
        layer_change_bucket=104,
        layer_change_period="30d",
        change_type="added",
        layer_transition_from=route["previous_label"],
        layer_transition_to=route["current_label"],
        layer_transition_parent=route["changed_parent_id"],
        layer_transition_previous=route["changed_previous_label"],
        layer_transition_current=route["changed_current_label"],
    )
    assert filtered["total"] == route["count"]
    assert filtered["rows"][0]["msku"] == "A"


def test_opposite_country_lifecycle_transitions_remain_two_business_units():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    previous_baseline = [
        internal_row("QL0052b", 101, lifecycle=203, store="QINGLEE", country="欧洲站"),
        internal_row("QL0052b", 101, lifecycle=204, store="QINGLEE", country="英国站"),
    ]
    current_baseline = [
        internal_row("QL0052b", 101, lifecycle=204, store="QINGLEE", country="欧洲站"),
        internal_row("QL0052b", 101, lifecycle=203, store="QINGLEE", country="英国站"),
    ]

    def day_payload(day, filters):
        rows = current_baseline if day == "2026-07-19" else previous_baseline
        result = payload(rows, rows, {101: 1})
        result["parent_label_id"] = 2
        return result

    service._day_payload = day_payload
    service._fetch_evidence = lambda *args: {}

    result = service.get_changes(metric_period="30d", parent_label_id=2)

    assert result["summary"]["changed"] == 2
    assert result["total"] == 2
    assert result["summary"]["unique_msku_count"] == 1
    directions = {
        (cell["row"], cell["column"]): cell["count"]
        for cell in result["transition_matrix"]["cells"]
        if cell["row"] != cell["column"]
    }
    assert directions == {("成长期", "成熟期"): 1, ("成熟期", "成长期"): 1}
    identities = {(row["country_category"], row["store"], row["msku"]) for row in result["rows"]}
    assert identities == {("欧洲站", "QINGLEE", "QL0052b"), ("英国站", "QINGLEE", "QL0052b")}
    assert {row["business_unit_count"] for row in result["rows"]} == {1}


def test_inventory_layer_uses_remote_inventory_rule_metric_instead_of_sales_role_metrics():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    unit = ("欧洲站", "StoreA", "A")
    previous = internal_row("A", 102)
    previous["_by_parent"][8] = {803}
    previous["_by_parent_period"][8] = {"current": {803}}
    current = internal_row("A", 102)
    current["_by_parent"][8] = {802}
    current["_by_parent_period"][8] = {"current": {802}}
    service._day_payload = lambda day, filters: (
        payload(
            [current],
            [current],
            {102: 1},
            canonical_breakdowns={8: {"802": {unit}, "803": set()}},
        )
        if day == "2026-07-19"
        else payload(
            [previous],
            [previous],
            {102: 1},
            canonical_breakdowns={8: {"802": set(), "803": {unit}}},
        )
    )
    service._fetch_evidence = lambda *args: {}
    service._fetch_remote_evidence = lambda *args: {
        ("2026-07-18", *unit): [{
            "sub_label_id": 803,
            "label_period": "current",
            "evidence": {
                "metrics": {"inventory_support_days": 64.5},
                "matched_rule": {"inventory_support_days": ">= 60"},
            },
        }],
        ("2026-07-19", *unit): [{
            "sub_label_id": 802,
            "label_period": "current",
            "evidence": {
                "metrics": {"inventory_support_days": 42.0},
                "matched_rule": {"inventory_support_days": "35–60"},
            },
        }],
    }

    result = service.get_changes(
        metric_period="30d",
        parent_label_id=8,
        layer_change_parent=8,
        layer_change_bucket=803,
        layer_change_period="current",
    )

    row = result["rows"][0]
    assert row["previous_layer_label"] == "高库存"
    assert row["current_layer_label"] == "中库存"
    assert row["sales_role_reason_code"] == "rule_metric_change"
    assert row["rule_metric_changes"] == [{
        "key": "inventory_support_days",
        "label": "库存可支撑天数",
        "previous": 64.5,
        "current": 42.0,
        "value_type": "days",
        "previous_rule": ">= 60",
        "current_rule": "35–60",
    }]
    assert row["previous_evidence"].get("daily_sales") is None


def test_sales_role_remote_evidence_prevents_false_missing_reason():
    service = LabelHubChangeDataService()
    service._hub = FakeHub()
    previous = internal_row("A", 103)
    current = internal_row("A", 101)
    unit = (previous["country_category"], previous["store"], previous["msku"])
    service._day_payload = lambda day, filters: (
        payload([current], [current], {101: 1})
        if day == "2026-07-19"
        else payload([previous], [previous], {103: 1})
    )
    service._fetch_evidence = lambda *args: {}
    service._fetch_remote_evidence = lambda *args: {
        ("2026-07-18", *unit): [{
            "sub_label_id": 103,
            "label_period": "30d",
            "evidence": {
                "metrics": {
                    "daily_sales": 0.8,
                    "tag_margin_rate": 33.0,
                },
                "matched_rule": {
                    "daily_sales": "< 1",
                    "tag_margin_rate": "> 25%",
                },
            },
        }],
        ("2026-07-19", *unit): [{
            "sub_label_id": 101,
            "label_period": "30d",
            "evidence": {
                "metrics": {
                    "daily_sales": 1.3,
                    "tag_margin_rate": 32.0,
                },
                "matched_rule": {
                    "daily_sales": "BETWEEN 1 AND 5",
                    "tag_margin_rate": "> 25%",
                },
            },
        }],
    }

    result = service.get_changes(
        metric_period="30d",
        parent_label_id=1,
        transition_period="30d",
    )

    row = result["rows"][0]
    assert row["sales_role_reason_code"] == "daily_cross"
    assert row["evidence_state"] == "confirmed"
    assert row["previous_evidence"]["status"] == "matched"
    assert row["current_evidence"]["status"] == "matched"


def test_remote_evidence_query_is_scoped_to_changed_business_units():
    executed = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params):
            executed["sql"] = sql
            executed["params"] = params

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

    class Hub(FakeHub):
        def _source_connection(self):
            return Connection()

    service = LabelHubChangeDataService()
    service._hub = Hub()
    units = {
        ("EU", "StoreA", "A"),
        ("UK", "StoreB", "B"),
    }

    service._fetch_remote_evidence(
        "2026-07-19",
        "2026-07-18",
        1,
        "30d",
        units,
    )

    assert "d.sub_label_id = f.label_id" not in executed["sql"]
    assert "f.label_id in" in executed["sql"].lower()
    assert "f.country_category = %(unit_cc_0)s" in executed["sql"]
    assert {executed["params"]["unit_msku_0"], executed["params"]["unit_msku_1"]} == {"A", "B"}
