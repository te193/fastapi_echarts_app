"""Generate an editable XMind map for the problem-product ad rules."""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path


OUTPUT = Path("docs/2026-09-14-问题产品广告调整规则思维导图.xmind")


def branch(title: str, *children: tuple) -> tuple:
    return title, list(children)


TREE = branch(
    "两组问题产品广告调整规则",
    branch(
        "固定产品范围（共 1,866 个）",
        branch("第一组：日销30天=0，且当前售价≤P15（1,037个）"),
        branch("第二组：0<日销<1，且毛利率<5%（829个）"),
        branch("两组按国家、店铺、MSKU 去重且互不重叠"),
    ),
    branch(
        "数据口径与安全边界",
        branch("竞价：当前成熟30天=每日 orders_7d、sales_7d、clicks、cost 汇总"),
        branch("趋势：前30天仅作趋势校验，不替代当前成熟30天"),
        branch("预算：成熟7天；活动当前日预算为基数"),
        branch("状态与对象：国家+店铺+MSKU 精确关联；记录 ODS 读取时间"),
        branch("缺汇率、关键字段、映射或样本：不出可执行数值"),
    ),
    branch(
        "广告状态分流",
        branch("无 SP 商品对象 / 商品、广告组、活动未启用", branch("标签：待开启广告"), branch("动作：不出竞价、预算执行值")),
        branch("配置启用但不可投放", branch("标签：待排查投放状态"), branch("动作：不出执行值")),
        branch("多账号、ASIN 疑似匹配或归属不唯一", branch("标签：待核对")),
        branch("商品、广告组、活动均启用且可投放", branch("进入竞价、预算、加词否词试算")),
    ),
    branch(
        "竞价规则（优先级：暂停 > 维持 > 降价 > 提价 > 观察）",
        branch(
            "暂停",
            branch("点击≥50、销售额=0、花费≥20欧元等值", branch("暂停竞价对象")),
            branch("曝光=0、花费>0", branch("暂停竞价对象")),
        ),
        branch(
            "维持 / 待复核",
            branch("花费=0", branch("维持")),
            branch("销售额=0、点击<10、花费<5欧元等值", branch("维持")),
            branch("销售额>0、ACOS≤20%、未命中提价", branch("维持")),
            branch("证据、映射或汇率不足", branch("待复核，不自动调整")),
        ),
        branch(
            "降价：超 MaxBid",
            branch("当前竞价 > MaxBid×1.2，且 销售额=0 或 ACOS>20%"),
            branch("建议价=max(0.10，当前竞价×50%，MaxBid)"),
            branch("策略：向 MaxBid 修正；单次最多 -50%"),
        ),
        branch(
            "降价：高 ACOS",
            branch("命中：ACOS>20%（20/30/40/50%只决定进入，不是固定跌幅）"),
            branch("公式：基础降幅=20%÷当前30天ACOS-1"),
            branch("边界：单次最多 -50%；竞价不低于0.10"),
            branch("前30天ACOS≤20%", branch("计算结果减半")),
            branch("前30天无有效ACOS", branch("按当前30天算，标记趋势不足")),
        ),
        branch(
            "降价：零销售（不是固定跌幅）",
            branch("先判断暂停：点击≥50且销售额=0且花费≥20欧元等值，则暂停优先"),
            branch("进入条件：点击≥15，或花费≥15欧元等值；销售额=0"),
            branch("当前CPC=当前成熟30天花费÷点击"),
            branch("可承受CPC=20%×预计每单成交额×估计直接CVR"),
            branch("公式降幅=max(-50%，min(0，可承受CPC÷当前CPC-1))"),
            branch("可承受CPC≥当前CPC", branch("维持并复核相关性、Listing、投放设置")),
            branch(
                "证据强度安全阀（限制最大单次降幅）",
                branch("点击15–24，或仅花费门槛", branch("最多 -15%")),
                branch("点击25–39", branch("最多 -30%")),
                branch("点击≥40", branch("最多 -50%")),
                branch("最终建议价=max(0.10，当前竞价×（1+实际降幅）)"),
            ),
            branch(
                "估计直接CVR：严格证据顺序",
                branch("对象自身前30天：点击≥20且直接订单>0"),
                branch("同国家、同店、同MSKU：累计点击≥20且直接订单>0"),
                branch("同国家、同店、同ASIN：累计点击≥20且直接订单>0"),
                branch("同国家、同店、同品牌、同叶类目、售价70%–130%、同匹配组：有效对象≥5、累计点击≥100"),
                branch("同国家、同品牌、同叶类目、售价70%–130%、同匹配组：有效对象≥5、累计点击≥100"),
                branch("未满足任一层", branch("待复核，不输出数值")),
            ),
            branch("同行CVR=同行直接订单合计÷同行点击合计"),
            branch("预计每单成交额：优先目标产品当前 Listing 售价；否则同一严格层级同行客单价中位数"),
            branch("禁止：同国家+币种+匹配方式的宽泛同行自动出价"),
        ),
        branch(
            "提价",
            branch("前提：销售额>0 且 ACOS≤20%"),
            branch("Exact / Phrase：ACOS≤10%且直接CVR≥18%且点击≥50；或逐级放宽至 ACOS≤20%、CVR≥12%、点击≥2"),
            branch("Broad / Close / Complements：同类效率门槛；最低点击≥3"),
            branch("Loose / Substitutes / 未知：ACOS≤15%、CVR≥15%、点击≥30；或 ACOS≤20%、CVR≥12%、点击≥15"),
            branch("基础涨幅=(20%-当前ACOS)÷20%"),
            branch("建议价=min(当前竞价×(1+实际涨幅)，MaxBid)"),
            branch("边界：单次最多 +20%；前30天ACOS>20%则涨幅减半"),
        ),
        branch("最终约束：降价下限0.10；提价上限MaxBid；缺关键值不下发"),
    ),
    branch(
        "加词与否词",
        branch("共同前置：按 Profile、广告组、标准化搜索词去重；核对已有正向投放、否词、保护词"),
        branch("加词：有订单且ACOS≤15%且未正向投放→候选加词"),
        branch("加词：15%<ACOS≤20%且有订单→待复核；ACOS>20%或无订单→不加词"),
        branch("否词：点击≥100、订单=0、未保护、未否定→候选否词"),
        branch("品牌词、核心类目词、新品词或资料不足→否词待复核"),
        branch("同词出现加词与否词方向冲突→人工复核"),
    ),
    branch(
        "活动预算（同一活动只出一条建议）",
        branch(
            "准入（任一不满足则只分析不出新预算）",
            branch("连续启用≥10天且当前启用"),
            branch("成熟7天点击≥10、报表完整"),
            branch("近3天无预算、状态、广告对象改动"),
            branch("可还原历史7天预算；活动不含范围外产品"),
        ),
        branch("目标ACOS：新品≤14天 28%；成长15–30天 23%；成熟>30天 20%"),
        branch("零订单：成熟期成熟7天订单=0→暂停；新品/成长受启用≤20天、花费≤100元等值、点击<50保护则维持"),
        branch("降预算：按ACOS偏差最高档 -45/-35/-25/-15/-8%；未命中且CVR<5%为-12%，CTR<0.2%为-10%"),
        branch("加预算：ACOS低于目标且预算饱和，按档位 +5% 至 +35%"),
        branch("CVR修正：≥11%加5个百分点；8–11%加3；5–8不变；<5%减3 / 扩大降幅3"),
        branch("建议日预算=max(1，当前日预算×（1+最终调整幅度）)，1为活动原币种"),
        branch("竞价提价只提示联动待复核，不叠加预算涨幅"),
    ),
    branch(
        "审核与观察",
        branch("待复核：映射/汇率/关键字段/同行样本/预算历史/范围外产品/报表缺日/方向冲突"),
        branch("竞价调整后：等待完整归因周期再判断"),
        branch("预算调整后：观察完整成熟7天；近3天不重复改动"),
        branch("输出必须保留：原值、新值、幅度、条件、窗口、证据来源、复核原因"),
        branch("只生成待审核建议：不写入广告平台或数据库"),
    ),
)


def as_topic(node: tuple) -> dict:
    title, children = node
    topic = {"id": uuid.uuid4().hex, "class": "topic", "title": title}
    if children:
        topic["children"] = {"attached": [as_topic(child) for child in children]}
    return topic


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    root = as_topic(TREE)
    root["structureClass"] = "org.xmind.ui.logic.right"
    sheet_id = uuid.uuid4().hex
    content = [{"id": sheet_id, "class": "sheet", "title": "广告调整规则", "rootTopic": root}]
    metadata = {
        "creator": {"name": "Codex", "version": "1.0"},
        "activeSheetId": sheet_id,
        "created": 1789315200000,
        "modified": 1789315200000,
    }
    manifest = {"file-entries": {"content.json": {}, "metadata.json": {}}}
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.json", json.dumps(content, ensure_ascii=False, separators=(",", ":")))
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, separators=(",", ":")))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    print(OUTPUT)


if __name__ == "__main__":
    main()
