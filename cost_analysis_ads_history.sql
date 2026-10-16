-- Target-cohort full-month July/August ad-cost ratio and actual-FBA-cost volatility.
WITH cohort AS (
  SELECT DISTINCT b.country,b.store,b.msku,p.`店铺名` full_store
  FROM dws_datasync.dws_标签表 b
  JOIN temporary_dwd.`在库节点_输出定价表` p
    ON p.`国家`=b.country AND p.`新店铺`=b.store AND p.msku=b.msku
  WHERE b.data_date='2026-09-13' AND b.label_id=1304 AND b.label_period='30d'
    AND b.country IN ('德国','法国','意大利','西班牙','荷兰','英国','美国')
    AND EXISTS (
      SELECT 1 FROM dws_datasync.dws_标签表 a
      WHERE a.data_date=b.data_date AND a.label_id=301 AND a.label_period='current'
        AND a.store=b.store AND a.msku=b.msku
    )
)
 , monthly AS (
  SELECT r.date_date,r.country,r.store_name,r.msku,
         SUM(r.total_sales_quantity) qty,SUM(r.total_sales_amount) sales,
         -SUM(r.total_ads_cost) ad_spend,-SUM(r.fba_delivery_fee) fba_cost,
         SUM(r.gross_profit) gross_profit
  FROM dwd_datasync.lx_finance_profit_report_msku r
  JOIN cohort c ON c.country=r.country AND c.full_store=r.store_name AND c.msku=r.msku
  WHERE r.date_date IN ('2026-07~2026-07','2026-08~2026-08')
  GROUP BY r.date_date,r.country,r.store_name,r.msku
), paired AS (
  SELECT a.country,a.store_name,a.msku,
         a.qty q0,b.qty q1,a.sales s0,b.sales s1,
         a.ad_spend/a.sales ad0,b.ad_spend/b.sales ad1,
         a.fba_cost/a.qty f0,b.fba_cost/b.qty f1,
         a.gross_profit/a.sales m0,b.gross_profit/b.sales m1
  FROM monthly a JOIN monthly b
    ON a.country=b.country AND a.store_name=b.store_name AND a.msku=b.msku
  WHERE a.date_date='2026-07~2026-07' AND b.date_date='2026-08~2026-08'
    AND a.qty>=5 AND b.qty>=5 AND a.sales>0 AND b.sales>0
)
SELECT COUNT(*) valid_pairs,
       SUM(ad0>0 AND ad1>=0) valid_ad,
       SUM(ad0>0 AND ad1>=0 AND ABS(ad1-ad0)/ad0>=0.20) ad_ge20_rel,
       SUM(ad0>0 AND ad1>=0 AND ABS(ad1-ad0)/ad0>=0.20 AND ABS(ad1-ad0)>=0.02) ad_ge20_rel_2pp,
       SUM(ad0>0 AND ad1>=0 AND (ad1-ad0)/ad0>=0.20 AND ad1-ad0>=0.02) ad_up20_rel_2pp,
       SUM(f0>0 AND f1>0) valid_fba,
       SUM(f0>0 AND f1>0 AND ABS(f1-f0)/f0>=0.20) fba_ge20_rel,
       SUM(f0>0 AND f1>0 AND ABS(f1-f0)/f0>=0.20 AND ABS(f1-f0)>=1) fba_ge20_rel_1cny,
       SUM(m1<0.05) actual_margin_lt5
FROM paired;
