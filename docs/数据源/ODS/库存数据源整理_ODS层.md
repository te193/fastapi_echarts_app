# 库存数据源整理 — ODS层

> 版本：v2.0（2026-06-22 重构）
> 目的：梳理库存相关ODS源表，记录所有字段名称和中文注释

---

## 一、ODS库存相关表总览

ODS层库存相关表共 **24张**，按业务域分组：

| 业务域 | ODS表名 | 中文注释 | 对应DWD表 | ETL脚本 | 领星数据源 | URL |
|--------|---------|---------|----------|---------|-----------|-----|
| **库存快照** | `lx_storage_fba_warehouse_detail` | FBA库存明细 | `lx_storage_fba_warehouse_detail` | `lx_storage_fba_warehouse_detail.py` | 仓库-FBA库存明细 | `/basicOpen/openapi/storage/fbaWarehouseDetail` |
| **库存快照** | `lx_storage_inventory_details` | 仓库库存明细 | `lx_storage_inventory_details` | `lx_storage_inventory_details.py` | 仓库-库存明细 | `/erp/sc/routing/data/local_inventory/inventoryDetails` |
| **库存变动** | `lx_storage_inventory_log` | 库存流水 | `lx_storage_inventory_log` | `lx_storage_inventory_log.py` | 仓库-库存流水 | `/erp/sc/routing/inventoryLog/WareHouseInventory/wareHouseCenterStatement` |
| **库存变动** | `lx_storage_inbound_order` | 入库单 | `lx_storage_inbound_order` | `lx_storage_inbound_order.py` | 仓库-入库单 | `/erp/sc/routing/storage/inbound/getOrders` |
| **库存变动** | `lx_storage_outbound_order` | 出库单 | `lx_storage_outbound_order` | `lx_storage_outbound_order.py` | 仓库-出库单 | `/erp/sc/routing/storage/outbound/getOrders` |
| **库存变动** | `lx_storage_receipt_order` | 收货单 | `lx_storage_receipt_order` | `lx_storage_receipt_order.py` | 仓库-收货单 | `/erp/sc/routing/deliveryReceipt/PurchaseReceiptOrder/getOrderList` |
| **库存变动** | `lx_storage_check_order_detail` | 盘点单详情 | `lx_storage_check_order_detail` | `lx_storage_check_order_detail.py` | 仓库-盘点单 | `/erp/sc/routing/inventoryReceipt/InventoryCheck/getOrderList` |
| **库存变动** | `lx_storage_qc_order` | 质检单 | `lx_storage_qc_order` | `lx_storage_qc_order.py` | 仓库-质检单 | `/erp/sc/routing/deliveryReceipt/ReceiptOrderQc/getOrderList` |
| **库存变动** | `lx_storage_order_lists` | 加工单列表 | `lx_storage_order_lists` | `lx_storage_order_lists.py` | 仓库-加工单 | `/erp/sc/routing/inventoryReceipt/StorageProcess/getOrderLists` |
| **库存变动** | `lx_reports_fulfillment_removal_order` | 亚马逊源报表-移除订单（新） | `lx_reports_fulfillment_removal_order` | `lx_reports_fulfillment_removal_order.py` | 统计-移除订单 | `/erp/sc/routing/data/order/removalOrderListNew` |
| **FBA货件** | `lx_fba_shipment` | FBA货件 | `lx_fba_shipment` | `lx_fba_shipment.py` | FBA-FBA货件 | `/erp/sc/data/fba_report/shipmentList` |
| **FBA货件** | `lx_fba_shipment_plan` | FBA发货计划 | `lx_fba_shipment_plan` | `lx_fba_shipment_plan.py` | FBA-发货计划 | `/erp/sc/data/fba_report/shipmentPlanLists` |
| **FBA货件** | `lx_inbound_shipment_detail` | FBA发货单详情 | `lx_inbound_shipment_detail` | `lx_inbound_shipment_detail.py` | FBA-发货单 | `/erp/sc/routing/storage/shipment/getInboundShipmentListMwsDetailList` |
| **库存报表** | `lx_statistics_fba_new_aggregate` | 库存报表-FBA-新版-汇总 | `lx_statistics_fba_new_aggregate` | `lx_statistics_fba_new_aggregate.py` | 统计-库存报表-FBA仓库-汇总 | `/cost/center/openApi/fba/gather/query` |
| **库存报表** | `lx_statistics_fba_new_detail` | 库存报表-FBA-新版-明细 | `lx_statistics_fba_new_detail` | `lx_statistics_fba_new_detail.py` | 统计-库存报表-FBA仓库-明细 | `/cost/center/openApi/fba/detail/query` |
| **库存报表** | `lx_statistics_local_new_aggregate` | 库存报表-本地仓-新版-汇总 | `lx_statistics_local_new_aggregate` | `lx_statistics_local_new_aggregate.py` | 统计-库存报表-本地仓库-汇总 | `/inventory/center/openapi/storageReport/local/aggregate/list` |
| **库存报表** | `lx_statistics_local_new_detail` | 库存报表-本地仓-新版-明细 | `lx_statistics_local_new_detail` | `lx_statistics_local_new_detail.py` | 统计-库存报表-本地仓库-明细 | `/inventory/center/openapi/storageReport/local/detail/page` |
| **库存报表** | `lx_statistics_product_performance` | 产品表现 | `lx_statistics_product_performance` | `lx_statistics_product_performance.py` | 统计-产品表现 | `/bd/productPerformance/openApi/asinList` |
| **仓储费用** | `lx_statistics_storage_fee_month` | FBA月仓储费 | `lx_statistics_storage_fee_month` | `lx_statistics_storage_fee_month.py` | 统计-月仓储费 | `/erp/sc/data/fba_report/storageFeeMonth` |
| **仓储费用** | `lx_statistics_storage_fee_long_term` | FBA长期仓储费 | `lx_statistics_storage_fee_long_term` | `lx_statistics_storage_fee_long_term.py` | 统计-长期仓储费 | `/erp/sc/data/fba_report/storageFeeLongTerm` |
| **仓储费用** | `lx_finance_fba_cost_stream` | FBA成本计价流水 | `lx_finance_fba_cost_stream` | `lx_finance_fba_cost_stream.py` | 财务-成本计价 | `/cost/center/api/cost/stream` |
| **补货** | `lx_replenishment_suggest_restocking` | 补货列表 | `lx_replenishment_suggest_restocking` | `lx_replenishment_suggest_restocking.py` | FBA-补货建议 | `/erp/sc/routing/restocking/analysis/getSummaryList` |
| **基础维度** | `lx_storage_warehouse` | 仓库 | `lx_storage_warehouse` | `lx_storage_warehouse.py` | 设置-仓库设置 | `/erp/sc/data/local_inventory/warehouse` |
| **基础维度** | `lx_sales_mws_listing` | 亚马逊Listing | `lx_sales_mws_listing` | `lx_sales_mws_listing.py` | 销售-Listing | `/erp/sc/data/mws/listing` |

---

## 二、ODS表字段明细

