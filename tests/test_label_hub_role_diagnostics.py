from app.services.label_hub_role_diagnostics import LabelHubRoleDiagnosticService


def evidence(role, issue, target, daily_sales, margin, rank=None):
    metrics = {
        "daily_sales": daily_sales,
        "tag_margin_rate": margin,
    }
    if rank is not None:
        metrics["small_rank"] = rank
    return {
        "schema_version": "1.1",
        "rule_version": "v45",
        "source_sales_role": {"sub_label_name": role},
        "product_issue": {
            "label": issue,
            "benchmark_target": target,
            "metrics_used": metrics,
        },
    }


def test_builds_global_and_country_upgrade_diagnostics():
    rows = [
        {
            "parent_id": 15,
            "sub_label_id": 1502,
            "sub_label_name": "潜力产品-低毛利",
            "tag_rule": "销售角色=潜力产品",
            "country": None,
            "evidence_json": evidence(
                "潜力产品",
                "潜力产品-低毛利",
                "明星产品",
                54.0667,
                10.7905,
            ),
        },
        {
            "parent_id": 16,
            "sub_label_id": 1612,
            "sub_label_name": "瘦狗产品(站点)-低日销且排名不足",
            "tag_rule": "站点销售角色=瘦狗产品(站点)",
            "country": "英国",
            "evidence_json": evidence(
                "瘦狗产品(站点)",
                "瘦狗产品(站点)-低日销且排名不足",
                "站点潜力",
                0.5333,
                11.3185,
                1106.3667,
            ),
        },
        {
            "parent_id": 16,
            "sub_label_id": 1605,
            "sub_label_name": "潜力产品(站点)-低毛利且排名不足",
            "tag_rule": "站点销售角色=潜力产品(站点)",
            "country": "德国",
            "evidence_json": evidence(
                "潜力产品(站点)",
                "潜力产品(站点)-低毛利且排名不足",
                "站点明星",
                27.7,
                14.1155,
                63.6667,
            ),
        },
    ]
    service = LabelHubRoleDiagnosticService()
    service._fetch_rows = lambda **_: rows

    payload = service.get_payload(
        data_date="2026-07-29",
        country_category="欧洲站",
        store="HUAWTONG",
        msku="HW065a",
        diagnostic_period="30d",
    )

    global_diagnostic = payload["global_diagnostic"]
    assert global_diagnostic["current_role"] == "潜力产品"
    assert global_diagnostic["target_role"] == "明星产品"
    assert global_diagnostic["main_blocker"] == "毛利率"
    assert global_diagnostic["metrics"][0]["status"] == "met"
    assert global_diagnostic["metrics"][1]["target_display"] == "> 15%"
    assert global_diagnostic["metrics"][1]["gap_display"] == "还差 4.21pp"

    england = payload["country_diagnostics"][0]
    assert england["country"] == "英国"
    assert england["current_role"] == "瘦狗产品(站点)"
    assert england["target_role"] == "站点潜力"
    assert england["issue_label"] == "瘦狗产品(站点)-低日销且排名不足"
    assert [item["key"] for item in england["metrics"]] == [
        "daily_sales",
        "tag_margin_rate",
        "small_rank",
    ]
    assert england["metrics"][0]["gap_display"] == "还差 0.47"
    assert england["metrics"][1]["status"] == "met"
    assert england["metrics"][2]["gap_display"] == "需提升 1006.37 位"
    assert england["unmet_count"] == 2

    germany = payload["country_diagnostics"][1]
    assert germany["metrics"][1]["gap_display"] == "还差 0.88pp"
    assert germany["metrics"][2]["gap_display"] == "需提升 13.67 位"


def test_problem_role_keeps_missing_margin_honest():
    rows = [
        {
            "parent_id": 16,
            "sub_label_id": 1614,
            "sub_label_name": "问题产品(站点)-零动销",
            "tag_rule": "站点销售角色=问题产品(站点)，且日销<=0。",
            "country": "土耳其",
            "evidence_json": evidence(
                "问题产品(站点)",
                "问题产品(站点)-零动销",
                "退出问题产品",
                0,
                None,
                213.8,
            ),
        }
    ]
    service = LabelHubRoleDiagnosticService()
    service._fetch_rows = lambda **_: rows

    payload = service.get_payload(
        data_date="2026-07-29",
        country_category="欧洲站",
        store="HUAWTONG",
        msku="HW065a",
        diagnostic_period="30d",
    )

    country = payload["country_diagnostics"][0]
    assert country["metrics"][0]["target_display"] == "> 0"
    assert country["metrics"][0]["gap_display"] == "需恢复销售"
    assert country["metrics"][1]["status"] == "missing"
    assert country["metrics"][1]["gap_display"] == "恢复销售后再判断"
    assert country["metrics"][2]["status"] == "met"
    assert country["summary"] == "需恢复销售；毛利率恢复销售后再判断"


def test_reuses_one_identity_query_when_reopening_or_switching_periods():
    calls = []
    rows = [
        {
            "parent_id": 15,
            "sub_label_id": 1502,
            "sub_label_name": "潜力产品-低毛利",
            "tag_rule": "销售角色：潜力产品",
            "country": None,
            "label_period": "30d",
            "evidence_json": evidence(
                "潜力产品",
                "潜力产品-低毛利",
                "明星产品",
                54.0667,
                10.7905,
            ),
        },
        {
            "parent_id": 15,
            "sub_label_id": 1505,
            "sub_label_name": "瘦狗产品-低日销",
            "tag_rule": "销售角色：瘦狗产品",
            "country": None,
            "label_period": "14d",
            "evidence_json": evidence(
                "瘦狗产品",
                "瘦狗产品-低日销",
                "潜力产品",
                0.8,
                12,
            ),
        },
    ]
    service = LabelHubRoleDiagnosticService()

    def fetch_rows(**kwargs):
        calls.append(kwargs)
        return rows

    service._fetch_rows = fetch_rows
    identity = {
        "data_date": "2026-07-29",
        "country_category": "欧洲站",
        "store": "HUAWTONG",
        "msku": "HW065a",
    }

    thirty_days = service.get_payload(**identity, diagnostic_period="30d")
    fourteen_days = service.get_payload(**identity, diagnostic_period="14d")
    reopened = service.get_payload(**identity, diagnostic_period="30d")

    assert len(calls) == 1
    assert thirty_days["global_diagnostic"]["current_role"] == "潜力产品"
    assert fourteen_days["global_diagnostic"]["current_role"] == "瘦狗产品"
    assert reopened == thirty_days


def test_fetches_all_supported_periods_through_existing_label_index():
    executed = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, params):
            executed["sql"] = " ".join(sql.lower().split())
            executed["params"] = params

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

    class Dashboard:
        def connect(self, autocommit=False):
            assert autocommit is True
            return Connection()

    service = LabelHubRoleDiagnosticService(dashboard=Dashboard())
    service._fetch_rows(
        data_date="2026-07-29",
        country_category="欧洲站",
        store="HUAWTONG",
        msku="HW065a",
        diagnostic_period="30d",
    )

    assert "force index (idx_label_date)" in executed["sql"]
    assert "dashboard_label_fact_snapshot" in executed["sql"]
    assert "dashboard_label_detail_snapshot" in executed["sql"]
    assert "f.label_id between 1501 and 1618" in executed["sql"]
    assert "f.label_period in ('7d', '14d', '30d', '90d')" in executed["sql"]
    assert executed["params"] == (
        "2026-07-29",
        "欧洲站",
        "HUAWTONG",
        "HW065a",
    )
