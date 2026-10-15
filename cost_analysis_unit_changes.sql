WITH paired AS (
  SELECT old.`国家` country,old.`店铺名` store,old.msku,
         old.`采购单价_cny` p0,new.`采购单价_cny` p1,
         old.`单位头程_cny` h0,new.`单位头程_cny` h1,
         old.`fba费用_cny` f0,new.`fba费用_cny` f1
  FROM temporary_dwd.`在库节点_输出定价表_每日快照` old
  JOIN temporary_dwd.`在库节点_输出定价表_每日快照` new
    ON new.`数据日期`='2026-09-14' AND new.`国家`=old.`国家`
   AND new.`店铺名`=old.`店铺名` AND new.msku=old.msku
  JOIN dws_datasync.dws_标签表 b
    ON b.data_date='2026-09-13' AND b.label_id=1304 AND b.label_period='30d'
   AND b.country=old.`国家` AND b.store=old.`新店铺` AND b.msku=old.msku
  WHERE old.`数据日期`='2026-08-21'
    AND old.`国家` IN ('德国','法国','意大利','西班牙','荷兰','英国','美国')
    AND EXISTS (
      SELECT 1 FROM dws_datasync.dws_标签表 a
      WHERE a.data_date=b.data_date AND a.label_id=301 AND a.label_period='current'
        AND a.store=b.store AND a.msku=b.msku
    )
), cost_rows AS (
  SELECT CASE c.i WHEN 1 THEN '采购' WHEN 2 THEN '头程' ELSE 'FBA' END component,
         CASE c.i WHEN 1 THEN p0 WHEN 2 THEN h0 ELSE f0 END baseline,
         CASE c.i WHEN 1 THEN p1 WHEN 2 THEN h1 ELSE f1 END current
  FROM paired CROSS JOIN (SELECT 1 i UNION ALL SELECT 2 UNION ALL SELECT 3) c
)
SELECT component,COUNT(*) matched,
       SUM(baseline>0 AND current>0) valid,
       SUM(baseline>0 AND current>0 AND ABS(current-baseline)/baseline>=0.05) ge5,
       SUM(baseline>0 AND current>0 AND ABS(current-baseline)/baseline>=0.10) ge10,
       SUM(baseline>0 AND current>0 AND ABS(current-baseline)/baseline>=0.20) ge20,
       SUM(baseline>0 AND current>0 AND ABS(current-baseline)/baseline>=0.30) ge30,
       SUM(baseline>0 AND current>0 AND ABS(current-baseline)/baseline>=0.50) ge50,
       SUM(baseline>0 AND current>0 AND ABS(current-baseline)/baseline>=0.20 AND ABS(current-baseline)>=1) ge20_1cny,
       SUM(baseline>0 AND current>0 AND (current-baseline)/baseline>=0.20 AND current-baseline>=1) up20_1cny
FROM cost_rows GROUP BY component;
