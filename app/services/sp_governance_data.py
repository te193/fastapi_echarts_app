from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pymysql
from pymysql.cursors import DictCursor

from .sp_recommendation_data import serialize


ENTITY_LEVELS = {"site", "campaign", "ad_group", "msku"}
ENTITY_STATES = {"active", "enabled", "paused", "archived", "all"}
ACTION_TYPES = {"", "bid", "add", "negative", "manual_review"}
TARGETING_TYPES = {"", "auto", "manual", "__unknown__"}


def base_store_name(seller_name: Any, country_code: Any = "") -> str:
    """Return the shared store subject without consuming internal hyphens."""
    name = str(seller_name or "").strip()
    country = str(country_code or "").strip()
    if country:
        name = re.sub(rf"-{re.escape(country)}$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"-(?:eu|uk)$", "", name, flags=re.IGNORECASE)
    return name or str(seller_name or "").strip()


@dataclass
class GovernanceFilters:
    base_store: str = ""
    store: str = ""
    country: str = ""
    targeting_type: str = ""
    entity_state: str = "active"
    action_type: str = ""
    keyword: str = ""
    profile_id: int | None = None
    campaign_id: int | None = None
    ad_group_id: int | None = None
    level: str = "campaign"

    def __init__(self, values: Mapping[str, Any] | None = None):
        source = values or {}
        self.base_store = str(source.get("base_store") or "").strip()
        self.store = str(source.get("store") or "").strip()
        self.country = str(source.get("country") or "").strip().upper()
        self.targeting_type = str(source.get("targeting_type") or "").strip().lower()
        self.entity_state = str(source.get("entity_state") or "active").strip().lower()
        self.action_type = str(source.get("action_type") or "").strip().lower()
        self.keyword = str(source.get("keyword") or "").strip()
        self.profile_id = _optional_int(source.get("profile_id"))
        self.campaign_id = _optional_int(source.get("campaign_id"))
        self.ad_group_id = _optional_int(source.get("ad_group_id"))
        self.level = str(source.get("level") or "campaign").strip().lower()
        if self.targeting_type not in TARGETING_TYPES:
            raise ValueError("不支持的广告投放方式")
        if self.entity_state not in ENTITY_STATES:
            raise ValueError("不支持的广告状态")
        if self.action_type not in ACTION_TYPES:
            raise ValueError("不支持的待办类型")
        if self.level not in ENTITY_LEVELS:
            raise ValueError("不支持的治理层级")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("广告对象ID必须为整数") from exc


def governance_where(filters: GovernanceFilters, alias: str = "") -> tuple[str, list[Any]]:
    prefix = f"{alias}." if alias else ""
    clauses = ["1=1"]
    params: list[Any] = []
    for column, value in (
        ("base_store_name", filters.base_store),
        ("seller_name", filters.store),
        ("country_code", filters.country),
    ):
        if value:
            clauses.append(f"{prefix}{column}=%s")
            params.append(value)
    if filters.targeting_type:
        if filters.targeting_type == "__unknown__":
            clauses.append(f"coalesce({prefix}targeting_type,'') not in ('auto','manual')")
        else:
            clauses.append(f"{prefix}targeting_type=%s")
            params.append(filters.targeting_type)
    state_column = f"{prefix}ad_group_state_current"
    if filters.entity_state == "active":
        clauses.append(f"{state_column} in ('enabled','paused')")
    elif filters.entity_state != "all":
        clauses.append(f"{state_column}=%s")
        params.append(filters.entity_state)
    action_column = {
        "bid": "bid_action_count",
        "add": "add_action_count",
        "negative": "negative_action_count",
        "manual_review": "manual_review_count",
    }.get(filters.action_type)
    if action_column:
        clauses.append(f"{prefix}{action_column}>0")
    for column, value in (
        ("profile_id", filters.profile_id),
        ("campaign_id", filters.campaign_id),
        ("ad_group_id", filters.ad_group_id),
    ):
        if value is not None:
            clauses.append(f"{prefix}{column}=%s")
            params.append(value)
    if filters.keyword:
        escaped = filters.keyword.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        clauses.append(
            f"(coalesce({prefix}campaign_name_current,'') like %s escape '!' "
            f"or coalesce({prefix}ad_group_name_current,'') like %s escape '!' "
            f"or coalesce({prefix}msku,'') like %s escape '!' "
            f"or coalesce({prefix}asin,'') like %s escape '!')"
        )
        params.extend([f"%{escaped}%"] * 4)
    return " and ".join(clauses), params


class SpGovernanceService:
    def __init__(self) -> None:
        config = configparser.ConfigParser()
        config.read(Path(__file__).resolve().parents[2] / "config" / "database.ini", encoding="utf-8")
        section = config["target"] if config.has_section("target") else {}
        import os

        self.host = os.getenv("DASHBOARD_DB_HOST", section.get("host", "127.0.0.1"))
        self.port = int(os.getenv("DASHBOARD_DB_PORT", section.get("port", "3306")))
        self.user = os.getenv("DASHBOARD_DB_USER", section.get("user", ""))
        self.password = os.getenv("DASHBOARD_DB_PASSWORD", section.get("password", ""))
        self.database = os.getenv("DASHBOARD_DB_NAME", section.get("database", "etl_datasync_test"))

    def connect(self):
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
        )

    @staticmethod
    def _batch(cur) -> dict[str, Any]:
        cur.execute(
            "select * from dashboard_sp_recommendation_batch "
            "where status='success' order by cutoff_date desc,batch_id desc limit 1"
        )
        batch = cur.fetchone()
        if not batch:
            raise LookupError("暂无已发布的广告治理数据")
        return batch

    def options(self) -> dict[str, Any]:
        with self.connect() as conn, conn.cursor() as cur:
            batch = self._batch(cur)
            cur.execute(
                "select distinct base_store_name from dashboard_sp_governance_ad_group_snapshot "
                "where batch_id=%s order by base_store_name limit 1000",
                (batch["batch_id"],),
            )
            stores = [row["base_store_name"] for row in cur.fetchall()]
            cur.execute(
                "select distinct seller_name,country_code from dashboard_sp_governance_ad_group_snapshot "
                "where batch_id=%s order by seller_name,country_code limit 2000",
                (batch["batch_id"],),
            )
            sites = cur.fetchall()
        return serialize({"batch": batch, "base_stores": stores, "sites": sites})

    def _filters_and_batch(self, values: Mapping[str, Any]) -> tuple[GovernanceFilters, dict[str, Any]]:
        filters = GovernanceFilters(values)
        with self.connect() as conn, conn.cursor() as cur:
            batch = self._batch(cur)
        return filters, batch

    def summary(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        clause, params = governance_where(filters, "g")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""select count(distinct g.campaign_id) campaign_count,count(*) ad_group_count,
                    count(distinct case when g.msku is not null then concat_ws('|',g.profile_id,g.msku) end) msku_count,
                    coalesce(sum(g.msku is null),0) unresolved_msku_ad_group_count,
                    coalesce(sum(g.actionable_flag),0) actionable_ad_group_count,
                    coalesce(sum(g.manual_review_count>0),0) manual_review_ad_group_count,
                    coalesce(sum(g.bid_increase_count),0) bid_increase_count,
                    coalesce(sum(g.bid_decrease_count),0) bid_decrease_count,
                    coalesce(sum(g.bid_action_count),0) bid_action_count,
                    coalesce(sum(g.add_action_count),0) add_action_count,
                    coalesce(sum(g.negative_action_count),0) negative_action_count
                    from dashboard_sp_governance_ad_group_snapshot g
                    where g.batch_id=%s and {clause} limit 1""",
                [batch["batch_id"], *params],
            )
            summary = cur.fetchone()
            cur.execute(
                f"""select coalesce(nullif(g.currency_code,''),'') currency_code,
                    coalesce(sum(g.cost),0) cost,coalesce(sum(g.sales),0) sales,
                    case when sum(g.sales)>0 then sum(g.cost)/sum(g.sales) end acos
                    from dashboard_sp_governance_ad_group_snapshot g
                    where g.batch_id=%s and {clause}
                    group by coalesce(nullif(g.currency_code,''),'') order by currency_code limit 30""",
                [batch["batch_id"], *params],
            )
            currency_totals = cur.fetchall()
        ad_groups = int(summary.get("ad_group_count") or 0)
        summary["actionable_rate"] = Decimal(str(summary.get("actionable_ad_group_count") or 0)) / Decimal(ad_groups) if ad_groups else None
        summary["currency_totals"] = currency_totals
        return serialize({"batch_id": batch["batch_id"], "summary": summary})

    def stores(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        clause, params = governance_where(filters, "g")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""select g.base_store_name,count(distinct concat_ws('|',g.seller_name,g.country_code)) site_count,
                    count(distinct g.campaign_id) campaign_count,count(*) ad_group_count,
                    count(distinct case when g.msku is not null then concat_ws('|',g.profile_id,g.msku) end) msku_count,
                    coalesce(sum(g.msku is null),0) unresolved_msku_ad_group_count,
                    coalesce(sum(g.actionable_flag),0) actionable_ad_group_count,
                    coalesce(sum(g.bid_action_count),0) bid_action_count,
                    coalesce(sum(g.add_action_count),0) add_action_count,
                    coalesce(sum(g.negative_action_count),0) negative_action_count,
                    coalesce(sum(g.bid_manual_review_count),0) bid_manual_review_count,
                    coalesce(sum(g.add_manual_review_count),0) add_manual_review_count,
                    coalesce(sum(g.negative_manual_review_count),0) negative_manual_review_count,
                    coalesce(sum(g.manual_review_count>0),0) manual_review_ad_group_count
                    from dashboard_sp_governance_ad_group_snapshot g
                    where g.batch_id=%s and {clause}
                    group by g.base_store_name
                    order by actionable_ad_group_count desc,ad_group_count desc,g.base_store_name limit 1000""",
                [batch["batch_id"], *params],
            )
            rows = cur.fetchall()
        return serialize({"batch_id": batch["batch_id"], "rows": rows})

    def entities(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        clause, params = governance_where(filters, "g")
        if filters.level == "site":
            group = "g.profile_id,g.seller_name,g.country_code,g.currency_code"
            select = "g.profile_id,g.seller_name,g.country_code,g.currency_code"
        elif filters.level == "campaign":
            group = "g.profile_id,g.seller_name,g.country_code,g.currency_code,g.campaign_id"
            select = (
                "g.profile_id,g.seller_name,g.country_code,g.currency_code,g.campaign_id,"
                "max(g.campaign_name_current) campaign_name_current,max(g.campaign_state_current) campaign_state_current,"
                "max(g.targeting_type) targeting_type"
            )
        elif filters.level == "ad_group":
            group = "g.profile_id,g.seller_name,g.country_code,g.currency_code,g.campaign_id,g.ad_group_id"
            select = (
                "g.profile_id,g.seller_name,g.country_code,g.currency_code,g.campaign_id,"
                "max(g.campaign_name_current) campaign_name_current,g.ad_group_id,"
                "max(g.ad_group_name_current) ad_group_name_current,max(g.ad_group_state_current) ad_group_state_current,"
                "max(g.targeting_type) targeting_type"
            )
        else:
            group = (
                "g.profile_id,g.seller_name,g.country_code,g.currency_code,"
                "coalesce(g.msku,''),coalesce(g.asin,''),g.msku_mapping_status"
            )
            select = (
                "g.profile_id,g.seller_name,g.country_code,g.currency_code,"
                "max(g.msku) msku,max(g.asin) asin,max(g.msku_mapping_status) msku_mapping_status,"
                "max(g.period_msku_count) period_msku_count,max(g.current_msku_count) current_msku_count,"
                "case when count(distinct g.targeting_type)=1 then max(g.targeting_type) else 'mixed' end targeting_type"
            )
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""select {select},count(distinct g.campaign_id) campaign_count,count(*) ad_group_count,
                    coalesce(sum(g.impressions),0) impressions,coalesce(sum(g.clicks),0) clicks,
                    coalesce(sum(g.cost),0) cost,coalesce(sum(g.orders),0) orders,
                    coalesce(sum(g.sales),0) sales,
                    case when sum(g.sales)>0 then sum(g.cost)/sum(g.sales) end acos,
                    coalesce(sum(g.actionable_flag),0) actionable_ad_group_count,
                    coalesce(sum(g.bid_increase_count),0) bid_increase_count,
                    coalesce(sum(g.bid_decrease_count),0) bid_decrease_count,
                    coalesce(sum(g.bid_action_count),0) bid_action_count,
                    coalesce(sum(g.add_action_count),0) add_action_count,
                    coalesce(sum(g.negative_action_count),0) negative_action_count,
                    coalesce(sum(g.bid_manual_review_count),0) bid_manual_review_count,
                    coalesce(sum(g.add_manual_review_count),0) add_manual_review_count,
                    coalesce(sum(g.negative_manual_review_count),0) negative_manual_review_count,
                    coalesce(sum(g.manual_review_count>0),0) manual_review_ad_group_count
                    from dashboard_sp_governance_ad_group_snapshot g
                    where g.batch_id=%s and {clause}
                    group by {group}
                    order by actionable_ad_group_count desc,ad_group_count desc limit 1000""",
                [batch["batch_id"], *params],
            )
            rows = cur.fetchall()
        return serialize({"batch_id": batch["batch_id"], "level": filters.level, "rows": rows})


sp_governance_service = SpGovernanceService()
