from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pymysql


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


EMPTY_BRAND_VALUES = {"", "#N/A", "N/A", "NULL", "None", "无", "-"}
XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


@dataclass(frozen=True)
class BrandRelation:
    raw_store_name: str
    store_name: str
    store_id: str | None
    brand_name: str
    brand_source: str
    is_replenish: str | None
    operator_name: str | None
    amazon_business_remark: str | None
    source_file: str


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_brand(value: object) -> str | None:
    text = clean_text(value)
    if text is None or text in EMPTY_BRAND_VALUES:
        return None
    return text


def normalize_store_name(value: object) -> str:
    text = clean_text(value) or ""
    return re.sub(r"-(?:eu|uk)$", "", text, flags=re.IGNORECASE)


def build_brand_relations(rows: list[dict[str, object]], source_file: str) -> list[BrandRelation]:
    relations: list[BrandRelation] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        raw_store_name = clean_text(row.get("店铺名"))
        store_name = normalize_store_name(raw_store_name)
        if not raw_store_name or not store_name:
            continue

        uk_brand = clean_brand(row.get("英标"))
        eu_brand = clean_brand(row.get("欧标"))
        if not uk_brand and not eu_brand:
            continue

        if uk_brand and eu_brand and uk_brand == eu_brand:
            brand_items = [(uk_brand, "英标欧标相同")]
        else:
            brand_items = []
            if uk_brand:
                brand_items.append((uk_brand, "英标"))
            if eu_brand:
                brand_items.append((eu_brand, "欧标"))

        for brand_name, brand_source in brand_items:
            key = (store_name, brand_name)
            if key in seen:
                continue
            seen.add(key)
            relations.append(
                BrandRelation(
                    raw_store_name=raw_store_name,
                    store_name=store_name,
                    store_id=clean_text(row.get("店铺ID")),
                    brand_name=brand_name,
                    brand_source=brand_source,
                    is_replenish=clean_text(row.get("是否补货")),
                    operator_name=clean_text(row.get("运营")),
                    amazon_business_remark=clean_text(row.get("亚马逊业务备注")),
                    source_file=source_file,
                )
            )
    return relations


def column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref)
    if not letters:
        raise ValueError(f"Invalid cell reference: {cell_ref}")
    index = 0
    for char in letters.group(0):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def worksheet_path(target: str) -> str:
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def read_xlsx_rows(path: Path, sheet_name: str | None = None) -> list[dict[str, object]]:
    with ZipFile(path) as archive:
        shared_strings = read_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        selected_sheet = None
        for sheet in workbook.findall(".//a:sheet", XLSX_NS):
            if sheet_name is None or sheet.attrib.get("name") == sheet_name:
                selected_sheet = sheet
                break
        if selected_sheet is None:
            raise RuntimeError(f"Sheet not found: {sheet_name}")

        rel_id = selected_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        root = ET.fromstring(archive.read(worksheet_path(relmap[rel_id])))
        raw_rows = [
            read_xlsx_row(row, shared_strings)
            for row in root.findall(".//a:sheetData/a:row", XLSX_NS)
        ]

    non_empty_rows = [row for row in raw_rows if any(clean_text(value) for value in row)]
    if not non_empty_rows:
        return []
    headers = [clean_text(value) or "" for value in non_empty_rows[0]]
    parsed_rows: list[dict[str, object]] = []
    for row in non_empty_rows[1:]:
        parsed_rows.append({header: row[index] if index < len(row) else None for index, header in enumerate(headers) if header})
    return parsed_rows


def read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//a:t", XLSX_NS))
        for item in root.findall("a:si", XLSX_NS)
    ]


def read_xlsx_row(row, shared_strings: list[str]) -> list[str | None]:
    values: list[str | None] = []
    for cell in row.findall("a:c", XLSX_NS):
        index = column_index(cell.attrib["r"])
        while len(values) <= index:
            values.append(None)
        values[index] = read_cell_value(cell, shared_strings)
    return values


