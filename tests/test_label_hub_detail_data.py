import unittest

from app.services.label_hub_detail_data import LabelHubDetailDataService


ROWS = [
    {
        "country_category": "Europe",
        "store": "StoreA",
        "msku": "MSKU-1",
        "sales_role_code": "star",
        "sales_trend_code": "growing",
        "daily_sales_band_code": "gt5",
        "margin_band_code": "gt25",
        "sales_amount": 100,
        "daily_sales": 6,
        "order_gross_profit": 20,
        "conflict": True,
        "_metric_present": True,
        "labels": [{"parent_id": 1, "id": 101}, {"parent_id": 15, "id": 1501}],
    },
    {
        "country_category": "Europe",
        "store": "StoreB",
        "msku": "MSKU-1",
        "sales_role_code": "eliminate",
        "sales_trend_code": "declining",
        "daily_sales_band_code": "zero",
        "margin_band_code": "lt5",
        "sales_amount": 0,
        "daily_sales": 0,
        "order_gross_profit": -2,
        "conflict": False,
        "_metric_present": True,
        "labels": [{"parent_id": 1, "id": 102}, {"parent_id": 15, "id": 1508}],
    },
    {
        "country_category": "US",
        "store": "StoreA",
        "msku": "MSKU-2",
        "sales_role_code": "potential",
        "sales_trend_code": "stable",
        "daily_sales_band_code": "missing",
        "margin_band_code": "missing",
        "sales_amount": None,
        "daily_sales": None,
        "order_gross_profit": None,
        "conflict": False,
        "_metric_present": False,
        "labels": [
            {"parent_id": 1, "id": 101},
            {"parent_id": 2, "id": 201},
            {"parent_id": 15, "id": 1502},
        ],
    },
]


