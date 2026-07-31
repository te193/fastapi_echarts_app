from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

from .label_hub_data import label_hub_service


DIAGNOSTIC_PARENT_BY_SCOPE = {"global": 15, "country": 16}
COUNTRY_ROLE_DEFINITIONS = (
    ("star", "站点明星", frozenset({1601})),
    ("potential", "站点潜力", frozenset(range(1602, 1607))),
    ("dog", "站点瘦狗", frozenset(range(1607, 1614))),
    ("problem", "站点问题/异常", frozenset(range(1614, 1619))),
)


def _business_unit_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("country_category") or ""),
        str(row.get("store") or ""),
        str(row.get("msku") or ""),
    )


def _has_evidence(fact: dict[str, Any]) -> bool:
    if fact.get("evidence_available"):
        return True
    evidence = fact.get("evidence")
    if not isinstance(evidence, dict):
        return False
    return bool(evidence.get("metrics") or evidence.get("matched_rule"))


def build_diagnostic_payload(
    rows: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    previous_facts: list[dict[str, Any]],
    scope: str,
    period: str,
    previous_available: bool = True,
) -> dict[str, Any]:
    """Aggregate diagnostic facts without multiplying business metrics by country."""
    if scope not in DIAGNOSTIC_PARENT_BY_SCOPE:
        raise ValueError("diagnostic_scope 只能是 global 或 country")
    if period not in {"7d", "14d", "30d", "90d"}:
        raise ValueError("diagnostic_period 只能是 7d、14d、30d 或 90d")

    parent_id = DIAGNOSTIC_PARENT_BY_SCOPE[scope]
    row_by_unit = {_business_unit_key(row): row for row in rows}

    def retained(source: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            fact
            for fact in source
            if int(fact.get("label_id") or 0) // 100 == parent_id
            and str(fact.get("label_period") or "") == period
            and _business_unit_key(fact) in row_by_unit
        ]

    current = retained(facts)
    previous = retained(previous_facts)
    current_by_child: dict[int, list[dict[str, Any]]] = defaultdict(list)
    previous_by_child: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for fact in current:
        current_by_child[int(fact["label_id"])].append(fact)
    for fact in previous:
        previous_by_child[int(fact["label_id"])].append(fact)

    buckets = []
    for child_id, child_facts in sorted(current_by_child.items()):
        units = {_business_unit_key(fact) for fact in child_facts}
        metric_rows = [row_by_unit[unit] for unit in units]
        previous_count = (
            (
                len(previous_by_child[child_id])
                if scope == "country"
                else len({_business_unit_key(fact) for fact in previous_by_child[child_id]})
            )
            if previous_available
            else None
        )
        evidence_count = sum(_has_evidence(fact) for fact in child_facts)
        countries = {str(fact.get("country") or "") for fact in child_facts if fact.get("country")}
        business_unit_count = len(units)
        current_count = len(child_facts) if scope == "country" else business_unit_count
        buckets.append(
            {
                "parent_id": parent_id,
                "child_id": child_id,
                "label": str(child_facts[0].get("sub_label_name") or child_id),
                "business_unit_count": business_unit_count,
                "country_record_count": len(child_facts) if scope == "country" else 0,
                "country_count": len(countries),
                "ratio": round(business_unit_count / len(row_by_unit), 4) if row_by_unit else 0,
                "previous_count": previous_count,
                "delta": current_count - previous_count if previous_count is not None else None,
                "sales_amount": round(sum(row.get("sales_amount") or 0 for row in metric_rows), 2),
                "order_gross_profit": round(
                    sum(row.get("order_gross_profit") or 0 for row in metric_rows), 2
                ),
                "evidence_count": evidence_count,
                "evidence_coverage": round(evidence_count / len(child_facts), 4)
                if child_facts
                else 0,
                "selected": False,
            }
        )

    country_role_distribution = []
    if scope == "country":
        bucket_by_child = {int(item["child_id"]): item for item in buckets}
        country_record_count = len(current)
        for role_id, role_label, child_ids in COUNTRY_ROLE_DEFINITIONS:
            role_facts = [fact for fact in current if int(fact["label_id"]) in child_ids]
            previous_role_facts = [
                fact for fact in previous if int(fact["label_id"]) in child_ids
            ]
            units = {_business_unit_key(fact) for fact in role_facts}
            metric_rows = [row_by_unit[unit] for unit in units]
            evidence_count = sum(_has_evidence(fact) for fact in role_facts)
            current_count = len(role_facts)
            previous_count = len(previous_role_facts) if previous_available else None
            country_role_distribution.append(
                {
                    "role_id": role_id,
                    "label": role_label,
                    "country_record_count": current_count,
                    "business_unit_count": len(units),
                    "country_count": len(
                        {
                            str(fact.get("country") or "")
                            for fact in role_facts
                            if fact.get("country")
                        }
                    ),
                    "ratio": current_count / country_record_count if country_record_count else 0,
                    "previous_count": previous_count,
                    "delta": current_count - previous_count
                    if previous_count is not None
                    else None,
                    "sales_amount": round(
                        sum(row.get("sales_amount") or 0 for row in metric_rows), 2
                    ),
                    "order_gross_profit": round(
                        sum(row.get("order_gross_profit") or 0 for row in metric_rows), 2
                    ),
                    "evidence_count": evidence_count,
                    "evidence_coverage": round(evidence_count / current_count, 4)
                    if current_count
                    else 0,
                    "children": [
                        bucket_by_child[child_id]
                        for child_id in sorted(child_ids)
                        if child_id in bucket_by_child
                    ],
                }
            )

    incomplete_evidence_count = sum(len(items) - sum(_has_evidence(item) for item in items) for items in current_by_child.values())
    return {
        "scope": {
            "diagnostic_scope": scope,
            "diagnostic_period": period,
        },
        "buckets": buckets,
        "business_unit_count": len(row_by_unit),
        "country_record_count": len(current) if scope == "country" else 0,
        "country_role_distribution": country_role_distribution,
        "attention": {
            "largest_growth": max(
                buckets,
                key=lambda item: item["delta"] if item["delta"] is not None else float("-inf"),
                default={},
            ),
            "incomplete_evidence_count": incomplete_evidence_count,
            "widest_scope": max(
                buckets,
                key=lambda item: (item["country_count"], item["business_unit_count"]),
                default={},
            ),
        },
    }