def read_cell_value(cell, shared_strings: list[str]) -> str | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", XLSX_NS))
    value = cell.find("a:v", XLSX_NS)
    if value is None or value.text is None:
        return None
    raw_value = value.text
    if cell_type == "s":
        return shared_strings[int(raw_value)]
    return raw_value


def connect_target():
    return pymysql.connect(
        host=os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1")),
        port=int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306"))),
        user=os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", "")),
        password=os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        charset=os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def connect_source():
    return pymysql.connect(
        host=os.getenv("DASHBOARD_SOURCE_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DASHBOARD_SOURCE_DB_PORT", "3306")),
        user=os.getenv("DASHBOARD_SOURCE_DB_USER", ""),
        password=os.getenv("DASHBOARD_SOURCE_DB_PASSWORD", ""),
        charset=os.getenv("DASHBOARD_SOURCE_DB_CHARSET", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def ensure_preview_table(conn, schema: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(f"create schema if not exists `{schema}` default character set utf8mb4")
        cursor.execute(
            f"""
            create table if not exists `{schema}`.`store_brand_relation_import_preview` (
                raw_store_name varchar(255) not null,
                store_name varchar(255) not null,
                store_id varchar(255) null,
                brand_name varchar(255) not null,
                brand_source varchar(50) not null,
                is_replenish varchar(50) null,
                operator_name varchar(255) null,
                amazon_business_remark varchar(255) null,
                source_file varchar(255) not null,
                imported_at datetime not null,
                unique key uk_store_brand (store_name, brand_name)
            ) engine=InnoDB default charset=utf8mb4
            """
        )


def write_preview(conn, schema: str, relations: list[BrandRelation], imported_at: datetime) -> None:
    ensure_preview_table(conn, schema)
    rows = [preview_row(item, imported_at) for item in relations]
    with conn.cursor() as cursor:
        cursor.execute(f"delete from `{schema}`.`store_brand_relation_import_preview`")
        if rows:
            cursor.executemany(
                f"""
                insert into `{schema}`.`store_brand_relation_import_preview` (
                    raw_store_name, store_name, store_id, brand_name, brand_source,
                    is_replenish, operator_name, amazon_business_remark, source_file, imported_at
                ) values (
                    %(raw_store_name)s, %(store_name)s, %(store_id)s, %(brand_name)s, %(brand_source)s,
                    %(is_replenish)s, %(operator_name)s, %(amazon_business_remark)s, %(source_file)s, %(imported_at)s
                )
                """,
                rows,
            )


def preview_row(item: BrandRelation, imported_at: datetime) -> dict[str, object]:
    return {
        "raw_store_name": item.raw_store_name,
        "store_name": item.store_name,
        "store_id": item.store_id,
        "brand_name": item.brand_name,
        "brand_source": item.brand_source,
        "is_replenish": item.is_replenish,
        "operator_name": item.operator_name,
        "amazon_business_remark": item.amazon_business_remark,
        "source_file": item.source_file,
        "imported_at": imported_at,
    }


def fetch_formal_rows(conn) -> list[dict[str, object]]:
    with conn.cursor() as cursor:
        cursor.execute("select `店铺名`, `品牌名` from `opt_db`.`store_brand_relation`")
        return list(cursor.fetchall())


def print_diff(old_rows: list[dict[str, object]], relations: list[BrandRelation]) -> None:
    old_pairs = {(clean_text(row.get("店铺名")) or "", clean_text(row.get("品牌名")) or "") for row in old_rows}
    new_pairs = {(item.store_name, item.brand_name) for item in relations}
    added = sorted(new_pairs - old_pairs)
    removed = sorted(old_pairs - new_pairs)
    kept = sorted(new_pairs & old_pairs)
    split_stores = sorted(
        store
        for store in {store for store, _ in new_pairs}
        if sum(1 for candidate_store, _ in new_pairs if candidate_store == store) > 1
    )
    print(f"[diff] 新增={len(added)} 删除={len(removed)} 保持={len(kept)} 多品牌店铺={len(split_stores)}")
    for label, pairs in (("新增", added), ("删除", removed), ("多品牌店铺", [(store, "") for store in split_stores])):
        print(f"[diff:{label}]")
        for store, brand in pairs[:20]:
            print(f"  {store} / {brand}")
        if len(pairs) > 20:
            print(f"  ... {len(pairs) - 20} more")


def backup_formal_table(conn) -> str:
    backup_table = f"store_brand_relation_backup_{datetime.now():%Y%m%d_%H%M%S}"
    with conn.cursor() as cursor:
        cursor.execute(f"create table `opt_db`.`{backup_table}` as select * from `opt_db`.`store_brand_relation`")
    return f"opt_db.{backup_table}"


def rebuild_formal_table(conn, relations: list[BrandRelation]) -> None:
    rows = [
        {
            "store_name": item.store_name,
            "store_id": item.store_id,
            "brand_name": item.brand_name,
            "amazon_business_remark": item.amazon_business_remark,
            "is_replenish": item.is_replenish,
            "operator_name": item.operator_name,
        }
        for item in relations
    ]
    with conn.cursor() as cursor:
        cursor.execute("delete from `opt_db`.`store_brand_relation`")
        if rows:
            cursor.executemany(
                """
                insert into `opt_db`.`store_brand_relation` (
                    `店铺名`, `店铺ID`, `品牌名`, `亚马逊业务备注`, `是否补货`, `运营`
                ) values (
                    %(store_name)s, %(store_id)s, %(brand_name)s,
                    %(amazon_business_remark)s, %(is_replenish)s, %(operator_name)s
                )
                """,
                rows,
            )


def print_relation_summary(relations: list[BrandRelation]) -> None:
    same = sum(1 for item in relations if item.brand_source == "英标欧标相同")
    uk = sum(1 for item in relations if item.brand_source == "英标")
    eu = sum(1 for item in relations if item.brand_source == "欧标")
    stores = len({item.store_name for item in relations})
    print(f"[summary] 预览映射={len(relations)} 店铺={stores} 英标={uk} 欧标={eu} 英欧相同={same}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import store-brand relations from data/店铺综合信息.xlsx.")
    parser.add_argument("--excel", default=str(Path("data") / "店铺综合信息.xlsx"))
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--preview-schema", default="etl_datasync_replenishment_test")
    parser.add_argument("--apply-formal", action="store_true", help="Backup and rebuild opt_db.store_brand_relation.")
    parser.add_argument("--skip-preview", action="store_true", help="Do not write the local preview table.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    excel_path = Path(args.excel)
    rows = read_xlsx_rows(excel_path, args.sheet)
    relations = build_brand_relations(rows, source_file=excel_path.as_posix())
    imported_at = datetime.now()
    print_relation_summary(relations)

    if not args.skip_preview:
        target_conn = connect_target()
        try:
            write_preview(target_conn, args.preview_schema, relations, imported_at)
            target_conn.commit()
            print(f"[success] preview table refreshed: {args.preview_schema}.store_brand_relation_import_preview")
        except Exception:
            target_conn.rollback()
            raise
        finally:
            target_conn.close()

    source_conn = connect_source()
    try:
        old_rows = fetch_formal_rows(source_conn)
        print_diff(old_rows, relations)
        if args.apply_formal:
            backup_table = backup_formal_table(source_conn)
            rebuild_formal_table(source_conn, relations)
            source_conn.commit()
            print(f"[success] formal table rebuilt: opt_db.store_brand_relation rows={len(relations)}")
            print(f"[success] backup table: {backup_table}")
        else:
            print("[info] formal table not changed. Pass --apply-formal to rebuild opt_db.store_brand_relation.")
    except Exception:
        source_conn.rollback()
        raise
    finally:
        source_conn.close()


if __name__ == "__main__":
    main()