### 2.1 `lx_storage_fba_warehouse_detail`（FBA库存明细）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL | 主键 |
| `name` | varchar(100) | 仓库名 |
| `sid` | int | 店铺id【当仓库为共享仓时，sid为0返回】 |
| `asin` | varchar(255) | ASIN |
| `product_name` | varchar(255) | 品名 |
| `small_image_url` | varchar(512) | 预览图链接 |
| `seller_sku` | varchar(100) | MSKU |
| `fnsku` | varchar(100) | FNSKU |
| `sku` | varchar(100) | SKU |
| `category_text` | varchar(100) | 分类文本 |
| `category_id` | int | 分类ID |
| `product_brand_text` | varchar(100) | 品牌文本 |
| `bid` | int | 品牌Id |
| `share_type` | int | 共享类型:0-非共享,1-北美共享,2-欧洲共享 |
| `total` | int | 总数 |
| `total_price` | decimal(12,2) | 总价 |
| `available_total` | int | 可用总数 |
| `available_total_price` | varchar(50) | 可用总数成本价 |
| `afn_fulfillable_quantity` | int | FBA可售 |
| `afn_fulfillable_quantity_price` | varchar(50) | FBA可售成本价 |
| `reserved_fc_transfers` | int | 待调仓 |
| `reserved_fc_transfers_price` | varchar(50) | 待调仓成本价 |
| `reserved_fc_processing` | int | 调仓中 |
| `reserved_fc_processing_price` | varchar(50) | 调仓中成本价 |
| `reserved_customerorders` | int | 待发货 |
| `reserved_customerorders_price` | varchar(50) | 待发货成本价 |
| `quantity` | int | FBM可售 |
| `quantity_price` | varchar(50) | FBM可售成本价 |
| `afn_unsellable_quantity` | int | 不可售 |
| `afn_unsellable_quantity_price` | varchar(50) | 不可售成本价 |
| `afn_inbound_working_quantity` | int | 计划入库 |
| `afn_inbound_working_quantity_price` | varchar(50) | 计划入库成本价 |
| `afn_inbound_shipped_quantity` | int | 在途 |
| `afn_inbound_shipped_quantity_price` | varchar(50) | 在途成本价 |
| `afn_inbound_receiving_quantity` | int | 入库中 |
| `afn_inbound_receiving_quantity_price` | varchar(50) | 入库中成本价 |
| `stock_up_num` | int | 实际在途 |
| `stock_up_num_price` | varchar(50) | 实际在途成本价 |
| `afn_researching_quantity` | int | 调查中数量 |
| `afn_researching_quantity_price` | varchar(50) | 调查中数量成本价 |
| `total_fulfillable_quantity` | int | 总可用库存:可售+待调仓+调仓中【非ERP页面对应总库存】 |
| `inv_age_0_to_30_days` | int | 0-1个月库龄 |
| `inv_age_0_to_30_price` | varchar(50) | 0-1个月库龄成本价 |
| `inv_age_31_to_60_days` | int | 1-2个月库龄 |
| `inv_age_31_to_60_price` | varchar(50) | 1-2个月库龄成本价 |
| `inv_age_61_to_90_days` | int | 2-3个月库龄 |
| `inv_age_61_to_90_price` | varchar(50) | 2-3个月库龄成本价 |
| `inv_age_0_to_90_days` | int | 0-3个月库龄 |
| `inv_age_0_to_90_price` | varchar(50) | 0-3个月库龄成本价 |
| `inv_age_91_to_180_days` | int | 3-6个月库龄 |
| `inv_age_91_to_180_price` | varchar(50) | 3-6个月库龄成本价 |
| `inv_age_181_to_270_days` | int | 6-9个月库龄 |
| `inv_age_181_to_270_price` | varchar(50) | 6-9个月库龄成本价 |
| `inv_age_271_to_330_days` | int | 9-11个月库龄 |
| `inv_age_271_to_330_price` | varchar(50) | 9-11个月库龄成本价 |
| `inv_age_271_to_365_days` | int | 9-12个月库龄 |
| `inv_age_271_to_365_price` | varchar(50) | 9-12个月库龄成本价 |
| `inv_age_331_to_365_days` | int | 11-12个月库龄 |
| `inv_age_331_to_365_price` | varchar(50) | 11-12个月库龄成本价 |
| `inv_age_365_plus_days` | int | 12个月以上库龄 |
| `inv_age_365_plus_price` | varchar(50) | 12个月以上库龄成本价 |
| `recommended_action` | varchar(100) | 推荐操作 |
| `sell_through` | decimal(12,2) | 售出率 |
| `estimated_excess_quantity` | decimal(12,2) | 预计冗余数量 |
| `estimated_storage_cost_next_month` | decimal(12,2) | 预计30天仓储费用 |
| `fba_minimum_inventory_level` | decimal(12,2) | 最低库存水平 |
| `fba_inventory_level_health_status` | varchar(50) | 库存水平健康度 |
| `historical_days_of_supply` | decimal(12,2) | 历史供货天数 |
| `historical_days_of_supply_price` | varchar(50) | 历史供货天数成本价 |
| `low_inventory_level_fee_applied` | varchar(100) | 低库存水平费收取情况 |
| `fulfillment_channel` | varchar(100) | 配送方式 |
| `cg_price` | varchar(25) | 单位采购成本 |
| `cg_transport_costs` | varchar(25) | 单位头程费用 |
| `fba_storage_quantity_list` | text | FBA可售信息列表，当仓库为共享仓库时，该字段才返回 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.2 `lx_storage_inventory_details`（仓库库存明细）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `wid` | int | 仓库id |
| `product_id` | int | 本地产品id |
| `sku` | varchar(100) | SKU |
| `seller_id` | varchar(100) | 店铺id |
| `fnsku` | varchar(100) | FNSKU |
| `product_total` | int | 实际库存总量【可用量+次品量+待检待上架量+锁定量】 |
| `product_valid_num` | int | 可用量 |
| `product_bad_num` | int | 次品量 |
| `product_qc_num` | int | 待检待上架量 |
| `product_lock_num` | int | 锁定量 |
| `stock_cost_total` | varchar(25) | 库存成本 |
| `quantity_receive` | varchar(25) | 待到货量 |
| `stock_cost` | varchar(25) | 单位库存成本 |
| `product_onway` | int | 调拨在途 |
| `transit_head_cost` | varchar(25) | 调拨在途头程成本 |
| `average_age` | int | 平均库龄 |
| `third_inventory` | text | 海外仓第三方库存信息 |
| `stock_age_list` | text | 库龄信息 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.3 `lx_mws_report_fba_inventory`（亚马逊源报表-FBA库存）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL | 主键 |
| `sku` | varchar(100) | MSKU |
| `fnsku` | varchar(100) | FNSKU |
| `asin` | varchar(100) | ASIN |
| `product_name` | varchar(500) | 品名 |
| `product_condition` | varchar(255) | 商品的状况 |
| `mfn_listing_exists` | varchar(10) | 商品是否由卖家自行配送 |
| `mfn_fulfillable_quantity` | int | 您的配送网络中可取件、包装和配送的商品数量 |
| `afn_listing_exists` | varchar(10) | 商品是否由亚马逊物流配送 |
| `afn_warehouse_quantity` | int | 亚马逊运营中心内某个 SKU 的已处理商品数量 |
| `afn_fulfillable_quantity` | int | 亚马逊运营中心内某个 SKU 可取件、包装和配送的商品数量 |
| `afn_unsellable_quantity` | int | 亚马逊运营中心内某个 SKU 处于不可售状况的商品数量 |
| `afn_reserved_quantity` | int | 亚马逊运营中心内某个 SKU 目前正在进行内部处理的商品数量 |
| `afn_total_quantity` | int | 入库货件或亚马逊运营中心内某个 SKU 的商品总数量 |
| `per_unit_volume` | varchar(100) | — |
| `afn_inbound_working_quantity` | int | 已通知亚马逊的入库货件中某个 SKU 的商品数量 |
| `afn_inbound_shipped_quantity` | int | 已通知亚马逊并提供追踪编码的入库货件中某个 SKU 的商品数量 |
| `afn_inbound_receiving_quantity` | int | 某个 SKU 抵达亚马逊运营中心等待处理的商品数量 |
| `your_price` | decimal(12,2) | 您当前的销售价格 |
| `cg_price` | decimal(12,2) | 采购成本（人民币） |
| `landed_price` | decimal(12,2) | 卖家自己产品的销售价格 |
| `gmt_modified` | varchar(100) | 最后修改时间(GMT) |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.4 `lx_storage_inventory_log`（库存流水）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键ID |
| `wid` | int | 仓库ID |
| `ware_house_name` | varchar(100) | 仓库名称 |
| `order_sn` | varchar(50) | 操作单据号 |
| `product_id` | int | 产品ID |
| `product_name` | varchar(500) | 品名 |
| `sku` | varchar(100) | SKU |
| `seller_id` | varchar(25) | 店铺ID |
| `fnsku` | varchar(100) | FNSKU |
| `product_good_num` | int | 可用量 |
| `product_bad_num` | int | 次品量 |
| `product_qc_num` | int | 待检量 |
| `product_lock_good_num` | int | 可用锁定量 |
| `product_lock_bad_num` | int | 次品锁定量 |
| `good_transit_num` | int | 良品在途 |
| `bad_transit_num` | int | 次品在途 |
| `type` | int | 流水类型 |
| `type_text` | varchar(50) | 流水类型文本 |
| `sub_type` | varchar(20) | 子类型 |
| `sub_type_text` | varchar(50) | 子类型文本 |
| `fee_cost` | varchar(20) | 总费用成本 |
| `single_cg_price` | varchar(20) | 采购单价 |
| `single_fee_cost` | varchar(20) | 单位费用 |
| `single_stock_price` | varchar(20) | 单位库存成本 |
| `stock_cost` | varchar(20) | 库存成本 |
| `product_amounts` | varchar(20) | 货值 |
| `head_stock_price` | varchar(20) | 单位头程 |
| `head_stock_cost` | varchar(20) | 头程 |
| `opt_uid` | int | 操作人员ID |
| `opt_time` | varchar(50) | 操作时间 |
| `opt_real_name` | varchar(50) | 操作人员姓名 |
| `remark` | varchar(500) | 备注 |
| `bid` | int | 品牌ID |
| `brand_name` | varchar(100) | 品牌名称 |
| `ref_order_sn` | varchar(50) | 关联单据号 |
| `product_total` | int | 总量 |
| `good_balance_num` | int | 可用结存量 |
| `bad_balance_num` | int | 次品结存量 |
| `good_lock_balance_num` | int | 可用锁定结存量 |
| `bad_lock_balance_num` | int | 次品锁定结存量 |
| `qc_balance_num` | int | 质检结存量 |
| `good_transit_balance_num` | int | 可用在途结存量 |
| `statement_id` | varchar(50) | 流水ID |
| `bad_transit_balance_num` | int | 次品在途结存量 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.5 `lx_storage_inbound_order`（入库单）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `increment_time` | varchar(50) | 单据数据更新时间 |
| `custom_fields` | text | 自定义字段 |
| `opt_realname` | varchar(25) | 入库人姓名 |
| `opt_time` | varchar(255) | 入库时间 |
| `opt_uid` | int | 操作人id |
| `inbound_time` | varchar(50) | 自定义入库时间 |
| `commit_realname` | varchar(25) | 提交人名称 |
| `commit_uid` | int | 提交人id |
| `commit_time` | varchar(50) | 提交时间 |
| `order_sn` | varchar(50) | 入库单号 |
| `status` | int | 入库单状态 |
| `status_text` | varchar(25) | 入库单状态名称 |
| `order_create_time` | varchar(50) | 入库单创建时间 |
| `create_uid` | int | 创建人id |
| `create_realname` | varchar(25) | 创建人名称 |
| `purchase_order_sn` | varchar(50) | 采购单号 |
| `receipt_order_sn` | varchar(50) | 收货单号 |
| `revoke_realname` | varchar(25) | 撤销人名称 |
| `revoke_uid` | int | 撤销人id |
| `revoke_time` | varchar(50) | 撤销时间 |
| `supplier_id` | varchar(50) | 供应商id |
| `supplier_name` | varchar(100) | 供应商名称 |
| `source_sn` | varchar(50) | 关联单据号 |
| `order_amount` | varchar(25) | 单据入库成本 |
| `cg_uid` | int | 采购员id |
| `return_price` | varchar(25) | 运费 |
| `currency` | varchar(25) | 运费币种 |
| `other_fee` | varchar(25) | 其他费用 |
| `fee_part_type` | varchar(25) | 费用分摊方式 |
| `fee_part_type_text` | varchar(50) | 费用分摊方式名称 |
| `type` | int | 入库类型 |
| `type_text` | varchar(25) | 入库类型名称 |
| `custom_type_id` | bigint | 自定义类型ID |
| `custom_type_name` | varchar(25) | 自定义类型名称 |
| `cg_realname` | varchar(25) | 采购员姓名 |
| `wid` | varchar(25) | 仓库id |
| `ware_house_name` | varchar(100) | 仓库名称 |
| `remark` | varchar(512) | 单据备注 |
| `item_list` | text | 产品明细 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.6 `lx_storage_outbound_order`（出库单）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `increment_time` | varchar(50) | 单据数据更新时间 |
| `custom_fields` | text | 自定义字段 |
| `opt_realname` | varchar(100) | 出库人姓名 |
| `opt_time` | varchar(50) | 出库时间 |
| `opt_uid` | int | 操作人id |
| `outbound_time` | varchar(50) | 自定义出库时间 |
| `commit_realname` | varchar(100) | 提交人名称 |
| `commit_uid` | int | 提交人id |
| `commit_time` | varchar(50) | 提交时间 |
| `order_sn` | varchar(50) | 出库单号 |
| `status` | int | 出库单状态 |
| `status_text` | varchar(100) | 出库单状态名称 |
| `order_create_time` | varchar(50) | 出库单创建时间 |
| `create_uid` | int | 创建人id |
| `create_realname` | varchar(100) | 创建人名称 |
| `purchase_order_sn` | varchar(50) | 采购单号 |
| `revoke_realname` | varchar(100) | 撤销人名称 |
| `revoke_uid` | int | 撤销人id |
| `revoke_time` | varchar(50) | 撤销时间 |
| `supplier_id` | varchar(50) | 供应商id |
| `supplier_name` | varchar(100) | 供应商名称 |
| `source_sn` | varchar(50) | 关联单据号 |
| `order_amount` | varchar(50) | 单据入库成本 |
| `cg_uid` | int | 采购员id |
| `return_price` | varchar(50) | 运费 |
| `currency` | varchar(20) | 运费币种 |
| `other_fee` | varchar(50) | 其他费用 |
| `fee_part_type` | varchar(50) | 费用分摊方式 |
| `fee_part_type_text` | varchar(100) | 费用分摊方式名称 |
| `type` | int | 出库类型 |
| `type_text` | varchar(100) | 出库类型名称 |
| `custom_type_id` | bigint | 自定义类型ID |
| `custom_type_name` | varchar(100) | 自定义类型名称 |
| `cg_realname` | varchar(100) | 采购员姓名 |
| `wid` | varchar(50) | 仓库id |
| `ware_house_name` | varchar(100) | 仓库名称 |
| `to_wid` | varchar(50) | 目的仓库id |
| `to_ware_house_name` | varchar(100) | 目的仓库名称 |
| `remark` | varchar(255) | 单据备注 |
| `item_list` | text | 产品列表 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.7 `lx_storage_receipt_order`（收货单）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `order_sn` | varchar(50) | 收货单号 |
| `status` | int | 状态：10 待收货，40 已完成 |
| `order_create_time` | varchar(50) | 收货单创建时间 |
| `create_uid` | int | 创建人id |
| `create_realname` | varchar(50) | 创建人 |
| `order_update_time` | varchar(50) | 收货单更新时间 |
| `receive_time` | varchar(50) | 收货时间 |
| `receive_uid` | int | 收货人id |
| `receive_realname` | varchar(50) | 收货人 |
| `wid` | int | 仓库id |
| `order_type` | int | 收货类型：1 采购订单，2 委外订单 |
| `qc_type` | int | 质检类型：1 仓库质检，2 预检，3 免检 |
| `business_order_sn` | varchar(50) | 来源单号 |
| `supplier_id` | int | 供应商id |
| `logistics_company` | varchar(100) | 物流商 |
| `logistics_order_no` | varchar(50) | 物流单号 |
| `expect_arrival_time` | varchar(50) | 预计到货时间 |
| `shipping_currency` | varchar(10) | 运费币种 |
| `shipping_cost` | varchar(25) | 运费 |
| `other_currency` | varchar(10) | 其他费用币种 |
| `other_fee` | varchar(25) | 其他费用 |
| `opt_uid` | int | 采购员id |
| `opt_realname` | varchar(50) | 采购员 |
| `inbound_order_sns` | text | 入库单号 |
| `remark` | text | 单据备注 |
| `item_list` | text | 产品列表 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.8 `lx_storage_check_order_detail`（盘点单详情）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `order_sn` | varchar(50) | 盘点单号 |
| `status` | int | 盘点状态：10-待盘点,20-预锁,30-盘点中,40-已盘点,121-待审核,122-已驳回,123-通过,124-作废 |
| `status_text` | varchar(20) | 状态文本 |
| `wid` | int | 盘点仓库ID |
| `ware_house_name` | varchar(100) | 盘点仓库名称 |
| `check_type` | int | 盘点类型：1-整仓盘点,2-SKU盘点,3-仓位盘点,4-SKU+仓位盘点 |
| `check_type_text` | varchar(50) | 盘点类型说明 |
| `is_display_check` | tinyint(1) | 是否明盘：0-否,1-是 |
| `display_check_name` | varchar(20) | 是否明盘文本 |
| `is_zero` | tinyint(1) | 是否零库存参与盘点：0-否,1-是 |
| `product_type` | int | 产品种类 |
| `create_uid` | int | 创建人ID |
| `create_user` | varchar(50) | 创建人姓名 |
| `order_create_time` | varchar(50) | 盘点单创建时间 |
| `check_uid` | int | 盘点人ID |
| `check_user` | varchar(50) | 盘点人姓名 |
| `real_check_uid` | int | 实际盘点人ID |
| `real_check_user` | varchar(50) | 实际盘点人姓名 |
| `check_time` | varchar(50) | 盘点时间 |
| `commit_uid` | int | 提交人ID |
| `commit_user` | varchar(50) | 提交人姓名 |
| `commit_time` | varchar(50) | 提交时间 |
| `cancel_uid` | int | 作废人ID |
| `cancel_user` | varchar(50) | 作废人姓名 |
| `cancel_time` | varchar(50) | 作废时间 |
| `cancel_reason` | varchar(255) | 作废原因 |
| `remark` | varchar(500) | 备注 |
| `request_status` | int | 单据状态：0-正常,1-处理中 |
| `file` | text | 上传附件信息 |
| `product_list` | longtext | 盘点明细列表 |
| `total` | int | 盘点明细总数 |
| `item_total` | text | 盘点明细汇总信息 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.9 `lx_storage_qc_order`（质检单）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `qc_sn` | varchar(50) | 质检单号 |
| `order_type` | int | 订单类型：1 采购订单，2 委外订单 |
| `qc_type` | int | 质检类型：1 仓库质检，2 预检，3 免检 |
| `qc_method` | int | 质检方式：1 抽检，2 全检 |
| `order_create_time` | varchar(20) | 质检单创建时间 |
| `status` | int | 状态：0待质检,1已质检,2已免检,10已质检(撤销),20已免检(撤销) |
| `order_sn` | varchar(50) | 来源单号 |
| `opt_uid` | int | 采购员id |
| `opt_realname` | varchar(50) | 采购员 |
| `receive_uid` | int | 收货人id |
| `receive_realname` | varchar(50) | 收货人 |
| `receive_time` | varchar(20) | 到货时间 |
| `qc_uid` | int | 质检人id |
| `qc_realname` | varchar(50) | 质检人 |
| `qc_time` | varchar(20) | 质检时间 |
| `wid` | int | 仓库id |
| `supplier_id` | int | 供应商id |
| `order_item_id` | int | 采购单子项id |
| `delivery_order_sn` | varchar(50) | 收货单号 |
| `delivery_item_id` | int | 收货单子项id |
| `sku` | varchar(50) | SKU |
| `product_name` | varchar(500) | 品名 |
| `fnsku` | varchar(50) | FNSKU |
| `seller_id` | varchar(25) | 店铺id |
| `product_receive_num` | int | 质检量 |
| `qc_num` | int | 抽检量 |
| `qc_bad_num` | int | 抽检次品量 |
| `qc_rate_pass` | varchar(10) | 抽检合格率 |
| `qc_rate` | varchar(10) | 抽检比例 |
| `product_good_num` | int | 总良品量 |
| `product_bad_num` | int | 总次品量 |
| `whb_code_good` | varchar(50) | 可用仓位 |
| `whb_code_bad` | varchar(50) | 次品仓位 |
| `qc_remark` | text | 备注 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.10 `lx_storage_order_lists`（加工单列表）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 自增主键 |
| `process_sn` | varchar(150) | 加工/拆分单号 |
| `status` | tinyint | 订单状态：0=待配货，1=待完成，2=已完成 |
| `type` | varchar(10) | 单据类型：1=加工单，2=拆分单 |
| `ware_house_name` | varchar(500) | 仓库名称 |
| `wid` | int | 仓库id |
| `create_by` | int | 创建人id |
| `create_realname` | varchar(150) | 创建人名称 |
| `order_create_time` | datetime | 创建时间 |
| `finish_realname` | varchar(150) | 最后操作人 |
| `finish_time` | datetime | 最后操作时间 |
| `finish_uid` | int | 最后操作人id |
| `remark` | varchar(500) | 备注 |
| `order_update_time` | datetime | 更新时间 |
| `product_list` | text | 组合品项 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.11 `lx_statistics_fba_new_aggregate`（库存报表-FBA-新版-汇总）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `adjustments_count` | int | 成本调整-数量 |
| `adjustments_logistic_amount` | decimal(10,2) | 成本调整-物流成本(精度：2位小数) |
| `adjustments_other_amount` | decimal(10,2) | 成本调整-其他成本(精度：2位小数) |
| `adjustments_total_amount` | decimal(10,2) | 成本调整-总成本(精度：2位小数) |
| `asin` | varchar(50) | ASIN编码 |
| `bid` | int | 品牌ID |
| `brand_name` | varchar(255) | 品牌名称 |
| `cid` | int | 分类ID |
| `country_code` | varchar(10) | 国家编码(如US) |
| `customer_returns_count` | int | 买家退货-数量 |
| `customer_returns_logistic_amount` | decimal(10,2) | 买家退货-物流成本(精度：2位小数) |
| `customer_returns_other_amount` | decimal(10,2) | 买家退货-其他成本(精度：2位小数) |
| `customer_returns_total_amount` | decimal(10,2) | 买家退货-总成本(精度：2位小数) |
| `damaged_count` | int | 残损-数量 |
| `damaged_logistic_amount` | decimal(10,2) | 残损-物流成本(精度：2位小数) |
| `damaged_other_amount` | decimal(10,2) | 残损-其他成本(精度：2位小数) |
| `damaged_total_amount` | decimal(10,2) | 残损-总成本(精度：2位小数) |
| `difference_count` | int | 库存差异-数量 |
| `difference_logistic_amount` | decimal(10,2) | 库存差异-物流成本(精度：2位小数) |
| `difference_other_amount` | decimal(10,2) | 库存差异-其他成本(精度：2位小数) |
| `difference_total_amount` | decimal(10,2) | 库存差异-总成本(精度：2位小数) |
| `disposed_count` | int | 丢弃-数量 |
| `disposed_logistic_amount` | decimal(10,2) | 丢弃-物流成本(精度：2位小数) |
| `disposed_other_amount` | decimal(10,2) | 丢弃-其他成本(精度：2位小数) |
| `disposed_total_amount` | decimal(10,2) | 丢弃-总成本(精度：2位小数) |
| `disposition` | varchar(20) | 库存属性：sellable(可售)/unsellable(不可售)/all(全部) |
| `end_count` | int | 期末库存-数量 |
| `end_logistic_amount` | decimal(10,2) | 期末库存-物流成本(精度：2位小数) |
| `end_on_way_count` | int | 期末在途-数量 |
| `end_on_way_logistic_amount` | decimal(10,2) | 期末在途-物流成本(精度：2位小数) |
| `end_on_way_other_amount` | decimal(10,2) | 期末在途-其他成本(精度：2位小数) |
| `end_on_way_total_amount` | decimal(10,2) | 期末在途-总成本(精度：2位小数) |
| `end_other_amount` | decimal(10,2) | 期末库存-其他成本(精度：2位小数) |
| `end_total_amount` | decimal(10,2) | 期末库存-总成本(精度：2位小数) |
| `fnsku` | varchar(100) | FNSKU编码 |
| `found_count` | int | 已找到-数量 |
| `found_logistic_amount` | decimal(10,2) | 已找到-物流成本(精度：2位小数) |
| `found_other_amount` | decimal(10,2) | 已找到-其他成本(精度：2位小数) |
| `found_total_amount` | decimal(10,2) | 已找到-总成本(精度：2位小数) |
| `inventory_turnover_days` | decimal(10,2) | 库存周转天数(精度：2位小数) |
| `inventory_turnover_rate` | decimal(10,2) | 库存周转率(精度：2位小数) |
| `moving_pin_rate` | decimal(10,2) | 动销率(精度：2位小数) |
| `local_name` | varchar(255) | 本地产品名称 |
| `local_sku` | varchar(100) | 本地产品SKU |
| `lost_count` | int | 丢失-数量 |
| `lost_logistic_amount` | decimal(10,2) | 丢失-物流成本(精度：2位小数) |
| `lost_other_amount` | decimal(10,2) | 丢失-其他成本(精度：2位小数) |
| `lost_total_amount` | decimal(10,2) | 丢失-总成本(精度：2位小数) |
| `mid` | int | 站点ID |
| `msku` | varchar(100) | MSKU编码 |
| `other_events_count` | int | 其他-数量 |
| `other_events_logistic_amount` | decimal(10,2) | 其他-物流成本(精度：2位小数) |
| `other_events_other_amount` | decimal(10,2) | 其他-其他成本(精度：2位小数) |
| `other_events_total_amount` | decimal(10,2) | 其他-总成本(精度：2位小数) |
| `parent_asin` | varchar(50) | 父ASIN |
| `parent_node` | varchar(10) | 是否父节点(true/false) |
| `product_category_name` | varchar(255) | 产品分类名称 |
| `product_id` | int | 产品ID |
| `receipts_count` | int | 货物补货-数量 |
| `receipts_logistic_amount` | decimal(10,2) | 货物补货-物流成本(精度：2位小数) |
| `receipts_other_amount` | decimal(10,2) | 货物补货-其他成本(精度：2位小数) |
| `receipts_total_amount` | decimal(10,2) | 货物补货-总成本(精度：2位小数) |
| `shipments_count` | int | 订单发货-数量 |
| `shipments_logistic_amount` | decimal(10,2) | 订单发货-物流成本(精度：2位小数) |
| `shipments_other_amount` | decimal(10,2) | 订单发货-其他成本(精度：2位小数) |
| `shipments_total_amount` | decimal(10,2) | 订单发货-总成本(精度：2位小数) |
| `sid` | int | 店铺ID |
| `seller_id` | varchar(100) | 亚马逊店铺ID |
| `start_count` | int | 期初库存-数量 |
| `start_logistic_amount` | decimal(10,2) | 期初库存-物流成本(精度：2位小数) |
| `start_other_amount` | decimal(10,2) | 期初库存-其他成本(精度：2位小数) |
| `start_total_amount` | decimal(10,2) | 期初库存-总成本(精度：2位小数) |
| `stock_to_use_rate` | decimal(10,2) | 存销比(精度：2位小数) |
| `valuation_method` | int | 计价方法:1-先进先出,2-移动加权,3-月末加权 |
| `vendor_returns_count` | int | 库存移除-数量 |
| `vendor_returns_logistic_amount` | decimal(10,2) | 库存移除-物流成本(精度：2位小数) |
| `vendor_returns_other_amount` | decimal(10,2) | 库存移除-其他成本(精度：2位小数) |
| `vendor_returns_total_amount` | decimal(10,2) | 库存移除-总成本(精度：2位小数) |
| `whse_transfers_logistic_amount` | decimal(10,2) | 库房转运-物流成本(精度：2位小数) |
| `whse_transfers_other_amount` | decimal(10,2) | 库房转运-其他成本(精度：2位小数) |
| `whse_transfers_total_amount` | decimal(10,2) | 库房转运-总成本(精度：2位小数) |
| `whse_transfers_count` | int | 库房转运-数量 |
| `wid` | int | 系统仓库ID |
| `ware_house_name` | varchar(255) | 仓库名称 |
| `child_data` | text | 返回字段与上级row_data一致 |
| `start_date` | varchar(25) | 来源数据-搜索开始时间 |
| `end_date` | varchar(25) | 来源数据-搜索结束时间 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.12 `lx_statistics_fba_new_detail`（库存报表-FBA-新版-明细）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `seller_id` | varchar(50) | 亚马逊店铺ID |
| `sid` | int | 店铺ID |
| `wid` | int | 系统仓库ID |
| `ware_house_name` | varchar(100) | 仓库名称 |
| `mid` | int | 站点ID |
| `country_code` | varchar(10) | 国家编码(如US) |
| `asin` | varchar(50) | ASIN编码 |
| `parent_asin` | varchar(50) | 父ASIN |
| `msku` | varchar(100) | MSKU编码 |
| `fnsku` | varchar(100) | FNSKU编码 |
| `product_id` | int | 本地产品ID |
| `local_sku` | varchar(100) | 本地产品SKU |
| `local_name` | varchar(255) | 本地产品名称 |
| `cid` | int | 商品分类ID |
| `product_category_name` | varchar(255) | 产品分类名称 |
| `bid` | int | 品牌ID |
| `brand_name` | varchar(255) | 品牌名称 |
| `disposition` | varchar(20) | 库存属性：sellable(可售)/unsellable(不可售)/all(全部) |
| `parent_node` | tinyint(1) | 是否父节点(1:是,0:否) |
| `category_count` | int | 商品种类数量 |
| `partition_index` | int | 分区索引 |
| `valuation_method` | tinyint | 计价方法:1-先进先出,2-移动加权,3-月末加权 |
| `start_count` | int | 期初库存-数量 |
| `start_logistic_amount` | decimal(12,2) | 期初库存-物流成本 |
| `start_other_amount` | decimal(12,2) | 期初库存-其他成本 |
| `start_total_amount` | decimal(12,2) | 期初库存-总成本 |
| `end_count` | int | 期末库存-数量 |
| `end_logistic_amount` | decimal(12,2) | 期末库存-物流成本 |
| `end_other_amount` | decimal(12,2) | 期末库存-其他成本 |
| `end_total_amount` | decimal(12,2) | 期末库存-总成本 |
| `end_on_way_count` | int | 期末在途-数量 |
| `end_on_way_logistic_amount` | decimal(12,2) | 期末在途-物流成本 |
| `end_on_way_other_amount` | decimal(12,2) | 期末在途-其他成本 |
| `end_on_way_total_amount` | decimal(12,2) | 期末在途-总成本 |
| `transferring_out_count` | int | 移仓在途-数量 |
| `transferring_out_logistic_amount` | decimal(12,2) | 移仓在途-物流成本 |
| `transferring_out_other_amount` | decimal(12,2) | 移仓在途-其他成本 |
| `transferring_out_total_amount` | decimal(12,2) | 移仓在途-总成本 |
| `shipments_count` | int | 订单发货-数量 |
| `shipments_logistic_amount` | decimal(12,2) | 订单发货-物流成本 |
| `shipments_other_amount` | decimal(12,2) | 订单发货-其他成本 |
| `shipments_total_amount` | decimal(12,2) | 订单发货-总成本 |
| `whse_transfers_count` | int | 库房转运-数量 |
| `whse_transfers_logistic_amount` | decimal(12,2) | 库房转运-物流成本 |
| `whse_transfers_other_amount` | decimal(12,2) | 库房转运-其他成本 |
| `whse_transfers_total_amount` | decimal(12,2) | 库房转运-总成本 |
| `disposed_count` | int | 弃置-数量 |
| `disposed_logistic_amount` | decimal(12,2) | 弃置-物流成本 |
| `disposed_other_amount` | decimal(12,2) | 弃置-其他成本 |
| `disposed_total_amount` | decimal(12,2) | 弃置-总成本 |
| `found_count` | int | 已找到-数量 |
| `found_logistic_amount` | decimal(12,2) | 已找到-物流成本 |
| `found_other_amount` | decimal(12,2) | 已找到-其他成本 |
| `found_total_amount` | decimal(12,2) | 已找到-总成本 |
| `lost_count` | int | 丢失-数量 |
| `lost_logistic_amount` | decimal(12,2) | 丢失-物流成本 |
| `lost_other_amount` | decimal(12,2) | 丢失-其他成本 |
| `lost_total_amount` | decimal(12,2) | 丢失-总成本 |
| `other_events_count` | int | 其他-数量 |
| `other_events_logistic_amount` | decimal(12,2) | 其他-物流成本 |
| `other_events_other_amount` | decimal(12,2) | 其他-其他成本 |
| `other_events_total_amount` | decimal(12,2) | 其他-总成本 |
| `receipts_count` | int | 货件补货-数量 |
| `receipts_logistic_amount` | decimal(12,2) | 货件补货-物流成本 |
| `receipts_other_amount` | decimal(12,2) | 货件补货-其他成本 |
| `receipts_total_amount` | decimal(12,2) | 货件补货-总成本 |
| `customer_returns_count` | int | 买家退货-数量 |
| `customer_returns_logistic_amount` | decimal(12,2) | 买家退货-物流成本 |
| `customer_returns_other_amount` | decimal(12,2) | 买家退货-其他成本 |
| `customer_returns_total_amount` | decimal(12,2) | 买家退货-总成本 |
| `vendor_returns_count` | int | 库存移除-数量 |
| `vendor_returns_logistic_amount` | decimal(12,2) | 库存移除-物流成本 |
| `vendor_returns_other_amount` | decimal(12,2) | 库存移除-其他成本 |
| `vendor_returns_total_amount` | decimal(12,2) | 库存移除-总成本 |
| `difference_count` | int | 库存差异-数量 |
| `difference_logistic_amount` | decimal(12,2) | 库存差异-物流成本 |
| `difference_other_amount` | decimal(12,2) | 库存差异-其他成本 |
| `difference_total_amount` | decimal(12,2) | 库存差异-总成本 |
| `damaged_count` | int | 残损-数量 |
| `damaged_logistic_amount` | decimal(12,2) | 残损-物流成本 |
| `damaged_other_amount` | decimal(12,2) | 残损-其他成本 |
| `damaged_total_amount` | decimal(12,2) | 残损-总成本 |
| `adjustments_count` | int | 成本调整-数量 |
| `adjustments_logistic_amount` | decimal(12,2) | 成本调整-物流成本 |
| `adjustments_other_amount` | decimal(12,2) | 成本调整-其他成本 |
| `adjustments_total_amount` | decimal(12,2) | 成本调整-总成本 |
| `inventory_turnover_rate` | decimal(12,2) | 库存周转率 |
| `inventory_turnover_days` | decimal(12,2) | 库存周转天数 |
| `stock_to_use_rate` | decimal(12,2) | 存销比 |
| `child_data` | text | 返回字段与上级row_data一致 |
| `start_date` | varchar(25) | 来源数据-搜索开始时间 |
| `end_date` | varchar(25) | 来源数据-搜索结束时间 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.13 `lx_statistics_local_new_aggregate`（库存报表-本地仓-新报表-汇总）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `sys_wid` | int | 系统仓库id |
| `ware_house_name` | varchar(100) | 仓库名称 |
| `product_count` | decimal(12,2) | 商品数量 |
| `allocation_in_cost` | decimal(12,2) | 调拨入库-成本 |
| `allocation_in_count` | decimal(12,2) | 调拨入库-数量 |
| `allocation_in_transit_cost` | decimal(12,2) | 期末在途-成本 |
| `allocation_in_transit_count` | decimal(12,2) | 期末在途-数量 |
| `allocation_out_cost` | decimal(12,2) | 调拨出库-成本 |
| `allocation_out_count` | decimal(12,2) | 调拨出库-数量 |
| `change_of_standard_in_cost` | decimal(12,2) | 换标入库-成本 |
| `change_of_standard_in_count` | decimal(12,2) | 换标入库-数量 |
| `change_of_standard_out_cost` | decimal(12,2) | 换标出库-成本 |
| `change_of_standard_out_count` | decimal(12,2) | 换标出库-数量 |
| `cost_adjustment` | decimal(12,2) | 成本调整 |
| `day_early_cost` | decimal(12,2) | 期初库存-成本 |
| `day_early_count` | decimal(12,2) | 期初库存-数量 |
| `day_end_cost` | decimal(12,2) | 期末库存-成本 |
| `day_end_count` | decimal(12,2) | 期末库存-数量 |
| `fba_out_cost` | decimal(12,2) | fba出库-成本 |
| `fba_out_count` | decimal(12,2) | fba出库-数量 |
| `fbm_out_cost` | decimal(12,2) | fbm出库-成本 |
| `fbm_out_count` | decimal(12,2) | fbm出库-数量 |
| `inventory_deficit_out_cost` | decimal(12,2) | 盘亏出库-成本 |
| `inventory_deficit_out_count` | decimal(12,2) | 盘亏出库-数量 |
| `inventory_surplus_in_cost` | decimal(12,2) | 盘盈入库-成本 |
| `inventory_surplus_in_count` | decimal(12,2) | 盘盈入库-数量 |
| `other_in_cost` | decimal(12,2) | 其他入库-成本 |
| `other_in_count` | decimal(12,2) | 其他入库-数量 |
| `other_out_cost` | decimal(12,2) | 其他出库-成本 |
| `other_out_count` | decimal(12,2) | 其他出库-数量 |
| `outsourcing_in_cost` | decimal(12,2) | 委外入库-成本 |
| `outsourcing_in_count` | decimal(12,2) | 委外入库-数量 |
| `outsourcing_out_cost` | decimal(12,2) | 委外出库-成本 |
| `outsourcing_out_count` | decimal(12,2) | 委外出库-数量 |
| `processing_in_cost` | decimal(12,2) | 加工入库-成本 |
| `processing_in_count` | decimal(12,2) | 加工入库-数量 |
| `processing_out_cost` | decimal(12,2) | 加工出库-成本 |
| `processing_out_count` | decimal(12,2) | 加工出库-数量 |
| `purchase_in_cost` | decimal(12,2) | 采购入库-成本 |
| `purchase_in_count` | decimal(12,2) | 采购入库-数量 |
| `purchase_return_cost` | decimal(12,2) | 退货出库-成本 |
| `purchase_return_count` | decimal(12,2) | 退货出库-数量 |
| `remove_in_cost` | decimal(12,2) | 移除入库-成本 |
| `remove_in_count` | decimal(12,2) | 移除入库-数量 |
| `return_goods_in_cost` | decimal(12,2) | 退货入库-成本 |
| `return_goods_in_count` | decimal(12,2) | 退货入库-数量 |
| `split_in_cost` | decimal(12,2) | 拆分入库-成本 |
| `split_in_count` | decimal(12,2) | 拆分入库-数量 |
| `split_out_cost` | decimal(12,2) | 拆分出库-成本 |
| `split_out_count` | decimal(12,2) | 拆分出库-数量 |
| `wfs_out_cost` | decimal(12,2) | WFS出库-成本 |
| `wfs_out_count` | decimal(12,2) | WFS出库-数量 |
| `gifts_in_cost` | decimal(12,2) | 赠品入库-成本 |
| `gifts_in_count` | decimal(12,2) | 赠品入库-数量 |
| `rotation_day_cost` | decimal(12,2) | 周转天数-成本 |
| `rotation_day_count` | decimal(12,2) | 周转天数-数量 |
| `rotation_rate_cost` | decimal(15,4) | 周转率-成本 |
| `rotation_rate_count` | decimal(12,4) | 周转率-数量 |
| `sales_ratio_cost` | decimal(12,4) | 存销比-成本 |
| `sales_ratio_count` | decimal(12,4) | 存销比-数量 |
| `sales_rate` | decimal(12,4) | 动销率 |
| `start_date` | varchar(50) | 来源数据-搜索开始时间 |
| `end_date` | varchar(50) | 来源数据-搜索结束时间 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.14 `lx_statistics_local_new_detail`（库存报表-本地仓-新报表-明细）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `sys_wid` | int | 系统仓库ID |
| `ware_house_name` | varchar(50) | 仓库名称 |
| `seller_name` | varchar(50) | 店铺名称 |
| `product_name` | varchar(255) | 商品名称 |
| `product_type` | varchar(25) | 产品类型:普通产品/组合产品/辅料/捆绑产品 |
| `sku` | varchar(50) | SKU |
| `fnsku` | varchar(50) | FNSKU |
| `spu` | varchar(50) | SPU |
| `spu_name` | varchar(255) | 款名 |
| `brand` | varchar(50) | 品牌名称 |
| `category1` | varchar(50) | 一级类目-名称 |
| `category2` | varchar(50) | 二级类目-名称 |
| `category3` | varchar(50) | 三级类目-名称 |
| `attribute_text` | varchar(20) | 库存属性:全部/可售/待检/不可售 |
| `global_tags` | text | 产品标签列表 |
| `sku_attribute` | text | 产品属性 |
| `allocation_in_cost` | decimal(12,2) | 调拨入库-成本 |
| `allocation_in_count` | decimal(12,2) | 调拨入库-数量 |
| `allocation_in_transit_cost` | decimal(12,2) | 期末在途-成本 |
| `allocation_in_transit_count` | decimal(12,2) | 期末在途-数量 |
| `allocation_out_cost` | decimal(12,2) | 调拨出库-成本 |
| `allocation_out_count` | decimal(12,2) | 调拨出库-数量 |
| `change_of_standard_in_cost` | decimal(12,2) | 换标入库-成本 |
| `change_of_standard_in_count` | decimal(12,2) | 换标入库-数量 |
| `change_of_standard_out_cost` | decimal(12,2) | 换标出库-成本 |
| `change_of_standard_out_count` | decimal(12,2) | 换标出库-数量 |
| `cost_adjustment` | decimal(12,2) | 成本调整 |
| `day_early_cost` | decimal(12,2) | 期初库存-成本 |
| `day_early_count` | decimal(12,2) | 期初库存-数量 |
| `day_end_cost` | decimal(12,2) | 期末库存-成本 |
| `day_end_count` | decimal(12,2) | 期末库存-数量 |
| `fba_out_cost` | decimal(12,2) | FBA出库-成本 |
| `fba_out_count` | decimal(12,2) | FBA出库-数量 |
| `fbm_out_cost` | decimal(12,2) | FBM出库-成本 |
| `fbm_out_count` | decimal(12,2) | FBM出库-数量 |
| `inventory_deficit_out_cost` | decimal(12,2) | 盘亏出库-成本 |
| `inventory_deficit_out_count` | decimal(12,2) | 盘亏出库-数量 |
| `inventory_surplus_in_cost` | decimal(12,2) | 盘盈入库-成本 |
| `inventory_surplus_in_count` | decimal(12,2) | 盘盈入库-数量 |
| `other_in_cost` | decimal(12,2) | 其他入库-成本 |
| `other_in_count` | decimal(12,2) | 其他入库-数量 |
| `other_out_cost` | decimal(12,2) | 其他出库-成本 |
| `other_out_count` | decimal(12,2) | 其他出库-数量 |
| `outsourcing_in_cost` | decimal(12,2) | 委外入库-成本 |
| `outsourcing_in_count` | decimal(12,2) | 委外入库-数量 |
| `outsourcing_out_cost` | decimal(12,2) | 委外出库-成本 |
| `outsourcing_out_count` | decimal(12,2) | 委外出库-数量 |
| `processing_in_cost` | decimal(12,2) | 加工入库-成本 |
| `processing_in_count` | decimal(12,2) | 加工入库-数量 |
| `processing_out_cost` | decimal(12,2) | 加工出库-成本 |
| `processing_out_count` | decimal(12,2) | 加工出库-数量 |
| `purchase_in_cost` | decimal(12,2) | 采购入库-成本 |
| `purchase_in_count` | decimal(12,2) | 采购入库-数量 |
| `purchase_return_cost` | decimal(12,2) | 退货出库-成本 |
| `purchase_return_count` | decimal(12,2) | 退货出库-数量 |
| `remove_in_cost` | decimal(12,2) | 移除入库-成本 |
| `remove_in_count` | decimal(12,2) | 移除入库-数量 |
| `return_goods_in_cost` | decimal(12,2) | 退货入库-成本 |
| `return_goods_in_count` | decimal(12,2) | 退货入库-数量 |
| `rotation_day_cost` | decimal(12,2) | 周转天数-成本 |
| `rotation_day_count` | decimal(12,2) | 周转天数-数量 |
| `split_in_cost` | decimal(12,2) | 拆分入库-成本 |
| `split_in_count` | decimal(12,2) | 拆分入库-数量 |
| `split_out_cost` | decimal(12,2) | 拆分出库-成本 |
| `split_out_count` | decimal(12,2) | 拆分出库-数量 |
| `wfs_out_cost` | decimal(12,2) | WFS出库-成本 |
| `wfs_out_count` | decimal(12,2) | WFS出库-数量 |
| `gifts_in_cost` | decimal(12,2) | 赠品入库-成本 |
| `gifts_in_count` | decimal(12,2) | 赠品入库-数量 |
| `rotation_rate_count` | decimal(12,4) | 周转率-数量 |
| `rotation_rate_cost` | decimal(15,4) | 周转率-成本 |
| `sales_ratio_count` | decimal(12,4) | 存销比-数量 |
| `sales_ratio_cost` | decimal(12,4) | 存销比-成本 |
| `child_list` | text | 子项，与外层列表字段一致-库存状态为全部时会有数据 |
| `start_date` | varchar(50) | 来源数据-搜索开始时间 |
| `end_date` | varchar(50) | 来源数据-搜索结束时间 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.15 `lx_statistics_storage_fee_month`（FBA月仓储费）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `sid` | int | 店铺ID |
| `asin` | varchar(20) | ASIN |
| `fnsku` | varchar(50) | FNSKU |
| `product_name` | varchar(255) | 产品名称 |
| `fulfillment_center` | varchar(20) | 仓库编号 |
| `country_code` | varchar(10) | 国家代码 |
| `longest_side` | varchar(20) | 长边 |
| `median_side` | varchar(20) | 中间边 |
| `shortest_side` | varchar(20) | 短边 |
| `measurement_units` | varchar(20) | 尺寸单位 |
| `weight` | varchar(20) | 重量 |
| `weight_units` | varchar(20) | 重量单位 |
| `item_volume` | varchar(20) | 单件体积 |
| `volume_units` | varchar(20) | 体积单位 |
| `product_size_tier` | varchar(50) | 产品尺寸标准 |
| `average_quantity_on_hand` | varchar(20) | 平均库存量 |
| `average_quantity_pending_removal` | varchar(20) | 待移除库存量 |
| `estimated_total_item_volume` | varchar(20) | 预估总体积 |
| `month_of_charge` | varchar(25) | 收费月份 |
| `storage_rate` | varchar(20) | 仓储费率 |
| `currency` | varchar(10) | 币种 |
| `estimated_monthly_storage_fee` | varchar(20) | 预估月仓储费 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.16 `lx_statistics_storage_fee_long_term`（FBA长期仓储费）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键ID |
| `sid` | int | 店铺ID |
| `snapshot_date` | varchar(50) | 时间 |
| `sku` | varchar(100) | SKU |
| `fnsku` | varchar(100) | FNSKU |
| `asin` | varchar(50) | ASIN |
| `product_name` | varchar(500) | 标题 |
| `condition` | varchar(50) | 状况 |
| `qty_charged_12_mo_long_term_storage_fee` | varchar(50) | 12个月以上收费商品量 |
| `per_unit_volume` | varchar(50) | 单个商品体积 |
| `currency` | varchar(10) | 币种 |
| `12_mo_long_terms_storage_fee` | varchar(50) | 12个月以上收费 |
| `qty_charged_6_mo_long_term_storage_fee` | varchar(50) | 6-12个月收费商品量 |
| `6_mo_long_terms_storage_fee` | varchar(50) | 6-12个月收费 |
| `volume_unit` | varchar(25) | 体积单位 |
| `country` | varchar(10) | 国家 |
| `is_small_and_light` | varchar(10) | 是否是亚马逊轻小商品计划：Y 是，N 否, 空表示未知 |
| `enrolled_in_small_and_light` | varchar(10) | 是否注册亚马逊轻小商品计划：Y 是，N 否 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.17 `lx_replenishment_suggest_restocking`（补货列表）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `parent_id` | bigint NOT NULL DEFAULT '0' | 父级id；父级为0 |
| `basic_info` | text | 基础数据 |
| `amazon_quantity_info` | text | 亚马逊数量 |
| `scm_quantity_info` | text | 供应链数量 |
| `sales_info` | text | 历史销量数据 |
| `suggest_info` | text | 建议数据 |
| `ext_info` | text | 附加信息 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.18 `lx_storage_warehouse`（仓库）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL | 主键 |
| `wid` | int | 系统仓库id |
| `name` | varchar(50) | 仓库名 |
| `type` | int | 仓库类型：1 本地仓，2 海外仓，3 平台仓，4 AWD仓 |
| `is_delete` | varchar(10) | 是否删除：0 未删除，1 已删除 |
| `wp_id` | int | 服务商ID，仅type=3且仓库为第三方海外仓时有值 |
| `wp_name` | varchar(50) | 系统服务商名称 |
| `sub_type` | int | 海外仓子类型：1 无API海外仓 2 有API海外仓【此参数只在type=3生效】 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.19 `lx_fba_shipment`（FBA货件）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `record_id` | int | 唯一记录id |
| `sid` | int | 店铺id |
| `seller` | varchar(255) | 店铺名称 |
| `uid` | int | 创建人id |
| `username` | varchar(100) | 创建人姓名 |
| `shipment_id` | varchar(255) | 亚马逊货件编号 |
| `shipment_name` | varchar(255) | 货件名称 |
| `sta_shipment_id` | varchar(255) | 亚马逊货件id（sta货件时返回） |
| `sta_inbound_plan_id` | varchar(255) | 亚马逊货件编号（sta货件时返回） |
| `sta_plan_name` | varchar(255) | STA任务名称（sta货件时返回） |
| `is_closed` | tinyint | 是否是已完成状态：0 进行中，1 已完成 |
| `shipment_status` | varchar(100) | 状态：working/shipped/In_transit/delivered/Check_in/receiving/closed/cancelled/delete/error |
| `gmt_modified` | varchar(255) | 数据更新时间 |
| `gmt_create` | varchar(255) | 数据创建时间 |
| `sync_time` | varchar(255) | 同步时间【已废弃】 |
| `destination_fulfillment_center_id` | varchar(255) | 物流中心编码 |
| `is_synchronous` | tinyint | 是否erp创建：0 erp创建，1 亚马逊后台同步 |
| `is_uploaded_box` | tinyint | 是否已上传装箱信息：0 未上传，1 已上传 |
| `is_sta` | tinyint | 是否sta货件：0 否，1 是 |
| `shipping_mode` | varchar(100) | 货件类型(GROUND_SMALL_PARCEL/FREIGHT_LTL) |
| `shipping_solution` | varchar(100) | 承运人(USE_YOUR_OWN_CARRIER/AMAZON_PARTNERED_CARRIER) |
| `alpha_code` | varchar(100) | 承运方式编码 |
| `alpha_name` | varchar(100) | 承运方式名称 |
| `sta_shipment_date` | varchar(100) | 发货日期 |
| `sta_delivery_start_date` | varchar(100) | 送达时段-开始时间 |
| `sta_delivery_end_date` | varchar(100) | 送达时段-结束时间 |
| `tracking_number_list` | text | 追踪编号（SPD类型货件时返回） |
| `bill_of_lading_number` | varchar(255) | 提货单号（BOL） |
| `freight_bill_number` | varchar(255) | 跟踪编号（PRO） |
| `item_list` | text | 子项数据 |
| `working_time` | varchar(100) | WORKING时间 |
| `shipped_time` | varchar(100) | SHIPPED时间 |
| `receiving_time` | varchar(100) | RECEIVING时间 |
| `closed_time` | varchar(100) | CLOSED时间 |
| `reference_id` | varchar(255) | Reference ID |
| `ship_from_address` | text | 发货地址 |
| `ship_to_address` | text | 配送地址 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.20 `lx_fba_shipment_plan`（FBA发货计划）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `ispg_id` | int | 发货计划组ID |
| `plan_create_time` | varchar(50) | 发货计划创建时间 |
| `seq` | varchar(50) | 批次号 |
| `remark` | varchar(500) | 备注 |
| `create_user` | varchar(50) | 创建用户 |
| `custom_fields` | text | 自定义字段 |
| `list` | longtext | 子项目列表 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.21 `lx_inbound_shipment_detail`（FBA发货单详情）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL | 主键 |
| `shipment_id` | int | 发货单ID |
| `tracking_id` | int | 物流追踪(运单)ID |
| `shipment_sn` | varchar(100) | 发货单号 |
| `status` | int | 发货单状态-1:待配货,0:待发货,1:已发货,3:已作废,4:已删除 |
| `shipment_time` | varchar(100) | 发货时间 |
| `wid` | int | 仓库ID |
| `gmt_modified` | varchar(100) | 修改时间 |
| `gmt_create` | varchar(100) | 创建时间 |
| `remark` | varchar(512) | 备注 |
| `creator_uid` | int | 创建人UID |
| `opt_uid` | int | 最后操作人UID |
| `msku_count` | int | 种类数 |
| `quantity_total` | int | 发货总量 |
| `logistics_channel_id` | int | 渠道商ID |
| `confirm_uid` | int | 确认人UID |
| `shipment_uid` | int | 发货人UID |
| `confirm_time` | int | 确认时间(时间戳格式) |
| `expected_arrival_date` | varchar(100) | 预计到货日期 |
| `is_related` | int | 1=关联；0=不关联 |
| `is_whb_checked` | int | 1=自动选择仓位扣减；0=不选择仓位扣减 |
| `head_fee_type` | int | 头程费分配方式：0 产品-计费重（默认）,1 产品-实重,2 产品-体积重,3 产品-数量,4 自定义,5 箱子-体积 |
| `is_points_behind` | int | 是否分抛计算(0:否,1:是) |
| `points_behind_coeffient` | int | 分抛系数(0-100) |
| `is_return_stock` | int | 是否恢复库存(0=否,1=是) |
| `ware_house_bak_name` | varchar(100) | 仓库名称(作为被删仓库的备用值) |
| `is_print` | int | 是否打印拣货单（0：未打印，1：已打印） |
| `print_num` | int | 打印次数 |
| `is_pick` | int | 是否拣货（0：未拣货，1:已拣货） |
| `pick_time` | varchar(100) | 完成拣货时间 |
| `print_time` | int | 最后一次打印时间 |
| `etd_date` | varchar(100) | 开船时间 |
| `eta_date` | varchar(100) | 预计到港时间 |
| `delivery_date` | varchar(100) | 实际妥投时间 |
| `order_logistics_status` | varchar(100) | 订单物流状态 |
| `shipment_user` | varchar(64) | 发货人 |
| `wname` | varchar(64) | 仓库名称 |
| `create_user` | varchar(64) | 创建人 |
| `file_id` | varchar(64) | 附件文件 |
| `actual_shipment_time` | varchar(100) | 实际发货时间 |
| `logistics_channel_name` | varchar(100) | 物流渠道名称 |
| `is_delete` | int | 0-未删除 |
| `destination_fulfillment_center_id` | varchar(64) | 物流中心编码 |
| `cancel_time` | int | 作废时间(时间戳格式) |
| `logistics_provider_id` | int | 物流商ID |
| `logistics_provider_name` | varchar(64) | 物流商名称 |
| `transportation_cost_status` | int | 物流费用填写状态(1-3) |
| `other_cost_status` | int | 其他费用填写状态(1-3) |
| `pay_status` | int | 付款状态(0-4) |
| `predicted_transportation_cost_status` | int | 预估物流费用填写状态(1-3) |
| `predicted_other_cost_status` | int | 预估其他费用填写状态(1-3) |
| `audit_status` | int | 审批状态(121-124) |
| `stash_shipment_uid` | int | 暂存发货人UID（审批流专用） |
| `stash_shipment_time` | int | 暂存发货时间（审批流专用） |
| `is_relate_aux` | int | 是否关联辅料(0：否，1：是) |
| `items` | longtext | 商品列表(JSON数组) |
| `logistics` | text | 物流信息列表(JSON数组) |
| `auxs` | text | 辅料列表(JSON数组) |
| `principals` | text | 权限人列表(JSON数组) |
| `msg` | varchar(512) | — |
| `status_name` | varchar(32) | 状态名称 |
| `last_update_time` | varchar(100) | 最后修改日期 |
| `head_fee_type_name` | varchar(100) | 头程费用名称 |
| `file_list` | text | 附件列表(JSON数组) |
| `box_type` | varchar(32) | 装箱类型(SINGLE/MULTIPLE) |
| `box_remark` | varchar(512) | 装箱备注 |
| `logistics_list_type` | text | 物流信息版本0旧版1新版 |
| `head_logistics_list` | text | 新版物流信息列表(JSON数组) |
| `box_list` | text | 箱规列表(JSON数组) |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.22 `lx_reports_fulfillment_removal_order`（亚马逊源报表-移除订单（新））

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL | 主键 |
| `seller_id` | varchar(50) | 亚马逊店铺id |
| `sid` | int | 店铺id【为0代表未确定订单店铺】 |
| `region` | varchar(10) | 地区 |
| `request_date` | varchar(50) | 订单日期 |
| `order_id` | varchar(50) | 订单号 |
| `order_type` | varchar(25) | 订单类型 |
| `order_status` | varchar(25) | 订单状态 |
| `last_updated_date` | varchar(50) | 更新时间 |
| `sku` | varchar(100) | msku |
| `fnsku` | varchar(50) | fnsku |
| `disposition` | varchar(50) | 库存属性 |
| `requested_quantity` | int | 请求数量 |
| `cancelled_quantity` | int | 取消数量 |
| `disposed_quantity` | int | 已处理数量 |
| `shipped_quantity` | int | 已发货数量 |
| `in_process_quantity` | int | 处理中数量 |
| `removal_fee` | varchar(10) | 移除费用 |
| `currency` | varchar(10) | 币种 |
| `address_detail` | text | 配送地址 |
| `country_code` | varchar(10) | 国家编码 |
| `local_sku` | varchar(100) | sku |
| `local_name` | varchar(500) | 品名 |
| `create_time` | datetime | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) DEFAULT b'0' | 删除标识 0-未删除 1-已删除 |

