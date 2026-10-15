SELECT b.country,
       COUNT(DISTINCT CONCAT(b.store,'|',b.msku)) AS site_msku_count
FROM dws_datasync.dws_标签表 b
JOIN dws_datasync.dws_标签表 a
  ON a.data_date=b.data_date AND a.store=b.store AND a.msku=b.msku
 AND a.label_id=301 AND a.label_period='current'
WHERE b.data_date='2026-09-13' AND b.label_id=1304 AND b.label_period='30d'
  AND b.country IN ('德国','法国','意大利','西班牙','荷兰','英国','美国')
GROUP BY b.country;
