from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pymysql


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def cell_column(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("a:si", NS):
                shared.append("".join((node.text or "") for node in item.findall(".//a:t", NS)))

        sheet_root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows: list[dict[str, str]] = []
        for row in sheet_root.findall(".//a:sheetData/a:row", NS):
            values: dict[str, str] = {}
            for cell in row.findall("a:c", NS):
                value_node = cell.find("a:v", NS)
                value = "" if value_node is None else value_node.text or ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                values[cell_column(cell.attrib.get("r", ""))] = value
            rows.append(values)
        return rows


def parse_month(value: str) -> int:
    match = re.search(r"\d+", value or "")
    if not match:
        raise ValueError(f"Invalid month value: {value!r}")
    month = int(match.group())
    if month < 1 or month > 12:
        raise ValueError(f"Month out of range: {value!r}")
    return month


def decimal_value(value: str) -> Decimal:
    return Decimal(str(value or "0").strip())


def connect():
    return pymysql.connect(
        host=os.getenv("DASHBOARD_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DASHBOARD_DB_PORT", "3306")),
        user=os.getenv("DASHBOARD_DB_USER", "lanuser"),
        password=os.getenv("DASHBOARD_DB_PASSWORD", "123456"),
        database=os.getenv("DASHBOARD_DB_NAME", "etl_datasync_test"),
        charset=os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
    )


def main() -> None:
    data_dir = Path("data")
    candidates = sorted(data_dir.glob("*目标*.xlsx"))
    if not candidates:
        raise SystemExit("No monthly goal xlsx found under data/")
    path = candidates[0]
    rows = read_xlsx_rows(path)
    records = []
    for row in rows[1:]:
        if not row.get("A"):
            continue
        month = parse_month(row["A"])
        records.append(
            {
                "goal_year": 2026,
                "goal_month": month,
                "month_start": date(2026, month, 1),
                "sales_goal": decimal_value(row.get("B", "0")) * Decimal("10000"),
                "margin_goal": decimal_value(row.get("C", "0")),
                "gross_profit_goal": decimal_value(row.get("D", "0")) * Decimal("10000"),
                "sales_volume_goal": decimal_value(row.get("E", "0")) * Decimal("10000"),
                "source_file": path.name,
            }
        )

    if len(records) != 12:
        raise SystemExit(f"Expected 12 monthly goal rows, got {len(records)}")

    create_sql = """
    create table if not exists dashboard_monthly_goal (
        goal_year int not null,
        goal_month tinyint not null,
        month_start date not null,
        sales_goal decimal(18,2) not null,
        margin_goal decimal(10,6) not null,
        gross_profit_goal decimal(18,2) not null,
        sales_volume_goal decimal(18,2) null,
        source_file varchar(255) null,
        created_at datetime not null default current_timestamp,
        updated_at datetime not null default current_timestamp on update current_timestamp,
        primary key (goal_year, goal_month),
        key idx_month_start (month_start)
    ) engine=InnoDB default charset=utf8mb4
    """
    insert_sql = """
    insert into dashboard_monthly_goal (
        goal_year, goal_month, month_start, sales_goal, margin_goal,
        gross_profit_goal, sales_volume_goal, source_file, created_at, updated_at
    ) values (
        %(goal_year)s, %(goal_month)s, %(month_start)s, %(sales_goal)s, %(margin_goal)s,
        %(gross_profit_goal)s, %(sales_volume_goal)s, %(source_file)s, now(), now()
    )
    on duplicate key update
        month_start = values(month_start),
        sales_goal = values(sales_goal),
        margin_goal = values(margin_goal),
        gross_profit_goal = values(gross_profit_goal),
        sales_volume_goal = values(sales_volume_goal),
        source_file = values(source_file),
        updated_at = now()
    """
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(create_sql)
            cursor.executemany(insert_sql, records)
        conn.commit()

    total_sales = sum(record["sales_goal"] for record in records)
    total_profit = sum(record["gross_profit_goal"] for record in records)
    print(f"Imported {len(records)} monthly goals from {path}")
    print(f"Annual sales goal: {total_sales:.2f}")
    print(f"Annual gross profit goal: {total_profit:.2f}")


if __name__ == "__main__":
    main()