### 2.23 `lx_finance_fba_cost_stream`（FBA成本计价流水）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `stream_date` | varchar(50) | 库存动作日期 |
| `settlement_date` | varchar(50) | 结算日期 |
| `source_data_time` | varchar(100) | 数据源更新时间 |
| `unique_key` | varchar(100) | 主键 |
| `data_version` | varchar(100) | 计算版本号 |
| `business_number` | varchar(100) | 业务编号 |
| `origin_account` | varchar(500) | 源头单据号 |
| `sku` | varchar(100) | SKU |
| `msku` | varchar(100) | MSKU |
| `wh_name` | varchar(100) | 仓库名称 |
| `shop_name` | varchar(100) | 店铺名称 |
| `disposition_type` | varchar(50) | 库存属性 |
| `business_type` | varchar(20) | 出入库类型编码 |
| `business_type_desc` | varchar(100) | 出入库类型名称 |
| `cost_source` | varchar(50) | 成本取值来源 |
| `change_quantity` | decimal(12,2) | 变动数量 |
| `change_purchase_unit_price` | varchar(50) | 变动采购单价 |
| `change_purchase_amount` | varchar(50) | 变动采购成本 |
| `change_logistics_unit_price` | varchar(50) | 变动头程单价 |
| `change_logistics_amount` | varchar(50) | 变动头程成本 |
| `change_other_unit_price` | varchar(50) | 变动其他单价 |
| `change_other_amount` | varchar(50) | 变动其他成本 |
| `balance_quantity` | decimal(12,2) | 结存数量 |
| `balance_purchase_unit_price` | varchar(50) | 结存采购成本单价 |
| `balance_purchase_amount` | varchar(50) | 结存采购成本 |
| `balance_logistics_unit_price` | varchar(50) | 结存头程成本单价 |
| `balance_logistics_amount` | varchar(50) | 结存头程成本 |
| `balance_other_unit_price` | varchar(50) | 结存其他成本单价 |
| `balance_other_amount` | varchar(50) | 结存其他成本 |
| `sales_platform` | varchar(50) | 销售平台 |
| `reason` | varchar(500) | 盘点原因 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.24 `lx_sales_mws_listing`（亚马逊Listing）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL AUTO_INCREMENT | 主键 |
| `listing_id` | varchar(255) | 亚马逊定义的listing的id【可能为空】 |
| `sid` | int | 店铺id |
| `marketplace` | varchar(50) | 国家 |
| `seller_sku` | varchar(255) | MSKU |
| `fnsku` | varchar(255) | FNSKU |
| `asin` | varchar(255) | ASIN |
| `parent_asin` | varchar(255) | 父ASIN |
| `small_image_url` | varchar(500) | 商品缩略图地址 |
| `status` | int | 状态：0 停售，1 在售 |
| `is_delete` | int | 是否删除：0 否，1 是 |
| `item_name` | varchar(500) | 标题 |
| `local_sku` | varchar(255) | 本地产品SKU |
| `local_name` | varchar(255) | 品名 |
| `currency_code` | varchar(25) | 币种 |
| `price` | varchar(50) | 价格【不包含促销，运费，积分】 |
| `landed_price` | varchar(50) | 总价【包含了促销、运费、积分】 |
| `listing_price` | varchar(50) | 优惠价 |
| `shipping` | varchar(50) | 运费 |
| `points` | varchar(50) | 积分，日本站才有 |
| `quantity` | int | FBM库存 |
| `afn_fulfillable_quantity` | int | FBA可售 |
| `afn_unsellable_quantity` | int | FBA不可售 |
| `reserved_fc_transfers` | int | 待调仓 |
| `reserved_fc_processing` | int | 调仓中 |
| `reserved_customerorders` | int | 待发货 |
| `afn_inbound_shipped_quantity` | int | 在途 |
| `afn_inbound_working_quantity` | int | 计划入库 |
| `afn_inbound_receiving_quantity` | int | 入库中 |
| `open_date` | varchar(100) | 商品创建时间 |
| `open_date_display` | varchar(100) | 商品创建时间，格式：Y-m-d H:i:s+时区 |
| `listing_update_date` | varchar(100) | All Listing报表更新时间 (注意：此为零时区时间) |
| `seller_rank` | int | 排名 |
| `seller_brand` | varchar(255) | 亚马逊品牌 |
| `seller_category` | varchar(255) | 排名所属的类别 |
| `review_num` | int | 评论条数 |
| `last_star` | varchar(10) | 星级评分 |
| `fulfillment_channel_type` | varchar(25) | 配送方式 |
| `principal_info` | text | 负责人信息 |
| `seller_category_new` | text | 排名所属的类别 |
| `pair_update_time` | varchar(100) | 配对更新时间 (注意：此为北京时间) |
| `first_order_time` | varchar(50) | 首单时间，格式：Y-m-d |
| `on_sale_time` | varchar(50) | 开售时间，格式：Y-m-d |
| `dimension_info` | text | 尺寸信息，没有尺寸信息时是空 |
| `small_rank` | text | 小类排名信息 |
| `global_tags` | text | 全局标签 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |

