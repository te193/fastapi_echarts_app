# 广告预算 MSKU 大小写修复与当日续跑计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留 CJ016A/CJ016a 两条源记录，修复预算快照主键冲突，并完成 2026-10-29 剩余 ETL 和钉钉完成通知。

**Architecture:** 新表 DDL 明确 MSKU 使用 utf8mb4_bin；旧表通过 ensure_tables 的幂等检查升级相同字段。只续跑原批次未成功的 pricing、return_strategy，通知汇总原批次七个成功步骤和续跑两个步骤。

**Tech Stack:** Python、PyMySQL、MySQL 8、pytest、现有 ETL 调度及钉钉工具。

**Spec:** 当前会话用户授权，及原批次 logs/etl_run_summary_20261029_080002.json。

## Global Constraints

- 源表只读，保持源表 MSKU 大小写语义；不忽略、合并冲突记录。
- 不重跑已成功的七步；沿用日期 snapshot_date=2026-10-29 / biz_date=2026-10-28。
- 保留其他未提交改动；不提交混合工作区。

## Review Focus

- 新建数据库同样保留大小写不同的 MSKU。
- 已有表的升级保留历史行、字段注释及主键。
- 重复初始化无额外表重建。
- 回滚过的预算失败分区由正常预算重载重新生成。
- 仅在原批次七步和续跑两步全部成功后发送完整成功通知。

## Tasks

- [x] 真实 MySQL 回归测试复现新表与旧表两种主键冲突。
- [x] 修改预算 DDL，增加幂等旧表 collation 升级，运行预算相关回归。
- [x] 审查变更，确认无遗留任务后在每日锁保护下升级正式目标表，核对行数与原始字段值。
- [x] 续跑定价及策略，直接会话监测至结束，校验今日结果与完整钉钉成功回执。

## Ledger

- Ruling: 沿用当前工作区，不新建 worktree。运行环境依赖现有未提交调度和保护逻辑；只修改预算相关内容并检查差异。
- 原因证据：源表 seller_sku_adj=utf8mb4_bin；目标表=utf8mb4_0900_ai_ci；德国 CHOOJEE 同时存在 CJ016A/CJ016a。
- 回归：两个真实 MySQL 用例先因 1062 失败，修复后预算 DDL、历史保护、数据/API 共 54 项通过；独立审查无阻塞项。
- 正式迁移：197564 行，主键字节 CRC 摘要 1776206400，月预算 5012139.33、周预算 1210756.09，迁移前后相同。DDL 和摘要备份 logs/ad_budget_collation_before_20261029.json。
- 续跑批次 20261029_091132，启动后 ad_budget_snapshot 已成功写入 27724 行。
- Ruling: 上游 09:08 实际主表与每日快照仍为 10/28，续跑临时定价模块等待 10/29 物理数据和三个任务同时完成，上限 11:30；不改上游、不使用昨日数据替代。
- 另 42 项日调度与定价流程回归通过，共 96 项；临时恢复脚本也已独立审查。
- 09:39 上游主表重建窗口返回 1146，091132 批次退出，失败通知已发送；独立六步均 exit_code=0，保留成功日志。不重跑已完成独立步骤。
- 修订临时等待脚本：1146/1412 与常见连接临时错误等待重试，buffered cursor，连接/读超时受限。
- 09:41 当前及每日快照已各 40919 行，当日价格内容摘要一致：xor=1411686556，sum=87993615765100；仅快照审计日志仍为昨日成功。用户明确答复“定价表跑完了”。
- Ruling: 仅在其他任务当日成功、快照审计为历史成功、两张当日物理表价格内容一致时接受日志滞后；不接受当日失败。只读就绪检查已通过，09:44 停止旧只读等待并启动后半段续跑，未修改源库或审计日志。
- 最终续跑批次 20261029_094446，10:00:37 完成，pricing 和 return_strategy 均 success/0，两个 stderr 均为空；与原七步合计 9/9 成功。独立六步沿用 091132 成功证据。
- 钉钉整批成功通知 10:00:37 发送成功，receipt=logs/dingtalk_recovery_20261029_094446_all_success.sent.json；源/续跑完整核对报告 logs/etl_recovery_verified_20261029_094446.json。最终确认任务锁已释放、MSKU collation=utf8mb4_bin、CJ016A/CJ016a 均保留。
