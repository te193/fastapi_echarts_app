# 补货明细导出列精简设计

## 目标

精简“补货计划”页面中“导出当前明细”生成的 Excel，移除计算过程中的重复或辅助字段，保留业务判断需要的关键结果字段。

本次只调整导出列，不修改页面表格、数据库表结构、ETL 计算、补货分层或补货数量。

## 删除字段

导出时排除以下 12 个数据库字段：

| 字段 | 当前导出列名 |
|---|---|
| `calculated_replenish_qty` | 计算补货量 |
| `calculated_replenish_box_qty` | 计算补货箱数 |
| `calculated_replenish_cost` | 计算补货货值 |
| `executable_replenish_qty` | 可执行补货量 |
| `executable_replenish_box_qty` | 可执行补货箱数 |
| `executable_replenish_cost` | 可执行补货货值 |
| `replenish_dur_calc_stocko_qty` | 补货周期断货计算量 |
| `replenish_need_qty` | 补货需求量 |
| `replenish_trigger_qty` | 补货触发量 |
| `base_replenish_need_qty` | 原补货需求量 |
| `lead_adjusted_replenish_need_qty` | 交期调整后补货需求量 |
| `lead_time_lost_sales_qty` | 交期内预计损失销量 |

## 明确保留字段

截图中位于两个箭头之间的字段继续导出：

- `lead_time_stockout_flag`：交期内断货标记
- `lead_time_stockout_days`：交期内预计断货天数

其他未列入删除清单的现有导出字段保持不变。

## 实现方式

将 12 个字段加入现有 `REPLENISHMENT_EXPORT_EXCLUDED_COLUMNS`。导出字段仍由数据库列顺序生成，在字段清单阶段统一过滤，不对生成后的 Excel 做二次删除，也不增加前端参数。

## 验证标准

- 自动化测试确认 12 个字段均不在导出字段列表中。
- 自动化测试确认“交期内断货标记”和“交期内预计断货天数”仍在导出字段列表中。
- 实际调用 8002 测试页面的导出接口，检查生成文件的表头，确认删除与保留结果一致。
- 页面表格及补货计算结果不发生变化。