### 2.25 `lx_statistics_product_performance`（产品表现）

| 字段名 | 类型 | 中文注释 |
|--------|------|---------|
| `id` | bigint NOT NULL | 主键 |
| `parent_asins` | text | 父asins信息 |
| `asins` | text | asin列表 |
| `price_list` | text | 价格列表 |
| `prev_cate_rank` | int | 上一次大类排名 |
| `item_name` | varchar(500) | 标题 |
| `cate_rank` | int | 大类排名 |
| `small_cate_rank` | text | 小类排名 |
| `currency_icon` | varchar(25) | 币种符号 |
| `seller_store_countries` | text | 店铺/国家 |
| `categories` | text | 分类，字符串数组 |
| `brands` | text | 品牌，字符串数组 |
| `principal_names` | text | 负责人 |
| `developer_names` | text | 开发人 |
| `month_stock_sales_ratio` | decimal(12,2) | 月库销比 |
| `volume` | int | 销量 |
| `order_items` | int | 订单量 |
| `order_items_chain` | int | 环比订单量 |
| `amount` | decimal(12,2) | 销售额 |
| `volume_chain_ratio` | decimal(12,4) | 销量环比 |
| `volume_chain` | int | 环比销量 |
| `amount_chain_ratio` | decimal(12,4) | 销量额环比 |
| `amount_chain` | decimal(12,2) | 环比销量额 |
| `order_chain_ratio` | decimal(12,4) | 订单量环比 |
| `b2b_volume` | int | B2B销量 |
| `b2b_amount` | decimal(12,2) | B2B销售额 |
| `b2b_order_items` | int | B2B订单量 |
| `grossprofit` | decimal(12,2) | 结算毛利润 |
| `predict_gross_profit` | decimal(12,2) | 订单毛利润 |
| `gross_margin` | decimal(12,4) | 结算毛利率 |
| `predict_gross_margin` | decimal(12,4) | 订单毛利率 |
| `roi` | decimal(12,4) | ROI |
| `promotion_volume` | int | 促销销量 |
| `promotion_amount` | decimal(12,2) | 促销销售额 |
| `promotion_order_items` | int | 促销订单量 |
| `promotion_discount` | decimal(12,2) | 促销折扣 |
| `reviews_count` | int | 评论数 |
| `return_count` | int | 退款量 |
| `return_rate` | decimal(12,4) | 退款率 |
| `afn_fulfillable_quantity` | int | FBA可售 |
| `afn_inbound_receiving_quantity` | int | FBA入库中 |
| `afn_inbound_shipped_quantity` | int | FBA在途 |
| `afn_inbound_working_quantity` | int | FBA计划入库 |
| `afn_unsellable_quantity` | int | FBA不可售 |
| `reserved_fc_processing` | int | 调仓中 |
| `reserved_fc_transfers` | int | 待调仓 |
| `fbm_quantity` | int | FBM可售 |
| `reserved_customerorders` | int | 待发货 |
| `stock_up_num` | int | 实际在途 |
| `clicks` | int | 点击量 |
| `available_days` | int | 可售预估天数 |
| `fbm_available_days` | int | FBM可售天数 |
| `avg_star` | decimal(12,2) | 评分 |
| `prev_star` | decimal(12,2) | 前一个评分 |
| `comment_rate` | decimal(12,2) | 留评率 |
| `sessions` | int | Sessions-Browser |
| `sessions_mobile` | int | Sessions-Mobile |
| `sessions_total` | int | Sessions-Total |
| `buy_box_percentage` | decimal(12,2) | Buybox |
| `page_views` | int | PV-Browser |
| `page_views_mobile` | int | PV-Mobile |
| `page_views_total` | int | PV-Total |
| `adv_rate` | decimal(12,4) | 广告订单量占比 |
| `ad_cvr` | decimal(12,4) | 广告CVR |
| `volume_cvr` | decimal(12,4) | 销量CVR |
| `cvr` | decimal(12,4) | CVR |
| `ctr` | decimal(12,4) | CTR,点击量/展示量 |
| `acoas` | decimal(12,4) | 广告花费/总销售额 |
| `acos` | decimal(12,4) | 广告花费/广告销售额 |
| `has_oprator_log` | tinyint(1) | 是否有操作日志 |
| `return_goods_count` | int | 退货量 |
| `return_goods_rate` | decimal(12,4) | 退货率 |
| `cpc` | decimal(12,2) | cpc,花费/点击量 |
| `spend` | decimal(12,2) | 广告花费【组成广告花费项目的总计】 |
| `shared_cost_of_advertising` | decimal(12,2) | 差异分摊 |
| `shared_ads_sb_cost` | decimal(12,2) | SB广告费 |
| `shared_ads_sbv_cost` | decimal(12,2) | SBV广告费 |
| `ads_sd_cost` | decimal(12,2) | SD广告费 |
| `ads_sp_cost` | decimal(12,2) | SP广告费 |
| `roas` | decimal(12,2) | ROAS,广告销售额/广告花费 |
| `asoas` | decimal(12,4) | ASoAS,广告销售额/总销售额 |
| `cpo` | decimal(12,2) | CPO,广告花费/广告订单量 |
| `cpm` | decimal(12,2) | CPM,广告花费/(1000*展示量) |
| `ad_sales_amount` | decimal(12,2) | 广告销售额 |
| `ads_sp_sales` | decimal(12,2) | SP广告销售额 |
| `ads_sd_sales` | decimal(12,2) | SD广告销售额 |
| `shared_ads_sb_sales` | decimal(12,2) | SB广告销售额 |
| `shared_ads_sbv_sales` | decimal(12,2) | SBV广告销售额 |
| `ad_order_quantity` | int | 广告订单量 |
| `impressions` | int | 展示 |
| `sids` | text | 店铺id |
| `net_amount` | decimal(12,2) | 净销售额 |
| `small_image_url` | varchar(512) | 页面所对应的缩略图地址,取自销量最高的msku的缩略图 |
| `ranking_update_time` | varchar(100) | 排名更新时间【已废弃】 |
| `avg_volume` | decimal(12,2) | 平均销量 |
| `avg_custom_price` | decimal(12,2) | 销售均价 |
| `icon_num` | int | 运营日志数量，用于前端判断是否存在运营日志数据 |
| `sku` | varchar(100) | sku【sku维度才有值】 |
| `local_name` | varchar(255) | 品名，【sku维度才有值】 |
| `spu_spu_names` | text | SPU数据 |
| `attributes` | text | 属性，注意内部属性与属性值的分隔符是"\001：\001"，存在特殊隐藏字符 |
| `cg_price` | decimal(12,2) | 采购成本，sku维度特有 |
| `whs_value` | decimal(12,2) | 可用货值，sku维度特有 |
| `cg_price_currency_icon` | varchar(25) | 采购成本，可用货值的币种符号 |
| `local_quantity` | int | 本地可用，sku维度特有 |
| `oversea_quantity` | int | 海外仓可用，sku维度特有 |
| `inventory_sales_ratio` | decimal(12,4) | 存销比，sku维度特有 |
| `avg_landed_price` | decimal(12,2) | 平均售价，sku维度特有 |
| `suppliers` | text | 供应商，sku维度特有 |
| `model` | text | 型号，sku维度特有 |
| `return_amount` | double | 退款金额 |
| `product_create_time` | varchar(100) | product创建时间，sku维度特有 |
| `ad_direct_sales_amount` | decimal(12,2) | 直接成交销售额 |
| `ad_direct_order_quantity` | int | 直接成交订单量 |
| `rank_category` | varchar(100) | 大类排名分类 |
| `available_inventory` | text | 可用库存数据 |
| `tag_set` | text | Listing标签信息 |
| `chain_start_date` | varchar(100) | 环比开始时间 |
| `chain_end_date` | varchar(100) | 环比结束时间 |
| `available_inventory_formula_zh` | varchar(255) | 可用库存计算公式 |
| `start_date` | varchar(100) | 来源数据-搜索开始时间 |
| `end_date` | varchar(100) | 来源数据-搜索结束时间 |
| `create_time` | datetime NOT NULL | 创建时间 |
| `update_time` | datetime | 更新时间 |
| `delete_flag` | bit(1) NOT NULL DEFAULT b'0' | 删除标识 |