def _without_parent_condition(value: str, parent_id: int) -> str:
    return ";".join(
        group
        for group in str(value or "").split(";")
        if group and group.partition(":")[0] != str(parent_id)
    )


class LabelHubDiagnosticsService:
    def __init__(self) -> None:
        self._label_hub = label_hub_service

    @staticmethod
    def _normalize_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for fact in facts:
            evidence = fact.get("evidence_json")
            if isinstance(evidence, str):
                try:
                    evidence = json.loads(evidence)
                except (TypeError, ValueError):
                    evidence = {}
            result.append({**fact, "evidence": evidence if isinstance(evidence, dict) else {}})
        return result

    def get_payload(self, **filters: Any) -> dict[str, Any]:
        scope = str(filters.pop("diagnostic_scope", "global") or "global")
        period = str(filters.pop("diagnostic_period", "30d") or "30d")
        if scope not in DIAGNOSTIC_PARENT_BY_SCOPE:
            raise ValueError("diagnostic_scope 只能是 global 或 country")
        parent_id = DIAGNOSTIC_PARENT_BY_SCOPE[scope]
        filters["conditions"] = _without_parent_condition(
            str(filters.get("conditions") or ""),
            parent_id,
        )
        filters.setdefault("compare_parent_id", 2)
        filters.setdefault("page", 1)
        filters.setdefault("page_size", 500)
        filters.setdefault("sort_field", "msku")
        filters.setdefault("sort_dir", "asc")

        meta = self._label_hub.get_meta()
        data_date = str(filters.get("data_date") or meta.get("default_data_date") or "")
        comparison = meta.get("comparison") or {}
        previous_date = str(comparison.get("previous_date") or "")
        current_rows = self._label_hub.get_diagnostic_base_rows(**filters)
        fact_filters = {
            "parent_id": parent_id,
            "country_category": str(filters.get("country_category") or "all"),
            "store": str(filters.get("store") or "all"),
            "keyword": str(filters.get("keyword") or ""),
            "label_period": period,
        }
        facts = self._normalize_facts(
            self._label_hub.get_diagnostic_facts(data_date=data_date, **fact_filters)
        )
        previous_available = bool(
            previous_date
            and self._label_hub.has_cached_diagnostic_facts(previous_date, parent_id)
        )
        previous_facts = (
            self._normalize_facts(
                self._label_hub.get_diagnostic_facts(
                    data_date=previous_date,
                    cached_only=True,
                    **fact_filters,
                )
            )
            if previous_available
            else []
        )
        payload = build_diagnostic_payload(
            rows=current_rows,
            facts=facts,
            previous_facts=previous_facts,
            scope=scope,
            period=period,
            previous_available=previous_available,
        )
        payload["scope"].update(
            {
                "current_date": data_date,
                "previous_date": previous_date,
                "comparison_available": previous_available,
            }
        )
        return payload


label_hub_diagnostics_service = LabelHubDiagnosticsService()
