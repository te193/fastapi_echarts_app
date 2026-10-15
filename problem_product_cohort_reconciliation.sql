WITH c12 AS (
  SELECT DISTINCT b.country,b.store,b.msku
  FROM dws_datasync.dws_标签表 b
  WHERE b.data_date='2026-09-12' AND b.label_id=1304 AND b.label_period='30d'
    AND b.country IN ('德国','法国','意大利','西班牙','荷兰','英国','美国')
    AND EXISTS (
      SELECT 1 FROM dws_datasync.dws_标签表 a
      WHERE a.data_date=b.data_date AND a.label_id=301 AND a.label_period='current'
        AND a.store=b.store AND a.msku=b.msku
    )
), c13 AS (
  SELECT DISTINCT b.country,b.store,b.msku
  FROM dws_datasync.dws_标签表 b
  WHERE b.data_date='2026-09-13' AND b.label_id=1304 AND b.label_period='30d'
    AND b.country IN ('德国','法国','意大利','西班牙','荷兰','英国','美国')
    AND EXISTS (
      SELECT 1 FROM dws_datasync.dws_标签表 a
      WHERE a.data_date=b.data_date AND a.label_id=301 AND a.label_period='current'
        AND a.store=b.store AND a.msku=b.msku
    )
), all_keys AS (
  SELECT c12.country,c12.store,c12.msku,1 in12,IF(c13.msku IS NULL,0,1) in13
  FROM c12 LEFT JOIN c13 USING(country,store,msku)
  UNION ALL
  SELECT c13.country,c13.store,c13.msku,0 in12,1 in13
  FROM c13 LEFT JOIN c12 USING(country,store,msku)
  WHERE c12.msku IS NULL
)
SELECT country,SUM(in12) sep12,SUM(in13) sep13,
       SUM(in12=1 AND in13=1) intersection_count,
       SUM(in12=1 AND in13=0) only_sep12,
       SUM(in12=0 AND in13=1) only_sep13
FROM all_keys GROUP BY country ORDER BY country;
