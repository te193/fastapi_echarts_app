WITH paired AS (
  SELECT old.`国家` country,old.`新店铺` store,old.msku,
         old.`采购单价_cny` p0,old.`单位头程_cny` h0,old.`fba费用_cny` f0,
         a.`采购单价_cny` p12,b.`采购单价_cny` p13,c.`采购单价_cny` p14,
         a.`单位头程_cny` h12,b.`单位头程_cny` h13,c.`单位头程_cny` h14,
         a.`fba费用_cny` f12,b.`fba费用_cny` f13,c.`fba费用_cny` f14
  FROM temporary_dwd.`在库节点_输出定价表_每日快照` old
  JOIN temporary_dwd.`在库节点_输出定价表_每日快照` a
    ON a.`数据日期`='2026-09-12' AND a.`国家`=old.`国家` AND a.`店铺名`=old.`店铺名` AND a.msku=old.msku
  JOIN temporary_dwd.`在库节点_输出定价表_每日快照` b
    ON b.`数据日期`='2026-09-13' AND b.`国家`=old.`国家` AND b.`店铺名`=old.`店铺名` AND b.msku=old.msku
  JOIN temporary_dwd.`在库节点_输出定价表_每日快照` c
    ON c.`数据日期`='2026-09-14' AND c.`国家`=old.`国家` AND c.`店铺名`=old.`店铺名` AND c.msku=old.msku
  JOIN dws_datasync.dws_标签表 tag
    ON tag.data_date='2026-09-13' AND tag.label_id=1304 AND tag.label_period='30d'
   AND tag.country=old.`国家` AND tag.store=old.`新店铺` AND tag.msku=old.msku
  WHERE old.`数据日期`='2026-08-21'
    AND old.`国家` IN ('德国','法国','意大利','西班牙','荷兰','英国','美国')
    AND EXISTS (
      SELECT 1 FROM dws_datasync.dws_标签表 status
      WHERE status.data_date=tag.data_date AND status.label_id=301 AND status.label_period='current'
        AND status.store=tag.store AND status.msku=tag.msku
    )
), costs AS (
  SELECT '采购' component,p0 baseline,p12 d12,p13 d13,p14 d14 FROM paired
  UNION ALL SELECT '头程',h0,h12,h13,h14 FROM paired
  UNION ALL SELECT 'FBA',f0,f12,f13,f14 FROM paired
)
SELECT component,COUNT(*) matched,
       SUM(baseline>0 AND d12>0 AND d13>0 AND d14>0) valid,
       SUM(baseline>0 AND d14>0 AND ABS(d14-baseline)/baseline>=0.20 AND ABS(d14-baseline)>=1) latest_ge20_1cny,
       SUM(baseline>0 AND d12>0 AND d13>0 AND d14>0
           AND ABS(d12-baseline)/baseline>=0.20 AND ABS(d13-baseline)/baseline>=0.20
           AND ABS(d14-baseline)/baseline>=0.20
           AND ABS(d12-baseline)>=1 AND ABS(d13-baseline)>=1 AND ABS(d14-baseline)>=1
           AND SIGN(d12-baseline)=SIGN(d13-baseline) AND SIGN(d13-baseline)=SIGN(d14-baseline)) persistent_3d
FROM costs GROUP BY component;