class LabelHubDetailDataTests(unittest.TestCase):
    def make_service(self, aliases=None):
        calls = []

        def rows_provider(**kwargs):
            calls.append(kwargs)
            return list(ROWS)

        service = LabelHubDetailDataService(
            business_row_provider=rows_provider,
            identifier_alias_provider=aliases or {},
        )
        return service, calls

    def test_identifiers_are_exact_case_insensitive_deduplicated_and_report_unknown(self):
        service, _ = self.make_service()

        payload = service.get_details(identifiers=["  msku-1 ", "MSKU-1", "", "unknown"])

        self.assertEqual(2, payload["total"])
        self.assertEqual(2, payload["identifier_resolution"]["input_count"])
        self.assertEqual(["msku-1"], payload["identifier_resolution"]["matched"])
        self.assertEqual(["unknown"], payload["identifier_resolution"]["unmatched"])
        self.assertNotIn("MSKU-2", {row["msku"] for row in payload["rows"]})

    def test_sku_alias_can_map_to_one_or_multiple_business_rows(self):
        service, _ = self.make_service({"SKU-ONE": ["MSKU-2"], "SKU-MANY": ["MSKU-1"]})

        one = service.get_details(identifiers=["sku-one"])
        many = service.get_details(identifiers=["sku-many"])

        self.assertEqual(["MSKU-2"], [row["msku"] for row in one["rows"]])
        self.assertEqual(2, many["total"])

    def test_rejects_more_than_one_hundred_unique_identifiers(self):
        service, _ = self.make_service()

        with self.assertRaisesRegex(ValueError, "100"):
            service.get_details(identifiers=[f"SKU-{index}" for index in range(101)])

    def test_multiselect_is_or_within_field_and_and_across_fields(self):
        service, _ = self.make_service()

        payload = service.get_details(
            country_categories=["Europe", "US"],
            stores=["StoreA"],
            sales_roles=["star", "potential"],
        )

        self.assertEqual({"MSKU-1", "MSKU-2"}, {row["msku"] for row in payload["rows"]})
        self.assertEqual({"StoreA"}, {row["store"] for row in payload["rows"]})

    def test_business_role_reason_multiselect_is_or_and_combines_with_role(self):
        service, _ = self.make_service()

        payload = service.get_details(
            sales_roles=["potential"],
            role_reason_ids=[1502, 1503],
        )

        self.assertEqual(["MSKU-2"], [row["msku"] for row in payload["rows"]])
        self.assertEqual([1502, 1503], payload["applied_filters"]["role_reason_ids"])

    def test_business_role_reason_reads_separate_real_diagnostic_labels(self):
        row = {
            **ROWS[2],
            "labels": [{"parent_id": 1, "id": 102}],
            "role_diagnostics": [{"parent_id": 15, "id": 1502}],
        }
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: [row],
        )

        payload = service.get_details(role_reason_ids=[1502])

        self.assertEqual(["MSKU-2"], [item["msku"] for item in payload["rows"]])

    def test_role_reason_ids_are_limited_to_the_current_detail_view(self):
        country_rows = [
            {
                "country": "DE",
                "country_category": "Europe",
                "store": "StoreA",
                "msku": "MSKU-1",
                "sku": "SKU-1",
                "labels": [{"parent_id": 16, "id": 1602}],
            }
        ]
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: ROWS,
            country_row_provider=lambda **kwargs: {
                "rows": country_rows,
                "metric_status": "available",
            },
        )

        with self.assertRaisesRegex(ValueError, "角色原因"):
            service.get_details(detail_view="business_unit", role_reason_ids=[1602])
        with self.assertRaisesRegex(ValueError, "角色原因"):
            service.get_details(detail_view="country", role_reason_ids=[1502])

    def test_country_role_reason_filters_parent_sixteen_labels(self):
        country_rows = [
            {
                "country": country,
                "country_category": "Europe",
                "store": "StoreA",
                "msku": "MSKU-1",
                "sku": f"SKU-{country}",
                "labels": [{"parent_id": 16, "id": reason_id}],
            }
            for country, reason_id in (("DE", 1602), ("FR", 1603))
        ]
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: [ROWS[0]],
            country_row_provider=lambda **kwargs: {
                "rows": country_rows,
                "metric_status": "available",
            },
        )

        payload = service.get_details(
            detail_view="country",
            role_reason_ids=[1603],
        )

        self.assertEqual(["FR"], [row["country"] for row in payload["rows"]])

    def test_country_stockout_operating_status_uses_country_member_keys(self):
        country_rows = [
            {
                "country": country,
                "country_category": "Europe",
                "store": "StoreA",
                "msku": "MSKU-1",
                "sku": f"SKU-{country}",
                "labels": [],
            }
            for country in ("DE", "FR")
        ]
        member_calls = []

        def member_provider(**kwargs):
            member_calls.append(kwargs)
            return {("Europe", "FR", "StoreA", "MSKU-1")}

        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: [ROWS[0]],
            country_row_provider=lambda **kwargs: {"rows": country_rows, "metric_status": "available"},
            country_stockout_role_provider=lambda **kwargs: [],
            stockout_operating_member_provider=member_provider,
        )

        payload = service.get_details(
            detail_view="country",
            stockout_operating_scope="country",
            stockout_operating_status_period="30d",
            stockout_operating_status="star",
            stockout_operating_trend="stable",
        )

        self.assertEqual(["FR"], [row["country"] for row in payload["rows"]])
        self.assertEqual("country", member_calls[0]["scope"])
        self.assertEqual("stable", member_calls[0]["trend_code"])

    def test_problems_support_any_and_all(self):
        service, _ = self.make_service()

        any_result = service.get_details(problems=["zero_sales", "negative_profit"], problem_mode="any")
        all_result = service.get_details(problems=["zero_sales", "negative_profit", "problem_role"], problem_mode="all")

        self.assertEqual(["StoreB"], [row["store"] for row in any_result["rows"]])
        self.assertEqual(["StoreB"], [row["store"] for row in all_result["rows"]])

    def test_countries_are_applied_state_but_ignored_for_business_view(self):
        service, _ = self.make_service()

        payload = service.get_details(countries=["DE"])

        self.assertEqual(3, payload["total"])
        self.assertEqual(["DE"], payload["applied_filters"]["countries"])

    def test_detail_scope_refines_global_scope_and_conditions_use_existing_syntax(self):
        service, calls = self.make_service()

        payload = service.get_details(
            country_category="Europe",
            store="all",
            country_categories=["US"],
            detail_conditions="1:101|102;2:201",
        )

        self.assertEqual("Europe", calls[0]["country_category"])
        self.assertEqual(0, payload["total"])

    def test_detail_conditions_support_existing_internal_parent_mapping(self):
        rows = [{"country_category": "Europe", "store": "StoreA", "msku": "A", "_by_parent": {1: {101}, 2: {201}}}]
        service = LabelHubDetailDataService(lambda **kwargs: rows)

        payload = service.get_details(detail_conditions="1:101;2:201")

        self.assertEqual(1, payload["total"])

    def test_stockout_before_role_filter_requires_current_stockout_and_selected_period(self):
        def row(msku, *, status_id, roles):
            return {
                "country_category": "Europe",
                "store": "StoreA",
                "msku": msku,
                "labels": [{"parent_id": 3, "id": status_id}],
                "stockout_before_roles": roles,
            }

        rows = [
            row(
                "A",
                status_id=304,
                roles=[{"id": 2001, "label": "明星产品", "period": "30d"}],
            ),
            row(
                "B",
                status_id=304,
                roles=[{"id": 2002, "label": "潜力产品", "period": "7d"}],
            ),
            row(
                "C",
                status_id=301,
                roles=[{"id": 2001, "label": "明星产品", "period": "30d"}],
            ),
        ]
        service = LabelHubDetailDataService(lambda **kwargs: rows)

        payload = service.get_details(
            current_stockout_only=True,
            stockout_before_role_period="30d",
            stockout_before_role_ids=[2001],
        )

        self.assertEqual(["A"], [item["msku"] for item in payload["rows"]])
        self.assertEqual("明星产品", payload["rows"][0]["stockout_before_role"])
        self.assertEqual("30d", payload["rows"][0]["stockout_before_role_period"])

    def test_current_stockout_defaults_evidence_period_to_30d(self):
        rows = [
            {
                "country_category": "Europe",
                "store": "StoreA",
                "msku": "A",
                "labels": [{"parent_id": 3, "id": 304}],
                "stockout_before_roles": [
                    {"id": 2001, "label": "明星产品", "period": "7d"},
                    {"id": 2002, "label": "潜力产品", "period": "30d"},
                ],
            },
        ]
        service = LabelHubDetailDataService(lambda **kwargs: rows)

        payload = service.get_details(current_stockout_only=True)

        self.assertEqual(1, payload["total"])
        self.assertEqual("潜力产品", payload["rows"][0]["stockout_before_role"])
        self.assertEqual(2002, payload["rows"][0]["stockout_before_role_id"])
        self.assertEqual("30d", payload["rows"][0]["stockout_before_role_period"])

    def test_selected_stockout_label_defaults_evidence_period_to_30d(self):
        rows = [
            {
                "country_category": "Europe",
                "store": "StoreA",
                "msku": "A",
                "labels": [{"parent_id": 3, "id": 304}],
                "stockout_before_roles": [
                    {"id": 2001, "label": "明星产品", "period": "30d"},
                ],
            },
        ]
        service = LabelHubDetailDataService(lambda **kwargs: rows)

        payload = service.get_details(conditions="3:304")

        self.assertEqual("明星产品", payload["rows"][0]["stockout_before_role"])
        self.assertEqual(2001, payload["rows"][0]["stockout_before_role_id"])
        self.assertEqual("30d", payload["rows"][0]["stockout_before_role_period"])

    def test_stockout_before_role_filter_rejects_invalid_period_and_role(self):
        service = LabelHubDetailDataService(lambda **kwargs: [])

        with self.assertRaisesRegex(ValueError, "周期"):
            service.get_details(stockout_before_role_period="current")
        with self.assertRaisesRegex(ValueError, "无效标签"):
            service.get_details(
                stockout_before_role_period="30d",
                stockout_before_role_ids=[2199],
            )
        with self.assertRaisesRegex(ValueError, "必须指定周期"):
            service.get_details(stockout_before_role_ids=[2001])

    def test_stockout_operating_status_filter_is_applied_by_the_business_provider(self):
        def provider(**kwargs):
            if (
                kwargs.get("stockout_operating_status_period") == "30d"
                and kwargs.get("stockout_operating_status") == "pre_oos_evidence_insufficient"
                and kwargs.get("stockout_insufficient_reason") == "history_data_insufficient"
            ):
                return [ROWS[0]]
            return ROWS

        service = LabelHubDetailDataService(provider)

        payload = service.get_details(
            stockout_operating_status_period="30d",
            stockout_operating_status="pre_oos_evidence_insufficient",
            stockout_insufficient_reason="history_data_insufficient",
        )

        self.assertEqual(["MSKU-1"], [row["msku"] for row in payload["rows"]])
        self.assertEqual("30d", payload["applied_filters"]["stockout_operating_status_period"])
        self.assertEqual(
            "pre_oos_evidence_insufficient",
            payload["applied_filters"]["stockout_operating_status"],
        )
        self.assertEqual(
            "history_data_insufficient",
            payload["applied_filters"]["stockout_insufficient_reason"],
        )

    def test_counts_precede_pagination_unique_msku_is_deduplicated_and_missing_sorts_last(self):
        rows = [
            {"country_category": "X", "store": f"S{i}", "msku": "A" if i < 2 else f"M{i}", "sales_amount": None if i == 0 else i}
            for i in range(21)
        ]
        service = LabelHubDetailDataService(lambda **kwargs: rows, {"SKU-A": {"mskus": ["A"], "country_unit_count": 4}})

        payload = service.get_details(page=1, page_size=20, sort_field="sales_amount", sort_dir="desc")

        self.assertEqual({"business_unit_count": 21, "country_unit_count": 0, "unique_msku_count": 20}, payload["counts"])
        self.assertEqual(21, payload["total"])
        self.assertEqual(2, payload["total_pages"])
        self.assertEqual(20, len(payload["rows"]))
        self.assertNotIn(None, [row["sales_amount"] for row in payload["rows"]])

    def test_export_rows_keep_filters_and_sort_but_ignore_pagination(self):
        rows = [
            {
                "country_category": "Europe",
                "store": f"S{index}",
                "msku": f"M{index}",
                "sales_amount": index,
            }
            for index in range(25)
        ]
        service = LabelHubDetailDataService(lambda **kwargs: rows)

        payload = service.get_export_rows(
            country_categories=["Europe"],
            page=2,
            page_size=20,
            sort_field="sales_amount",
            sort_dir="desc",
        )

        self.assertEqual(25, payload["total"])
        self.assertEqual(25, len(payload["rows"]))
        self.assertEqual(list(range(24, -1, -1)), [row["sales_amount"] for row in payload["rows"]])

    def test_missing_sort_values_are_last_for_ascending_and_descending(self):
        rows = [
            {"msku": "missing", "sales_amount": None},
            {"msku": "low", "sales_amount": 1},
            {"msku": "high", "sales_amount": 2},
        ]
        service = LabelHubDetailDataService(lambda **kwargs: rows)

        ascending = service.get_details(sort_field="sales_amount", sort_dir="asc")
        descending = service.get_details(sort_field="sales_amount", sort_dir="desc")

        self.assertEqual(["low", "high", "missing"], [row["msku"] for row in ascending["rows"]])
        self.assertEqual(["high", "low", "missing"], [row["msku"] for row in descending["rows"]])

    def test_invalid_business_sort_field_is_rejected_with_clear_chinese_error(self):
        service, _ = self.make_service()

        with self.assertRaisesRegex(ValueError, "排序字段"):
            service.get_details(sort_field="not_a_column")

    def test_missing_metrics_problem_is_not_inferred_when_metrics_are_unavailable(self):
        row = {"msku": "A", "_metric_present": False}
        unavailable = LabelHubDetailDataService(
            lambda **kwargs: {"rows": [row], "metric_status": "unavailable", "warnings": []}
        )
        available = LabelHubDetailDataService(
            lambda **kwargs: {"rows": [row], "metric_status": "available", "warnings": []}
        )
        no_snapshot = LabelHubDetailDataService(
            lambda **kwargs: {"rows": [row], "metric_status": "no_snapshot", "warnings": []}
        )

        self.assertEqual(0, unavailable.get_details(problems=["missing_metrics"])["total"])
        self.assertEqual(1, available.get_details(problems=["missing_metrics"])["total"])
        self.assertEqual(0, no_snapshot.get_details(problems=["missing_metrics"])["total"])

    def test_country_view_returns_every_country_for_a_sku_with_true_country_metrics(self):
        country_rows = [
            {
                "country": "德国", "country_category": "欧洲站", "store": "StoreA",
                "msku": "MSKU-1", "sku": "SKU-1", "sales_amount": 120,
                "order_gross_profit": 24, "_metric_present": True,
            },
            {
                "country": "法国", "country_category": "欧洲站", "store": "StoreA",
                "msku": "MSKU-1", "sku": "SKU-1", "sales_amount": 45,
                "order_gross_profit": 3, "_metric_present": True,
            },
        ]
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: [{**ROWS[0], "country_category": "欧洲站"}],
            country_row_provider=lambda **kwargs: {
                "rows": country_rows, "metric_status": "available", "warnings": []
            },
        )

        payload = service.get_details(detail_view="country", identifiers=[" sku-1 "])

        self.assertEqual(["德国", "法国"], [row["country"] for row in payload["rows"]])
        self.assertEqual([120, 45], [row["sales_amount"] for row in payload["rows"]])
        self.assertEqual(
            {"business_unit_count": 1, "country_unit_count": 2, "unique_msku_count": 1},
            payload["counts"],
        )

    def test_country_filter_only_applies_in_country_view_and_sku_resolves_business_units(self):
        country_rows = [
            {"country": "德国", "country_category": "Europe", "store": "StoreA", "msku": "MSKU-1", "sku": "SKU-1"},
            {"country": "法国", "country_category": "Europe", "store": "StoreB", "msku": "MSKU-1", "sku": "SKU-1"},
        ]
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: ROWS,
            country_row_provider=lambda **kwargs: {"rows": country_rows, "metric_status": "available"},
        )

        country = service.get_details(detail_view="country", identifiers=["SKU-1"], countries=["德国"])
        business = service.get_details(detail_view="business_unit", identifiers=["SKU-1"], countries=["德国"])

        self.assertEqual(["德国"], [row["country"] for row in country["rows"]])
        self.assertEqual({"StoreA", "StoreB"}, {row["store"] for row in business["rows"]})
        self.assertEqual(["德国"], business["applied_filters"]["countries"])

    def test_country_stockout_rows_use_parent_twenty_one_role_for_each_country(self):
        country_rows = [
            {"country": "法国", "country_category": "欧洲站", "store": "StoreA", "msku": "MSKU-1", "sku": "SKU-FR"},
            {"country": "德国", "country_category": "欧洲站", "store": "StoreA", "msku": "MSKU-1", "sku": "SKU-DE"},
        ]
        country_role_facts = [
            {"country": "法国", "country_category": "欧洲站", "store": "StoreA", "msku": "MSKU-1", "label_id": 2102, "label_period": "30d"},
            {"country": "德国", "country_category": "欧洲站", "store": "StoreA", "msku": "MSKU-1", "label_id": 2101, "label_period": "30d"},
        ]
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: [
                {"country_category": "欧洲站", "store": "StoreA", "msku": "MSKU-1", "labels": [{"parent_id": 3, "id": 304}]},
            ],
            country_row_provider=lambda **kwargs: {"rows": country_rows, "metric_status": "available"},
            country_stockout_role_provider=lambda **kwargs: country_role_facts,
        )

        payload = service.get_details(detail_view="country", detail_conditions="3:304")
        by_country = {row["country"]: row for row in payload["rows"]}

        self.assertEqual(2102, by_country["法国"]["stockout_before_role_id"])
        self.assertEqual("潜力产品", by_country["法国"]["stockout_before_role"])
        self.assertEqual(2101, by_country["德国"]["stockout_before_role_id"])
        self.assertEqual("明星产品", by_country["德国"]["stockout_before_role"])
        self.assertEqual("30d", by_country["法国"]["stockout_before_role_period"])
        self.assertEqual("country", by_country["法国"]["stockout_before_role_scope"])

    def test_country_metric_filters_fail_clearly_when_metric_source_is_unavailable(self):
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: [
                {"country_category": "欧洲站", "store": "S", "msku": "M"}
            ],
            country_row_provider=lambda **kwargs: {
                "rows": [{"country": "德国", "country_category": "欧洲站", "store": "S", "msku": "M", "sku": "K"}],
                "metric_status": "unavailable", "warnings": ["国家经营指标暂不可用"],
            },
        )

        kept = service.get_details(detail_view="country")
        with self.assertRaisesRegex(ValueError, "指标"):
            service.get_details(detail_view="country", problems=["negative_profit"])

        self.assertEqual(1, kept["total"])
        self.assertEqual("unavailable", kept["metric_status"])

    def test_country_ranking_bands_cover_boundaries_and_multiselect_is_or(self):
        ranked_rows = [
            {
                "country": chr(65 + index), "country_category": "Europe",
                "store": "StoreA", "msku": f"M-{index}", "sku": f"S-{index}",
                "ranking": ranking,
            }
            for index, ranking in enumerate((10, 11, 20, 21, 50, 51, 100, 101, None))
        ]
        business_rows = [
            {"country_category": row["country_category"], "store": row["store"], "msku": row["msku"]}
            for row in ranked_rows
        ]
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: business_rows,
            country_row_provider=lambda **kwargs: {
                "rows": ranked_rows, "metric_status": "available",
            },
        )

        payload = service.get_details(
            detail_view="country", ranking_bands=["11_20", "51_100"]
        )

        self.assertEqual({11, 20, 51, 100}, {row["ranking"] for row in payload["rows"]})
        self.assertEqual(["11_20", "51_100"], payload["applied_filters"]["ranking_bands"])

    def test_ranking_filter_is_retained_but_ignored_in_business_view(self):
        service, _ = self.make_service()

        payload = service.get_details(
            detail_view="business_unit", ranking_bands=["top10"]
        )

        self.assertEqual(3, payload["total"])
        self.assertEqual(["top10"], payload["applied_filters"]["ranking_bands"])

    def test_ranking_filter_rejects_invalid_band_and_unavailable_country_metrics(self):
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: ROWS,
            country_row_provider=lambda **kwargs: {
                "rows": [{"country": "DE", "country_category": "Europe", "store": "StoreA", "msku": "MSKU-1"}],
                "metric_status": "unavailable",
            },
        )

        with self.assertRaisesRegex(ValueError, "排名"):
            service.get_details(detail_view="country", ranking_bands=["bad"])
        with self.assertRaisesRegex(ValueError, "指标"):
            service.get_details(detail_view="country", ranking_bands=["missing"])

    def test_alias_provider_may_report_country_count_for_selected_identifier(self):
        service, _ = self.make_service({"SKU-ONE": {"mskus": ["MSKU-2"], "country_unit_count": 4}})

        payload = service.get_details(identifiers=["sku-one"])

        self.assertEqual(4, payload["counts"]["country_unit_count"])

    def test_plain_business_view_uses_lightweight_country_summary(self):
        country_calls = []
        summary_calls = []
        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: ROWS,
            country_row_provider=lambda **kwargs: country_calls.append(kwargs) or {"rows": []},
            country_summary_provider=lambda **kwargs: summary_calls.append(kwargs) or {"country_unit_count": 41},
        )

        payload = service.get_details(detail_view="business_unit")

        self.assertEqual(41, payload["counts"]["country_unit_count"])
        self.assertEqual(1, len(summary_calls))
        self.assertEqual([], country_calls)

    def test_business_rows_are_cached_across_detail_only_filters_and_pages(self):
        calls = []

        def provider(**kwargs):
            calls.append(kwargs)
            return ROWS

        service = LabelHubDetailDataService(provider)

        service.get_details(page=1, stores=["StoreA"])
        service.get_details(page=2, problems=["negative_profit"])

        self.assertEqual(1, len(calls))

    def test_country_rows_are_cached_across_detail_only_filters_and_pages(self):
        calls = []

        def country_provider(**kwargs):
            calls.append(kwargs)
            return {
                "rows": [
                    {
                        "country": "DE",
                        "country_category": "Europe",
                        "store": "StoreA",
                        "msku": "MSKU-1",
                        "sku": "SKU-1",
                    }
                ],
                "metric_status": "available",
            }

        service = LabelHubDetailDataService(
            business_row_provider=lambda **kwargs: ROWS,
            country_row_provider=country_provider,
        )

        service.get_details(detail_view="country", page=1, stores=["StoreA"])
        service.get_details(detail_view="country", page=2, problems=["negative_profit"])

        self.assertEqual(1, len(calls))


if __name__ == "__main__":
    unittest.main()
